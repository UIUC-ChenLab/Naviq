from m5.objects import NocNode
from m5.params import *
from m5.proxy import *


class AxisBackpressureShimNode(NocNode):
    type = "AxisBackpressureShimNode"
    cxx_header = "noc/endpoints/sink/AxisBackpressureShimNode.hh"
    cxx_class = "gem5::noc::AxisBackpressureShimNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")

    backpressure_enabled = Param.Bool(False, "Enable deterministic ready gating")
    backpressure_config_name = Param.String("none", "Backpressure configuration name")
    backpressure_period = Param.UInt32(1, "Ready pattern period in cycles")
    backpressure_allow = Param.UInt32(1, "Ready cycles allowed per period")
    backpressure_scope = Param.String(
        "dma_fed_axis_correctness_shim",
        "Backpressure experiment scope",
    )
    fifo_depth = Param.UInt32(1, "Bounded skid/FIFO depth in beats")
