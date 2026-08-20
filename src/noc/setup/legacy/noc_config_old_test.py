import json
import os
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

from math import log

import m5
import gem5
from m5.defines import buildEnv
from m5.objects import *
from gem5.components import *

from m5.objects import (
    Port,
)

from m5.util import addToPath

# from noc_graphs import *

# so it can find topologies and network
addToPath(str(REPO_ROOT / "configs"))

from noc_config_funcs import (
    get_parser,
    address_to_id,
    get_address_map,
    axis_tdest_name_to_id,
)
from noc_hbm_config import configure_hbm
from noc_ddr_config import configure_ddr
from topologies.Mesh_XY import Mesh_XY
from topologies.NoC_Topology import NoC_Topology

# Get paths we might need.  It's expected this file is in m5/configs/example.
config_path = "/home/mlanz2/gem5/configs/example"
src_root = os.path.dirname(config_path)
gem5_root = os.path.dirname(src_root)

# I think this should be set automatically when doing garnet standalone build but...
# Garnet_standalone.py errored
buildEnv["PROTOCOL"] = "Garnet_standalone"


# create default options
options = get_parser()

if options.network != "nocgarnet":
    m5.fatal("Unsupported network type: {}".format(options.network))

aximm_nsu = []
aximm_nmu = []
axis_nsu = []
axis_nmu = []
hbm_nsu = []
hbm_nmu = []
ddr_nsu = []
address_name_map = []

# filename = "1_to_1_far"
# basepath = "src/noc/topology/topologies/"
# nts_filename = basepath + filename + ".nts"
# ncr_filename = basepath + filename + ".ncr"  # Store for later
filename = options.noc_topology  # Get from command line
nts_filename = filename + ".nts"
ncr_filename = filename + ".ncr"
# print(f"Reading tile info from {nts_filename}...")
address_name_map, aximm_nsu, aximm_nmu, axis_nsu, axis_nmu, hbm_nsu, hbm_nmu, hbm_channels, ddr_nsu, ddr_channels, src_addr_options, axis_nmu_to_dest_names = get_address_map(
    nts_filename
)
num_aximm_nsu = len(aximm_nsu)
num_aximm_nmu = len(aximm_nmu)
num_axis_nsu = len(axis_nsu)
num_axis_nmu = len(axis_nmu)
num_hbm_nsu = len(hbm_nsu)
num_hbm_nmu = len(hbm_nmu)
num_ddr_nsu = len(ddr_nsu)
total_num_aximm_nsu = num_aximm_nsu + num_hbm_nsu + num_ddr_nsu
total_num_aximm_nmu = num_aximm_nmu + num_hbm_nmu
final_num_tiles = num_aximm_nsu + num_aximm_nmu + num_axis_nsu + num_axis_nmu + num_hbm_nsu + num_hbm_nmu + num_ddr_nsu
print("Num aximm nsu: ", num_aximm_nsu)
print("Num aximm nmu: ", num_aximm_nmu)
print("Num axis nsu: ", num_axis_nsu)
print("Num axis nmu: ", num_axis_nmu)
print("Num hbm nsu: ", num_hbm_nsu)
print("Num hbm nmu: ", num_hbm_nmu)
print("Num ddr nsu: ", num_ddr_nsu)
print("Total num aximm nsu: ", total_num_aximm_nsu)
print("Total num aximm nmu: ", total_num_aximm_nmu)
print("Final num tiles: ", final_num_tiles)

tiles = []
master_nodes = []
slave_nodes = []
nameToID = {}  # Maps NMU/NSU name -> Controller Index (0..N-1)
address_ID_map = []  # Maps (start, end) -> Controller Index
 # Maintain order: NMUs first, then NSUs

n = 0
numAxisPackets = 100

node_conn_names = []

def add_node_connection(tile_obj, ni_name):
    tiles.append(tile_obj)
    node_conn_names.append([ni_name])

# for i in range(num_aximm_nsu):
#     tile_name = aximm_nsu[i]
#     nameToID[tile_name] = n
#     tile_obj = BramEndpoint(
#                 sim_cycles=options.sim_cycles
#             )  
#     slave_nodes.append(tile_obj)
#     add_node_connection(tile_obj, tile_name)
#     n += 1

for i in range(num_aximm_nsu):
    tile_name = aximm_nsu[i]
    nameToID[tile_name] = n
    tile_obj = BramEndpoint(
                sim_cycles=options.sim_cycles
            )  
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

