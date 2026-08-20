import json
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
    get_address_map,
    get_parser,
    metrics_fragment_path,
    print_targeted_clock_policy,
    write_windowed_metrics_artifact,
)
from noc_ddr_config import configure_ddr
from noc_network import *
from topologies.NoC_Topology import NoC_Topology


AXIS_DATA_WIDTH = 512
AXIS_TID_WIDTH = 16
AXIS_TDEST_WIDTH = 12
AXIS_TUSER_WIDTH = 16


addToPath(str(REPO_ROOT / "configs"))
buildEnv["PROTOCOL"] = "Garnet_standalone"


def make_ddr_dma_node(options, *, packet_count=None, min_payload_bytes=16,
                      max_payload_bytes=64, seed=1, flow_count=4,
                      tid=0, tdest=0, tuser=0,
                      profile="mixed_tcp_udp", payload_sizes="",
                      corrupt_ipv4_checksum=False, corrupt_l4_checksum=False,
                      prefix_bytes=0, prefix_value=0,
                      axi_id=0,
                      descriptor_base=0x00000000, packet_base=0x00100000,
                      control_base=0x40000000,
                      packet_stride=2048, max_read_burst_beats=16,
                      max_outstanding_reads=None,
                      descriptor_prefetch_depth=None,
                      packet_prefetch_depth=None,
                      start_delay_cycles=0,
                      post_preload_read_delay_cycles=0,
                      packet_gap_cycles=0,
                      descriptor_flags=0x1, stop_on_eoc=True,
                      preload_ddr=True, preload_descriptors=True,
                      preload_packets=True, functional_preload_packets=False,
                      wait_for_control_start=False):
    packets = max(packet_count if packet_count is not None else options.num_packets, 1)
    return DdrPacketDmaNode(
        sim_cycles=options.sim_cycles,
        descriptor_base=descriptor_base,
        packet_base=packet_base,
        control_base=control_base,
        packet_stride=packet_stride,
        packet_count=packets,
        max_read_burst_beats=max_read_burst_beats,
        max_outstanding_reads=(
            max_outstanding_reads if max_outstanding_reads is not None else 16
        ),
        descriptor_prefetch_depth=(
            descriptor_prefetch_depth if descriptor_prefetch_depth is not None else 64
        ),
        packet_prefetch_depth=(
            packet_prefetch_depth if packet_prefetch_depth is not None else 16
        ),
        start_delay_cycles=start_delay_cycles,
        post_preload_read_delay_cycles=post_preload_read_delay_cycles,
        packet_gap_cycles=packet_gap_cycles,
        descriptor_flags=descriptor_flags,
        stop_on_eoc=stop_on_eoc,
        preload_ddr=preload_ddr,
        preload_descriptors=preload_descriptors,
        preload_packets=preload_packets,
        functional_preload_packets=functional_preload_packets,
        wait_for_control_start=wait_for_control_start,
        print_summary=True,
        data_width=AXIS_DATA_WIDTH,
        tid_width=AXIS_TID_WIDTH,
        tdest_width=AXIS_TDEST_WIDTH,
        tuser_width=AXIS_TUSER_WIDTH,
        axi_id=axi_id,
        profile=profile,
        seed=seed,
        min_payload_bytes=min_payload_bytes,
        max_payload_bytes=max_payload_bytes,
        payload_sizes=payload_sizes,
        flow_count=flow_count,
        tid=tid,
        tdest=tdest,
        tuser=tuser,
        src_ip="192.168.1.100",
        dst_ip="8.8.8.8",
        src_port=12345,
        dst_port=80,
        corrupt_ipv4_checksum=corrupt_ipv4_checksum,
        corrupt_l4_checksum=corrupt_l4_checksum,
        prefix_bytes=prefix_bytes,
        prefix_value=prefix_value,
    )


