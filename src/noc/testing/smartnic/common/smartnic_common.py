import json
import sys
from pathlib import Path

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.util import addToPath
from m5.util.convert import toFrequency

NOC_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = NOC_ROOT.parents[1]
for _path in (
    NOC_ROOT / "setup",
    NOC_ROOT / "setup" / "legacy",
    NOC_ROOT / "ddr" / "setup",
    NOC_ROOT / "hbm" / "setup",
    REPO_ROOT / "configs",
):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from noc_network import *
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
from noc_hbm_config import configure_hbm
from topologies.NoC_Topology import NoC_Topology


AXIS_DATA_WIDTH = 512
AXIS_TID_WIDTH = 16
AXIS_TDEST_WIDTH = 12
AXIS_TUSER_WIDTH = 16


addToPath(str(REPO_ROOT / "configs"))
buildEnv["PROTOCOL"] = "Garnet_standalone"


def make_packet_source(options, *, profile="mixed_tcp_udp", check_seed=1,
                       min_payload_bytes=16, max_payload_bytes=64,
                       initial_gap_cycles=16, packet_count=None,
                       flow_count=4, min_gap_cycles=0, max_gap_cycles=0,
                       tid=0, tdest=0, tuser=0,
                       corrupt_ipv4_checksum=False,
                       corrupt_l4_checksum=False,
                       prefix_bytes=0, prefix_value=0):
    packets = max(packet_count if packet_count is not None else options.num_packets, 1)
    return AxisPacketTrafficGenerator(
        data_width=AXIS_DATA_WIDTH,
        tid_width=AXIS_TID_WIDTH,
        tdest_width=AXIS_TDEST_WIDTH,
        tuser_width=AXIS_TUSER_WIDTH,
        profile=profile,
        max_packets=packets,
        seed=check_seed,
        min_payload_bytes=min_payload_bytes,
        max_payload_bytes=max_payload_bytes,
        flow_count=flow_count,
        min_gap_cycles=min_gap_cycles,
        max_gap_cycles=max_gap_cycles,
        initial_gap_cycles=initial_gap_cycles,
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


def make_packet_checker(options, *, check_mode="exact", profile="mixed_tcp_udp",
                        check_seed=1, min_payload_bytes=16,
                        max_payload_bytes=64,
                        packet_count=None,
                        validate_ipv4_checksum=True,
                        validate_l4_checksum=True,
                        flow_count=4, tid=0, tdest=0, tuser=0,
                        validation_skip_bytes=0, check_tdest=False,
                        prefix_bytes=0, prefix_value=0):
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
        seed=check_seed,
        min_payload_bytes=min_payload_bytes,
        max_payload_bytes=max_payload_bytes,
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
        nat_public_ip="10.0.0.1",
        nat_base_port=40000,
        nat_port_count=256,
    )


def add_axis_tdest_aliases(axis_tdest_id_map, name_to_id, aliases):
    if not aliases:
        return
    for nmu_name, tdest, nsu_name in aliases:
        if nmu_name not in name_to_id:
            m5.fatal(f"Cannot add AXIS TDEST alias for unknown NMU {nmu_name}")
        if nsu_name not in name_to_id:
            m5.fatal(f"Cannot add AXIS TDEST alias for unknown NSU {nsu_name}")
        nmu_id = name_to_id[nmu_name]
        nsu_id = name_to_id[nsu_name]
        axis_tdest_id_map.setdefault(nmu_id, {})[int(tdest)] = nsu_id
        print(f"[AXIS ID Map Alias] NMU {nmu_id} tdest={tdest} -> dest_ni={nsu_id}")


def make_stream_rtl_node(cls, options, expected_packets=None, reset_cycles=8):
    return cls(
        sim_cycles=options.sim_cycles,
        data_width=AXIS_DATA_WIDTH,
        id_width=AXIS_TID_WIDTH,
        dest_width=AXIS_TDEST_WIDTH,
        user_width=AXIS_TUSER_WIDTH,
        expected_packets=expected_packets if expected_packets is not None else max(options.num_packets, 1),
        reset_cycles=reset_cycles,
    )


