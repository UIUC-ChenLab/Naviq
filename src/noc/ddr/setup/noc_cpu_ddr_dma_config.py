import json
import os
import sys
from pathlib import Path

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.util import addToPath
from m5.util.convert import toFrequency

NOC_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = NOC_ROOT.parents[1]
for _path in (
    NOC_ROOT / "setup",
    NOC_ROOT / "ddr" / "setup",
    NOC_ROOT / "hbm" / "setup",
    REPO_ROOT / "configs",
):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from noc_config_funcs import (
    apply_targeted_endpoint_clock_policy,
    address_to_id,
    axis_tdest_name_to_id,
    build_endpoint_metric_map,
    clear_metrics_artifacts,
    create_targeted_clock_domains,
    configure_topology_tracing,
    extract_cpu_dma_ddr_route_metadata,
    get_address_map,
    get_parser,
    metrics_fragment_path,
    print_targeted_clock_policy,
    write_windowed_metrics_artifact,
)
from noc_ddr_config import configure_ddr
from noc_hbm_config import configure_hbm
from noc_ddr_packet_dma_config import (
    AXIS_DATA_WIDTH,
    AXIS_TDEST_WIDTH,
    AXIS_TID_WIDTH,
    AXIS_TUSER_WIDTH,
    make_ddr_dma_checker,
    make_ddr_dma_node,
    make_ppe_base_node,
)
from noc_network import *
from topologies.NoC_Topology import NoC_Topology


addToPath(str(REPO_ROOT / "configs"))
buildEnv["PROTOCOL"] = "Garnet_standalone"


DESC_BASE = 0x10000000
PACKET_BASE = 0x11000000
SCRATCH_BASE = 0x12000000
HBM_DESC_BASE = 0x4000000000
HBM_PACKET_BASE = 0x4010000000
HBM_SCRATCH_BASE = 0x4020000000
DMA_CONTROL_BASE = 0x40000000
DMA_CONTROL_SIZE = 0x1000
SCRATCH_SIZE = 1 << 16
PPE_STEERING_BASE = 0xFFFC0000
PPE_STEERING_SIZE = 0x1000
PAYLOAD_SIZES = "16,100,160,228"
PACKET_COUNT = 4
FLOW_PREFIX_BYTES = 2
HASH_PREFIX_BYTES = 1
FLOW_ID = 0x35
FLOW_TDEST = 7
HASH_TABLE_ENTRIES = 256


