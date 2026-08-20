from m5.objects import NocNode
from m5.params import *
from m5.proxy import *


class tile(NocNode):
    type = "tile"
    cxx_header = "noc/endpoints/legacy/tile.hh"
    cxx_class = "gem5::noc::tile"

    tile_controller = Param.NocInterface("")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    interleaved = Param.Bool(True, "true = interleaved RW false = parallel RW")
    do_reads = Param.Bool(True, "Turns reads on")
    do_writes = Param.Bool(True, "Turns writes on")

    num_reads = Param.Int(1, "Number of reads to perform")
    read_size = Param.Int(6, "axi read size")
    read_length = Param.Int(3, "axi read length")
    bandwidth = Param.Int(300, "Read/write bandwidth in MBps")
    clk_period = Param.Int(1000, "Clock period in ps")

    addr_options = VectorParam.UInt64(
        [],
        "list of addresses followed by address sizes per reachable destination",
    )