def run_axis_test(topology_base, make_nsu, make_nmu, configure_options=None,
                  axis_tdest_aliases=None, interface_validator=None,
                  record_mode=None):
    options = get_parser()
    if configure_options is not None:
        configure_options(options)
    if options.network != "nocgarnet":
        m5.fatal(f"Unsupported network type: {options.network}")
    monitor_record_mode = (
        options.record_mode if record_mode is None else record_mode
    )

    options.noc_topology = topology_base
    nts_filename = topology_base + ".nts"
    ncr_filename = topology_base + ".ncr"

    topology = get_address_map(nts_filename, ncr_filename)
    address_name_map = topology.address_name_map
    aximm_nsu = topology.aximm_nsu
    aximm_nmu = topology.aximm_nmu
    axis_nsu = topology.axis_nsu
    axis_nmu = topology.axis_nmu
    hbm_nsu = topology.hbm_nsu
    hbm_nmu = topology.hbm_nmu
    hbm_channels = topology.hbm_channels
    ddr_nsu = topology.ddr_nsu
    ddr_channels = topology.ddr_channels
    axis_nmu_to_dest_names = topology.axis_nmu_to_dest_names

    if interface_validator is not None:
        interface_validator(axis_nsu, axis_nmu, options)

    system = System()
    run_label = f"smartnic_axis_{Path(topology_base).name}"
    clear_metrics_artifacts(run_label, ["checker"])
    checker_fragment = metrics_fragment_path(run_label, "checker")
    tiles = []
    slave_nodes = []
    master_nodes = []
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

    n = 0
    for tile_name in axis_nsu:
        name_to_id[tile_name] = n
        tile_obj = make_nsu(tile_name, options)
        if isinstance(tile_obj, AxisPacketCheckerSink):
            tile_obj.metrics_output_path = checker_fragment
        slave_nodes.append(tile_obj)
        add_node_connection(tile_obj, tile_name)
        n += 1

    for tile_name in axis_nmu:
        name_to_id[tile_name] = n
        tile_obj = make_nmu(tile_name, options)
        master_nodes.append(tile_obj)
        add_node_connection(tile_obj, tile_name)
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

    if len(hbm_channels) > 0:
        configure_hbm(system, hbm_channels, len(hbm_nsu), len(aximm_nsu))

    if len(ddr_channels) > 0:
        ddr_nsu_start_idx = len(aximm_nsu) + len(hbm_nsu)
        configure_ddr(
            system,
            ddr_channels,
            len(ddr_nsu),
            ddr_nsu_start_idx,
            ddr_memctrl_clk_domain=system.ddr_memctrl_clk_domain,
            ddr_memctrl_clock_label=options.ddr_memctrl_clock,
        )

    system.noc = NocSystem()
    noc = system.noc
    network, IntLinkClass, ExtLinkClass, RouterClass = create_network(options, noc)
    noc.network = network
    network.routing_algorithm = options.routing_algorithm
    network.number_of_virtual_networks = options.number_of_virtual_networks
    network.address_map_json = json.dumps(address_to_id(address_name_map, name_to_id))
    axis_tdest_id_map = axis_tdest_name_to_id(axis_nmu_to_dest_names, name_to_id)
    add_axis_tdest_aliases(axis_tdest_id_map, name_to_id, axis_tdest_aliases)
    network.axis_tdest_map_json = json.dumps(axis_tdest_id_map)

    controllers = []
    n = 0
    for ctrl_name in axis_nsu:
        controllers.append(NocInterface(
            id=n,
            version=n,
            endpoint_name=ctrl_name,
            protocol="AXIS",
            role="Slave",
            noc_system=noc,
            axis_data_width=AXIS_DATA_WIDTH,
            axis_id_width=AXIS_TID_WIDTH,
            axis_dest_width=AXIS_TDEST_WIDTH,
            record_mode=monitor_record_mode,
        ))
        n += 1

    for ctrl_name in axis_nmu:
        controllers.append(NocInterface(
            id=n,
            version=n,
            endpoint_name=ctrl_name,
            protocol="AXIS",
            role="Master",
            noc_system=noc,
            axis_data_width=AXIS_DATA_WIDTH,
            axis_id_width=AXIS_TID_WIDTH,
            axis_dest_width=AXIS_TDEST_WIDTH,
            record_mode=monitor_record_mode,
        ))
        n += 1

    noc.tile_controllers = controllers

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

    adjacency_list = []
    adjacency_index = []
    for conn_names in node_conn_names:
        adjacency_index.append(len(adjacency_list))
        for ni_name in conn_names:
            adjacency_list.append(name_to_id[ni_name])

    network.num_aximm_nmu = len(aximm_nmu) + len(hbm_nmu)
    network.num_aximm_nsu = len(aximm_nsu) + len(hbm_nsu) + len(ddr_nsu)

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
        "smartnic_axis",
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
    endpoint_entries = []
    for idx, logical_name in enumerate(axis_nmu):
        endpoint_entries.append(
            {
                "logical_name": logical_name,
                "endpoint_label": "axis_packet_source" if idx == 0 else logical_name.lower(),
                "protocol": "AXIS",
                "role": "source",
            }
        )
    for idx, logical_name in enumerate(axis_nsu):
        endpoint_entries.append(
            {
                "logical_name": logical_name,
                "endpoint_label": "axis_checker_sink" if idx == 0 else logical_name.lower(),
                "protocol": "AXIS",
                "role": "sink",
            }
        )
    write_windowed_metrics_artifact(
        label=run_label,
        options=options,
        clock_policy=clock_policy,
        endpoint_map=build_endpoint_metric_map(name_to_id, endpoint_entries),
        fragment_paths={"checker": checker_fragment},
        required_windows=["axis_stream_window"],
    )
