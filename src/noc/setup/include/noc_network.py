# basically copy of configs/network/Network.py but take out ruby usage

# Copyright (c) 2016 Georgia Institute of Technology
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import math
import os

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.util import (
    addToPath,
    fatal,
    warn,
)
from noc_trace_paths import (
    NPS_QUEUE_TRACE_FILENAME,
    NSU_READ_DRAIN_TRACE_FILENAME,
    ensure_runtime_trace_artifact_dir,
    runtime_trace_artifact_path,
)


def _has_simobject_param(simobject_class, param_name):
    return param_name in getattr(simobject_class, "_params", {})


def _optional_simobject_kwargs(simobject_class, **kwargs):
    return {
        name: value
        for name, value in kwargs.items()
        if _has_simobject_param(simobject_class, name)
    }


def _nsu_read_response_kwargs(options):
    gap_cycles = getattr(options, "nsu_read_response_gap_cycles", 1)
    per_flit_gap_cycles = getattr(
        options, "nsu_read_response_per_flit_gap_cycles", 0
    )

    if getattr(options, "nsu_read_response_half_rate", False):
        gap_cycles = 0
        per_flit_gap_cycles = max(per_flit_gap_cycles or 0, 1)

    return _optional_simobject_kwargs(
        mmNocSlaveUnit,
        read_response_gap_cycles=gap_cycles,
        read_response_per_flit_gap_cycles=per_flit_gap_cycles,
    )


def define_options(parser):
    # By default, ruby uses the simple timing cpu and the X86 ISA
    parser.set_defaults(cpu_type="X86TimingSimpleCPU")

    parser.add_argument(
        "--topology",
        type=str,
        default="Crossbar",
        help="check configs/topologies for complete set",
    )
    parser.add_argument(
        "--mesh-rows",
        type=int,
        default=0,
        help="the number of rows in the mesh topology",
    )
    parser.add_argument(
        "--network",
        default="simple",
        choices=["simple", "garnet", "nocgarnet"],
        help="""'simple'|'garnet'|'nocgarnet' (garnet2.0 will be deprecated.)""",
    )
    parser.add_argument(
        "--router-latency",
        action="store",
        type=int,
        default=1,
        help="""number of pipeline stages in the garnet router.
            Has to be >= 1.
            Can be over-ridden on a per router basis
            in the topology file.""",
    )
    parser.add_argument(
        "--link-latency",
        action="store",
        type=int,
        default=1,
        help="""latency of each link the simple/garnet networks.
        Has to be >= 1. Can be over-ridden on a per link basis
        in the topology file.""",
    )
    parser.add_argument(
        "--link-width-bits",
        action="store",
        type=int,
        default=128,
        help="width in bits for all links inside garnet.",
    )
    parser.add_argument(
        "--vcs-per-vnet",
        action="store",
        type=int,
        default=4,
        help="""number of virtual channels per virtual network
            inside garnet network.""",
    )
    parser.add_argument(
        "--routing-algorithm",
        action="store",
        type=int,
        default=0,
        help="""routing algorithm in network.
            0: weight-based table
            1: XY (for Mesh. see garnet/RoutingUnit.cc)
            2: Custom (see garnet/RoutingUnit.cc""",
    )
    parser.add_argument(
        "--network-fault-model",
        action="store_true",
        default=False,
        help="""enable network fault model:
            see src/mem/ruby/network/fault_model/""",
    )
    parser.add_argument(
        "--garnet-deadlock-threshold",
        action="store",
        type=int,
        default=50000,
        help="network-level deadlock threshold.",
    )
    parser.add_argument(
        "--simple-physical-channels",
        action="store_true",
        default=False,
        help="""SimpleNetwork links uses a separate physical
            channel for each virtual network""",
    )


