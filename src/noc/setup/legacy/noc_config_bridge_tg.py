"""
CPU NoC Bridge Test Configuration

Extended config to test CpuNocBridge with various topologies.
This replaces the traffic generator NMU with a CPU + CpuNocBridge.
Supports all NSU types: AXIMM, HBM, DDR, and AXIS.

Usage:
  build/NULL/gem5.opt src/noc/setup/legacy/noc_config_cpu_test.py \
      --noc-topology=src/noc/topology/topologies/1nmu_to_ddr

For debugging, add: --debug-flags=NocPacketFlow
"""

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

from m5.objects import Port
from m5.objects.PyTrafficGen import PyTrafficGen
from m5.util import addToPath

addToPath(str(REPO_ROOT / "configs"))

from noc_config_funcs import (
    get_parser,
    address_to_id,
    get_address_map,
    axis_tdest_name_to_id,
)
from noc_ddr_config import configure_ddr
from noc_hbm_config import configure_hbm
from topologies.NoC_Topology import NoC_Topology

buildEnv["PROTOCOL"] = "Garnet_standalone"

# Get options
options = get_parser()

if options.network != "nocgarnet":
    m5.fatal("Unsupported network type: {}".format(options.network))

# Create System early to handle parenting
system = System()


# =============================================================================
# Parse topology
# =============================================================================
filename = options.noc_topology
nts_filename = filename + ".nts"
ncr_filename = filename + ".ncr"

# Parse the NTS file
(address_name_map, aximm_nsu, aximm_nmu, axis_nsu, axis_nmu, 
 hbm_nsu, hbm_nmu, hbm_channels, ddr_nsu, ddr_channels, 
 src_addr_options, axis_nmu_to_dest_names) = get_address_map(nts_filename)

# Get counts for all NSU/NMU types
num_aximm_nsu = len(aximm_nsu)
num_aximm_nmu = len(aximm_nmu)
num_hbm_nsu = len(hbm_nsu)
num_hbm_nmu = len(hbm_nmu)
num_ddr_nsu = len(ddr_nsu)
num_axis_nsu = len(axis_nsu)
num_axis_nmu = len(axis_nmu)

# Total counts for network initialization
total_num_aximm_nsu = num_aximm_nsu + num_hbm_nsu + num_ddr_nsu
total_num_aximm_nmu = num_aximm_nmu + num_hbm_nmu

numAxisPackets = 100  # For AXIS traffic testing

print("=" * 60)
print("CPU NoC Bridge Test Configuration")
print("=" * 60)
print(f"AXIMM NSU: {aximm_nsu}")
print(f"AXIMM NMU (will be CPU): {aximm_nmu}")
print(f"HBM NSU: {hbm_nsu}")
print(f"HBM NMU: {hbm_nmu}")
print(f"HBM channels: {hbm_channels}")
print(f"DDR NSU: {ddr_nsu}")
print(f"DDR channels: {ddr_channels}")
print(f"AXIS NSU: {axis_nsu}")
print(f"AXIS NMU: {axis_nmu}")
print(f"Address map: {address_name_map}")
print("=" * 60)

# =============================================================================
# Create tiles (NocNodes)
# Order: aximm_nsu → hbm_nsu → ddr_nsu → axis_nsu → aximm_nmu → hbm_nmu → axis_nmu
# =============================================================================
tiles = []
master_nodes = []
slave_nodes = []
nameToID = {}
node_conn_names = []

def add_node_connection(tile_obj, ni_name):
    tiles.append(tile_obj)
    node_conn_names.append([ni_name])

n = 0

# AXIMM NSU tiles (BRAM-like storage)
for i in range(num_aximm_nsu):
    tile_name = aximm_nsu[i]
    nameToID[tile_name] = n
    
    # Find address range for this NSU from address_name_map
    nsu_base_addr = 0
    nsu_mem_size = 64 * 1024  # Default 64KB
    for start, end, name in address_name_map:
        if name == tile_name:
            nsu_base_addr = start
            nsu_mem_size = end - start  # end is exclusive
            print(f"  {tile_name}: base=0x{nsu_base_addr:x} size=0x{nsu_mem_size:x}")
            break
    
    tile_obj = BramEndpoint(
        sim_cycles=options.sim_cycles,
        base_addr=nsu_base_addr,
        memory_size=nsu_mem_size
    )
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

