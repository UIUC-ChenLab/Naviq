from m5.params import *
from m5.proxy import *
from m5.objects import NocNode

class CpuNocBridge(NocNode):
    type = "CpuNocBridge"
    cxx_header = "noc/endpoints/cpu/CpuNocBridge.hh"
    cxx_class = "gem5::noc::CpuNocBridge"

    cpu_side = ResponsePort("Port for CPU to send memory requests")

    noc_system = Param.NocSystem(Parent.any, "NoC system")
    noc_network = Param.NocGarnetNetwork("NoC Garnet network for address mapping")

    max_outstanding = Param.Int(4, "Max outstanding transactions (AXI ID limit)")

    sim_cycles = Param.UInt64(1000000, "Max simulation cycles")
    
    addr_ranges = VectorParam.AddrRange([], "Address ranges handled by this bridge")
    mmio_ranges = VectorParam.AddrRange(
        [], "Ranges that should use narrow MMIO-style AXI accesses"
    )
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    scratch_read_burst_base = Param.Addr(0, "Base of optional CPU DDR scratch burst-read window")
    scratch_read_burst_size = Param.Unsigned(0, "Size of optional CPU DDR scratch burst-read window")
    scratch_read_burst_bytes = Param.Unsigned(
        64,
        "NoC-visible AXI bytes to read for each CPU read inside the scratch window",
    )
    
    functional_memory = Param.NocNode(NULL, "Default backing store for functional access")
    secondary_functional_memory = Param.NocNode(
        NULL, "Optional backing store for selected functional address ranges"
    )
    secondary_functional_ranges = VectorParam.AddrRange(
        [], "Address ranges handled by secondary_functional_memory"
    )
    
    run_consistency_check = Param.Bool(False, "Run functional consistency check at startup")