def make_ddr_dma_checker(options, *, packet_count=None, min_payload_bytes=16,
                         max_payload_bytes=64, seed=1, flow_count=4,
                         tid=0, tdest=0, tuser=0,
                         profile="mixed_tcp_udp", payload_sizes="",
                         check_mode="exact", check_tdest=False,
                         validate_ipv4_checksum=True,
                         validate_l4_checksum=True,
                         prefix_bytes=0, prefix_value=0,
                         validation_skip_bytes=0):
    packets = max(packet_count if packet_count is not None else options.num_packets, 1)
    return AxisPacketCheckerSink(
        data_width=AXIS_DATA_WIDTH,
        tid_width=AXIS_TID_WIDTH,
        tdest_width=AXIS_TDEST_WIDTH,
        tuser_width=AXIS_TUSER_WIDTH,
        check_mode=check_mode,
        ready_percent=100,
        expected_packets=packets,
        validate_ipv4_checksum=validate_ipv4_checksum,
        validate_l4_checksum=validate_l4_checksum,
        print_summary=True,
        validation_skip_bytes=validation_skip_bytes,
        check_tdest=check_tdest,
        profile=profile,
        seed=seed,
        min_payload_bytes=min_payload_bytes,
        max_payload_bytes=max_payload_bytes,
        payload_sizes=payload_sizes,
        flow_count=flow_count,
        tid=tid,
        tdest=tdest,
        tuser=tuser,
        src_ip="192.168.1.100",
        dst_ip="8.8.8.8",
        src_port=12345,
        dst_port=80,
        prefix_bytes=prefix_bytes,
        prefix_value=prefix_value,
    )


def make_ppe_base_node(options, *, offload="none", packet_count=None,
                       reset_cycles=16):
    if offload == "none":
        from m5.objects import PacketProcessingEngineBaseNoneRtlNode as cls
    elif offload == "telemetry":
        from m5.objects import PacketProcessingEngineBaseTelemetryRtlNode as cls
    elif offload == "segmentation":
        from m5.objects import PacketProcessingEngineBaseSegmentationRtlNode as cls
    elif offload == "checksum":
        from m5.objects import PacketProcessingEngineBaseChecksumRtlNode as cls
    elif offload == "nat":
        from m5.objects import PacketProcessingEngineBaseNatRtlNode as cls
    else:
        m5.fatal(f"Unsupported DDR DMA PPE base offload: {offload}")

    return cls(
        sim_cycles=options.sim_cycles,
        data_width=AXIS_DATA_WIDTH,
        id_width=AXIS_TID_WIDTH,
        dest_width=AXIS_TDEST_WIDTH,
        user_width=AXIS_TUSER_WIDTH,
        expected_packets=max(packet_count if packet_count is not None else options.num_packets, 1),
        reset_cycles=reset_cycles,
    )