# HBM NSU tiles
for i in range(num_hbm_nsu):
    tile_name = hbm_nsu[i]
    nameToID[tile_name] = n
    tile_obj = tileNSU_HBM(
        sim_cycles=options.sim_cycles,
        requestorId=i
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

# AXIS NSU tiles
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

# Parent slave nodes immediately
# system.slave_nodes = slave_nodes

# =============================================================================
# NMU tiles - CpuNocBridge as the NMU
# =============================================================================
cpu_bridges = []  # Store bridges to set network later
cpus = []         # Store CPUs
membuses = []     # Store membuses

# Build addr_ranges from topology's address map
# Note: address_name_map is (start_addr, end_addr, name) tuples
bridge_addr_ranges = []
for (start, end, name) in address_name_map:
    bridge_addr_ranges.append(AddrRange(start, size=(end - start)))
if not bridge_addr_ranges:
    bridge_addr_ranges = [AddrRange(0x0, size='4GB')]  # Fallback

# SE mode uses default stack at ~0xbf000000, which is outside the DDR range
# We need to extend to 4GB to include the stack region
# Override the ranges to use full 4GB for SE mode compatibility
bridge_addr_ranges = [AddrRange(0x0, size='4GB')]
print(f"Using 4GB address range for SE mode stack compatibility")

# AXIMM NMU tiles (CPU + bridge)
# AXIMM NMU tiles (TG + bridge)
tgs = []
for i, tile_name in enumerate(aximm_nmu):
    nameToID[tile_name] = n
    
    # Create CpuNocBridge as the NMU tile
    bridge = CpuNocBridge(
        max_outstanding=4,
        addr_ranges=bridge_addr_ranges,
        sim_cycles=options.sim_cycles,
    )
    cpu_bridges.append(bridge)
    
    # Create Traffic Generator
    tg = PyTrafficGen()
    tgs.append(tg)
    
    # Connect TG directly to Bridge (TG Master -> Bridge Slave)
    tg.port = bridge.cpu_side
    
    master_nodes.append(bridge)
    add_node_connection(bridge, tile_name)
    n += 1

# HBM NMU tiles (for now, use tile.cc traffic generator)
for i in range(num_hbm_nmu):
    tile_name = hbm_nmu[i]
    nameToID[tile_name] = n
    tile_obj = tile(
        sim_cycles=options.sim_cycles,
        interleaved=options.interleaved,
        do_writes=options.do_writes,
        do_reads=options.do_reads,
        num_reads=options.num_packets,
        read_size=options.read_size,
        read_length=options.read_length,
        bandwidth=options.bandwidth,
        clk_period=options.clk_period,
        addr_options=src_addr_options.get(tile_name, []),
    )
    master_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

# AXIS NMU tiles
for i in range(num_axis_nmu):
    tile_name = axis_nmu[i]
    nameToID[tile_name] = n
    tile_obj = AxisRandomTrafficGenerator(
        max_gap_cycles=0,
        data_width=512,
        max_tid=0,
        max_tdest=0,
        max_packets=numAxisPackets
    )
    master_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

# Parent master nodes immediately
# system.master_nodes = master_nodes
system.noc_tiles = tiles

# Set functional memory for bridges (now that everyone has a parent)
for bridge in cpu_bridges:
    bridge.functional_memory = slave_nodes[0] if slave_nodes else None
    bridge.run_consistency_check = True

final_num_tiles = n
print(f"Total tiles: {final_num_tiles}")

# =============================================================================
# System setup
# =============================================================================
# system = System() # Already created

# Configure TGs
system.tgs = tgs

# Clock and voltage domains
system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)
system.clk_domain = SrcClockDomain(
    clock=options.sys_clock, voltage_domain=system.voltage_domain
)

# Set TG clock domains
for tg in system.tgs:
    tg.clk_domain = system.clk_domain

# Configure HBM if there are HBM channels
if len(hbm_channels) > 0:
    configure_hbm(system, hbm_channels, num_hbm_nsu, num_aximm_nsu)

# Configure DDR if there are DDR channels
if len(ddr_channels) > 0:
    # DDR NSU tiles start after aximm_nsu + hbm_nsu
    ddr_nsu_start_idx = num_aximm_nsu + num_hbm_nsu
    configure_ddr(system, ddr_channels, num_ddr_nsu, ddr_nsu_start_idx)

# If no memory backend (DDR/HBM), create SimpleMemory for the address ranges
# This is needed because CPUs check system.isMemAddr() before access
if len(ddr_channels) == 0 and len(hbm_channels) == 0:
    from m5.objects import SimpleMemory
    
    # Create SimpleMemory objects for each address range
    simple_mems = []
    for i, addr_range in enumerate(bridge_addr_ranges):
        mem = SimpleMemory(range=addr_range, latency='1ns')
        simple_mems.append(mem)
        print(f"Created SimpleMemory for range {i}: {addr_range}")
    
    system.memories = simple_mems
    system.mem_ranges = bridge_addr_ranges
    print(f"Registered {len(bridge_addr_ranges)} address ranges with SimpleMemory backends")

