from m5.params import *
from m5.proxy import *
from m5.objects import NocNode, AxisSinkNode, BramBuggyNode


class SynchronizerNode(NocNode):
    """
    Two-port wrapper: port 0 is an AxisSinkNode, port 1 is a BramBuggyNode.
    JSON / noc_config supplies the union of parameters for both inner nodes;
    noc_config constructs the children and passes them via axis_sink and bram.
    Connections must list the AXIS sink first, then the AXIMM BRAM port.
    """

    type = "SynchronizerNode"
    cxx_header = "noc/endpoints/misc/SynchronizerNode.hh"
    cxx_class = "gem5::noc::SynchronizerNode"

    # Shared (both inner types expose these)
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    # --- AxisSinkNode side (port 0) ---
    ready_percent = Param.UInt8(80, "Percent cycles asserting TREADY (0-100)")
    print_data = Param.Bool(True, "Print accepted beats")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits) for sink")
    id_width = Param.UInt32(6, "AXIS TID width for sink")
    dest_width = Param.UInt32(4, "AXIS TDEST width for sink")
    expected_packets = Param.UInt32(0, "How many TLASTs the sink expects")
    ready_percent_start_fraction = Param.Float(
        0.0,
        "Axis sink: apply ready_percent only after this fraction (0..1) of "
        "expected_packets TLASTs (inner AxisSinkNode).",
    )

    # --- BramBuggyNode side (port 1); same surface as BramBuggyNode / BramEndpoint ---
    tile_controller = Param.NocInterface("")
    base_addr = Param.Addr(0, "Base address of BRAM region")
    memory_size = Param.UInt64(65536, "Size of BRAM storage in bytes")
    read_latency = Param.Cycles(1, "Read latency in cycles")
    write_latency = Param.Cycles(1, "Write latency in cycles")
    awready_percentage = Param.UInt8(
        100, "Percent of cycles asserting AWREADY toward the master (0-100)"
    )
    wready_percentage = Param.UInt8(
        100, "Percent of cycles asserting WREADY toward the master (0-100)"
    )
    arready_percentage = Param.UInt8(
        100, "Percent of cycles asserting ARREADY toward the master (0-100)"
    )

    axis_sink = Param.AxisSinkNode(
        "Inner AxisSinkNode (first connection in JSON must be AXIS / sink port)"
    )
    bram = Param.BramBuggyNode(
        "Inner BramBuggyNode (second connection must be AXIMM / BRAM port)"
    )
