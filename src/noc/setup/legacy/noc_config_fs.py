"""
NoC Full System (FS) Mode Configuration

Boots a Linux kernel through the NoC using a CPU. Supports both ARM and RISC-V
by auto-detecting the ISA from the gem5 build.

Usage (RISC-V):
  ./build/RISCV/gem5.opt src/noc/setup/legacy/noc_config_fs.py \
      --noc-topology=src/noc/topology/topologies/1nmu_to_ddr \
      --kernel=fs_resources/riscv/bootloader-vmlinux-5.10 \
      --disk-image=fs_resources/riscv/riscv-disk.img

Usage (ARM):
  ./build/ARM/gem5.opt src/noc/setup/legacy/noc_config_fs.py \
      --noc-topology=src/noc/topology/topologies/1nmu_to_ddr \
      --kernel=fs_resources/arm/binaries/vmlinux.arm64 \
      --disk-image=fs_resources/arm/ubuntu-18.04-arm64-docker.img
"""

import json
import os
from os import path
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

# =============================================================================
# Detect ISA
# =============================================================================
if buildEnv.get("USE_RISCV_ISA", False):
    TARGET_ISA = "riscv"
elif buildEnv.get("USE_ARM_ISA", False):
    TARGET_ISA = "arm"
elif buildEnv.get("USE_X86_ISA", False):
    TARGET_ISA = "x86"
else:
    m5.fatal("FS mode not supported: build with ARM, RISCV, or X86 ISA.")

print(f"Detected ISA: {TARGET_ISA}")

if TARGET_ISA == "riscv":
    from m5.util.fdthelper import *

# =============================================================================
# Cache Definitions
# =============================================================================
class L1Cache(Cache):
    assoc = 2
    tag_latency = 2
    data_latency = 2
    response_latency = 2
    mshrs = 4
    tgts_per_mshr = 20

class L1ICache(L1Cache):
    size = '16kB'

class L1DCache(L1Cache):
    size = '64kB'

class L2Cache(Cache):
    size = '256kB'
    assoc = 8
    tag_latency = 12 # 20
    data_latency = 12 # 20
    response_latency = 12 # 20
    mshrs = 20
    tgts_per_mshr = 12

USE_CPU_CACHES = True

# =============================================================================
# RISC-V DTB Generation
# =============================================================================
def generateMemNode(state, mem_range):
    node = FdtNode(f"memory@{int(mem_range.start):x}")
    node.append(FdtPropertyStrings("device_type", ["memory"]))
    node.append(
        FdtPropertyWords(
            "reg",
            state.addrCells(mem_range.start)
            + state.sizeCells(mem_range.size()),
        )
    )
    return node


def generateDtb(system):
    state = FdtState(addr_cells=2, size_cells=2, cpu_cells=1)
    root = FdtNode("/")
    root.append(state.addrCellsProperty())
    root.append(state.sizeCellsProperty())
    root.appendCompatible(["riscv-virtio"])

    for mem_range in system.mem_ranges:
        root.append(generateMemNode(state, mem_range))

    sections = [*system.cpu, system.platform]

    for section in sections:
        for node in section.generateDeviceTree(state):
            if node.get_name() == root.get_name():
                root.merge(node)
            else:
                root.append(node)

    node = FdtNode("chosen")
    node.append(FdtPropertyStrings("bootargs", [system.workload.command_line]))
    node.append(FdtPropertyStrings("stdout-path", ["/uart@10000000"]))
    root.append(node)

    fdt = Fdt()
    fdt.add_rootnode(root)
    fdt.writeDtsFile(path.join(m5.options.outdir, "device.dts"))
    fdt.writeDtbFile(path.join(m5.options.outdir, "device.dtb"))


# =============================================================================
# Options
# =============================================================================
buildEnv["PROTOCOL"] = "Garnet_standalone"

options = get_parser()

if options.network != "nocgarnet":
    m5.fatal("Unsupported network type: {}".format(options.network))

if not options.kernel:
    m5.fatal("--kernel is required for FS mode")

# =============================================================================
# Create System
# =============================================================================
if TARGET_ISA == "arm":
    system = ArmSystem()
else:
    system = System()

