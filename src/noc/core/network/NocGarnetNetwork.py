# copied and modified from src/mem/ruby/network/garnet/GarnetNetwork.py

from m5.citations import add_citation
from m5.objects.BasicRouter import BasicRouter
from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocNetwork import NocNetwork
from m5.params import *
from m5.proxy import *


class NocGarnetNetwork(NocNetwork):
    type = "NocGarnetNetwork"
    cxx_header = "noc/core/network/NocGarnetNetwork.hh"
    cxx_class = "gem5::noc::garnet::NocGarnetNetwork"
    # abstract = True

    num_rows = Param.Int(0, "number of rows if 2D (mesh/torus/..) topology")
    ni_flit_size = Param.UInt32(16, "network interface flit size in bytes")
    vcs_per_vnet = Param.UInt32(4, "virtual channels per virtual network")
    buffers_per_data_vc = Param.UInt32(4, "buffers per data virtual channel")
    buffers_per_ctrl_vc = Param.UInt32(1, "buffers per ctrl virtual channel")
    buffers_per_data_vc_overridden = Param.Bool(
        False,
        "True when buffers_per_data_vc was explicitly overridden and should "
        "drive live NoC VC credit/input-buffer capacity.",
    )
    buffers_per_ctrl_vc_overridden = Param.Bool(
        False,
        "True when buffers_per_ctrl_vc was explicitly overridden and should "
        "drive live NoC VC credit/input-buffer capacity.",
    )
    routing_algorithm = Param.Int(0, "0: Weight-based Table, 1: XY, 2: Custom")
    enable_fault_model = Param.Bool(False, "enable network fault model")
    fault_model = Param.FaultModel(NULL, "network fault model")
    garnet_deadlock_threshold = Param.UInt32(
        50000, "network-level deadlock threshold"
    )
    enable_detailed_metrics = Param.Bool(
        True, "enable detailed percentiles and fairness calculation"
    )
    custom_routing_table_json = Param.String(
        "",
        "Custom routing table (JSON encoded list of lists: [[link_id, src, dst, vc],...])",
    )
    address_map_json = Param.String(
        "", "Address map (JSON encoded list of [start, end, dest_id])"
    )
    source_address_map_json = Param.String(
        "",
        "Source-aware address map (JSON encoded list of [src_id, start, end, dest_id])",
    )
    route_to_vc_json = Param.String(
        "", "VC mapping info (JSON [[src_id, dst_id, req_type, vc_id],...])"
    )
    axis_tdest_map_json = Param.String(
        "",
        "AXIS tdest routing map (JSON {nmu_id: {tdest: dest_ni, ...}, ...})",
    )
    num_aximm_nmu = Param.Int(0, "Number of AXIMM NMU's in the system")
    num_aximm_nsu = Param.Int(0, "Number of AXIMM NSU's in the system")

    num_axis_nmu = Param.Int(0, "Number of AXIS NMU's in the system")
    num_axis_nsu = Param.Int(0, "Number of AXIS NSU's in the system")

    rptr_latency = Param.Cycles(1, "Repeater latency")
    vnoc_latency = Param.Cycles(2, "VNOC latency")
    hnoc_latency = Param.Cycles(2, "HNOC latency")
    ncrb_latency = Param.Cycles(5, "NCRB latency")
    nidb_latency = Param.Cycles(6, "NIDB latency")

    rptr_credits = Param.UInt32(1, "Repeater credits")
    vnoc_credits = Param.UInt32(5, "VNOC credits")
    hnoc_credits = Param.UInt32(7, "HNOC credits")
    ncrb_credits = Param.UInt32(12, "NCRB credits")
    nidb_credits = Param.UInt32(14, "NIDB credits")

    nps_queue_trace_mode = Param.Int(
        0,
        "0 = off; non-zero = periodic CSV trace of per-router input VC / "
        "credit queue occupancy (sparse rows when depth > 0).",
    )
    nps_queue_trace_path = Param.String(
        "",
        "Absolute or relative path for nps_queue_trace.csv (parent dirs are "
        "created when trace is enabled). Empty uses "
        "src/noc/out/csv/.",
    )
    nsu_read_drain_trace_mode = Param.Int(
        0,
        "0 = off; non-zero = CSV trace of AXI-MM NSU read-response drain "
        "selection and flit injection order.",
    )
    nsu_read_drain_trace_path = Param.String(
        "",
        "Absolute or relative path for nsu_read_drain_trace.csv (parent dirs "
        "are created when trace is enabled). Empty uses src/noc/out/csv/.",
    )


# class GarnetNetworkInterface(ClockedObject):
#     type = "GarnetNetworkInterface"
#     cxx_class = "gem5::ruby::garnet::NetworkInterface"
#     cxx_header = "mem/ruby/network/garnet/NetworkInterface.hh"

#     id = Param.UInt32("ID in relation to other network interfaces")
#     vcs_per_vnet = Param.UInt32(
#         Parent.vcs_per_vnet, "virtual channels per virtual network"
#     )
#     virt_nets = Param.UInt32(
#         Parent.number_of_virtual_networks, "number of virtual networks"
#     )
#     garnet_deadlock_threshold = Param.UInt32(
#         Parent.garnet_deadlock_threshold, "network-level deadlock threshold"
#     )


# class GarnetRouter(BasicRouter):
#     type = "GarnetRouter"
#     cxx_class = "gem5::ruby::garnet::Router"
#     cxx_header = "mem/ruby/network/garnet/Router.hh"
#     vcs_per_vnet = Param.UInt32(
#         Parent.vcs_per_vnet, "virtual channels per virtual network"
#     )
#     virt_nets = Param.UInt32(
#         Parent.number_of_virtual_networks, "number of virtual networks"
#     )
#     width = Param.UInt32(
#         Parent.ni_flit_size, "bit width supported by the router"
#     )