for i in range(num_hbm_nsu):
    tile_name = hbm_nsu[i]
    nameToID[tile_name] = n
    tile_obj = tileNSU_HBM(
            sim_cycles=options.sim_cycles,
            requestorId=i  # Use tile index as requestor ID
        )
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

# DDR NSU tiles - reuse tileNSU_HBM since port interface is identical
for i in range(num_ddr_nsu):
    tile_name = ddr_nsu[i]
    nameToID[tile_name] = n
    tile_obj = tileNSU_HBM(
            sim_cycles=options.sim_cycles,
            requestorId=num_hbm_nsu + i  # Continue requestor ID from HBM
        )
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

for i in range(num_axis_nsu):
    tile_name = axis_nsu[i]
    nameToID[tile_name] = n
    tile_obj = AxisSinkNode(
                sim_cycles=options.sim_cycles,
                ready_percent=100,
                expected_packets=numAxisPackets-1,
                print_data=False,
                data_width=options.data_width if hasattr(options, "data_width") else 512,
                id_width=16,
                dest_width=12
            )
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

for i in range(num_aximm_nmu):
    tile_name = aximm_nmu[i]
    nameToID[tile_name] = n
    # tile_obj = tile(
    #         sim_cycles=options.sim_cycles,
    #         interleaved=options.interleaved,
    #         do_writes=1000,
    #         do_reads=False,
    #         num_reads=options.num_packets,
    #         read_size=options.write_size,
    #         read_length=options.write_length,
    #         bandwidth=7000,  
    #         clk_period=options.clk_period,    
    #         addr_options=src_addr_options.get(tile_name, []),
    #     )
    # tile_obj = AxiRandomTrafficGenerator(
    #     addr_width=64,
    #     data_width=512,
    #     tid_width=16,
    #     base_addr=0x20100000000,
    #     max_addr=0x20100000000+0x10000,
    #     min_transaction_size_bytes=2048,
    #     max_transaction_size_bytes=2048,
    #     max_gap_cycles=0,
    #     min_awid=0,  max_awid=0,
    #     min_arid=0,  max_arid=0,
    #     awsize=6, arsize=6,      # log2(bytes/beat) for 512-bit data
    #     read_write_mode="INTERLEAVED",
    #     max_outstanding_writes=64,
    #     max_write_commands=32,
    # )
    base_addr = src_addr_options.get(tile_name, [])[0]
    max_addr = base_addr + src_addr_options.get(tile_name, [])[1]
    axi_size_bytes = 2 ** options.write_size
    transaction_size = axi_size_bytes * (options.write_length + 1)
    # Keep TG data bus width aligned with configured AXI beat size.
    tg_data_width_bits = axi_size_bytes * 8
    # AXIMM random TG: align burst starts to full transaction size. No CLI; change here if needed.
    aximm_align_addresses = False

    # Determine read/write mode and max writes
    rw_mode = options.direction
    max_writes = options.num_packets

    tile_obj = AxiRandomTrafficGenerator(
        addr_width=64,
        data_width=tg_data_width_bits,
        tid_width=16,
        base_addr=base_addr,
        max_addr=max_addr,
        nsu_min_addrs=[base_addr],
        nsu_address_spaces=[max_addr - base_addr],
        min_transaction_size_bytes=transaction_size,
        max_transaction_size_bytes=transaction_size,
        max_gap_cycles=0,
        read_write_mode=rw_mode,
        max_write_commands=max_writes,
        max_write_bandwidth_mbps=options.bandwidth,
        max_read_bandwidth_mbps=options.bandwidth,
        max_outstanding_writes=1,
        address_distribution="INCREMENT",
        address_increment=transaction_size,
        align_addresses=aximm_align_addresses,
    )
    master_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

for i in range(num_hbm_nmu):
    tile_name = hbm_nmu[i]
    nameToID[tile_name] = n
    tile_obj = tile(
            sim_cycles=options.sim_cycles,
            interleaved=options.interleaved,
            do_writes=options.do_writes,
            do_reads=options.do_reads,
            num_reads=options.num_packets,
            read_size=options.write_size,
            read_length=options.write_length,
            bandwidth=options.bandwidth,  
            clk_period=options.clk_period,    
            addr_options=src_addr_options.get(tile_name, []),
        )
    master_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

