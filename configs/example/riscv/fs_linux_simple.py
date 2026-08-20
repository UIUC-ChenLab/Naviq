
import argparse
import sys
import os

import m5
from m5.objects import *
from m5.util import addToPath
from m5.util.fdthelper import *



def generateMemNode(state, mem_range):
    node = FdtNode("memory@%x" % int(mem_range.start))
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
    fdt.writeDtsFile(os.path.join(m5.options.outdir, "device.dts"))
    fdt.writeDtbFile(os.path.join(m5.options.outdir, "device.dtb"))

# Argument Parsing
parser = argparse.ArgumentParser()
parser.add_argument("--kernel", type=str, required=True, help="Path to kernel binary")
parser.add_argument("--disk-image", type=str, required=True, help="Path to disk image")
args = parser.parse_args()

# System Config
system = System()

system.clk_domain = SrcClockDomain()
system.clk_domain.clock = "1GHz"
system.clk_domain.voltage_domain = VoltageDomain()

system.mem_mode = "atomic"
system.mem_ranges = [AddrRange(0x80000000, size="512MiB")]

# CPU
system.cpu = [AtomicSimpleCPU(cpu_id=0)]

# Buses
system.membus = SystemXBar()

# Connect CPU
for cpu in system.cpu:
    cpu.createThreads()
    cpu.icache_port = system.membus.cpu_side_ports
    cpu.dcache_port = system.membus.cpu_side_ports
    cpu.createInterruptController()
    cpu.mmu.connectWalkerPorts(system.membus.cpu_side_ports, system.membus.cpu_side_ports)

# Platform
system.platform = HiFive()
system.platform.rtc = RiscvRTC(frequency=Frequency("100MHz"))
system.platform.clint.int_pin = system.platform.rtc.int_pin


# IO Bus (Must be created before attaching devices)
system.iobus = IOXBar()
system.bridge = Bridge(delay="50ns")
system.bridge.mem_side_port = system.iobus.cpu_side_ports
system.bridge.cpu_side_port = system.membus.mem_side_ports

# VirtIO Disk
image = CowDiskImage(
    child=RawDiskImage(image_file=args.disk_image, read_only=True),
    read_only=False,
)
system.platform.disk = RiscvMmioVirtIO(
    vio=VirtIOBlock(image=image),
    interrupt_id=0x8,
    pio_size=4096,
    pio_addr=0x10008000,
)
system.platform.pci_host.pio = system.iobus.mem_side_ports

# Attach Platform Devices
system.platform.attachOnChipIO(system.membus)
system.platform.attachOffChipIO(system.iobus)
system.platform.attachPlic()
system.platform.setNumCores(len(system.cpu))

# Set bridge ranges AFTER all devices are attached (so they are included in _off_chip_ranges)
system.bridge.ranges = system.platform._off_chip_ranges()

# Workload
system.workload = RiscvLinux()
system.workload.object_file = args.kernel
system.workload.command_line = "console=ttyS0 root=/dev/vda ro"

# DTB
system.workload.dtb_addr = 0x87E00000
generateDtb(system)
system.workload.dtb_filename = os.path.join(m5.options.outdir, "device.dtb")

# Memory Controller
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

system.system_port = system.membus.cpu_side_ports

root = Root(full_system=True, system=system)
m5.instantiate()

print("Beginning simulation!")
exit_event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