# =============================================================================
# NoC setup
# =============================================================================
system.noc = NocSystem()
noc = system.noc

(network, IntLinkClass, ExtLinkClass, RouterClass) = create_network(options, noc)
noc.network = network
network.routing_algorithm = options.routing_algorithm
network.number_of_virtual_networks = options.number_of_virtual_networks

# Address map
address_ID_map = address_to_id(address_name_map, nameToID)
network.address_map_json = json.dumps(address_ID_map)

# Create AXIS tdest-to-dest_ni mapping and pass to network
axis_tdest_id_map = axis_tdest_name_to_id(axis_nmu_to_dest_names, nameToID)
axis_tdest_map_json_string = json.dumps(axis_tdest_id_map)
network.axis_tdest_map_json = axis_tdest_map_json_string

# Set network on CpuNocBridge instances (deferred because network wasn't created yet)
for bridge in cpu_bridges:
    bridge.noc_network = network

# =============================================================================
# Controllers (NocInterfaces)
# Order must match tile order: aximm_nsu → hbm_nsu → ddr_nsu → axis_nsu → aximm_nmu → hbm_nmu → axis_nmu
# =============================================================================
controllers = []
record = 2
n = 0

# AXIMM NSU controllers
for i in range(num_aximm_nsu):
    ctrl_name = aximm_nsu[i]
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

# HBM NSU controllers
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

# AXIS NSU controllers
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

# AXIMM NMU controllers (for CPU bridge)
for tile_name in aximm_nmu:
    newController = NocInterface(
        id=n, version=n,
        nocname=tile_name,
        protocol="AXIMM",
        role="Master",
        noc_system=noc,
        record_mode=record
    )
    controllers.append(newController)
    n += 1

# HBM NMU controllers
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

# AXIS NMU controllers
for i in range(num_axis_nmu):
    ctrl_name = axis_nmu[i]
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

# =============================================================================
# Topology
# =============================================================================
topology_helper = NoC_Topology(controllers)
topology_helper.set_file_path(ncr_filename)
topology_helper.set_node_dict(nameToID)

print("Building NoC topology...")
topology_helper.makeTopology(
    options, network, IntLinkClass, ExtLinkClass, RouterClass
)
init_network(options, network, num_aximm_nsu, num_aximm_nmu, num_hbm_nsu, num_hbm_nmu, num_axis_nsu, num_axis_nmu, num_ddr_nsu)

noc.num_of_sequencers = 0
noc.number_of_virtual_networks = 5

# Connect tiles to controllers
# Connect tiles to controllers
for i in range(final_num_tiles):
    tiles[i].tile_controller = system.noc.tile_controllers[i]

network.num_aximm_nmu = total_num_aximm_nmu
network.num_aximm_nsu = total_num_aximm_nsu

# Build adjacency list
adjacency_list = []
adjacency_index = []
for conn_names in node_conn_names:
    adjacency_index.append(len(adjacency_list))
    for ni_name in conn_names:
        adjacency_list.append(nameToID[ni_name])

# Control object
system.control = Control(
    noc_interfaces=controllers,
    nodes=tiles,
    adjacency_list=adjacency_list,
    adjacency_index=adjacency_index,
    sim_cycles=options.sim_cycles,
)

system.noc.clk_domain = SrcClockDomain(
    clock=options.noc_clock, voltage_domain=system.voltage_domain
)

for t in tiles:
    t.clk_domain = system.clk_domain

# =============================================================================
# Simulation
# =============================================================================
root = Root(full_system=False, system=system)
root.system.mem_mode = "timing"

m5.ticks.setGlobalFrequency("1ps")

print("Instantiating simulation...")
m5.instantiate()

# Define traffic pattern
def create_traffic_pattern(tgen):
    # duration, start_addr, end_addr, block_size, min_period, max_period, read_percent, data_limit
    # Run for 1ms simulated time, range 0x0-0x2000, 64 bytes, 1ns period, 50% reads
    yield tgen.createLinear(1000000000, 0x0, 0x2000, 64, 1000, 1000, 50, 0)
    yield tgen.createExit(0)

print("Starting Traffic Generators...")
for tg in tgs:
    tg.start(create_traffic_pattern(tg))

print("Running simulation...")
exit_event = m5.simulate(options.abs_max_tick)

print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