# =============================================================================
# Parse Topology
# =============================================================================
filename = options.noc_topology
nts_filename = filename + ".nts"
ncr_filename = filename + ".ncr"

(address_name_map, aximm_nsu, aximm_nmu, axis_nsu, axis_nmu,
 hbm_nsu, hbm_nmu, hbm_channels, ddr_nsu, ddr_channels,
 src_addr_options, axis_nmu_to_dest_names) = get_address_map(nts_filename)

num_aximm_nsu = len(aximm_nsu)
num_aximm_nmu = len(aximm_nmu)
num_hbm_nsu = len(hbm_nsu)
num_hbm_nmu = len(hbm_nmu)
num_ddr_nsu = len(ddr_nsu)
num_axis_nsu = len(axis_nsu)
num_axis_nmu = len(axis_nmu)

total_num_aximm_nsu = num_aximm_nsu + num_hbm_nsu + num_ddr_nsu
total_num_aximm_nmu = num_aximm_nmu + num_hbm_nmu

numAxisPackets = 100

print("=" * 60)
print("NoC Full System Configuration")
print("=" * 60)
print(f"ISA: {TARGET_ISA}")
print(f"Kernel: {options.kernel}")
print(f"Disk Image: {options.disk_image}")
print(f"AXIMM NSU: {aximm_nsu}")
print(f"AXIMM NMU (CPU): {aximm_nmu}")
print(f"DDR NSU: {ddr_nsu}")
print(f"DDR channels: {ddr_channels}")
print(f"Address map: {address_name_map}")
print("=" * 60)

# =============================================================================
# Create tiles (NocNodes)
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

# AXIMM NSU tiles (BRAM endpoints)
for i in range(num_aximm_nsu):
    tile_name = aximm_nsu[i]
    nameToID[tile_name] = n
    tile_obj = tileNSU_HBM(
        sim_cycles=options.sim_cycles,
        requestorId=i,
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
        requestorId=i,
    )
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

# DDR NSU tiles
for i in range(num_ddr_nsu):
    tile_name = ddr_nsu[i]
    nameToID[tile_name] = n
    tile_obj = tileNSU_HBM(
        sim_cycles=options.sim_cycles,
        requestorId=i,
    )
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

# AXIS NSU tiles
for i in range(num_axis_nsu):
    tile_name = axis_nsu[i]
    nameToID[tile_name] = n
    tile_obj = AxisRandomTrafficGenerator(
        max_gap_cycles=0,
        data_width=512,
        max_tid=0,
        max_tdest=0,
        max_packets=numAxisPackets,
    )
    slave_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

# =============================================================================
# NMU tiles - CpuNocBridge as the NMU
# =============================================================================
cpu_bridges = []
cpus = []
membuses = []
icaches = []
dcaches = []
l2caches = []

# Build address ranges from topology
bridge_addr_ranges = []
for (start, end, name) in address_name_map:
    bridge_addr_ranges.append(AddrRange(start, size=(end - start)))
if not bridge_addr_ranges:
    bridge_addr_ranges = [AddrRange(0x0, size='4GB')]

# FS mode: memory starts at 0x80000000 for ARM and RISC-V, but 0x0 for X86
if TARGET_ISA == "x86":
    fs_mem_base = 0x0
    # Provide the string representation for mdesc
    fs_mem_size_str = "512MiB"
    fs_mem_size_bytes = 512 * 1024 * 1024
    
    # x86 requires memory holes if > 3GB. `makeLinuxX86System` splits this into `mem_ranges` automatically.
    # To keep NoC routing simple, we will map the single overarching DDR region from the topology 
    # directly into `fs_mem_base` for `fs_mem_size_bytes`, and let the CpuNocBridge accept everything 
    # except the I/O bus ranges.
    system.mem_ranges = [AddrRange(start=fs_mem_base, size=fs_mem_size_bytes)]
    noc_bridge_ranges = system.mem_ranges
else:
    fs_mem_base = 0x80000000
    fs_mem_size = '2GiB'
    fs_mem_size_bytes = 2 * 1024 * 1024 * 1024
    system.mem_ranges = [AddrRange(start=fs_mem_base, size=fs_mem_size)]
    noc_bridge_ranges = [AddrRange(start=fs_mem_base, size=fs_mem_size)]

