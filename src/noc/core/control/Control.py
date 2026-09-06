from m5.objects import NocInterface
from m5.objects.ClockedObject import ClockedObject
from m5.params import *
from m5.proxy import *


class Control(ClockedObject):
    type = "Control"
    cxx_header = "noc/core/control/Control.hh"
    cxx_class = "gem5::noc::Control"

    noc_interfaces = VectorParam.NocInterface("")
    nodes = VectorParam.NocNode("")
    adjacency_list = VectorParam.Int("")
    adjacency_index = VectorParam.Int("")
    direct_sources = VectorParam.NocNode([], "Direct AXIS link sources, without a NoC interface")
    direct_targets = VectorParam.NocNode([], "Direct AXIS link targets")
    direct_source_ports = VectorParam.String([], "Source port endpoint names")
    direct_target_ports = VectorParam.String([], "Target port endpoint names")
    
    #TODO: create virtual abstract parent class for BramEndpoint so that children can be called here
    # slave_nodes = VectorParam.tileNSU_HBM("")
    # slave_nodes = VectorParam.BramEndpoint("")
    # master_nodes =  VectorParam.tile("")
    # slave_nodes = VectorParam.NocNode("")
    # master_nodes =  VectorParam.NocNode("")

    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    noc_clock_domain_mhz = Param.UInt32(
        1000,
        "NoC clock frequency in MHz for scheduling nocSideUpdate (match --noc-clock)",
    )
