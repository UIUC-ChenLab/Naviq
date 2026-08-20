from m5.objects import NocNode
from m5.params import *
from m5.proxy import *
from warnings import warn


class TrafficGenerator(NocNode):
    type = "TrafficGenerator"
    cxx_header = "noc/endpoints/generator/TrafficGenerator.hh"
    cxx_class = "gem5::noc::TrafficGenerator"

    protocol = Param.String("AXIS", "Type of traffic generator (AXIS/AXIMM)")
    mode = Param.String("RANDOM", "Mode of traffic generator")

    # AXIMM bandwidth limits (passed to AxiTrafficGenerator base; 0 = unlimited)
    max_write_bandwidth_mbps = Param.Float(0.0, "Maximum write bandwidth in MBps (0.0 = unlimited)")
    max_read_bandwidth_mbps = Param.Float(0.0, "Maximum read bandwidth in MBps (0.0 = unlimited)")
    clock_period_ns = Param.Float(1.0, "Clock period in nanoseconds (for bandwidth limiting)")

    nsu_min_addrs = VectorParam.UInt64([], "NSU min addresses for AXIMM; pair with nsu_address_spaces")
    nsu_address_spaces = VectorParam.UInt64([], "NSU address space sizes in bytes for AXIMM")

    data_width = Param.Int(512, "Data width")
    addr_width = Param.Int(64, "Address width")
    id_width = Param.Int(4, "ID width")
    tdest_width = Param.Int(12, "AXIS TDEST width")
    tid_width = Param.Int(16, "AXIS TID width")
    tuser_width = Param.Int(0, "AXIS TUSER width")
    aw_user_width = Param.Int(0, "AW user width")
    w_user_width = Param.Int(0, "W user width")
    b_user_width = Param.Int(0, "B user width")
    ar_user_width = Param.Int(0, "AR user width")
    r_user_width = Param.Int(0, "R user width")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if self.protocol == "AXIMM":
            assert self.data_width and self.addr_width and self.id_width and self.aw_user_width and self.w_user_width and self.b_user_width and self.ar_user_width and self.r_user_width
            if(self.tdest_width or self.tid_width or self.tuser_width or self.mode):
                warn(f"TDEST width, TID width, TUSER width, or MODE were set for AXIMM type traffic generator, but will be ignored")
        elif self.protocol == "AXIS":
            assert self.data_width and self.tdest_width and self.tid_width and self.tuser_width
            if(self.id_width or self.aw_user_width or self.w_user_width or self.b_user_width or self.ar_user_width or self.r_user_width):
                warn(f"ID width, AW user width, W user width, B user width, AR user width, or R user width were set for AXIS type traffic generator, but will be ignored")
        else:
            raise ValueError(f"Unknown type: {self.type}")
