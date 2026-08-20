from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocNetwork import NocGarnetNetworkInterface
from m5.objects.NocSlaveUnit import NocSlaveUnit
from m5.params import *
from m5.proxy import *


class mmNocSlaveUnit(NocSlaveUnit):
    type = "mmNocSlaveUnit"
    cxx_class = "gem5::noc::garnet::mmNocSlaveUnit"
    cxx_header = "noc/core/network/nsu_types/mmNocSlaveUnit.hh"

    read_response_gap_cycles = Param.UInt32(
        1,
        "Extra idle cycles inserted after read-response flit groups; 0 disables response bubbles",
    )
    read_response_per_flit_gap_cycles = Param.UInt32(
        0,
        "Extra idle cycles inserted after each read-response flit; 0 disables per-flit response bubbles",
    )
