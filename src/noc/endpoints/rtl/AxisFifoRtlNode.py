from m5.params import *
from m5.proxy import *
from m5.objects import NocNode


class AxisFifoRtlNode(NocNode):
    type = "AxisFifoRtlNode"
    cxx_header = "noc/endpoints/rtl/AxisFifoRtlNode.hh"
    cxx_class = "gem5::noc::AxisFifoRtlNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    fifo_depth = Param.UInt32(16, "FIFO depth")
    print_data = Param.Bool(False, "Print forwarded beats")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(1, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(4, "Cycles to hold the RTL model in reset")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    limiter_enabled = Param.Bool(False, "Enable controlled AXIS backpressure for limiter experiments")
    limiter_config_name = Param.String("none", "Human-readable limiter configuration name")
    limiter_rate_setting = Param.String("period1_allow1", "Limiter rate setting label")
    limiter_scope = Param.String("empty_or_not_applicable", "Limiter metric/configuration scope")
    limiter_backpressure_period = Param.UInt32(1, "Controlled AXIS backpressure period")
    limiter_backpressure_allow = Param.UInt32(1, "Ready/valid slots allowed per backpressure period")
