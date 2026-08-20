from m5.params import *
from m5.SimObject import SimObject


class NocNode(SimObject):
    type = "NocNode"
    cxx_header = "noc/endpoints/NocNode.hh"
    cxx_class = "gem5::noc::NocNode"
    abstract = True

    clockDomains = VectorParam.Int([], "Clock domain(s) in MHz")
    port_endpoint_names = VectorParam.String(
        [], "Endpoint names per port in port order"
    )


