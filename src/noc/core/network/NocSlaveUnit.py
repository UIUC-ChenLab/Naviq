from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocNetwork import NocGarnetNetworkInterface
from m5.params import *
from m5.proxy import *


class NocSlaveUnit(NocGarnetNetworkInterface):
    type = "NocSlaveUnit"
    cxx_class = "gem5::noc::garnet::NocSlaveUnit"
    cxx_header = "noc/core/network/NocSlaveUnit.hh"
    # data_width is inherited from NocGarnetNetworkInterface

    abstract = True
