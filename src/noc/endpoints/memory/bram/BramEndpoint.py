from m5.params import *
from m5.proxy import *
from m5.objects import NocNode


class BramEndpoint(NocNode):
    type = "BramEndpoint"
    cxx_header = "noc/endpoints/memory/bram/BramEndpoint.hh"
    cxx_class = "gem5::noc::BramEndpoint"

    tile_controller = Param.NocInterface("")
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    # BRAM configuration parameters
    base_addr = Param.Addr(0, "Base address of BRAM region")
    memory_size = Param.UInt64(65536, "Size of BRAM storage in bytes")
    read_latency = Param.Cycles(1, "Read latency in cycles")
    write_latency = Param.Cycles(1, "Write latency in cycles")
