from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocMasterUnit import NocMasterUnit
from m5.objects.rrob import rrob
from m5.params import *
from m5.proxy import *


class mmNocMasterUnit(NocMasterUnit):
    type = "mmNocMasterUnit"
    cxx_class = "gem5::noc::garnet::mmNocMasterUnit"
    cxx_header = "noc/core/network/nmu_types/mmNocMasterUnit.hh"

    # Override to ensure a default is present even if parent default changes
    rrob = Param.rrob(rrob(), "ReadReorderBuffer")
    read_response_delay_cycles = Param.Int32(
        -1,
        "Override NMU read-response enqueue delay in cycles; -1 preserves the built-in formula",
    )