def create_network(options, noc):
    # Allow legacy users to use garnet through garnet2.0 option
    # until next gem5 release.
    if options.network == "garnet2.0":
        warn(
            "Usage of option 'garnet2.0' will be depracated. "
            "Please use 'garnet' for using the latest garnet "
            "version. Current version: 3.0"
        )
        options.network = "garnet"

    # Set the network classes
    NetworkClass = NocGarnetNetwork
    IntLinkClass = NocGarnetIntLink
    ExtLinkClass = NocGarnetExtLink
    RouterClass = NocGarnetRouter
    # NMUClass = sNocMasterUnit #mmNocMasterUnit
    # NSUClass = sNocSlaveUnit #mmNocSlaveUnit

    # Trace mode + output path must be set at construction so C++ init() sees them.
    nps_trace = getattr(options, "nps_queue_trace", 0)
    nps_trace_path = ""
    if nps_trace:
        ensure_runtime_trace_artifact_dir()
        nps_trace_path = runtime_trace_artifact_path(NPS_QUEUE_TRACE_FILENAME)
    nsu_read_drain_trace = getattr(options, "nsu_read_drain_trace", 0)
    nsu_read_drain_trace_path = ""
    if nsu_read_drain_trace:
        ensure_runtime_trace_artifact_dir()
        nsu_read_drain_trace_path = runtime_trace_artifact_path(
            NSU_READ_DRAIN_TRACE_FILENAME
        )

    network_kwargs = {
        "noc_system": noc,
        "topology": options.topology,
        "routers": [],
        "ext_links": [],
        "int_links": [],
        "netifs": [],
    }
    if _has_simobject_param(NetworkClass, "nps_queue_trace_mode"):
        network_kwargs["nps_queue_trace_mode"] = nps_trace
        network_kwargs["nps_queue_trace_path"] = nps_trace_path
    elif nps_trace:
        warn(
            "NPS queue tracing requested, but this gem5 binary does not expose "
            "NocGarnetNetwork.nps_queue_trace_* params. Ignoring trace request."
        )
    if _has_simobject_param(NetworkClass, "nsu_read_drain_trace_mode"):
        network_kwargs["nsu_read_drain_trace_mode"] = nsu_read_drain_trace
        network_kwargs["nsu_read_drain_trace_path"] = nsu_read_drain_trace_path
    elif nsu_read_drain_trace:
        warn(
            "NSU read-drain tracing requested, but this gem5 binary does not "
            "expose NocGarnetNetwork.nsu_read_drain_trace_* params. "
            "Ignoring trace request."
        )

    # Instantiate the network object
    # so that the controllers can connect to it.
    network = NetworkClass(**network_kwargs)

    return (
        network,
        IntLinkClass,
        ExtLinkClass,
        RouterClass,
    )