def run_ddr_dma_axis_sink_test(topology_base, configure_options=None,
                               packet_count=None, min_payload_bytes=16,
                               max_payload_bytes=64, seed=1, flow_count=4,
                               tid=0, tdest=0, tuser=0,
                               profile="mixed_tcp_udp", payload_sizes="",
                               max_read_burst_beats=16,
                               start_delay_cycles=0,
                               packet_gap_cycles=0):
    options = get_parser()
    if configure_options is not None:
        configure_options(options)
    if options.network != "nocgarnet":
        m5.fatal(f"Unsupported network type: {options.network}")
    monitor_record_mode = options.record_mode

    options.noc_topology = topology_base
    nts_filename = topology_base + ".nts"
    ncr_filename = topology_base + ".ncr"

    topology = get_address_map(nts_filename, ncr_filename)
    ddr_nsu = topology.ddr_nsu
    axis_nsu = topology.axis_nsu
    aximm_nmu = topology.aximm_nmu
    axis_nmu = topology.axis_nmu
    hbm_nsu = topology.hbm_nsu
    hbm_nmu = topology.hbm_nmu
    aximm_nsu = topology.aximm_nsu

    if len(ddr_nsu) != 1 or len(axis_nsu) != 1 or len(aximm_nmu) != 1 or len(axis_nmu) != 1:
        m5.fatal(
            "DDR DMA smoke topology expects one DDR NSU, one AXIS NSU, "
            "one AXI-MM NMU, and one AXIS NMU"
        )

    packets = max(packet_count if packet_count is not None else options.num_packets, 1)
    run_label = f"ddr_dma_axis_{Path(topology_base).name}"
    clear_metrics_artifacts(run_label, ["dma", "checker"])
    dma_fragment = metrics_fragment_path(run_label, "dma")
    checker_fragment = metrics_fragment_path(run_label, "checker")
    system = System()
    tiles = []
    name_to_id = {}
    node_conn_names = []

    def add_node_connection(tile_obj, ni_name):
        if tile_obj in tiles:
            idx = tiles.index(tile_obj)
            node_conn_names[idx].append(ni_name)
        else:
            tiles.append(tile_obj)
            node_conn_names.append([ni_name])

    n = 0
    ddr_tile = tileNSU_HBM(sim_cycles=options.sim_cycles, requestorId=0)
    name_to_id[ddr_nsu[0]] = n
    add_node_connection(ddr_tile, ddr_nsu[0])
    n += 1

    checker = make_ddr_dma_checker(
        options,
        packet_count=packets,
        min_payload_bytes=min_payload_bytes,
        max_payload_bytes=max_payload_bytes,
        seed=seed,
        flow_count=flow_count,
        tid=tid,
        tdest=tdest,
        tuser=tuser,
        profile=profile,
        payload_sizes=payload_sizes,
        check_tdest=True,
    )
    checker.metrics_output_path = checker_fragment
    name_to_id[axis_nsu[0]] = n
    add_node_connection(checker, axis_nsu[0])
    n += 1

    dma = make_ddr_dma_node(
        options,
        packet_count=packets,
        min_payload_bytes=min_payload_bytes,
        max_payload_bytes=max_payload_bytes,
        seed=seed,
        flow_count=flow_count,
        tid=tid,
        tdest=tdest,
        tuser=tuser,
        profile=profile,
        payload_sizes=payload_sizes,
        max_read_burst_beats=max_read_burst_beats,
        start_delay_cycles=start_delay_cycles,
        packet_gap_cycles=packet_gap_cycles,
    )
    dma.metrics_output_path = dma_fragment
    name_to_id[aximm_nmu[0]] = n
    add_node_connection(dma, aximm_nmu[0])
    n += 1
    name_to_id[axis_nmu[0]] = n
    add_node_connection(dma, axis_nmu[0])
    n += 1

    system.cpu = tiles

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
        ddr_endpoint_names=ddr_nsu,
    )
    configure_ddr(
        system,
        topology.ddr_channels,
        len(ddr_nsu),
        0,
        ddr_memctrl_clk_domain=system.ddr_memctrl_clk_domain,
        ddr_memctrl_clock_label=options.ddr_memctrl_clock,
    )

    system.noc = NocSystem()
    noc = system.noc
    network, IntLinkClass, ExtLinkClass, RouterClass = create_network(options, noc)
    noc.network = network
    network.routing_algorithm = options.routing_algorithm
    network.number_of_virtual_networks = options.number_of_virtual_networks
    network.address_map_json = json.dumps(address_to_id(topology.address_name_map, name_to_id))
    network.axis_tdest_map_json = json.dumps(
        axis_tdest_name_to_id(topology.axis_nmu_to_dest_names, name_to_id)
    )

    controllers = []
    controller_specs = [
        (ddr_nsu[0], "AXIMM", "Slave", monitor_record_mode),
        (axis_nsu[0], "AXIS", "Slave", monitor_record_mode),
        (aximm_nmu[0], "AXIMM", "Master", monitor_record_mode),
        (axis_nmu[0], "AXIS", "Master", monitor_record_mode),
    ]
    for idx, (name, protocol, role, record_mode) in enumerate(controller_specs):
        kwargs = dict(
            id=idx,
            version=idx,
            endpoint_name=name,
            protocol=protocol,
            role=role,
            noc_system=noc,
            record_mode=record_mode,
        )
        if protocol == "AXIS":
            kwargs.update(
                axis_data_width=AXIS_DATA_WIDTH,
                axis_id_width=AXIS_TID_WIDTH,
                axis_dest_width=AXIS_TDEST_WIDTH,
            )
        controllers.append(NocInterface(**kwargs))

    noc.tile_controllers = controllers
    for tile_obj, conn_names in zip(tiles, node_conn_names):
        if "tile_controller" in getattr(tile_obj, "_params", {}) and conn_names:
            tile_obj.tile_controller = controllers[name_to_id[conn_names[0]]]

    topology_helper = NoC_Topology(controllers)
    topology_helper.set_file_path(ncr_filename)
    topology_helper.set_node_dict(name_to_id)
    configure_topology_tracing(topology_helper, options)
    topology_helper.makeTopology(options, network, IntLinkClass, ExtLinkClass, RouterClass)

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
        "ddr_dma_axis",
        system,
        tiles,
        node_conn_names,
        clock_policy,
        ddr_endpoint_names=ddr_nsu,
    )

    root = Root(full_system=False, system=system)
    root.system.mem_mode = "timing"
    m5.ticks.setGlobalFrequency("1ps")
    m5.instantiate()
    exit_event = m5.simulate(options.abs_max_tick)
    print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
    endpoint_map = build_endpoint_metric_map(
        name_to_id,
        [
            {"logical_name": ddr_nsu[0], "endpoint_label": "ddr_endpoint", "protocol": "AXIMM", "role": "sink"},
            {"logical_name": axis_nsu[0], "endpoint_label": "axis_checker_sink", "protocol": "AXIS", "role": "sink"},
            {"logical_name": aximm_nmu[0], "endpoint_label": "dma_ddr_read", "protocol": "AXIMM", "role": "source"},
            {"logical_name": axis_nmu[0], "endpoint_label": "dma_axis_source", "protocol": "AXIS", "role": "source"},
        ],
    )
    write_windowed_metrics_artifact(
        label=run_label,
        options=options,
        clock_policy=clock_policy,
        endpoint_map=endpoint_map,
        fragment_paths={"dma": dma_fragment, "checker": checker_fragment},
        required_windows=["operation_window", "axis_stream_window"],
    )


