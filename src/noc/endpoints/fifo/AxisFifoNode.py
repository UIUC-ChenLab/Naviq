from m5.objects import NocNode
from m5.params import *
from m5.proxy import *


class AxisFifoNode(NocNode):
    type = "AxisFifoNode"
    cxx_header = "noc/endpoints/fifo/AxisFifoNode.hh"
    cxx_class = "gem5::noc::AxisFifoNode"

    # optional hook-ins for consistency with other test nodes
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    # general parameters
    fifo_depth = Param.UInt32(1024, "FIFO depth")
    delay = Param.UInt32(0, "Delay in cycles")

    # slave-side parameters
    ready_percent = Param.UInt8(80, "Percent cycles asserting TREADY (0-100)")
    print_data = Param.Bool(False, "Print accepted beats")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(6, "AXIS TID width")
    dest_width = Param.UInt32(4, "AXIS TDEST width")
    expected_packets = Param.UInt32(0, "How many tlasts to expect")