# Override DDR entries in NoC address map to match FS memory
new_address_name_map = []
for start, end, name in address_name_map:
    # Check if the destination is a DDR NSU port
    is_ddr = any(name.startswith(ddr_name) for ddr_name in ddr_nsu)
    if is_ddr:
        print(f"  Overriding NoC address mapping for {name} to {hex(fs_mem_base)}-{hex(fs_mem_base + fs_mem_size_bytes)}")
        new_address_name_map.append((fs_mem_base, fs_mem_base + fs_mem_size_bytes, name))
    else:
        new_address_name_map.append((start, end, name))
address_name_map = new_address_name_map

print(f"FS memory range: {fs_mem_base:#x} - {fs_mem_base + fs_mem_size_bytes:#x}")

# AXIMM NMU tiles (CPU + bridge)
for i, tile_name in enumerate(aximm_nmu):
    nameToID[tile_name] = n

    bridge = CpuNocBridge(
        max_outstanding=4,
        addr_ranges=noc_bridge_ranges,
        sim_cycles=options.sim_cycles,
    )
    cpu_bridges.append(bridge)

    # Create CPU
    print(f"Instantiating CPU type: {options.cpu_type}")
    if options.cpu_type == "AtomicSimple":
        if TARGET_ISA == "arm":
             cpu = AtomicSimpleCPU(cpu_id=i)
        else:
             cpu = X86AtomicSimpleCPU(cpu_id=i)
    elif options.cpu_type == "O3":
        if TARGET_ISA == "arm":
            cpu = O3CPU(cpu_id=i)
        else:
            cpu = X86O3CPU(cpu_id=i)
    else: # Default or TimingSimple
        if TARGET_ISA == "arm":
            cpu = TimingSimpleCPU(cpu_id=i)
        else:
            cpu = X86TimingSimpleCPU(cpu_id=i)
            
    cpus.append(cpu)

    # Create membus (coherent crossbar) for this CPU
    membus = SystemXBar()
    membuses.append(membus)

    if USE_CPU_CACHES:
        icache = L1ICache()
        dcache = L1DCache()
        icaches.append(icache)
        dcaches.append(dcache)

        cpu.icache_port = icache.cpu_side
        cpu.dcache_port = dcache.cpu_side

        icache.mem_side = membus.cpu_side_ports
        dcache.mem_side = membus.cpu_side_ports
    else:
        cpu.icache_port = membus.cpu_side_ports
        cpu.dcache_port = membus.cpu_side_ports

    # Create L2 Cache
    if USE_CPU_CACHES:
        l2cache = L2Cache()
        l2caches.append(l2cache)
        
        # Connect L2 as the DEFAULT port on membus.
        # The I/O bridge claims specific device ranges. The L2 (default)
        # catches everything else, including kernel virtual addresses like
        # 0xffffffe000c04000 that don't match any declared range.
        membus.default = l2cache.cpu_side
        
        # Connect L2 to Bridge
        l2cache.mem_side = bridge.cpu_side
    else:
        # Connect membus to NocBridge directly for memory traffic
        membus.default = bridge.cpu_side

    # Create interrupt controller
    cpu.createInterruptController()
    if TARGET_ISA == "x86":
        cpu.interrupts[0].pio = membus.mem_side_ports
        cpu.interrupts[0].int_requestor = membus.cpu_side_ports
        cpu.interrupts[0].int_responder = membus.mem_side_ports

    # Connect MMU page table walker ports (required for FS mode)
    cpu.mmu.connectWalkerPorts(membus.cpu_side_ports, membus.cpu_side_ports)

    master_nodes.append(bridge)
    add_node_connection(bridge, tile_name)
    n += 1

# HBM NMU tiles
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
        max_packets=numAxisPackets,
    )
    master_nodes.append(tile_obj)
    add_node_connection(tile_obj, tile_name)
    n += 1

# Parent tiles
system.noc_tiles = tiles

# Set functional memory for bridges
for bridge in cpu_bridges:
    bridge.functional_memory = slave_nodes[0] if slave_nodes else None
    bridge.run_consistency_check = False

final_num_tiles = n
print(f"Total tiles: {final_num_tiles}")