def _cpu_dma_payload_sizes(packet_count, fixed_payload_bytes=None):
    if fixed_payload_bytes is not None:
        return ",".join([str(int(fixed_payload_bytes))] * packet_count)
    base_sizes = [16, 100, 160, 228]
    out = []
    for index in range(packet_count):
        out.append(str(base_sizes[index % 4] + 4 * (index // 4)))
    return ",".join(out)


STEERING_CONFIGS = {
    "flow_prefix": {
        "node_class": "PacketProcessingEngineBaseFlowPrefixRtlNode",
        "mmio_base": PPE_STEERING_BASE,
        "mmio_size": PPE_STEERING_SIZE,
        "checker": {
            "check_mode": "exact",
            "tdest": FLOW_TDEST,
            "check_tdest": True,
            "validation_skip_bytes": FLOW_PREFIX_BYTES,
            "prefix_bytes": FLOW_PREFIX_BYTES,
            "prefix_value": FLOW_ID,
            "validate_ipv4_checksum": True,
            "validate_l4_checksum": True,
        },
        "dma": {
            "prefix_bytes": FLOW_PREFIX_BYTES,
            "prefix_value": FLOW_ID,
            "start_delay_cycles": 5000,
        },
        "axis_tdest": FLOW_TDEST,
    },
    "five_tuple_hash": {
        "node_class": "PacketProcessingEngineBaseFiveTupleHashRtlNode",
        "mmio_base": PPE_STEERING_BASE,
        "mmio_size": PPE_STEERING_SIZE,
        "checker": {
            "check_mode": "ipv4",
            "tdest": FLOW_TDEST,
            "check_tdest": True,
            "validation_skip_bytes": HASH_PREFIX_BYTES,
            "validate_ipv4_checksum": True,
            "validate_l4_checksum": True,
        },
        "dma": {
            "prefix_bytes": 0,
            "prefix_value": 0,
            "start_delay_cycles": 200000,
        },
        "axis_tdest": FLOW_TDEST,
    },
}


def _cpu_class():
    cls = globals().get("X86TimingSimpleCPU", globals().get("TimingSimpleCPU"))
    if cls is None:
        m5.fatal("CPU-controlled DDR DMA tests require a timing CPU build, e.g. build/X86/gem5.opt")
    return cls


def _remap_address_window(address_map, endpoint_name, window_base, window_size):
    split = []
    window_start = window_base
    window_end = window_base + window_size
    for start, end, name in address_map:
        if name == endpoint_name:
            split.append((window_start, window_end, name))
            continue
        if start < window_start and end > window_end:
            split.append((start, window_start, name))
            split.append((window_end, end, name))
        elif start < window_start < end:
            split.append((start, window_start, name))
        elif start < window_end < end:
            split.append((window_end, end, name))
        elif end <= window_start or start >= window_end:
            split.append((start, end, name))
    return sorted(split, key=lambda item: item[0])


def _split_address_map_for_dma_control(address_map, control_name):
    return _remap_address_window(
        address_map, control_name, DMA_CONTROL_BASE, DMA_CONTROL_SIZE
    )


def _endpoint_covering_address(address_map, address, candidates):
    candidate_set = set(candidates)
    for start, end, name in address_map:
        if name in candidate_set and start <= address < end:
            return name
    return None


def _add_axis_tdest_alias(axis_tdest_map, name_to_id, nmu_name, tdest, nsu_name):
    nmu_id = name_to_id[nmu_name]
    nsu_id = name_to_id[nsu_name]
    axis_tdest_map.setdefault(nmu_id, {})[int(tdest)] = nsu_id


def _make_controller(
    idx, name, protocol, role, noc, record_mode, protocol_buffer_size=32,
):
    kwargs = dict(
        id=idx,
        version=idx,
        endpoint_name=name,
        protocol=protocol,
        role=role,
        noc_system=noc,
        record_mode=record_mode,
        protocol_buffer_size=protocol_buffer_size,
    )
    if protocol == "AXIS":
        kwargs.update(
            axis_data_width=AXIS_DATA_WIDTH,
            axis_id_width=AXIS_TID_WIDTH,
            axis_dest_width=AXIS_TDEST_WIDTH,
        )
    return NocInterface(**kwargs)


def run_cpu_ddr_dma_test(topology_base, *, with_ppe=False,
                         configure_options=None, offload="none",
                         limiter_config=None,
                         backpressure_config=None,
                         memory_endpoint_type="ddr",
                         descriptor_base=DESC_BASE,
                         packet_base=PACKET_BASE,
                         scratch_base=SCRATCH_BASE,
                         cpu_descriptor_base=None,
                         cpu_scratch_base=None,
                         scratch_size=SCRATCH_SIZE,
                         cpu_addr_range_size="4GB",
                         preload_descriptors=False,
                         map_cpu_descriptor=True,
                         map_cpu_scratch=True):
    options = get_parser()
    if configure_options is not None:
        configure_options(options)
    if options.network != "nocgarnet":
        m5.fatal(f"Unsupported network type: {options.network}")
    if with_ppe and limiter_config is not None:
        m5.fatal("CPU DDR DMA test supports either PPE or limiter middle AXIS node, not both")
    if backpressure_config is not None and (with_ppe or limiter_config is not None):
        m5.fatal("CPU DDR DMA test supports only one middle AXIS node")
    monitor_record_mode = options.record_mode

    options.noc_topology = topology_base
    nts_filename = topology_base + ".nts"
    ncr_filename = topology_base + ".ncr"
    topology = get_address_map(nts_filename, ncr_filename)
    memory_endpoint_type = str(memory_endpoint_type).lower()
    if memory_endpoint_type not in ("ddr", "hbm"):
        m5.fatal(f"Unsupported SmartNIC memory endpoint type: {memory_endpoint_type}")
    memory_is_hbm = memory_endpoint_type == "hbm"
    cpu_descriptor_base = descriptor_base if cpu_descriptor_base is None else cpu_descriptor_base
    cpu_scratch_base = scratch_base if cpu_scratch_base is None else cpu_scratch_base
    run_label = getattr(
        options,
        "metrics_run_label",
        (
            f"cpu_{memory_endpoint_type}_dma_ppe_{offload}_{Path(topology_base).name}"
            if with_ppe
            else f"cpu_{memory_endpoint_type}_dma_{Path(topology_base).name}"
        ),
    )
    fragment_components = ["cpu", "dma", "checker"]
    if limiter_config is not None:
        fragment_components.append("limiter")
    if backpressure_config is not None:
        fragment_components.append("backpressure")
    clear_metrics_artifacts(run_label, fragment_components)
    cpu_fragment = metrics_fragment_path(run_label, "cpu")
    dma_fragment = metrics_fragment_path(run_label, "dma")
    checker_fragment = metrics_fragment_path(run_label, "checker")
    limiter_fragment = (
        metrics_fragment_path(run_label, "limiter")
        if limiter_config is not None else None
    )
    backpressure_fragment = (
        metrics_fragment_path(run_label, "backpressure")
        if backpressure_config is not None else None
    )

    ddr_nsu = topology.ddr_nsu
    aximm_nsu = topology.aximm_nsu
    aximm_nmu = topology.aximm_nmu
    axis_nsu = topology.axis_nsu
    axis_nmu = topology.axis_nmu
    hbm_nsu = topology.hbm_nsu
    hbm_nmu = topology.hbm_nmu
    if memory_is_hbm:
        memory_nsu = [name for name in hbm_nsu if str(name).endswith("_PORT0")]
        if not memory_nsu and hbm_nsu:
            memory_nsu = [hbm_nsu[0]]
    else:
        memory_nsu = ddr_nsu
    memory_kind = "HBM" if memory_is_hbm else "DDR"
    dma_ctrl_nsu = _endpoint_covering_address(
        topology.address_name_map, DMA_CONTROL_BASE, aximm_nsu)
    if dma_ctrl_nsu is None:
        m5.fatal("CPU DMA topology is missing the DMA control AXI-MM NSU")
    cpu_mem_nsu = None
    if memory_is_hbm:
        cpu_mem_nsu = _endpoint_covering_address(topology.address_name_map, 0x0, aximm_nsu)
        if cpu_mem_nsu is None:
            m5.fatal("CPU HBM DMA topology is missing the low CPU memory AXI-MM NSU")

    with_middle_axis_node = (
        with_ppe or limiter_config is not None or backpressure_config is not None
    )
    expected_axis_nsu = 2 if with_middle_axis_node else 1
    expected_axis_nmu = 2 if with_middle_axis_node else 1
    requested_packets = max(options.num_packets, PACKET_COUNT)
    requested_payload_sizes = _cpu_dma_payload_sizes(
        requested_packets,
        getattr(options, "dma_fixed_payload_bytes", None),
    )
    requested_packet_stride = int(getattr(options, "dma_packet_stride", 2048))
    expected_aximm_nsu = 2 if memory_is_hbm else 1
    if len(memory_nsu) != 1 or len(aximm_nsu) != expected_aximm_nsu or len(aximm_nmu) != 2:
        m5.fatal(
            f"CPU {memory_kind} DMA topology expects one {memory_kind} NSU, "
            f"{expected_aximm_nsu} AXI-MM control/memory NSU(s), and two AXI-MM NMUs"
        )
    if len(axis_nsu) != expected_axis_nsu or len(axis_nmu) != expected_axis_nmu:
        m5.fatal(
            f"CPU DDR DMA topology expects {expected_axis_nsu} AXIS NSUs "
            f"and {expected_axis_nmu} AXIS NMUs"
        )

    cpu_aximm_nmu = aximm_nmu[0]
    dma_aximm_nmu = aximm_nmu[1]
    checker_nsu = axis_nsu[0]
    dma_axis_nmu = axis_nmu[0]
    middle_in_nsu = axis_nsu[1] if with_middle_axis_node else None
    middle_out_nmu = axis_nmu[1] if with_middle_axis_node else None

    system = System()
    cpu_process_range_size = "16MB" if memory_is_hbm else cpu_addr_range_size
    system.mem_ranges = [AddrRange(0x0, size=cpu_process_range_size)]
    tiles = []
    name_to_id = {}
    node_conn_names = []
    controller_specs = []

    def add_node_connection(tile_obj, ni_name):
        if tile_obj in tiles:
            idx = tiles.index(tile_obj)
            if ni_name not in node_conn_names[idx]:
                node_conn_names[idx].append(ni_name)
        else:
            tiles.append(tile_obj)
            node_conn_names.append([ni_name])

    def add_endpoint(tile_obj, ni_name, protocol, role, record_mode):
        idx = len(controller_specs)
        name_to_id[ni_name] = idx
        controller_specs.append((ni_name, protocol, role, record_mode))
        add_node_connection(tile_obj, ni_name)

    memory_tile = tileNSU_HBM(sim_cycles=options.sim_cycles, requestorId=0)
    add_endpoint(memory_tile, memory_nsu[0], "AXIMM", "Slave", monitor_record_mode)
    cpu_code_memory = None
    if memory_is_hbm:
        cpu_code_memory = BramEndpoint(
            sim_cycles=options.sim_cycles,
            base_addr=0x0,
            memory_size=16 * 1024 * 1024,
            read_latency=1,
            write_latency=1,
        )
        add_endpoint(cpu_code_memory, cpu_mem_nsu, "AXIMM", "Slave", monitor_record_mode)
    functional_memory = memory_tile

    checker_mode = "exact"
    checker_check_tdest = True
    checker_validate_ipv4_checksum = True
    checker_validate_l4_checksum = True
    if with_ppe and offload == "nat":
        checker_mode = "nat_outbound"
        checker_check_tdest = False
        checker_validate_ipv4_checksum = False
        checker_validate_l4_checksum = False
    elif with_ppe and offload == "segmentation":
        checker_mode = "ipv4"
        checker_check_tdest = False
    elif limiter_config is not None:
        # The limiter/backpressure experiment validates packet preservation,
        # not beat-exact AXI-S segmentation. The limiter may shift TLAST/TKEEP
        # presentation while still producing a valid packet stream.
        checker_mode = "ipv4"
    dma_start_delay_cycles = 0
    dma_packet_gap_cycles = 0
    if with_ppe and offload == "nat":
        dma_start_delay_cycles = 3000
        dma_packet_gap_cycles = 4096
    if limiter_config is not None:
        dma_start_delay_cycles = max(dma_start_delay_cycles, 5000)
        if str(limiter_config.get("node_type", "limiter")) == "throttle":
            dma_start_delay_cycles = max(dma_start_delay_cycles, 20000)

    checker = make_ddr_dma_checker(
        options,
        packet_count=requested_packets,
        profile="ipv4_udp",
        payload_sizes=requested_payload_sizes,
        seed=7,
        flow_count=4,
        tid=3,
        tdest=0,
        tuser=0x55,
        check_mode=checker_mode,
        check_tdest=checker_check_tdest,
        validate_ipv4_checksum=checker_validate_ipv4_checksum,
        validate_l4_checksum=checker_validate_l4_checksum,
    )
    checker.metrics_output_path = checker_fragment
    add_endpoint(checker, checker_nsu, "AXIS", "Slave", monitor_record_mode)

    ppe = None
    if with_ppe:
        ppe_reset_cycles = 2500 if offload == "nat" else 16
        ppe = make_ppe_base_node(
            options, offload=offload, packet_count=requested_packets,
            reset_cycles=ppe_reset_cycles)
        add_endpoint(ppe, middle_in_nsu, "AXIS", "Slave", monitor_record_mode)

    limiter = None
    if limiter_config is not None:
        from m5.objects import PacketRateLimiterRtlNode, PacketRateLimiterThrottleRtlNode

        limiter_node_type = str(limiter_config.get("node_type", "limiter"))
        if limiter_node_type == "throttle":
            LimiterNode = PacketRateLimiterThrottleRtlNode
        elif limiter_node_type == "limiter":
            LimiterNode = PacketRateLimiterRtlNode
        else:
            m5.fatal(f"Unsupported limiter node_type: {limiter_node_type}")

        limiter = LimiterNode(
            sim_cycles=options.sim_cycles,
            data_width=AXIS_DATA_WIDTH,
            id_width=AXIS_TID_WIDTH,
            dest_width=AXIS_TDEST_WIDTH,
            user_width=AXIS_TUSER_WIDTH,
            expected_packets=requested_packets,
            reset_cycles=int(limiter_config.get("reset_cycles", 16)),
            metrics_output_path=limiter_fragment,
            limiter_enabled=bool(limiter_config.get("enabled", False)),
            limiter_config_name=str(limiter_config.get("config_name", "none")),
            limiter_rate_setting=str(limiter_config.get("rate_setting", "period1_allow1")),
            limiter_scope=str(
                limiter_config.get(
                    "scope",
                    "controlled_axis_backpressure_v1",
                )
            ),
            limiter_backpressure_period=int(limiter_config.get("period", 1)),
            limiter_backpressure_allow=int(limiter_config.get("allow", 1)),
        )
        add_endpoint(limiter, middle_in_nsu, "AXIS", "Slave", monitor_record_mode)

    backpressure = None
    if backpressure_config is not None:
        from m5.objects import AxisBackpressureShimNode

        backpressure = AxisBackpressureShimNode(
            sim_cycles=options.sim_cycles,
            data_width=AXIS_DATA_WIDTH,
            id_width=AXIS_TID_WIDTH,
            dest_width=AXIS_TDEST_WIDTH,
            expected_packets=requested_packets,
            metrics_output_path=backpressure_fragment,
            backpressure_enabled=bool(backpressure_config.get("enabled", False)),
            backpressure_config_name=str(backpressure_config.get("config_name", "none")),
            backpressure_period=int(backpressure_config.get("period", 1)),
            backpressure_allow=int(backpressure_config.get("allow", 1)),
            backpressure_scope=str(
                backpressure_config.get(
                    "scope",
                    "dma_fed_axis_correctness_shim",
                )
            ),
            fifo_depth=int(backpressure_config.get("fifo_depth", 1)),
        )
        add_endpoint(backpressure, middle_in_nsu, "AXIS", "Slave", monitor_record_mode)

    cpu_bridge_addr_ranges = [AddrRange(0x0, size=cpu_addr_range_size)]
    if memory_is_hbm:
        cpu_bridge_addr_ranges = [
            AddrRange(DMA_CONTROL_BASE, size=DMA_CONTROL_SIZE),
            AddrRange(descriptor_base, size=0x40000000),
        ]

    cpu_bridge = CpuNocBridge(
        max_outstanding=1,
        addr_ranges=cpu_bridge_addr_ranges,
        mmio_ranges=[AddrRange(DMA_CONTROL_BASE, size=DMA_CONTROL_SIZE)],
        metrics_output_path=cpu_fragment,
        scratch_read_burst_base=scratch_base,
        scratch_read_burst_size=scratch_size,
        scratch_read_burst_bytes=getattr(options, "cpu_scratch_read_burst_bytes", 64),
        sim_cycles=options.sim_cycles,
        run_consistency_check=False,
    )
    add_endpoint(cpu_bridge, cpu_aximm_nmu, "AXIMM", "Master", monitor_record_mode)

    dma = make_ddr_dma_node(
        options,
        packet_count=requested_packets,
        profile="ipv4_udp",
        payload_sizes=requested_payload_sizes,
        seed=7,
        flow_count=4,
        tid=3,
        tdest=0,
        tuser=0x55,
        axi_id=1,
        corrupt_ipv4_checksum=with_ppe and offload == "checksum",
        corrupt_l4_checksum=with_ppe and offload == "checksum",
        descriptor_base=descriptor_base,
        packet_base=packet_base,
        packet_stride=requested_packet_stride,
        control_base=DMA_CONTROL_BASE,
        preload_ddr=True,
        preload_descriptors=preload_descriptors,
        preload_packets=True,
        functional_preload_packets=getattr(
            options, "dma_functional_preload_packets", False
        ),
        wait_for_control_start=True,
        stop_on_eoc=True,
        max_read_burst_beats=16,
        max_outstanding_reads=getattr(options, "dma_max_outstanding_reads", None),
        descriptor_prefetch_depth=getattr(options, "dma_descriptor_prefetch_depth", None),
        packet_prefetch_depth=getattr(options, "dma_packet_prefetch_depth", None),
        start_delay_cycles=dma_start_delay_cycles,
        post_preload_read_delay_cycles=getattr(
            options, "dma_post_preload_read_delay_cycles", 0
        ),
        packet_gap_cycles=dma_packet_gap_cycles,
    )
    dma.metrics_output_path = dma_fragment
    add_endpoint(dma, dma_aximm_nmu, "AXIMM", "Master", monitor_record_mode)
    add_endpoint(dma, dma_axis_nmu, "AXIS", "Master", monitor_record_mode)
    add_endpoint(dma, dma_ctrl_nsu, "AXIMM", "Slave", monitor_record_mode)

    if with_ppe:
        add_endpoint(ppe, middle_out_nmu, "AXIS", "Master", monitor_record_mode)
    if limiter_config is not None:
        add_endpoint(limiter, middle_out_nmu, "AXIS", "Master", monitor_record_mode)
    if backpressure_config is not None:
        add_endpoint(backpressure, middle_out_nmu, "AXIS", "Master", monitor_record_mode)

    system.noc_tiles = tiles
    if getattr(options, "dma_functional_preload_packets", False):
        dma.preload_memory = memory_tile
    cpu_bridge.functional_memory = functional_memory
    if memory_is_hbm:
        cpu_bridge.secondary_functional_memory = memory_tile
        cpu_bridge.secondary_functional_ranges = [AddrRange(descriptor_base, size=0x40000000)]

    system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)
    system.clk_domain = SrcClockDomain(
        clock=options.sys_clock, voltage_domain=system.voltage_domain
    )
    clock_policy = create_targeted_clock_domains(system, options)
    noc_clock_mhz = clock_policy["noc_mhz"]
    apply_targeted_endpoint_clock_policy(
        system,
        options,
        tiles,
        node_conn_names,
        ddr_endpoint_names=memory_nsu,
        sys_endpoint_names=[cpu_aximm_nmu],
    )
    if memory_is_hbm:
        configure_hbm(
            system,
            topology.hbm_channels,
            len(memory_nsu),
            0,
            hbm_tile_indices=[tiles.index(memory_tile)],
        )
    else:
        configure_ddr(
            system,
            topology.ddr_channels,
            len(memory_nsu),
            0,
            ddr_memctrl_clk_domain=system.ddr_memctrl_clk_domain,
            ddr_memctrl_clock_label=options.ddr_memctrl_clock,
        )

    cpu = _cpu_class()(cpu_id=0)
    cpu.clk_domain = system.clk_domain
    cpu_membus = SystemXBar()
    cpu.icache_port = cpu_membus.cpu_side_ports
    cpu.dcache_port = cpu_membus.cpu_side_ports
    cpu_membus.mem_side_ports = cpu_bridge.cpu_side
    cpu.createInterruptController()
    if buildEnv.get("USE_X86_ISA", False):
        cpu.interrupts[0].pio = cpu_membus.mem_side_ports
        cpu.interrupts[0].int_requestor = cpu_membus.cpu_side_ports
        cpu.interrupts[0].int_responder = cpu_membus.mem_side_ports

    system.cpus = [cpu]
    system.cpu_membus = cpu_membus
    if memory_is_hbm:
        system.cpu_local_mem = SimpleMemory(range=system.mem_ranges[0])
        system.cpu_local_mem.port = cpu_membus.mem_side_ports

    binary = options.binary
    if not os.path.exists(binary):
        m5.fatal(f"Binary {binary} not found")

    process = Process(pid=100)
    process.cmd = [binary] + options.options.split()
    process.cwd = os.getcwd()
    process.executable = binary
    process.gid = os.getgid()
    cpu.workload = process
    cpu.createThreads()
    system.workload = SEWorkload.init_compatible(binary)

    system.multi_thread = False

    system.noc = NocSystem()
    noc = system.noc
    network, IntLinkClass, ExtLinkClass, RouterClass = create_network(options, noc)
    noc.network = network
    network.routing_algorithm = options.routing_algorithm
    network.number_of_virtual_networks = options.number_of_virtual_networks
    base_address_map = topology.address_name_map
    if memory_is_hbm:
        base_address_map = [
            entry for entry in topology.address_name_map
            if entry[2] not in hbm_nsu or entry[2] in memory_nsu
        ]
    address_map = _split_address_map_for_dma_control(
        base_address_map, dma_ctrl_nsu)
    network.address_map_json = json.dumps(address_to_id(address_map, name_to_id))
    network.axis_tdest_map_json = json.dumps(
        axis_tdest_name_to_id(topology.axis_nmu_to_dest_names, name_to_id)
    )
    cpu_bridge.noc_network = network
    noc_interface_buffer_size = getattr(options, "noc_interface_buffer_size", 32)

    controllers = [
        _make_controller(
            idx,
            name,
            protocol,
            role,
            noc,
            record_mode,
            noc_interface_buffer_size,
        )
        for idx, (name, protocol, role, record_mode)
        in enumerate(controller_specs)
    ]
    noc.tile_controllers = controllers

    for tile_obj, conn_names in zip(tiles, node_conn_names):
        if "tile_controller" in getattr(tile_obj, "_params", {}) and conn_names:
            tile_obj.tile_controller = controllers[name_to_id[conn_names[0]]]

    topology_helper = NoC_Topology(controllers)
    topology_helper.set_file_path(ncr_filename)
    topology_helper.set_node_dict(name_to_id)
    configure_topology_tracing(topology_helper, options)
    topology_helper.makeTopology(
        options, network, IntLinkClass, ExtLinkClass, RouterClass)

    init_network(
        options,
        network,
        len(aximm_nsu),
        len(aximm_nmu),
        len(memory_nsu) if memory_is_hbm else len(hbm_nsu),
        len(hbm_nmu),
        len(axis_nsu),
        len(axis_nmu),
        len(ddr_nsu),
        controllers=controllers,
    )

    noc.num_of_sequencers = 0
    noc.number_of_virtual_networks = 5
    network.num_aximm_nmu = len(aximm_nmu) + len(hbm_nmu)
    network.num_aximm_nsu = (
        len(aximm_nsu)
        + (len(memory_nsu) if memory_is_hbm else len(hbm_nsu))
        + len(ddr_nsu)
    )

    adjacency_list = []
    adjacency_index = []
    for conn_names in node_conn_names:
        adjacency_index.append(len(adjacency_list))
        for ni_name in conn_names:
            adjacency_list.append(name_to_id[ni_name])

    system.control = Control(
        noc_interfaces=controllers,
        nodes=tiles,
        adjacency_list=adjacency_list,
        adjacency_index=adjacency_index,
        sim_cycles=options.sim_cycles,
        noc_clock_domain_mhz=noc_clock_mhz,
    )

    system.noc.clk_domain = SrcClockDomain(
        clock=options.noc_clock, voltage_domain=system.voltage_domain
    )
    print_targeted_clock_policy(
        f"cpu_{memory_endpoint_type}_dma",
        system,
        tiles,
        node_conn_names,
        clock_policy,
        ddr_endpoint_names=memory_nsu,
        sys_endpoint_names=[cpu_aximm_nmu],
    )

    root = Root(full_system=False, system=system)
    root.system.mem_mode = "timing"
    m5.ticks.setGlobalFrequency("1ps")
    m5.instantiate()
    if map_cpu_descriptor:
        process.map(cpu_descriptor_base, descriptor_base, max(0x1000, requested_packets * 64))
    if map_cpu_scratch:
        process.map(cpu_scratch_base, scratch_base, scratch_size)
    process.map(DMA_CONTROL_BASE, DMA_CONTROL_BASE, DMA_CONTROL_SIZE)
    exit_event = m5.simulate(options.abs_max_tick)
    if (
        hasattr(options, "post_cpu_exit_sim_ticks")
        and "last active thread context" in str(exit_event.getCause())
        and m5.curTick() < options.abs_max_tick
    ):
        remaining_ticks = options.abs_max_tick - m5.curTick()
        continue_ticks = int(getattr(options, "post_cpu_exit_sim_ticks"))
        if continue_ticks > 0:
            exit_event = m5.simulate(min(remaining_ticks, continue_ticks))
    print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
    dma_memory_label = "dma_hbm_read" if memory_is_hbm else "dma_ddr_read"
    memory_endpoint_label = "hbm_endpoint" if memory_is_hbm else "ddr_endpoint"
    endpoint_entries = [
        {"logical_name": cpu_aximm_nmu, "endpoint_label": "cpu_mmio", "protocol": "AXIMM", "role": "source"},
        {"logical_name": dma_aximm_nmu, "endpoint_label": dma_memory_label, "protocol": "AXIMM", "role": "source"},
        {"logical_name": dma_axis_nmu, "endpoint_label": "dma_axis_source", "protocol": "AXIS", "role": "source"},
        {"logical_name": checker_nsu, "endpoint_label": "axis_checker_sink", "protocol": "AXIS", "role": "sink"},
        {"logical_name": memory_nsu[0], "endpoint_label": memory_endpoint_label, "protocol": "AXIMM", "role": "sink"},
        {"logical_name": dma_ctrl_nsu, "endpoint_label": "dma_csr", "protocol": "AXIMM", "role": "sink"},
    ]
    if memory_is_hbm:
        endpoint_entries.append(
            {"logical_name": cpu_mem_nsu, "endpoint_label": "cpu_code_mem", "protocol": "AXIMM", "role": "sink"}
        )
    if with_ppe:
        endpoint_entries.extend(
            [
                {"logical_name": middle_in_nsu, "endpoint_label": "ppe_axis_input", "protocol": "AXIS", "role": "sink"},
                {"logical_name": middle_out_nmu, "endpoint_label": "ppe_axis_output", "protocol": "AXIS", "role": "source"},
            ]
        )
    if limiter_config is not None:
        endpoint_entries.extend(
            [
                {"logical_name": middle_in_nsu, "endpoint_label": "limiter_axis_input", "protocol": "AXIS", "role": "sink"},
                {"logical_name": middle_out_nmu, "endpoint_label": "limiter_axis_output", "protocol": "AXIS", "role": "source"},
            ]
        )
    if backpressure_config is not None:
        endpoint_entries.extend(
            [
                {"logical_name": middle_in_nsu, "endpoint_label": "backpressure_axis_input", "protocol": "AXIS", "role": "sink"},
                {"logical_name": middle_out_nmu, "endpoint_label": "backpressure_axis_output", "protocol": "AXIS", "role": "source"},
            ]
        )
    fragment_paths = {"cpu": cpu_fragment, "dma": dma_fragment, "checker": checker_fragment}
    if limiter_fragment is not None:
        fragment_paths["limiter"] = limiter_fragment
    if backpressure_fragment is not None:
        fragment_paths["backpressure"] = backpressure_fragment
    route_metadata = None
    if not memory_is_hbm:
        route_metadata = extract_cpu_dma_ddr_route_metadata(
            ncr_filename,
            cpu_ddr_from=cpu_aximm_nmu,
            dma_ddr_from=dma_aximm_nmu,
            ddr_to="MC0_ddrc",
        )
    write_windowed_metrics_artifact(
        label=run_label,
        options=options,
        clock_policy=clock_policy,
        endpoint_map=build_endpoint_metric_map(name_to_id, endpoint_entries),
        fragment_paths=fragment_paths,
        required_windows=["operation_window", "axis_stream_window"],
        route_metadata=route_metadata,
        memory_endpoint_type=memory_endpoint_type,
        scratch_base=scratch_base,
        scratch_size=scratch_size,
    )


def run_cpu_hbm_dma_test(topology_base, *, with_ppe=False,
                         configure_options=None, offload="none",
                         limiter_config=None,
                         backpressure_config=None,
                         map_cpu_scratch=False,
                         cpu_writes_descriptors=False,
                         cpu_init_scratch=False):
    cpu_writes_descriptors = bool(cpu_writes_descriptors)
    cpu_init_scratch = bool(cpu_init_scratch)
    return run_cpu_ddr_dma_test(
        topology_base,
        with_ppe=with_ppe,
        configure_options=configure_options,
        offload=offload,
        limiter_config=limiter_config,
        backpressure_config=backpressure_config,
        memory_endpoint_type="hbm",
        descriptor_base=HBM_DESC_BASE,
        packet_base=HBM_PACKET_BASE,
        scratch_base=HBM_SCRATCH_BASE,
        cpu_descriptor_base=DESC_BASE,
        cpu_scratch_base=SCRATCH_BASE,
        scratch_size=SCRATCH_SIZE,
        cpu_addr_range_size="512GB",
        preload_descriptors=not cpu_writes_descriptors,
        map_cpu_descriptor=cpu_writes_descriptors,
        map_cpu_scratch=bool(map_cpu_scratch) or cpu_init_scratch,
    )


def run_cpu_ppe_steering_control_test(
    topology_base, *, steering="flow_prefix", configure_options=None, enable_dma=True,
    memory_endpoint_type="ddr"
):
    options = get_parser()
    if configure_options is not None:
        configure_options(options)
    if options.network != "nocgarnet":
        m5.fatal(f"Unsupported network type: {options.network}")
    monitor_record_mode = options.record_mode
    steering_key = steering.lower()
    steering_cfg = STEERING_CONFIGS.get(steering_key)
    if steering_cfg is None:
        m5.fatal(f"Unsupported CPU PPE steering mode: {steering}")

    options.noc_topology = topology_base
    nts_filename = topology_base + ".nts"
    ncr_filename = topology_base + ".ncr"
    topology = get_address_map(nts_filename, ncr_filename)
    memory_endpoint_type = str(memory_endpoint_type).lower()
    if memory_endpoint_type not in ("ddr", "hbm"):
        m5.fatal(f"Unsupported CPU PPE steering memory endpoint type: {memory_endpoint_type}")
    memory_is_hbm = memory_endpoint_type == "hbm"
    memory_kind = "HBM" if memory_is_hbm else "DDR"
    run_label = (
        f"cpu_{memory_endpoint_type}_ppe_steering_{steering_key}_{'control' if enable_dma else 'mmio'}_"
        f"{Path(topology_base).name}"
    )
    clear_metrics_artifacts(run_label, ["cpu", "dma", "checker"])
    cpu_fragment = metrics_fragment_path(run_label, "cpu")
    dma_fragment = metrics_fragment_path(run_label, "dma")
    checker_fragment = metrics_fragment_path(run_label, "checker")

    ddr_nsu = topology.ddr_nsu
    aximm_nsu = topology.aximm_nsu
    aximm_nmu = topology.aximm_nmu
    axis_nsu = topology.axis_nsu
    axis_nmu = topology.axis_nmu
    hbm_nsu = topology.hbm_nsu
    hbm_nmu = topology.hbm_nmu

    if memory_is_hbm:
        memory_nsu = [name for name in hbm_nsu if str(name).endswith("_PORT0")]
        if not memory_nsu and hbm_nsu:
            memory_nsu = [hbm_nsu[0]]
    else:
        memory_nsu = ddr_nsu
    expected_aximm_nsu = 2 if memory_is_hbm else 1
    if len(memory_nsu) != 1 or len(aximm_nsu) != expected_aximm_nsu or len(aximm_nmu) != 2:
        m5.fatal(
            f"CPU PPE steering topology expects one {memory_kind} NSU, "
            f"{expected_aximm_nsu} AXI-MM control/memory NSU(s), and two AXI-MM NMUs"
        )
    if len(axis_nsu) != 2 or len(axis_nmu) != 2:
        m5.fatal(
            "CPU PPE flow-prefix control topology expects two AXIS NSUs "
            "and two AXIS NMUs"
        )

    cpu_aximm_nmu = aximm_nmu[0]
    dma_aximm_nmu = aximm_nmu[1]
    if memory_is_hbm:
        cpu_mem_nsu = _endpoint_covering_address(topology.address_name_map, 0x0, aximm_nsu)
        ppe_ctrl_nsu = _endpoint_covering_address(topology.address_name_map, DMA_CONTROL_BASE, aximm_nsu)
        if cpu_mem_nsu is None:
            m5.fatal("CPU HBM PPE steering topology is missing the low CPU memory AXI-MM NSU")
        if ppe_ctrl_nsu is None:
            m5.fatal("CPU HBM PPE steering topology is missing the PPE control AXI-MM NSU")
    else:
        cpu_mem_nsu = None
        ppe_ctrl_nsu = aximm_nsu[0]
    checker_nsu = axis_nsu[0]
    ppe_in_nsu = axis_nsu[1]
    dma_axis_nmu = axis_nmu[0]
    ppe_out_nmu = axis_nmu[1]

    system = System()
    system.mem_ranges = [AddrRange(0x0, size="16MB" if memory_is_hbm else "4GB")]
    tiles = []
    name_to_id = {}
    node_conn_names = []
    controller_specs = []

    def add_node_connection(tile_obj, ni_name):
        if tile_obj in tiles:
            idx = tiles.index(tile_obj)
            if ni_name not in node_conn_names[idx]:
                node_conn_names[idx].append(ni_name)
        else:
            tiles.append(tile_obj)
            node_conn_names.append([ni_name])

    def add_endpoint(tile_obj, ni_name, protocol, role, record_mode):
        idx = len(controller_specs)
        name_to_id[ni_name] = idx
        controller_specs.append((ni_name, protocol, role, record_mode))
        add_node_connection(tile_obj, ni_name)

    memory_tile = tileNSU_HBM(sim_cycles=options.sim_cycles, requestorId=0)
    add_endpoint(memory_tile, memory_nsu[0], "AXIMM", "Slave", monitor_record_mode)
    cpu_code_memory = None
    if memory_is_hbm:
        cpu_code_memory = BramEndpoint(
            sim_cycles=options.sim_cycles,
            base_addr=0x0,
            memory_size=16 * 1024 * 1024,
            read_latency=1,
            write_latency=1,
        )
        add_endpoint(cpu_code_memory, cpu_mem_nsu, "AXIMM", "Slave", monitor_record_mode)

    checker_packet_count = (max(options.num_packets, PACKET_COUNT) if enable_dma else 0)
    requested_payload_sizes = _cpu_dma_payload_sizes(checker_packet_count) if enable_dma else ""
    checker = make_ddr_dma_checker(
        options,
        packet_count=checker_packet_count,
        profile="ipv4_udp",
        payload_sizes=requested_payload_sizes,
        seed=7,
        flow_count=4,
        tid=3,
        tdest=steering_cfg["checker"]["tdest"],
        tuser=0x55,
        check_mode=steering_cfg["checker"]["check_mode"],
        check_tdest=steering_cfg["checker"]["check_tdest"],
        validate_ipv4_checksum=steering_cfg["checker"]["validate_ipv4_checksum"],
        validate_l4_checksum=steering_cfg["checker"]["validate_l4_checksum"],
        prefix_bytes=steering_cfg["checker"].get("prefix_bytes", 0),
        prefix_value=steering_cfg["checker"].get("prefix_value", 0),
        validation_skip_bytes=steering_cfg["checker"]["validation_skip_bytes"],
    )
    checker.metrics_output_path = checker_fragment
    add_endpoint(checker, checker_nsu, "AXIS", "Slave", monitor_record_mode)

    ppe_node_cls = globals().get(steering_cfg["node_class"])
    if ppe_node_cls is None:
        m5.fatal(
            f"Missing PPE node class {steering_cfg['node_class']} for steering mode {steering_key}"
        )
    ppe = ppe_node_cls(
        sim_cycles=options.sim_cycles,
        data_width=AXIS_DATA_WIDTH,
        id_width=AXIS_TID_WIDTH,
        dest_width=AXIS_TDEST_WIDTH,
        user_width=AXIS_TUSER_WIDTH,
        expected_packets=checker_packet_count,
        reset_cycles=16,
    )
    add_endpoint(ppe, ppe_in_nsu, "AXIS", "Slave", monitor_record_mode)
    add_endpoint(ppe, ppe_out_nmu, "AXIS", "Master", monitor_record_mode)
    add_endpoint(ppe, ppe_ctrl_nsu, "AXIMM", "Slave", monitor_record_mode)

    cpu_bridge = CpuNocBridge(
        max_outstanding=1,
        addr_ranges=(
            [
                AddrRange(steering_cfg["mmio_base"], size=steering_cfg["mmio_size"]),
                AddrRange(HBM_DESC_BASE, size=0x40000000),
            ]
            if memory_is_hbm else [AddrRange(0x0, size="4GB")]
        ),
        mmio_ranges=[AddrRange(steering_cfg["mmio_base"], size=steering_cfg["mmio_size"])],
        metrics_output_path=cpu_fragment,
        scratch_read_burst_base=HBM_SCRATCH_BASE if memory_is_hbm else SCRATCH_BASE,
        scratch_read_burst_size=SCRATCH_SIZE,
        scratch_read_burst_bytes=getattr(options, "cpu_scratch_read_burst_bytes", 64),
        sim_cycles=options.sim_cycles,
        run_consistency_check=False,
    )
    add_endpoint(cpu_bridge, cpu_aximm_nmu, "AXIMM", "Master", monitor_record_mode)

    dma_packet_count = (max(options.num_packets, PACKET_COUNT) if enable_dma else 0)
    dma = make_ddr_dma_node(
        options,
        packet_count=dma_packet_count,
        profile="ipv4_udp",
        payload_sizes=requested_payload_sizes,
        seed=7,
        flow_count=4,
        tid=3,
        tdest=0,
        tuser=0x55,
        axi_id=1,
        prefix_bytes=steering_cfg["dma"]["prefix_bytes"],
        prefix_value=steering_cfg["dma"]["prefix_value"],
        descriptor_base=HBM_DESC_BASE if memory_is_hbm else DESC_BASE,
        packet_base=HBM_PACKET_BASE if memory_is_hbm else PACKET_BASE,
        preload_ddr=enable_dma,
        preload_descriptors=enable_dma,
        preload_packets=enable_dma,
        wait_for_control_start=not enable_dma,
        stop_on_eoc=True,
        max_read_burst_beats=16,
        start_delay_cycles=steering_cfg["dma"]["start_delay_cycles"] if enable_dma else 0,
        packet_gap_cycles=0,
    )
    dma.metrics_output_path = dma_fragment
    add_endpoint(dma, dma_aximm_nmu, "AXIMM", "Master", monitor_record_mode)
    add_endpoint(dma, dma_axis_nmu, "AXIS", "Master", monitor_record_mode)

    system.noc_tiles = tiles
    cpu_bridge.functional_memory = cpu_code_memory if memory_is_hbm else memory_tile
    if memory_is_hbm:
        cpu_bridge.secondary_functional_memory = memory_tile
        cpu_bridge.secondary_functional_ranges = [AddrRange(HBM_DESC_BASE, size=0x40000000)]

    system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)
    system.clk_domain = SrcClockDomain(
        clock=options.sys_clock, voltage_domain=system.voltage_domain
    )
    clock_policy = create_targeted_clock_domains(system, options)
    noc_clock_mhz = clock_policy["noc_mhz"]
    apply_targeted_endpoint_clock_policy(
        system,
        options,
        tiles,
        node_conn_names,
        ddr_endpoint_names=memory_nsu,
        sys_endpoint_names=[cpu_aximm_nmu],
    )
    if memory_is_hbm:
        configure_hbm(
            system,
            topology.hbm_channels,
            len(memory_nsu),
            0,
            hbm_tile_indices=[tiles.index(memory_tile)],
        )
    else:
        configure_ddr(
            system,
            topology.ddr_channels,
            len(memory_nsu),
            0,
            ddr_memctrl_clk_domain=system.ddr_memctrl_clk_domain,
            ddr_memctrl_clock_label=options.ddr_memctrl_clock,
        )

    cpu = _cpu_class()(cpu_id=0)
    cpu.clk_domain = system.clk_domain
    cpu_membus = SystemXBar()
    cpu.icache_port = cpu_membus.cpu_side_ports
    cpu.dcache_port = cpu_membus.cpu_side_ports
    cpu_membus.mem_side_ports = cpu_bridge.cpu_side
    cpu.createInterruptController()
    if buildEnv.get("USE_X86_ISA", False):
        cpu.interrupts[0].pio = cpu_membus.mem_side_ports
        cpu.interrupts[0].int_requestor = cpu_membus.cpu_side_ports
        cpu.interrupts[0].int_responder = cpu_membus.mem_side_ports

    system.cpus = [cpu]
    system.cpu_membus = cpu_membus

    binary = options.binary
    if not os.path.exists(binary):
        m5.fatal(f"Binary {binary} not found")

    process = Process(pid=100)
    process.cmd = [binary] + options.options.split()
    process.cwd = os.getcwd()
    process.executable = binary
    process.gid = os.getgid()
    cpu.workload = process
    cpu.createThreads()
    system.workload = SEWorkload.init_compatible(binary)
    system.multi_thread = False

    system.noc = NocSystem()
    noc = system.noc
    network, IntLinkClass, ExtLinkClass, RouterClass = create_network(options, noc)
    noc.network = network
    network.routing_algorithm = options.routing_algorithm
    network.number_of_virtual_networks = options.number_of_virtual_networks
    base_address_map = topology.address_name_map
    if memory_is_hbm:
        base_address_map = [
            entry for entry in topology.address_name_map
            if entry[2] not in hbm_nsu or entry[2] in memory_nsu
        ]
    address_map = _remap_address_window(
        base_address_map, ppe_ctrl_nsu, PPE_STEERING_BASE, PPE_STEERING_SIZE
    )
    network.address_map_json = json.dumps(address_to_id(address_map, name_to_id))
    axis_tdest_map = axis_tdest_name_to_id(
        topology.axis_nmu_to_dest_names, name_to_id
    )
    _add_axis_tdest_alias(
        axis_tdest_map, name_to_id, ppe_out_nmu, steering_cfg["axis_tdest"], checker_nsu
    )
    network.axis_tdest_map_json = json.dumps(axis_tdest_map)
    cpu_bridge.noc_network = network

    controllers = [
        _make_controller(idx, name, protocol, role, noc, record_mode)
        for idx, (name, protocol, role, record_mode)
        in enumerate(controller_specs)
    ]
    noc.tile_controllers = controllers

    for tile_obj, conn_names in zip(tiles, node_conn_names):
        if "tile_controller" in getattr(tile_obj, "_params", {}) and conn_names:
            tile_obj.tile_controller = controllers[name_to_id[conn_names[0]]]

    topology_helper = NoC_Topology(controllers)
    topology_helper.set_file_path(ncr_filename)
    topology_helper.set_node_dict(name_to_id)
    configure_topology_tracing(topology_helper, options)
    topology_helper.makeTopology(
        options, network, IntLinkClass, ExtLinkClass, RouterClass)

    init_network(
        options,
        network,
        len(aximm_nsu),
        len(aximm_nmu),
        len(hbm_nsu),
        len(hbm_nmu),
        len(axis_nsu),
        len(axis_nmu),
        len(ddr_nsu),
        controllers=controllers,
    )

    noc.num_of_sequencers = 0
    noc.number_of_virtual_networks = 5
    network.num_aximm_nmu = len(aximm_nmu) + len(hbm_nmu)
    network.num_aximm_nsu = len(aximm_nsu) + len(hbm_nsu) + len(ddr_nsu)

    adjacency_list = []
    adjacency_index = []
    for conn_names in node_conn_names:
        adjacency_index.append(len(adjacency_list))
        for ni_name in conn_names:
            adjacency_list.append(name_to_id[ni_name])

    system.control = Control(
        noc_interfaces=controllers,
        nodes=tiles,
        adjacency_list=adjacency_list,
        adjacency_index=adjacency_index,
        sim_cycles=options.sim_cycles,
        noc_clock_domain_mhz=noc_clock_mhz,
    )

    system.noc.clk_domain = SrcClockDomain(
        clock=options.noc_clock, voltage_domain=system.voltage_domain
    )
    print_targeted_clock_policy(
        f"cpu_{memory_endpoint_type}_ppe_steering",
        system,
        tiles,
        node_conn_names,
        clock_policy,
        ddr_endpoint_names=memory_nsu,
        sys_endpoint_names=[cpu_aximm_nmu],
    )

    root = Root(full_system=False, system=system)
    root.system.mem_mode = "timing"
    m5.ticks.setGlobalFrequency("1ps")
    m5.instantiate()
    process.map(
        steering_cfg["mmio_base"], steering_cfg["mmio_base"], steering_cfg["mmio_size"]
    )
    exit_event = m5.simulate(options.abs_max_tick)
    if (
        enable_dma
        and "last active thread context" in str(exit_event.getCause())
        and m5.curTick() < options.abs_max_tick
    ):
        remaining_ticks = options.abs_max_tick - m5.curTick()
        continue_ticks = getattr(options, "post_cpu_exit_sim_ticks", remaining_ticks)
        exit_event = m5.simulate(min(remaining_ticks, continue_ticks))
    print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
    endpoint_entries = [
        {"logical_name": cpu_aximm_nmu, "endpoint_label": "cpu_mmio", "protocol": "AXIMM", "role": "source"},
        {"logical_name": dma_aximm_nmu, "endpoint_label": "dma_hbm_read" if memory_is_hbm else "dma_ddr_read", "protocol": "AXIMM", "role": "source"},
        {"logical_name": dma_axis_nmu, "endpoint_label": "dma_axis_source", "protocol": "AXIS", "role": "source"},
        {"logical_name": checker_nsu, "endpoint_label": "axis_checker_sink", "protocol": "AXIS", "role": "sink"},
        {"logical_name": ppe_in_nsu, "endpoint_label": "ppe_axis_input", "protocol": "AXIS", "role": "sink"},
        {"logical_name": ppe_out_nmu, "endpoint_label": "ppe_axis_output", "protocol": "AXIS", "role": "source"},
        {"logical_name": ppe_ctrl_nsu, "endpoint_label": "ppe_csr", "protocol": "AXIMM", "role": "sink"},
    ]
    if memory_is_hbm:
        endpoint_entries.append(
            {"logical_name": cpu_mem_nsu, "endpoint_label": "cpu_code_mem", "protocol": "AXIMM", "role": "sink"}
        )
    if enable_dma:
        endpoint_entries.append(
            {"logical_name": memory_nsu[0], "endpoint_label": "hbm_endpoint" if memory_is_hbm else "ddr_endpoint", "protocol": "AXIMM", "role": "sink"}
        )
    write_windowed_metrics_artifact(
        label=run_label,
        options=options,
        clock_policy=clock_policy,
        endpoint_map=build_endpoint_metric_map(name_to_id, endpoint_entries),
        fragment_paths={"cpu": cpu_fragment, "dma": dma_fragment, "checker": checker_fragment},
        required_windows=["operation_window", "axis_stream_window"] if enable_dma else [],
        memory_endpoint_type=memory_endpoint_type,
    )


def run_cpu_ppe_flow_prefix_control_test(
    topology_base, *, configure_options=None, enable_dma=True, memory_endpoint_type="ddr"
):
    run_cpu_ppe_steering_control_test(
        topology_base,
        steering="flow_prefix",
        configure_options=configure_options,
        enable_dma=enable_dma,
        memory_endpoint_type=memory_endpoint_type,
    )
