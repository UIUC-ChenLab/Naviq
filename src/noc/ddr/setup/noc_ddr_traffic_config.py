import json
import sys
from pathlib import Path

import m5
from m5.defines import buildEnv
from m5.objects import Root, SrcClockDomain, System, VoltageDomain
from m5.util import addToPath

NOC_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = NOC_ROOT.parents[1]
CONFIGS_DIR = REPO_ROOT / "configs"
for _path in (
    NOC_ROOT / "setup",
    NOC_ROOT / "ddr" / "setup",
    CONFIGS_DIR,
):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from noc_network import *  # noqa: F401,F403
from noc_config_funcs import (
    apply_targeted_endpoint_clock_policy,
    address_to_id,
    create_targeted_clock_domains,
    configure_topology_tracing,
    get_address_map,
    get_parser,
    print_targeted_clock_policy,
)
from noc_ddr_config import configure_ddr
from topologies.NoC_Topology import NoC_Topology


addToPath(str(CONFIGS_DIR))
buildEnv["PROTOCOL"] = "Garnet_standalone"
NODE_CLOCK_DOMAIN_MHZ = 1000


def _make_aximm_tg(options, tile_name, src_addr_options):
    addr_info = src_addr_options.get(tile_name, [])
    if len(addr_info) < 2:
        m5.fatal(f"No AXI-MM address space registered for TG endpoint {tile_name}")

    base_addr = addr_info[0]
    addr_space = addr_info[1]
    max_addr = base_addr + addr_space
    axi_size_bytes = 2 ** options.write_size
    transaction_size = axi_size_bytes * (options.write_length + 1)

    return AxiRandomTrafficGenerator(
        clockDomains=[NODE_CLOCK_DOMAIN_MHZ],
        port_endpoint_names=[tile_name],
        addr_width=64,
        data_width=axi_size_bytes * 8,
        tid_width=16,
        base_addr=base_addr,
        max_addr=max_addr,
        nsu_min_addrs=[base_addr],
        nsu_address_spaces=[addr_space],
        min_transaction_size_bytes=transaction_size,
        max_transaction_size_bytes=transaction_size,
        max_gap_cycles=0,
        read_write_mode=options.direction,
        max_write_commands=options.num_packets,
        max_write_bandwidth_mbps=options.bandwidth,
        max_read_bandwidth_mbps=options.bandwidth,
        max_outstanding_writes=1,
        address_distribution="INCREMENT",
        address_increment=transaction_size,
        align_addresses=False,
    )


def run_ddr_traffic_test(topology_base, configure_options=None):
    options = get_parser()
    if configure_options is not None:
        configure_options(options)

    if options.network != "nocgarnet":
        m5.fatal(f"Unsupported network type: {options.network}")

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
    src_addr_options = topology.src_addr_options

    if aximm_nsu or axis_nsu or axis_nmu or hbm_nsu or hbm_nmu or hbm_channels:
        m5.fatal(
            "DDR traffic config only supports pure AXI-MM TG -> DDR topologies"
        )
    if not ddr_nsu or not aximm_nmu:
        m5.fatal("DDR traffic config expects at least one DDR NSU and one AXI-MM NMU")

    tiles = []
    name_to_id = {}
    node_conn_names = []

    def add_node_connection(tile_obj, ni_name):
        tiles.append(tile_obj)
        node_conn_names.append([ni_name])

    n = 0
    for i, tile_name in enumerate(ddr_nsu):
        name_to_id[tile_name] = n
        tile_obj = tileNSU_HBM(
            sim_cycles=options.sim_cycles,
            requestorId=i,
            clockDomains=[NODE_CLOCK_DOMAIN_MHZ],
            port_endpoint_names=[tile_name],
        )
        add_node_connection(tile_obj, tile_name)
        n += 1

    for tile_name in aximm_nmu:
        name_to_id[tile_name] = n
        tile_obj = _make_aximm_tg(options, tile_name, src_addr_options)
        add_node_connection(tile_obj, tile_name)
        n += 1

    system = System()
    system.noc_tiles = tiles

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
        ddr_channels,
        len(ddr_nsu),
        0,
        ddr_memctrl_clk_domain=system.ddr_memctrl_clk_domain,
        ddr_memctrl_clock_label=options.ddr_memctrl_clock,
    )

    system.noc = NocSystem()
    noc = system.noc
    (network, IntLinkClass, ExtLinkClass, RouterClass) = create_network(options, noc)
    noc.network = network
    network.routing_algorithm = options.routing_algorithm
    network.number_of_virtual_networks = options.number_of_virtual_networks
    network.address_map_json = json.dumps(address_to_id(address_name_map, name_to_id))

    controllers = []
    controller_id = 0

    for ctrl_name in ddr_nsu:
        controllers.append(
            NocInterface(
                id=controller_id,
                version=controller_id,
                endpoint_name=ctrl_name,
                protocol="AXIMM",
                role="Slave",
                noc_system=noc,
                record_mode=1,
            )
        )
        controller_id += 1

    for ctrl_name in aximm_nmu:
        controllers.append(
            NocInterface(
                id=controller_id,
                version=controller_id,
                endpoint_name=ctrl_name,
                protocol="AXIMM",
                role="Master",
                noc_system=noc,
                record_mode=1,
            )
        )
        controller_id += 1

    noc.tile_controllers = controllers

    topology_helper = NoC_Topology(controllers)
    topology_helper.set_file_path(ncr_filename)
    topology_helper.set_node_dict(name_to_id)
    configure_topology_tracing(topology_helper, options)
    topology_helper.makeTopology(options, network, IntLinkClass, ExtLinkClass, RouterClass)
    init_network(
        options,
        network,
        0,
        len(aximm_nmu),
        0,
        0,
        0,
        0,
        len(ddr_nsu),
    )

    noc.num_of_sequencers = 0
    noc.number_of_virtual_networks = 5

    for i, tile in enumerate(tiles):
        tile.tile_controller = controllers[i]

    network.num_aximm_nmu = len(aximm_nmu)
    network.num_aximm_nsu = len(ddr_nsu)

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
        "ddr_traffic",
        system,
        tiles,
        node_conn_names,
        clock_policy,
        ddr_endpoint_names=ddr_nsu,
    )

    root = Root(full_system=False, system=system)
    root.system.mem_mode = "timing"

    m5.ticks.setGlobalFrequency("1ps")

    print(
        f"[DDR traffic test] topology={topology_base} "
        f"masters={len(aximm_nmu)} ddr_nsu={len(ddr_nsu)} "
        f"direction={options.direction} num_packets={options.num_packets} "
        f"bandwidth={options.bandwidth}MBps"
    )
    print("Instantiating simulation...")
    m5.instantiate()

    print("Running simulation...")
    exit_event = m5.simulate(options.abs_max_tick)
    exit_cause = exit_event.getCause()
    print(f"Exiting @ tick {m5.curTick()} because {exit_cause}")
    return exit_cause
