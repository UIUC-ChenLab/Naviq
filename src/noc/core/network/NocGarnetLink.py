from m5.objects.ClockedObject import ClockedObject
from m5.objects.GarnetLink import (
    NocCreditLink,
    NocNetworkBridge,
    NocNetworkLink,
)
from m5.objects.NocBasicLink import (
    NocBasicExtLink,
    NocBasicIntLink,
)
from m5.params import *
from m5.proxy import *


# copied and modified from src/mem/ruby/network/garnet
# Interior fixed pipeline links between routers
class NocGarnetIntLink(NocBasicIntLink):
    type = "NocGarnetIntLink"
    cxx_header = "noc/core/network/NocGarnetLink.hh"
    cxx_class = "gem5::noc::garnet::NocGarnetIntLink"

    # The internal link includes one forward link (for flit)
    # and one backward flow-control link (for credit)
    network_link = Param.NocNetworkLink(NocNetworkLink(), "forward link")
    credit_link = Param.NocCreditLink(
        NocCreditLink(), "backward flow-control link"
    )

    # The src_cdc and dst_cdc flags are used to enable the
    # clock domain crossing(CDC) at the source and destination
    # end of the link respectively. This is required when the
    # link and the objected connected to the link are operating
    # at different clock domains. These flags should be set
    # in the network topology files.
    src_cdc = Param.Bool(False, "Enable Clock Domain Crossing")
    dst_cdc = Param.Bool(False, "Enable Clock Domain Crossing")

    # The src_serdes and dst_serdes flags are used to enable
    # the Serializer-Deserializer units at the source and
    # destination end of the link respectively. Enabling
    # these flags is necessary when the connecting object
    # supports a different flit width.
    src_serdes = Param.Bool(False, "Enable Serializer-Deserializer")
    dst_serdes = Param.Bool(False, "Enable Serializer-Deserializer")

    # The network bridge encapsulates both the CDC and Ser-Des
    # units in HeteroGarnet. This is automatically enabled when
    # either CDC or Ser-Des is enabled.
    src_net_bridge = Param.NocNetworkBridge(NULL, "Network Bridge at source")
    dst_net_bridge = Param.NocNetworkBridge(NULL, "Network Bridge at dest")
    src_cred_bridge = Param.NocNetworkBridge(NULL, "Credit Bridge at source")
    dst_cred_bridge = Param.NocNetworkBridge(NULL, "Credit Bridge at dest")

    width = Param.UInt32(
        Parent.ni_flit_size, "bit width supported by the router"
    )


# Exterior fixed pipeline links between a router and a controller
class NocGarnetExtLink(NocBasicExtLink):
    type = "NocGarnetExtLink"
    cxx_header = "noc/core/network/NocGarnetLink.hh"
    cxx_class = "gem5::noc::garnet::NocGarnetExtLink"

    # The external link is bi-directional.
    # It includes two forward links (for flits)
    # and two backward flow-control links (for credits),
    # one per direction
    _nls = []
    # In uni-directional link
    _nls.append(NocNetworkLink())
    # Out uni-directional link
    _nls.append(NocNetworkLink())
    network_links = VectorParam.NocNetworkLink(_nls, "forward links")

    _cls = []
    # In uni-directional link
    _cls.append(NocCreditLink())
    # Out uni-directional link
    _cls.append(NocCreditLink())
    credit_links = VectorParam.NocCreditLink(
        _cls, "backward flow-control links"
    )

    # The ext_cdc and intt_cdc flags are used to enable the
    # clock domain crossing(CDC) at the external and internal
    # end of the link respectively. This is required when the
    # link and the objected connected to the link are operating
    # at different clock domains. These flags should be set
    # in the network topology files.
    ext_cdc = Param.Bool(False, "Enable Clock Domain Crossing")
    int_cdc = Param.Bool(False, "Enable Clock Domain Crossing")

    # The ext_serdes and int_serdes flags are used to enable
    # the Serializer-Deserializer units at the external and
    # internal end of the link respectively. Enabling
    # these flags is necessary when the connecting object
    # supports a different flit width.
    ext_serdes = Param.Bool(False, "Enable Serializer-Deserializer")
    int_serdes = Param.Bool(False, "Enable Serializer-Deserializer")

    # The network bridge encapsulates both the CDC and Ser-Des
    # units in HeteroGarnet. This is automatically enabled when
    # either CDC or Ser-Des is enabled.
    ext_net_bridge = VectorParam.NocNetworkBridge(
        [], "Network Bridge at external end"
    )
    ext_cred_bridge = VectorParam.NocNetworkBridge(
        [], "Credit Bridge at external end"
    )
    int_net_bridge = VectorParam.NocNetworkBridge(
        [], "Network Bridge at internal end"
    )
    int_cred_bridge = VectorParam.NocNetworkBridge(
        [], "Credit Bridge at internal end"
    )

    width = Param.UInt32(
        Parent.ni_flit_size, "bit width supported by the router"
    )