# =============================================================================
# System Setup
# =============================================================================
system.cpu = cpus if len(cpus) > 1 else cpus[0]
system.membuses = membuses

# Clock and voltage domains
system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)
system.clk_domain = SrcClockDomain(
    clock=options.sys_clock, voltage_domain=system.voltage_domain
)

for cpu in cpus:
    cpu.clk_domain = system.clk_domain

if USE_CPU_CACHES:
    system.icaches = icaches
    system.dcaches = dcaches
    for cache in system.icaches:
        cache.clk_domain = system.clk_domain
    for cache in system.dcaches:
        cache.clk_domain = system.clk_domain
    
    system.l2caches = l2caches
    for cache in system.l2caches:
        cache.clk_domain = system.clk_domain

# =============================================================================
# I/O Bus for platform devices (bypasses NoC)
# =============================================================================
system.iobus = IOXBar()

# Single bridge from the first CPU's membus to iobus for I/O traffic
system.bridge = Bridge(delay="1ns")
system.bridge.cpu_side_port = membuses[0].mem_side_ports

# =============================================================================
# Platform and Workload Setup (ISA-specific)
# =============================================================================
if TARGET_ISA == "riscv":
    # --- RISC-V FS Setup ---
    system.workload = RiscvLinux()
    system.workload.object_file = options.kernel

    # HiFive platform
    system.platform = HiFive()
    system.platform.rtc = RiscvRTC(frequency=Frequency("10MHz"))
    system.platform.clint.int_pin = system.platform.rtc.int_pin
    system.platform.uart.pio_latency = "1ns"
    system.platform.clint.pio_latency = "1ns"
    system.platform.plic.pio_latency = "1ns"

    # Connect PCI host to iobus
    system.platform.pci_host.pio = system.iobus.mem_side_ports

    # VirtIO disk (optional)
    if options.disk_image:
        image = CowDiskImage(
            child=RawDiskImage(image_file=options.disk_image, read_only=True),
            read_only=False,
        )
        system.platform.disk = RiscvMmioVirtIO(
            vio=VirtIOBlock(image=image),
            interrupt_id=0x8,
            pio_size=4096,
            pio_addr=0x10008000,
        )

    # I/O bridge ranges  
    system.bridge.mem_side_port = system.iobus.cpu_side_ports
    system.bridge.ranges = system.platform._off_chip_ranges()

    # On-chip devices connect to membus directly
    system.platform.attachOnChipIO(membuses[0])
    system.platform.attachOffChipIO(system.iobus)
    system.platform.attachPlic()
    system.platform.setNumCores(len(cpus))

    # PMA checker for marking I/O as uncacheable
    uncacheable_range = [
        *system.platform._on_chip_ranges(),
        *system.platform._off_chip_ranges(),
    ]
    for cpu in cpus:
        cpu.mmu.pma_checker = PMAChecker(uncacheable=uncacheable_range)

    # Linux boot command
    kernel_cmd = ["console=ttyS0", "root=/dev/vda", "ro"]
    system.workload.command_line = " ".join(kernel_cmd)

    # DTB generation
    system.workload.dtb_addr = 0x87E00000
    generateDtb(system)
    system.workload.dtb_filename = path.join(m5.options.outdir, "device.dtb")

    # CPU threads
    for cpu in cpus:
        cpu.createThreads()

