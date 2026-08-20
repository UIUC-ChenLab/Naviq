from m5.params import *
from m5.proxy import *
from m5.objects import NocNode


class AximmMemorySmokeRtlNode(NocNode):
    type = "AximmMemorySmokeRtlNode"
    cxx_header = "noc/endpoints/rtl/generated/AximmMemorySmokeRtlNode.hh"
    cxx_class = "gem5::noc::AximmMemorySmokeRtlNode"

    noc_system = Param.NocSystem(Parent.any, "")
    data_width = Param.UInt32(512, "AXI-MM data width in bits")
    id_width = Param.UInt32(4, "AXI-MM ID width in bits")
    addr_width = Param.UInt32(32, "AXI-MM address width in bits")
    reset_cycles = Param.UInt32(4, "RTL reset cycles")