for i in range(num_axis_nmu):
    tile_name = axis_nmu[i]
    nameToID[tile_name] = n
    
    data_width_bytes = int(options.data_width / 8) if hasattr(options, "data_width") else 64
    axis_packet_size = data_width_bytes * (options.write_length + 1)
    
    tile_obj = AxisRandomTrafficGenerator(
        # seed = 2,
        max_gap_cycles = 0,
        data_width=options.data_width if hasattr(options, "data_width") else 512,
        max_tid = 0,
        max_tdest = 0,
        max_packets=options.num_packets,
        min_packet_size_bytes=axis_packet_size,
        max_packet_size_bytes=axis_packet_size
    )
    # traffic_generators.append(tg)
    master_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1
    

system = System(cpu=tiles)  # defined in src/sim/System.py

# Configure HBM if there are HBM channels
if (len(hbm_channels) > 0):
    configure_hbm(system, hbm_channels, num_hbm_nsu, num_aximm_nsu)

# Configure DDR if there are DDR channels
if (len(ddr_channels) > 0):
    # DDR NSU tiles start after aximm_nsu + hbm_nsu
    ddr_nsu_start_idx = num_aximm_nsu + num_hbm_nsu
    configure_ddr(system, ddr_channels, num_ddr_nsu, ddr_nsu_start_idx)


# Create a top-level voltage domain and clock domain
system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)

system.clk_domain = SrcClockDomain(
    clock=options.sys_clock, voltage_domain=system.voltage_domain
)

# create_system(system, options)
system.noc = NocSystem()
noc = system.noc
(
    network,
    IntLinkClass,
    ExtLinkClass,
    RouterClass,
) = create_network(options, noc)
noc.network = network
network.routing_algorithm = options.routing_algorithm  # Set routing algorithm
network.number_of_virtual_networks = options.number_of_virtual_networks

address_ID_map = address_to_id(address_name_map, nameToID)
# Pass address map to network param
address_map_json_string = json.dumps(address_ID_map)
network.address_map_json = address_map_json_string

# Create AXIS tdest-to-dest_ni mapping and pass to network
axis_tdest_id_map = axis_tdest_name_to_id(axis_nmu_to_dest_names, nameToID)
print(f"\\n=== AXIS TDEST Mapping Summary ===")
print(f"Raw name mapping: {axis_nmu_to_dest_names}")
print(f"ID-based mapping: {axis_tdest_id_map}")
for nmu_id, tdest_map in axis_tdest_id_map.items():
    print(f"  NMU {nmu_id}: tdest -> dest_ni = {tdest_map}")
print(f"===================================\\n")
axis_tdest_map_json_string = json.dumps(axis_tdest_id_map)
network.axis_tdest_map_json = axis_tdest_map_json_string

controllers = []
record = 2
# *** FUTURE: Use different controller types? ***
# Pass NMU/NSU names to generate_tiles if needed

n = 0
for i in range(num_aximm_nsu):
    ctrl_name = aximm_nsu[i]
    newController = NocInterface(
            id=n, version=n,
            nocname=ctrl_name,
            protocol="AXIMM",
            # TODO: why slave not master for nsu?
            role="Slave",
            noc_system=noc,
            record_mode=record
        )

    controllers.append(newController)
    n += 1

for i in range(num_hbm_nsu):
    ctrl_name = hbm_nsu[i]
    newController = NocInterface(
            id=n, version=n,
            nocname=ctrl_name,
            protocol="AXIMM",
            role="Slave",
            noc_system=noc,
            record_mode=record
        )

    controllers.append(newController)
    n += 1

# DDR NSU controllers
for i in range(num_ddr_nsu):
    ctrl_name = ddr_nsu[i]
    newController = NocInterface(
            id=n, version=n,
            nocname=ctrl_name,
            protocol="AXIMM",
            role="Slave",
            noc_system=noc,
            record_mode=1
        )

    controllers.append(newController)
    n += 1

for i in range(num_axis_nsu):
    ctrl_name = axis_nsu[i]
    newController = NocInterface(
            id=n, version=n,
            nocname=ctrl_name,
            protocol="AXIS",
            role="Slave",
            noc_system=noc,
            axis_data_width=512,
            axis_id_width=16,
            axis_dest_width=12,
            record_mode=record
        )
    controllers.append(newController)
    n += 1