elif TARGET_ISA == "arm":
    # --- ARM FS Setup ---
    from common import SysPaths

    system.workload = ArmFsLinux(object_file=options.kernel)

    # VExpress_GEM5_V1 platform corresponds to `starter_fs.py` defaults
    system.realview = VExpress_GEM5_V1()

    # Peripherals that RealView proxies depend on
    system.terminal = Terminal()
    system.vncserver = VncServer()

    # Release info
    system.release = ArmDefaultRelease()

    # Highest EL is 64-bit (AArch64)
    system.highest_el_is_64 = True

    # I/O bridge ranges
    system.bridge.mem_side_port = system.iobus.cpu_side_ports
    system.bridge.ranges = system.realview._off_chip_ranges

    # Attach platform I/O
    system.realview.attachOnChipIO(membuses[0], system.bridge)
    system.realview.attachIO(system.iobus)

    # VirtIO disk
    if options.disk_image:
        image = CowDiskImage(
            child=RawDiskImage(image_file=options.disk_image, read_only=True),
            read_only=False,
        )
        system.pci_devices = [
            PciVirtIO(vio=VirtIOBlock(image=image))
        ]
        for dev in system.pci_devices:
            system.realview.attachPciDevice(dev, system.iobus)

    # Setup bootloader
    bootloader_path = os.path.join(
        os.path.dirname(options.kernel), "boot_v2.arm64"
    )
    if os.path.exists(bootloader_path):
        system.realview.setupBootLoader(
            system, lambda name: os.path.join(os.path.dirname(options.kernel), name)
        )
    else:
        system.realview.setupBootLoader(system, SysPaths.binary)

    # Linux boot command
    kernel_cmd = [
        "console=ttyAMA0",
        "lpj=19988480",
        "norandmaps",
        "root=/dev/vda1",
        "rw",
        f"mem={fs_mem_size}",
    ]
    system.workload.command_line = " ".join(kernel_cmd)

    # DTB generation
    system.workload.dtb_filename = os.path.join(m5.options.outdir, "system.dtb")
    system.generateDtb(system.workload.dtb_filename)

    # CPU threads
    for cpu in cpus:
        cpu.createThreads()

