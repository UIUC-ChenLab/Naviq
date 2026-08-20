from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocNetwork import NocGarnetNetworkInterface
from m5.objects.rrob import rrob
from m5.params import *
from m5.proxy import *


class NocMasterUnit(NocGarnetNetworkInterface):
    type = "NocMasterUnit"
    cxx_class = "gem5::noc::garnet::NocMasterUnit"
    cxx_header = "noc/core/network/NocMasterUnit.hh"
    abstract = True

    # # Provide a sensible default to avoid nullptr deref if not explicitly wired
    # rrob = Param.rrob(rrob(), "ReadReorderBuffer")
