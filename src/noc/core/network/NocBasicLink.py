# copied and modified from src/mem/ruby/network/BasicLink.py

from m5.params import *
from m5.SimObject import SimObject


class NocBasicLink(SimObject):
    type = "NocBasicLink"
    cxx_header = "noc/core/network/NocBasicLink.hh"
    cxx_class = "gem5::noc::NocBasicLink"

    link_id = Param.Int("ID in relation to other links")
    latency = Param.Cycles(1, "latency")
    # Width of the link in bytes
    # Only used by simple network.
    # Garnet models this by flit size
    # For the simple links, the bandwidth factor translates to the
    # bandwidth multiplier.  The multipiler, in combination with the
    # endpoint bandwidth multiplier - message size multiplier ratio,
    # determines the link bandwidth in bytes
    bandwidth_factor = Param.Int("generic bandwidth factor, usually in bytes")
    weight = Param.Int(1, "used to restrict routing in shortest path analysis")
    supported_vnets = VectorParam.Int([], "Vnets supported Default:All([])")


class NocBasicExtLink(NocBasicLink):
    type = "NocBasicExtLink"
    cxx_header = "noc/core/network/NocBasicLink.hh"
    cxx_class = "gem5::noc::NocBasicExtLink"

    ext_node = Param.NocInterface("External node")
    int_node = Param.BasicRouter("ID of internal node")
    bandwidth_factor = 16  # only used by simple network


class NocBasicIntLink(NocBasicLink):
    type = "NocBasicIntLink"
    cxx_header = "noc/core/network/NocBasicLink.hh"
    cxx_class = "gem5::noc::NocBasicIntLink"

    src_node = Param.BasicRouter("Router on src end")
    dst_node = Param.BasicRouter("Router on dst end")

    # only used by Garnet.
    src_outport = Param.String("", "Outport direction at src router")
    dst_inport = Param.String("", "Inport direction at dst router")

    # only used by simple network
    bandwidth_factor = 16