elif TARGET_ISA == "x86":
    # --- X86 FS Setup ---
    # Replicates makeX86System / connectX86ClassicSystem / makeLinuxX86System
    # from configs/common/FSConfig.py, adapted for our NoC architecture.
    from common import SysPaths
    from common.SysPaths import binary

    IO_address_space_base = 0x8000000000000000
    pci_config_address_space_base = 0xC000000000000000
    interrupts_address_space_base = 0xA000000000000000
    APIC_range_size = 1 << 12

    system.m5ops_base = 0xFFFF0000

    # Workload
    system.workload = X86FsLinux()
    system.workload.object_file = options.kernel

    # Platform
    system.pc = Pc()

    # Bridge: membus[0] -> iobus (for PCI/IO device access)
    system.bridge.mem_side_port = system.iobus.cpu_side_ports
    system.bridge.ranges = [
        AddrRange(0xC0000000, 0xFFFF0000),
        AddrRange(IO_address_space_base, interrupts_address_space_base - 1),
        AddrRange(pci_config_address_space_base, Addr.max),
    ]

    # APIC bridge: iobus -> membus[0] (for local APIC access)
    system.apicbridge = Bridge(delay="50ns")
    system.apicbridge.cpu_side_port = system.iobus.mem_side_ports
    system.apicbridge.mem_side_port = membuses[0].cpu_side_ports
    system.apicbridge.ranges = [
        AddrRange(
            interrupts_address_space_base,
            interrupts_address_space_base + len(cpus) * APIC_range_size - 1,
        )
    ]

    # Attach south bridge I/O devices to iobus
    system.pc.attachIO(system.iobus)

    # Disk image (via IDE on south bridge)
    if options.disk_image:
        from common.FSConfig import makeCowDisks
        from common.Benchmarks import SysConfig
        mdesc_disk = SysConfig(disks=[options.disk_image], mem="2GiB")
        disks = makeCowDisks(mdesc_disk.disks())
        system.pc.south_bridge.ide.disks = disks

    # Note: system.system_port is connected in noc_ddr_config.py

    # --- Intel MP Table & ACPI ---
    numCPUs = len(cpus)
    base_entries = []
    ext_entries = []
    madt_records = []
    for i in range(numCPUs):
        bp = X86IntelMPProcessor(
            local_apic_id=i,
            local_apic_version=0x14,
            enable=True,
            bootstrap=(i == 0),
        )
        base_entries.append(bp)
        lapic = X86ACPIMadtLAPIC(acpi_processor_id=i, apic_id=i, flags=1)
        madt_records.append(lapic)

    io_apic = X86IntelMPIOAPIC(
        id=numCPUs, version=0x11, enable=True, address=0xFEC00000
    )
    system.pc.south_bridge.io_apic.apic_id = io_apic.id
    base_entries.append(io_apic)
    madt_records.append(
        X86ACPIMadtIOAPIC(id=io_apic.id, address=io_apic.address, int_base=0)
    )

    pci_bus = X86IntelMPBus(bus_id=0, bus_type="PCI   ")
    base_entries.append(pci_bus)
    isa_bus = X86IntelMPBus(bus_id=1, bus_type="ISA   ")
    base_entries.append(isa_bus)
    connect_busses = X86IntelMPBusHierarchy(
        bus_id=1, subtractive_decode=True, parent_bus=0
    )
    ext_entries.append(connect_busses)

    pci_dev4_inta = X86IntelMPIOIntAssignment(
        interrupt_type="INT",
        polarity="ConformPolarity",
        trigger="ConformTrigger",
        source_bus_id=0,
        source_bus_irq=0 + (4 << 2),
        dest_io_apic_id=io_apic.id,
        dest_io_apic_intin=16,
    )
    base_entries.append(pci_dev4_inta)
    madt_records.append(X86ACPIMadtIntSourceOverride(
        bus_source=pci_dev4_inta.source_bus_id,
        irq_source=pci_dev4_inta.source_bus_irq,
        sys_int=pci_dev4_inta.dest_io_apic_intin,
        flags=0,
    ))

    def assignISAInt(irq, apicPin):
        assign_8259_to_apic = X86IntelMPIOIntAssignment(
            interrupt_type="ExtInt",
            polarity="ConformPolarity",
            trigger="ConformTrigger",
            source_bus_id=1,
            source_bus_irq=irq,
            dest_io_apic_id=io_apic.id,
            dest_io_apic_intin=0,
        )
        base_entries.append(assign_8259_to_apic)
        assign_to_apic = X86IntelMPIOIntAssignment(
            interrupt_type="INT",
            polarity="ConformPolarity",
            trigger="ConformTrigger",
            source_bus_id=1,
            source_bus_irq=irq,
            dest_io_apic_id=io_apic.id,
            dest_io_apic_intin=apicPin,
        )
        base_entries.append(assign_to_apic)
        madt_records.append(X86ACPIMadtIntSourceOverride(
            bus_source=1, irq_source=irq, sys_int=apicPin, flags=0
        ))

    assignISAInt(0, 2)
    assignISAInt(1, 1)
    for i in range(3, 15):
        assignISAInt(i, i)
    system.workload.intel_mp_table.base_entries = base_entries
    system.workload.intel_mp_table.ext_entries = ext_entries

    madt = X86ACPIMadt(
        local_apic_address=0, records=madt_records, oem_id="madt"
    )
    system.workload.acpi_description_table_pointer.rsdt.entries.append(madt)
    system.workload.acpi_description_table_pointer.xsdt.entries.append(madt)
    system.workload.acpi_description_table_pointer.oem_id = "gem5"
    system.workload.acpi_description_table_pointer.rsdt.oem_id = "gem5"
    system.workload.acpi_description_table_pointer.xsdt.oem_id = "gem5"

    # BIOS info
    structures = [X86SMBiosBiosInformation()]
    system.workload.smbios_table.structures = structures

    # --- E820 Memory Map (from makeLinuxX86System) ---
    phys_mem_size = sum([r.size() for r in system.mem_ranges])
    entries = [
        X86E820Entry(addr=0, size="639KiB", range_type=1),
        X86E820Entry(addr=0x9FC00, size="385KiB", range_type=2),
        X86E820Entry(
            addr=0x100000,
            size="%dB" % (system.mem_ranges[0].size() - 0x100000),
            range_type=1,
        ),
    ]
    if len(system.mem_ranges) == 1:
        entries.append(
            X86E820Entry(
                addr=system.mem_ranges[0].size(),
                size="%dB" % (0xC0000000 - system.mem_ranges[0].size()),
                range_type=2,
            )
        )
    entries.append(X86E820Entry(addr=0xFFFF0000, size="64KiB", range_type=2))
    if len(system.mem_ranges) == 2:
        entries.append(
            X86E820Entry(
                addr=0x100000000,
                size="%dB" % (system.mem_ranges[1].size()),
                range_type=1,
            )
        )
    system.workload.e820_table.entries = entries

    # Command line
    system.workload.command_line = \
        "earlyprintk=ttyS0 console=ttyS0 lpj=7999923 root=/dev/hda1"

    # CPU threads (populates cpu.isa automatically)
    for cpu in cpus:
        cpu.createThreads()

