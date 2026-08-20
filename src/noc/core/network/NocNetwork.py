# copied from src/mem/ruby/network/Network.py

from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocBasicLink import NocBasicLink
from m5.params import *
from m5.proxy import *


class NocNetwork(ClockedObject):
    type = "NocNetwork"
    cxx_class = "gem5::noc::NocNetwork"
    cxx_header = "noc/core/network/NocNetwork.hh"
    abstract = True

    topology = Param.String(
        "Not Specified", "the name of the imported topology module"
    )

    number_of_virtual_networks = Param.Unsigned(
        "Number of virtual networks "
        "used by the coherence protocol in use.  The on-chip network "
        "assumes the protocol numbers vnets starting from 0.  Therefore, "
        "the number of virtual networks should be one more than the "
        "highest numbered vnet in use."
    )
    control_msg_size = Param.Int(8, "")
    noc_system = Param.NocSystem("")

    routers = VectorParam.BasicRouter("Network routers")
    netifs = VectorParam.ClockedObject("Network Interfaces")
    ext_links = VectorParam.NocBasicExtLink("Links to external nodes")
    int_links = VectorParam.NocBasicIntLink("Links between internal nodes")

    in_port = VectorResponsePort("CPU input port")
    slave = DeprecatedParam(in_port, "`slave` is now called `in_port`")
    out_port = VectorRequestPort("CPU output port")
    master = DeprecatedParam(out_port, "`master` is now called `out_port`")

    data_msg_size = Param.Int(
        Parent.block_size_bytes,
        "Size of data messages. Defaults to the parent "
        "RubySystem cache line size.",
    )


class NocGarnetNetworkInterface(ClockedObject):
    type = "NocGarnetNetworkInterface"
    cxx_class = "gem5::noc::garnet::NetworkInterface"
    cxx_header = "noc/core/network/NocNetworkInterface.hh"
    abstract = True

    id = Param.UInt32("ID in relation to other network interfaces")
    vcs_per_vnet = Param.UInt32(
        Parent.vcs_per_vnet, "virtual channels per virtual network"
    )
    virt_nets = Param.UInt32(
        Parent.number_of_virtual_networks, "number of virtual networks"
    )
    garnet_deadlock_threshold = Param.UInt32(
        Parent.garnet_deadlock_threshold, "network-level deadlock threshold"
    )

    data_width = Param.Int(64, "Data width in bytes")

    noc_probe = Param.NocProbe(
        NULL, "Optional NocProbe for NI hook callbacks (flit / message path)"
    )
