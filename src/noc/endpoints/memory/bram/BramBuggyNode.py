from m5.params import *
from m5.proxy import *
from m5.objects import NocNode, BramEndpoint


class BramBuggyNode(NocNode):
    """
    Same constructor surface as BramEndpoint (tile_controller, BRAM geometry, etc.)
    plus ready percentages. JSON uses the same keys as BramEndpoint; noc_config builds
    the inner BramEndpoint from those keys.
    """

    type = "BramBuggyNode"
    cxx_header = "noc/endpoints/memory/bram/BramBuggyNode.hh"
    cxx_class = "gem5::noc::BramBuggyNode"

    tile_controller = Param.NocInterface("")
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    base_addr = Param.Addr(0, "Base address of BRAM region")
    memory_size = Param.UInt64(65536, "Size of BRAM storage in bytes")
    read_latency = Param.Cycles(1, "Read latency in cycles")
    write_latency = Param.Cycles(1, "Write latency in cycles")

    bram = Param.BramEndpoint(
        "Inner BramEndpoint (noc_config builds this from the same JSON parameters "
        "as BramEndpoint when using node_config)"
    )

    awready_percentage = Param.UInt8(
        100, "Percent of cycles asserting AWREADY toward the master (0-100)"
    )
    wready_percentage = Param.UInt8(
        100, "Percent of cycles asserting WREADY toward the master (0-100)"
    )
    arready_percentage = Param.UInt8(
        100, "Percent of cycles asserting ARREADY toward the master (0-100)"
    )
    mutate_response_axi_id_percentage = Param.UInt8(
        0, "Percent of AXI read/write response beats whose ID is overwritten (0-100)"
    )
    mutate_axi_id_val = Param.UInt32(
        0, "AXI ID value to drive on mutated read/write responses"
    )