def init_network(
    options,
    network,
    num_aximm_nsu,
    num_aximm_nmu,
    num_hbm_nsu,
    num_hbm_nmu,
    num_axis_nsu,
    num_axis_nmu,
    num_ddr_nsu=0,
    controllers=None,
):
    if options.network == "garnet" or options.network == "nocgarnet":
        network.num_aximm_nmu = num_aximm_nmu
        network.num_aximm_nsu = num_aximm_nsu
        network.num_axis_nmu = num_axis_nmu
        network.num_axis_nsu = num_axis_nsu

        network.num_rows = options.mesh_rows
        network.vcs_per_vnet = options.vcs_per_vnet
        network.ni_flit_size = options.link_width_bits / 8
        network.routing_algorithm = options.routing_algorithm
        network.garnet_deadlock_threshold = options.garnet_deadlock_threshold
        has_queue_trace = _has_simobject_param(
            network.__class__, "nps_queue_trace_mode"
        )
        has_nsu_read_drain_trace = _has_simobject_param(
            network.__class__, "nsu_read_drain_trace_mode"
        )
        if has_queue_trace:
            network.nps_queue_trace_mode = getattr(options, "nps_queue_trace", 0)
        if has_nsu_read_drain_trace:
            network.nsu_read_drain_trace_mode = getattr(
                options, "nsu_read_drain_trace", 0
            )
        for attr in (
            "buffers_per_data_vc",
            "buffers_per_ctrl_vc",
            "rptr_credits",
            "vnoc_credits",
            "hnoc_credits",
            "ncrb_credits",
            "nidb_credits",
        ):
            value = getattr(options, attr, None)
            if value is not None:
                setattr(network, attr, value)
                if (
                    attr == "buffers_per_data_vc"
                    and _has_simobject_param(
                        network.__class__, "buffers_per_data_vc_overridden"
                    )
                ):
                    network.buffers_per_data_vc_overridden = True
                elif (
                    attr == "buffers_per_ctrl_vc"
                    and _has_simobject_param(
                        network.__class__, "buffers_per_ctrl_vc_overridden"
                    )
                ):
                    network.buffers_per_ctrl_vc_overridden = True
        if has_queue_trace and network.nps_queue_trace_mode:
            ensure_runtime_trace_artifact_dir()
            network.nps_queue_trace_path = runtime_trace_artifact_path(
                NPS_QUEUE_TRACE_FILENAME
            )
        if has_nsu_read_drain_trace and network.nsu_read_drain_trace_mode:
            ensure_runtime_trace_artifact_dir()
            network.nsu_read_drain_trace_path = runtime_trace_artifact_path(
                NSU_READ_DRAIN_TRACE_FILENAME
            )

        # Create Bridges and connect them to the corresponding links
        for intLink in network.int_links:
            intLink.src_net_bridge = NocNetworkBridge(
                link=intLink.network_link,
                vtype="OBJECT_LINK",
                width=intLink.src_node.width,
            )
            intLink.src_cred_bridge = NocNetworkBridge(
                link=intLink.credit_link,
                vtype="LINK_OBJECT",
                width=intLink.src_node.width,
            )
            intLink.dst_net_bridge = NocNetworkBridge(
                link=intLink.network_link,
                vtype="LINK_OBJECT",
                width=intLink.dst_node.width,
            )
            intLink.dst_cred_bridge = NocNetworkBridge(
                link=intLink.credit_link,
                vtype="OBJECT_LINK",
                width=intLink.dst_node.width,
            )

        for extLink in network.ext_links:
            ext_net_bridges = []
            ext_net_bridges.append(
                NocNetworkBridge(
                    link=extLink.network_links[0],
                    vtype="OBJECT_LINK",
                    width=extLink.width,
                )
            )
            ext_net_bridges.append(
                NocNetworkBridge(
                    link=extLink.network_links[1],
                    vtype="LINK_OBJECT",
                    width=extLink.width,
                )
            )
            extLink.ext_net_bridge = ext_net_bridges

            ext_credit_bridges = []
            ext_credit_bridges.append(
                NocNetworkBridge(
                    link=extLink.credit_links[0],
                    vtype="LINK_OBJECT",
                    width=extLink.width,
                )
            )
            ext_credit_bridges.append(
                NocNetworkBridge(
                    link=extLink.credit_links[1],
                    vtype="OBJECT_LINK",
                    width=extLink.width,
                )
            )
            extLink.ext_cred_bridge = ext_credit_bridges

            int_net_bridges = []
            int_net_bridges.append(
                NocNetworkBridge(
                    link=extLink.network_links[0],
                    vtype="LINK_OBJECT",
                    width=extLink.int_node.width,
                )
            )
            int_net_bridges.append(
                NocNetworkBridge(
                    link=extLink.network_links[1],
                    vtype="OBJECT_LINK",
                    width=extLink.int_node.width,
                )
            )
            extLink.int_net_bridge = int_net_bridges

            int_cred_bridges = []
            int_cred_bridges.append(
                NocNetworkBridge(
                    link=extLink.credit_links[0],
                    vtype="OBJECT_LINK",
                    width=extLink.int_node.width,
                )
            )
            int_cred_bridges.append(
                NocNetworkBridge(
                    link=extLink.credit_links[1],
                    vtype="LINK_OBJECT",
                    width=extLink.int_node.width,
                )
            )
            extLink.int_cred_bridge = int_cred_bridges

    if options.network == "simple":
        if options.simple_physical_channels:
            network.physical_vnets_channels = [1] * int(
                network.number_of_virtual_networks
            )
        network.setup_buffers()

    netifs = []
    # createCustomLinks uses controller version as NI index directly (no globalToLocal
    # conversion). So netifs[i] must match the NI type for controller with version i.
    # Create NIs in controller order to remove list-order dependency.
    if controllers is not None:
        ni_id = 0
        aximm_master_rrob_max_entries = getattr(
            options, "aximm_master_rrob_max_entries", 0)
        for ctrl in controllers:
            protocol = getattr(ctrl, "protocol", "AXIMM")
            role = getattr(ctrl, "role", "Master")
            endpoint_name = getattr(ctrl, "endpoint_name", "") or ""
            is_hbm = "hbm" in endpoint_name.lower()
            if protocol == "AXIS":
                if role == "Master":
                    ni = sNocMasterUnit(id=ni_id, rrob=rrob())
                else:
                    ni = sNocSlaveUnit(id=ni_id, data_width=options.data_width)
            else:
                # AXIMM
                if role == "Master":
                    master_rrob = (
                        rrob(max_entries=aximm_master_rrob_max_entries)
                        if aximm_master_rrob_max_entries > 0
                        else rrob(max_entries=64, entry_size=64)
                        if is_hbm
                        else rrob()
                    )
                    ni = mmNocMasterUnit(
                        id=ni_id,
                        rrob=master_rrob,
                        **_optional_simobject_kwargs(
                            mmNocMasterUnit,
                            read_response_delay_cycles=getattr(
                                options, "nmu_read_response_delay_cycles", -1
                            ),
                        ),
                    )
                else:
                    ni = mmNocSlaveUnit(
                        id=ni_id,
                        data_width=options.data_width,
                        **_nsu_read_response_kwargs(options),
                    )
            netifs.append(ni)
            ni_id += 1
    else:
        # Legacy: create NIs in fixed type order (for configs that do not pass controllers)
        ni_id = 0
        aximm_master_rrob_max_entries = getattr(
            options, "aximm_master_rrob_max_entries", 0)
        for i in range(num_aximm_nsu):
            ni = mmNocSlaveUnit(
                id=ni_id,
                data_width=options.data_width,
                **_nsu_read_response_kwargs(options),
            )
            netifs.append(ni)
            ni_id += 1
        for i in range(num_hbm_nsu):
            ni = mmNocSlaveUnit(
                id=ni_id,
                data_width=options.data_width,
                **_nsu_read_response_kwargs(options),
            )
            netifs.append(ni)
            ni_id += 1
        for i in range(num_ddr_nsu):
            ni = mmNocSlaveUnit(
                id=ni_id,
                data_width=options.data_width,
                **_nsu_read_response_kwargs(options),
            )
            netifs.append(ni)
            ni_id += 1
        for i in range(num_axis_nsu):
            ni = sNocSlaveUnit(id=ni_id, data_width=options.data_width)
            netifs.append(ni)
            ni_id += 1
        for i in range(num_aximm_nmu):
            ni = mmNocMasterUnit(
                id=ni_id,
                rrob=rrob(max_entries=aximm_master_rrob_max_entries)
                if aximm_master_rrob_max_entries > 0
                else rrob(),
                **_optional_simobject_kwargs(
                    mmNocMasterUnit,
                    read_response_delay_cycles=getattr(
                        options, "nmu_read_response_delay_cycles", -1
                    ),
                ),
            )
            netifs.append(ni)
            ni_id += 1
        for i in range(num_hbm_nmu):
            ni = mmNocMasterUnit(
                id=ni_id,
                rrob=rrob(max_entries=aximm_master_rrob_max_entries)
                if aximm_master_rrob_max_entries > 0
                else rrob(max_entries=128),
                **_optional_simobject_kwargs(
                    mmNocMasterUnit,
                    read_response_delay_cycles=getattr(
                        options, "nmu_read_response_delay_cycles", -1
                    ),
                ),
            )
            netifs.append(ni)
            ni_id += 1
        for i in range(num_axis_nmu):
            ni = sNocMasterUnit(id=ni_id, rrob=rrob())
            netifs.append(ni)
            ni_id += 1

    print("NETIFS:", netifs)
    network.netifs = netifs

    if options.network_fault_model:
        assert options.network == "garnet" or options.network == "nocgarnet"
        network.enable_fault_model = True
        network.fault_model = FaultModel()