def run_ddr_dma_ppe_base_axis_sink_test(topology_base, configure_options=None,
                                        packet_count=None, min_payload_bytes=16,
                                        max_payload_bytes=64, seed=1,
                                        flow_count=4, tid=0, tdest=0,
                                        tuser=0, offload="none",
                                        profile="mixed_tcp_udp",
                                        payload_sizes="",
                                        corrupt_ipv4_checksum=False,
                                        corrupt_l4_checksum=False,
                                        max_read_burst_beats=16,
                                        start_delay_cycles=None,
                                        packet_gap_cycles=None):
    options = get_parser()
    if configure_options is not None:
        configure_options(options)
    if options.network != "nocgarnet":
        m5.fatal(f"Unsupported network type: {options.network}")
    monitor_record_mode = options.record_mode

    options.noc_topology = topology_base
    nts_filename = topology_base + ".nts"
    ncr_filename = topology_base + ".ncr"

    topology = get_address_map(nts_filename, ncr_filename)
    ddr_nsu = topology.ddr_nsu
    axis_nsu = topology.axis_nsu
    aximm_nmu = topology.aximm_nmu
    axis_nmu = topology.axis_nmu
    hbm_nsu = topology.hbm_nsu
    hbm_nmu = topology.hbm_nmu
    aximm_nsu = topology.aximm_nsu

    if len(ddr_nsu) != 1 or len(axis_nsu) != 2 or len(aximm_nmu) != 1 or len(axis_nmu) != 2:
        m5.fatal(
            "DDR DMA PPE smoke topology expects one DDR NSU, two AXIS NSUs, "
            "one AXI-MM NMU, and two AXIS NMUs"
        )

    packets = max(packet_count if packet_count is not None else options.num_packets, 1)
    run_label = f"ddr_dma_ppe_base_{offload}_{Path(topology_base).name}"
    clear_metrics_artifacts(run_label, ["dma", "checker"])
    dma_fragment = metrics_fragment_path(run_label, "dma")
    checker_fragment = metrics_fragment_path(run_label, "checker")
    checker_mode = "exact"
    checker_check_tdest = True
    checker_validate_ipv4_checksum = True
    checker_validate_l4_checksum = True
    if offload == "nat":
        checker_mode = "nat_outbound"
        checker_check_tdest = False
        checker_validate_ipv4_checksum = False
        checker_validate_l4_checksum = False
    elif offload == "segmentation":
        checker_mode = "ipv4"
        checker_check_tdest = False
    dma_start_delay_cycles = (
        3000 if start_delay_cycles is None and offload == "nat"
        else (start_delay_cycles or 0)
    )
    dma_packet_gap_cycles = (
        4096 if packet_gap_cycles is None and offload == "nat"
        else (packet_gap_cycles or 0)
    )

    system = System()
    tiles = []
    name_to_id = {}
    node_conn_names = []

    def add_node_connection(tile_obj, ni_name):
        if tile_obj in tiles:
            idx = tiles.index(tile_obj)
            if ni_name not in node_conn_names[idx]:
                node_conn_names[idx].append(ni_name)
        else:
            tiles.append(tile_obj)
            node_conn_names.append([ni_name])

    checker_nsu = axis_nsu[0]
    ppe_in_nsu = axis_nsu[1]
    dma_axis_nmu = axis_nmu[0]
    ppe_out_nmu = axis_nmu[1]

    n = 0
    ddr_tile = tileNSU_HBM(sim_cycles=options.sim_cycles, requestorId=0)
    name_to_id[ddr_nsu[0]] = n
    add_node_connection(ddr_tile, ddr_nsu[0])
    n += 1

    checker = make_ddr_dma_checker(
        options,
        packet_count=packets,
        min_payload_bytes=min_payload_bytes,
        max_payload_bytes=max_payload_bytes,
        seed=seed,
        flow_count=flow_count,
        tid=tid,
        tdest=tdest,
        tuser=tuser,
        profile=profile,
        payload_sizes=payload_sizes,
        check_mode=checker_mode,
        check_tdest=checker_check_tdest,
        validate_ipv4_checksum=checker_validate_ipv4_checksum,
        validate_l4_checksum=checker_validate_l4_checksum,
    )
    checker.metrics_output_path = checker_fragment
    name_to_id[checker_nsu] = n
    add_node_connection(checker, checker_nsu)
    n += 1

    ppe_reset_cycles = 2500 if offload == "nat" else 16
    ppe = make_ppe_base_node(
        options, offload=offload, packet_count=packets,
        reset_cycles=ppe_reset_cycles)
    name_to_id[ppe_in_nsu] = n
    add_node_connection(ppe, ppe_in_nsu)
    n += 1

    dma = make_ddr_dma_node(
        options,
        packet_count=packets,
        min_payload_bytes=min_payload_bytes,
        max_payload_bytes=max_payload_bytes,
        seed=seed,
        flow_count=flow_count,
        tid=tid,
        tdest=tdest,
        tuser=tuser,
        profile=profile,
        payload_sizes=payload_sizes,
        corrupt_ipv4_checksum=corrupt_ipv4_checksum,
        corrupt_l4_checksum=corrupt_l4_checksum,
        max_read_burst_beats=max_read_burst_beats,
        start_delay_cycles=dma_start_delay_cycles,
        packet_gap_cycles=dma_packet_gap_cycles,
    )
    dma.metrics_output_path = dma_fragment
    name_to_id[aximm_nmu[0]] = n
    add_node_connection(dma, aximm_nmu[0])
    n += 1

    name_to_id[dma_axis_nmu] = n
    add_node_connection(dma, dma_axis_nmu)
    n += 1

    name_to_id[ppe_out_nmu] = n
    add_node_connection(ppe, ppe_out_nmu)
    n += 1

    system.cpu = tiles

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
        ddr_endpoint_names=ddr_nsu,
    )
    configure_ddr(
        system,
        topology.ddr_channels,
        len(ddr_nsu),
        0,
        ddr_memctrl_clk_domain=system.ddr_memctrl_clk_domain,
        ddr_memctrl_clock_label=options.ddr_memctrl_clock,
    )

    system.noc = NocSystem()
    noc = system.noc
    network, IntLinkClass, ExtLinkClass, RouterClass = create_network(options, noc)
    noc.network = network
    network.routing_algorithm = options.routing_algorithm
    network.number_of_virtual_networks = options.number_of_virtual_networks
    network.address_map_json = json.dumps(address_to_id(topology.address_name_map, name_to_id))
    network.axis_tdest_map_json = json.dumps(
        axis_tdest_name_to_id(topology.axis_nmu_to_dest_names, name_to_id)
    )

    controllers = []
    controller_specs = [
        (ddr_nsu[0], "AXIMM", "Slave", monitor_record_mode),
        (checker_nsu, "AXIS", "Slave", monitor_record_mode),
        (ppe_in_nsu, "AXIS", "Slave", monitor_record_mode),
        (aximm_nmu[0], "AXIMM", "Master", monitor_record_mode),
        (dma_axis_nmu, "AXIS", "Master", monitor_record_mode),
        (ppe_out_nmu, "AXIS", "Master", monitor_record_mode),
    ]
    for idx, (name, protocol, role, record_mode) in enumerate(controller_specs):
        kwargs = dict(
            id=idx,
            version=idx,
            endpoint_name=name,
            protocol=protocol,
            role=role,
            noc_system=noc,
            record_mode=record_mode,
        )
        if protocol == "AXIS":
            kwargs.update(
                axis_data_width=AXIS_DATA_WIDTH,
                axis_id_width=AXIS_TID_WIDTH,
                axis_dest_width=AXIS_TDEST_WIDTH,
            )
        controllers.append(NocInterface(**kwargs))

    noc.tile_controllers = controllers
    for tile_obj, conn_names in zip(tiles, node_conn_names):
        if "tile_controller" in getattr(tile_obj, "_params", {}) and conn_names:
            tile_obj.tile_controller = controllers[name_to_id[conn_names[0]]]

    topology_helper = NoC_Topology(controllers)
    topology_helper.set_file_path(ncr_filename)
    topology_helper.set_node_dict(name_to_id)
    configure_topology_tracing(topology_helper, options)
    topology_helper.makeTopology(options, network, IntLinkClass, ExtLinkClass, RouterClass)

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
        "ddr_dma_ppe_base_axis",
        system,
        tiles,
        node_conn_names,
        clock_policy,
        ddr_endpoint_names=ddr_nsu,
    )

    root = Root(full_system=False, system=system)
    root.system.mem_mode = "timing"
    m5.ticks.setGlobalFrequency("1ps")
    m5.instantiate()
    exit_event = m5.simulate(options.abs_max_tick)
    print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
    endpoint_map = build_endpoint_metric_map(
        name_to_id,
        [
            {"logical_name": ddr_nsu[0], "endpoint_label": "ddr_endpoint", "protocol": "AXIMM", "role": "sink"},
            {"logical_name": checker_nsu, "endpoint_label": "axis_checker_sink", "protocol": "AXIS", "role": "sink"},
            {"logical_name": ppe_in_nsu, "endpoint_label": "ppe_axis_input", "protocol": "AXIS", "role": "sink"},
            {"logical_name": aximm_nmu[0], "endpoint_label": "dma_ddr_read", "protocol": "AXIMM", "role": "source"},
            {"logical_name": dma_axis_nmu, "endpoint_label": "dma_axis_source", "protocol": "AXIS", "role": "source"},
            {"logical_name": ppe_out_nmu, "endpoint_label": "ppe_axis_output", "protocol": "AXIS", "role": "source"},
        ],
    )
    write_windowed_metrics_artifact(
        label=run_label,
        options=options,
        clock_policy=clock_policy,
        endpoint_map=endpoint_map,
        fragment_paths={"dma": dma_fragment, "checker": checker_fragment},
        required_windows=["operation_window", "axis_stream_window"],
    )
