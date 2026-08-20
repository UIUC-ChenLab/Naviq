from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocNetwork import NocGarnetNetworkInterface
from m5.objects.NocSlaveUnit import NocSlaveUnit
from m5.params import *
from m5.proxy import *


class sNocSlaveUnit(NocSlaveUnit):
    type = "sNocSlaveUnit"
    cxx_class = "gem5::noc::garnet::sNocSlaveUnit"
    cxx_header = "noc/core/network/nsu_types/sNocSlaveUnit.hh"