for i in range(num_aximm_nmu):
    ctrl_name = aximm_nmu[i]
    newController = NocInterface(
            id=n, version=n,
            nocname=ctrl_name,
            protocol="AXIMM",
            role="Master",
            noc_system=noc,
            record_mode=record
        )
    controllers.append(newController)
    n += 1

for i in range(num_hbm_nmu):
    ctrl_name = hbm_nmu[i]
    newController = NocInterface(
            id=n, version=n,
            nocname=ctrl_name,
            protocol="AXIMM",
            role="Master",
            noc_system=noc,
            record_mode=1
        )

    controllers.append(newController)
    n += 1

for i in range(num_axis_nmu):
    tile_name = axis_nmu[i]
    newController = NocInterface(
            id=n, version=n,
            nocname=ctrl_name,
            protocol="AXIS",
            role="Master",
            noc_system=noc,
            axis_data_width=512,
            axis_id_width=16,
            axis_dest_width=12,
            record_mode=record
        )
    controllers.append(newController)
    n += 1

noc.tile_controllers = controllers

topology_helper = NoC_Topology(controllers)
# topology_helper = Mesh_XY(controllers)
topology_helper.set_file_path(ncr_filename)  # Set path previously stored
topology_helper.set_node_dict(nameToID)  # Give it name->ID map

print("Calling topology_helper.makeTopology...")
topology_helper.makeTopology(
    options, network, IntLinkClass, ExtLinkClass, RouterClass
)
# init_network(options, network, NMUClass, NSUClass, total_num_aximm_nmu, total_num_aximm_nsu)
init_network(options, network, num_aximm_nsu, num_aximm_nmu, num_hbm_nsu, num_hbm_nmu, num_axis_nsu, num_axis_nmu, num_ddr_nsu)

noc.num_of_sequencers = 0
noc.number_of_virtual_networks = 5

# connect new tile controller to its tile.
for i in range(final_num_tiles):
    system.cpu[i].tile_controller = system.noc.tile_controllers[i]

network.num_aximm_nmu = total_num_aximm_nmu
network.num_aximm_nsu = total_num_aximm_nsu

# Build flattened adjacency list from node connection names
adjacency_list = []
adjacency_index = []
for conn_names in node_conn_names:
    adjacency_index.append(len(adjacency_list))
    for ni_name in conn_names:
        adjacency_list.append(nameToID[ni_name])

# create the control object which advances time for NSU tiles/tile controllers
system.control = Control(
    noc_interfaces=controllers,
    nodes=tiles,
    adjacency_list=adjacency_list,
    adjacency_index=adjacency_index,
    sim_cycles=options.sim_cycles,
)

# Create a seperate clock domain for Ruby
# system.ruby.clk_domain = SrcClockDomain(
#     clock=options.ruby_clock, voltage_domain=system.voltage_domain
system.noc.clk_domain = SrcClockDomain(
    clock=options.noc_clock, voltage_domain=system.voltage_domain
)

for t in system.cpu:
    t.clk_domain = system.clk_domain


# -----------------------
# run simulation
# -----------------------

root = Root(full_system=False, system=system)
root.system.mem_mode = "timing"

# Not much point in this being higher than the L1 latency
m5.ticks.setGlobalFrequency("1ps")

# instantiate configuration
# breakpoint()
# for obj in dir(m5.objects):  # or another relevant parent object
#     print(f"Object: {obj}, Type: {type(getattr(m5.objects, obj))}")
print("calling m5.instantiate")
print(
    f"right before instantiate, one ext_node is {root.system.noc.network.ext_links[0].ext_node}"
)
print(f"type is {type(root.system.noc.network.ext_links[0].ext_node)}")
m5.instantiate()

# simulate until program terminates
exit_event = m5.simulate(options.abs_max_tick)

print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())

dir = 'src/noc/out/csv'

# plot_average_bandwidth(dir, 5)
# plot_windowed_avg_bandwidth(dir, 5000)
# # plot_bytes_transferred_per_link(dir)
# plot_axis_tlast_counts_over_time(dir)
# plot_axis_tlast_diff_over_time(dir)
# # plot_latency_boxplots(dir)
# # plot_latency_histograms(dir)
# # plot_latency_ecdf(dir)
# # plot_latency_percentiles(dir)
# # plot_ready_valid_pct(dir)
# # plot_ready_valid_timeline(dir)
