import json
import sys
from pathlib import Path

NOC_ROOT = Path(__file__).resolve().parents[2]
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

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.util import addToPath
from m5.util.convert import toFrequency

addToPath(str(REPO_ROOT / "configs"))

from noc_config_funcs import (
    get_parser,
    address_to_id,
    get_address_map,
    axis_tdest_name_to_id,
)
from noc_hbm_config import configure_hbm
from noc_ddr_config import configure_ddr
from topologies.NoC_Topology import NoC_Topology

buildEnv["PROTOCOL"] = "Garnet_standalone"

options = get_parser()

if options.network != "nocgarnet":
    m5.fatal("Unsupported network type: {}".format(options.network))

default_topology = "src/noc/topology/topologies/1_to_1_far"
if options.noc_topology == default_topology:
    options.noc_topology = "src/noc/topology/topologies/smartnic_axis_fifo_smoke"

filename = options.noc_topology
nts_filename = filename + ".nts"
ncr_filename = filename + ".ncr"

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

num_aximm_nsu = len(aximm_nsu)
num_aximm_nmu = len(aximm_nmu)
num_axis_nsu = len(axis_nsu)
num_axis_nmu = len(axis_nmu)
num_hbm_nsu = len(hbm_nsu)
num_hbm_nmu = len(hbm_nmu)
num_ddr_nsu = len(ddr_nsu)
total_num_aximm_nsu = num_aximm_nsu + num_hbm_nsu + num_ddr_nsu
total_num_aximm_nmu = num_aximm_nmu + num_hbm_nmu

if num_axis_nsu != 2 or num_axis_nmu != 2:
    m5.fatal(
        "smartnic_axis_fifo config expects exactly 2 AXIS NSUs and 2 AXIS NMUs "
        f"(got NSU={num_axis_nsu}, NMU={num_axis_nmu})"
    )

system = System()
tiles = []
slave_nodes = []
master_nodes = []
nameToID = {}
node_conn_names = []

numPackets = max(options.num_packets, 1)
axis_traffic_gen_name = "S00_AXIS_nmu"
axis_fifo_input_name = "M01_AXIS_nsu"
axis_fifo_output_name = "S01_AXIS_nmu"
axis_sink_name = "M00_AXIS_nsu"
beat_bytes = int(options.data_width / 8) if hasattr(options, "data_width") else 64
packet_bytes = beat_bytes * (options.write_length + 1)
axis_print_data = getattr(options, "axis_print_data", False)

print(
    "[smartnic_axis_fifo] "
    f"packets={numPackets} packet_bytes={packet_bytes} "
    f"beats_per_packet={options.write_length + 1} beat_bytes={beat_bytes}"
)


def add_node_connection(tile_obj, ni_name):
    if tile_obj in tiles:
        idx = tiles.index(tile_obj)
        if ni_name not in node_conn_names[idx]:
            node_conn_names[idx].append(ni_name)
    else:
        tiles.append(tile_obj)
        node_conn_names.append([ni_name])


axis_fifo_node = AxisFifoRtlNode(
    sim_cycles=options.sim_cycles,
    fifo_depth=32,
    print_data=axis_print_data,
    data_width=options.data_width if hasattr(options, "data_width") else 512,
    id_width=16,
    dest_width=12,
    user_width=1,
    expected_packets=numPackets,
)

n = 0
for tile_name in axis_nsu:
    nameToID[tile_name] = n
    if tile_name == axis_fifo_input_name:
        tile_obj = axis_fifo_node
    elif tile_name == axis_sink_name:
        tile_obj = AxisSinkNode(
            sim_cycles=options.sim_cycles,
            ready_percent=100,
            expected_packets=numPackets,
            print_data=axis_print_data,
            data_width=options.data_width if hasattr(options, "data_width") else 512,
            id_width=16,
            dest_width=12,
        )
    else:
        m5.fatal(f"Unexpected AXIS NSU name {tile_name}; update config constants")
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

