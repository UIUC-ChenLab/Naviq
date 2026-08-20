from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocMasterUnit import NocMasterUnit
from m5.params import *
from m5.proxy import *


class sNocMasterUnit(NocMasterUnit):
    type = "sNocMasterUnit"
    cxx_class = "gem5::noc::garnet::sNocMasterUnit"
    cxx_header = "noc/core/network/nmu_types/sNocMasterUnit.hh"
