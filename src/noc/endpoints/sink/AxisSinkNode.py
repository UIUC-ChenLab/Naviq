from m5.objects import NocNode
from m5.params import *
from m5.proxy import *


class AxisSinkNode(NocNode):
    type = "AxisSinkNode"
    cxx_header = "noc/endpoints/sink/AxisSinkNode.hh"
    cxx_class = "gem5::noc::AxisSinkNode"

    # optional hook-ins for consistency with other test nodes
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    # AXIS parameters
    ready_percent = Param.UInt8(80, "Percent cycles asserting TREADY (0-100)")
    ready_percent_start_fraction = Param.Float(
        0.0,
        "Apply ready_percent only after this fraction (0..1) of expected_packets "
        "TLASTs have been received; until then TREADY is always asserted. "
        "0 = stochastic ready from the first packet.",
    )
    print_data = Param.Bool(False, "Print accepted beats")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(6, "AXIS TID width")
    dest_width = Param.UInt32(4, "AXIS TDEST width")
    expected_packets = Param.UInt32(0, "How many tlasts to expect")