# =============================================================================
# Configure DDR Memory
# =============================================================================
if len(ddr_channels) > 0:
    ddr_nsu_start_idx = num_aximm_nsu + num_hbm_nsu
    configure_ddr(system, ddr_channels, num_ddr_nsu, ddr_nsu_start_idx)
    
    # In FS mode, override DDR ranges to match the FS memory range.
    # configure_ddr uses the raw topology range (e.g. 0x0, 4GiB) but FS mode
    # needs memory at 0x80000000. This also ensures checkpoint/restore
    # compatibility with fs_linux_simple.py which uses the same FS range.
    fs_range = AddrRange(start=fs_mem_base, size=fs_mem_size_bytes)
    system.mem_ranges = [fs_range]
    
    for i in range(len(ddr_channels)):
        ctrl = getattr(system, f"mem_ctrl_{i}")
        ctrl.dram.range = fs_range
    print(f"  Overrode DDR range to FS range: {fs_mem_base:#x}, size={fs_mem_size_bytes}")

if len(hbm_channels) > 0:
    configure_hbm(system, hbm_channels, num_hbm_nsu, num_aximm_nsu)

# If no DDR/HBM, create SimpleMemory
if len(ddr_channels) == 0 and len(hbm_channels) == 0:
    from m5.objects import SimpleMemory
    simple_mems = []
    for i, addr_range in enumerate(noc_bridge_ranges):
        mem = SimpleMemory(range=addr_range, latency='1ns')
        simple_mems.append(mem)
    system.memories = simple_mems
    print(f"Created {len(simple_mems)} SimpleMemory backends")

# =============================================================================
# NoC Setup
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

# AXIS tdest mapping
axis_tdest_id_map = axis_tdest_name_to_id(axis_nmu_to_dest_names, nameToID)
axis_tdest_map_json_string = json.dumps(axis_tdest_id_map)
network.axis_tdest_map_json = axis_tdest_map_json_string

# Set network on bridges
for bridge in cpu_bridges:
    bridge.noc_network = network

# =============================================================================
# Controllers (NocInterfaces)
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
        record_mode=record,
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
        record_mode=record,
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
        record_mode=1,
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
        record_mode=record,
    )
    controllers.append(newController)
    n += 1

# AXIMM NMU controllers (CPU bridge)
for tile_name in aximm_nmu:
    newController = NocInterface(
        id=n, version=n,
        nocname=tile_name,
        protocol="AXIMM",
        role="Master",
        noc_system=noc,
        record_mode=record,
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
        record_mode=1,
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
        record_mode=record,
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
for i in range(final_num_tiles):
    tiles[i].tile_controller = system.noc.tile_controllers[i]

network.num_aximm_nmu = total_num_aximm_nmu
network.num_aximm_nsu = total_num_aximm_nsu

# Adjacency list
adjacency_list = []
adjacency_index = []
for conn_names in node_conn_names:
    adjacency_index.append(len(adjacency_list))
    for ni_name in conn_names:
        adjacency_list.append(nameToID[ni_name])

# Control
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
if options.script:
    system.readfile = options.script

root = Root(full_system=True, system=system)
if options.cpu_type == "AtomicSimple":
    root.system.mem_mode = "atomic"
else:
    root.system.mem_mode = "timing"

m5.ticks.setGlobalFrequency("1ps")

print("Instantiating simulation...")
if options.checkpoint_dir:
    print(f"Restoring from checkpoint: {options.checkpoint_dir}")
    m5.instantiate(options.checkpoint_dir)
else:
    m5.instantiate()

# =============================================================================
# Workaround: Periodic CPU wakeup after checkpoint restore
# When restoring from a checkpoint, the CPU may enter WFI (Wait For Interrupt)
# but timer interrupts from the CLINT may not properly wake it. This schedules
# periodic wakeup events to force the CPU to resume and check for interrupts.
# =============================================================================
print("Running simulation...")
if options.abs_max_tick:
    max_ticks = options.abs_max_tick - m5.curTick()
    exit_event = m5.simulate(max_ticks)
else:
    exit_event = m5.simulate()

print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