for tile_name in axis_nmu:
    nameToID[tile_name] = n
    if tile_name == axis_fifo_output_name:
        tile_obj = axis_fifo_node
    elif tile_name == axis_traffic_gen_name:
        tile_obj = AxisRandomTrafficGenerator(
            data_width=options.data_width if hasattr(options, "data_width") else 512,
            tdest_width=12,
            tid_width=16,
            tuser_width=1,
            seed=1,
            packet_size_distribution="FIXED",
            min_packet_size_bytes=beat_bytes * (options.write_length + 1),
            max_packet_size_bytes=beat_bytes * (options.write_length + 1),
            gap_distribution="FIXED",
            min_gap_cycles=0,
            max_gap_cycles=0,
            tid_distribution="FIXED",
            min_tid=0,
            max_tid=0,
            tdest_distribution="FIXED",
            min_tdest=0,
            max_tdest=0,
            max_packets=numPackets,
        )
    else:
        m5.fatal(f"Unexpected AXIS NMU name {tile_name}; update config constants")
    master_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

noc_clock_mhz = int(toFrequency(options.noc_clock) / 1e6)
for tile_obj, conn_names in zip(tiles, node_conn_names):
    tile_obj.clockDomains = [noc_clock_mhz] * len(conn_names)
    tile_obj.port_endpoint_names = list(conn_names)

system.cpu = tiles

if len(hbm_channels) > 0:
    configure_hbm(system, hbm_channels, num_hbm_nsu, num_aximm_nsu)

if len(ddr_channels) > 0:
    ddr_nsu_start_idx = num_aximm_nsu + num_hbm_nsu
    configure_ddr(system, ddr_channels, num_ddr_nsu, ddr_nsu_start_idx)

system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)
system.clk_domain = SrcClockDomain(
    clock=options.sys_clock, voltage_domain=system.voltage_domain
)

system.noc = NocSystem()
noc = system.noc
(
    network,
    IntLinkClass,
    ExtLinkClass,
    RouterClass,
) = create_network(options, noc)
noc.network = network
network.routing_algorithm = options.routing_algorithm
network.number_of_virtual_networks = options.number_of_virtual_networks

address_ID_map = address_to_id(address_name_map, nameToID)
network.address_map_json = json.dumps(address_ID_map)

axis_tdest_id_map = axis_tdest_name_to_id(axis_nmu_to_dest_names, nameToID)
network.axis_tdest_map_json = json.dumps(axis_tdest_id_map)

controllers = []
record = 0
n = 0

for ctrl_name in axis_nsu:
    controllers.append(
        NocInterface(
            id=n,
            version=n,
            endpoint_name=ctrl_name,
            protocol="AXIS",
            role="Slave",
            noc_system=noc,
            axis_data_width=options.data_width if hasattr(options, "data_width") else 512,
            axis_id_width=16,
            axis_dest_width=12,
            record_mode=record,
        )
    )
    n += 1

for ctrl_name in axis_nmu:
    controllers.append(
        NocInterface(
            id=n,
            version=n,
            endpoint_name=ctrl_name,
            protocol="AXIS",
            role="Master",
            noc_system=noc,
            axis_data_width=options.data_width if hasattr(options, "data_width") else 512,
            axis_id_width=16,
            axis_dest_width=12,
            record_mode=record,
        )
    )
    n += 1

noc.tile_controllers = controllers

topology_helper = NoC_Topology(controllers)
topology_helper.set_file_path(ncr_filename)
topology_helper.set_node_dict(nameToID)
topology_helper.makeTopology(options, network, IntLinkClass, ExtLinkClass, RouterClass)

init_network(
    options,
    network,
    num_aximm_nsu,
    num_aximm_nmu,
    num_hbm_nsu,
    num_hbm_nmu,
    num_axis_nsu,
    num_axis_nmu,
    num_ddr_nsu,
    controllers=controllers,
)

noc.num_of_sequencers = 0
noc.number_of_virtual_networks = 5

adjacency_list = []
adjacency_index = []
for conn_names in node_conn_names:
    adjacency_index.append(len(adjacency_list))
    for ni_name in conn_names:
        adjacency_list.append(nameToID[ni_name])

network.num_aximm_nmu = total_num_aximm_nmu
network.num_aximm_nsu = total_num_aximm_nsu

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

for t in system.cpu:
    t.clk_domain = system.clk_domain

root = Root(full_system=False, system=system)
root.system.mem_mode = "timing"
m5.ticks.setGlobalFrequency("1ps")
m5.instantiate()
exit_event = m5.simulate(options.abs_max_tick)

print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
