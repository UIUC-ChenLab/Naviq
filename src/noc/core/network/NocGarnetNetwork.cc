/*
 * Copyright (c) 2020 Advanced Micro Devices, Inc.
 * Copyright (c) 2008 Princeton University
 * Copyright (c) 2016 Georgia Institute of Technology
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

//copied and modified from src/mem/ruby/network/garnet/s.cc
//  #include "mem/ruby/network/garnet/GarnetNetwork.hh"

#include "noc/core/network/NocGarnetNetwork.hh"
#include "noc/core/network/NocSystem.hh"

#include <cassert>

#include "base/cast.hh"
#include "base/compiler.hh"
#include "debug/RubyNetwork.hh"
#include "sim/serialize.hh"
//  #include "mem/ruby/common/NetDest.hh"
#include "mem/ruby/network/MessageBuffer.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "noc/core/network/NocGarnetLink.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "mem/ruby/network/garnet/NetworkLink.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/network/garnet/InputUnit.hh"
#include "noc/core/network/switch/NocRouter.hh"
#include "mem/ruby/system/RubySystem.hh"
#include "sim/core.hh"

#include <filesystem>

namespace gem5
{

namespace noc
{

namespace garnet
{

namespace
{

constexpr const char *kRuntimeTraceDir = "src/noc/out/csv";
constexpr const char *kNpsQueueTracePath =
    "src/noc/out/csv/nps_queue_trace.csv";
constexpr const char *kNpsSwitchArbTraceFilename =
    "nps_switch_arb_trace.csv";
constexpr const char *kNsuReadDrainTracePath =
    "src/noc/out/csv/nsu_read_drain_trace.csv";

/** Write a CSV field; quote if needed. */
void
writeCsvField(std::ostream &os, const std::string &s)
{
    if (s.find_first_of(",\"\r\n") != std::string::npos) {
        os << '"';
        for (char c : s) {
            if (c == '"')
                os << "\"\"";
            else
                os << c;
        }
        os << '"';
    } else {
        os << s;
    }
}

} // namespace

/*
 * GarnetNetwork sets up the routers and links and collects stats.
 * Default parameters (GarnetNetwork.py) can be overwritten from command line
 * (see configs/network/Network.py)
 */

NocGarnetNetwork::NocGarnetNetwork(const Params &p)
    : NocNetwork(p), m_custom_routing_table_json(p.custom_routing_table_json),
     m_address_map_json(p.address_map_json), m_source_address_map_json(p.source_address_map_json),
     m_route_to_vc_json(p.route_to_vc_json),
     m_enable_detailed_metrics(p.enable_detailed_metrics),
     m_axis_tdest_map_json(p.axis_tdest_map_json),
     npsQueueTraceEvent([this] { npsQueueTraceSample(); }, name()),
     m_trafficMonitorOutstandingPollEvent(
         [this] { trafficMonitorOutstandingPoll(); }, name()),
     m_trafficMonitorCsvHeartbeatEvent(
         [this] { trafficMonitorCsvHeartbeat(); }, name())

{
    m_num_rows = p.num_rows;
    m_ni_flit_size = p.ni_flit_size;
    m_max_vcs_per_vnet = 0;
    m_buffers_per_data_vc = p.buffers_per_data_vc;
    m_buffers_per_ctrl_vc = p.buffers_per_ctrl_vc;
    m_buffers_per_data_vc_overridden = p.buffers_per_data_vc_overridden;
    m_buffers_per_ctrl_vc_overridden = p.buffers_per_ctrl_vc_overridden;
    m_routing_algorithm = p.routing_algorithm;
    m_next_packet_id = 0;
    m_num_aximm_nmu = p.num_aximm_nmu;
    m_num_aximm_nsu = p.num_aximm_nsu;
    m_num_axis_nmu = p.num_axis_nmu;
    m_num_axis_nsu = p.num_axis_nsu;

    m_rptr_latency = p.rptr_latency;
    m_vnoc_latency = p.vnoc_latency;
    m_hnoc_latency = p.hnoc_latency;
    m_ncrb_latency = p.ncrb_latency;
    m_nidb_latency = p.nidb_latency;

    m_rptr_credits = p.rptr_credits;
    m_vnoc_credits = p.vnoc_credits;
    m_hnoc_credits = p.hnoc_credits;
    m_ncrb_credits = p.ncrb_credits;
    m_nidb_credits = p.nidb_credits;

    m_enable_fault_model = p.enable_fault_model;
    if (m_enable_fault_model)
        fault_model = p.fault_model;

    m_vnet_type.resize(m_virtual_networks);

    for (int i = 0 ; i < m_virtual_networks ; i++) {
        if (m_vnet_type_names[i] == "response")
            m_vnet_type[i] = gem5::ruby::garnet::DATA_VNET_; // carries data (and ctrl) packets
        else
            m_vnet_type[i] = gem5::ruby::garnet::CTRL_VNET_; // carries only ctrl packets
    }

    // record the routers
    for (std::vector<gem5::ruby::BasicRouter*>::const_iterator i =  p.routers.begin();
       i != p.routers.end(); ++i) {
       NocRouter<NocMessage, NocRouteInfo>* router = safe_cast<NocRouter<NocMessage, NocRouteInfo>*>(*i);
       m_routers.push_back(router);

       // initialize the router's network pointers
       router->init_net_ptr(this);
    }

    // record the network interfaces
    for (std::vector<ClockedObject*>::const_iterator i = p.netifs.begin();
         i != p.netifs.end(); ++i) {
          NetworkInterface *ni = safe_cast<NetworkInterface *>(*i);
        m_nis.push_back(ni);
        ni->init_net_ptr(this);
    }

    // Print Garnet version
    inform("Garnet version %s\n", garnetVersion);
}

void
NocGarnetNetwork::init()
{
    NocNetwork::init();

    // Checkpoint/restore correctness:
    // NocInterface::unserialize() stashes traffic-monitor state and applies it
    // at the end of unserialize() (after registerNode() in init()). If we call
    // NocTrafficMonitor::init() after controllers have registered, we can wipe
    // restored per-node state. Initialize the traffic monitor early.
    if (!m_nis.empty() && m_nis[0] != nullptr) {
        Tick period_ticks = m_nis[0]->clockPeriod();
        m_traffic_monitor.init(period_ticks,
            m_num_aximm_nmu+m_num_axis_nmu+m_num_aximm_nsu+m_num_axis_nsu/*+m_num_hbm_nmu*/);
        m_traffic_monitor.setNetworkContext(this);
        const Tick poll_pd = m_traffic_monitor.outstandingPollPeriodTicks();
        if (poll_pd > 0) {
            schedule(m_trafficMonitorOutstandingPollEvent, curTick() + poll_pd);
        }
        const Tick csv_hb_pd = m_traffic_monitor.csvHeartbeatPeriodTicks();
        if (csv_hb_pd > 0) {
            schedule(m_trafficMonitorCsvHeartbeatEvent, curTick() + csv_hb_pd);
        }
    } else {
        warn("NocGarnetNetwork::init: No NIs found to infer AXI clock period; traffic monitor may be uninitialized.");
    }

    getNocSystem()->initControllerQueues();
    parseAddressMap();
    parseSourceAddressMap();
    parseVcMap();
    parseAxisTdestMap();  // Parse AXIS tdest routing map

    for (int i=0; i < m_nodes; i++) {
        m_nis[i]->addNode(m_toNetQueues[i], m_fromNetQueues[i]);
    }

    // The topology pointer should have already been initialized in the
    // parent network constructor
    assert(m_topology_ptr != NULL);
    if (m_routing_algorithm ==2) {
        m_topology_ptr->createCustomLinks(this, m_custom_routing_table_json);
    } else {
        m_topology_ptr->createLinks(this);
    }

    m_traffic_monitor.setDetailedMetrics(m_enable_detailed_metrics);

    registerExitCallback([this]() {
        // This code will execute when the simulation exits normally
        std::cout << "\n--- NocGarnetNetwork Exit Callback: Printing Stats ---" << std::endl;
        if (m_trafficMonitorOutstandingPollEvent.scheduled()) {
            deschedule(m_trafficMonitorOutstandingPollEvent);
        }
        if (m_trafficMonitorCsvHeartbeatEvent.scheduled()) {
            deschedule(m_trafficMonitorCsvHeartbeatEvent);
        }
        // Call printStats on the member variable
        m_traffic_monitor.printStats(curTick());
        if (NocSystem* ns = getNocSystem()) {
            ns->printNocProbeSnoopSummariesAtExit();
        }
        // Flush traffic CSVs on every exit path (e.g. simCycles).
        m_traffic_monitor.outputCSV();
        std::cout << "----------------------------------------------------" << std::endl;
        if (m_npsQueueTraceFile) {
            if (npsQueueTraceEvent.scheduled())
                deschedule(npsQueueTraceEvent);
            m_npsQueueTraceFile->flush();
            m_npsQueueTraceFile.reset();
        }
        if (m_npsSwitchArbTraceFile) {
            m_npsSwitchArbTraceFile->flush();
            m_npsSwitchArbTraceFile.reset();
        }
        if (m_nsuReadDrainTraceFile) {
            m_nsuReadDrainTraceFile->flush();
            m_nsuReadDrainTraceFile.reset();
        }
    });

    // Initialize topology specific parameters
    if (getNumRows() > 0) {
        // Only for Mesh topology
        // m_num_rows and m_num_cols are only used for
        // implementing XY or custom routing in RoutingUnit.cc
        m_num_rows = getNumRows();
        m_num_cols = m_routers.size() / m_num_rows;
        // assert(m_num_rows * m_num_cols == m_routers.size());
    } else {
        m_num_rows = -1;
        m_num_cols = -1;
    }

    // Optional sparse CSV trace of input VC / credit queue occupancy (NPS routers).
    if (params().nps_queue_trace_mode != 0) {
        std::string path = params().nps_queue_trace_path;
        if (path.empty())
            path = kNpsQueueTracePath;
        std::filesystem::path fs_path(path);
        const std::filesystem::path parent = fs_path.parent_path();
        if (!parent.empty())
            std::filesystem::create_directories(parent);
        else
            std::filesystem::create_directories(kRuntimeTraceDir);
        m_npsQueueTraceFile = std::make_unique<std::ofstream>(
            path, std::ios::out | std::ios::trunc);
        fatal_if(!m_npsQueueTraceFile->good(),
            "NocGarnetNetwork: cannot open NPS queue trace file '%s'", path);
        *m_npsQueueTraceFile
            << "tick,cycle,router_id,nocname,nps_type,queue_kind,inport,vc,"
               "depth\n";
        std::filesystem::path arb_path = fs_path.parent_path();
        if (arb_path.empty()) {
            arb_path = kRuntimeTraceDir;
        }
        arb_path /= kNpsSwitchArbTraceFilename;
        const std::string arb_path_str = arb_path.string();
        m_npsSwitchArbTraceFile = std::make_unique<std::ofstream>(
            arb_path_str, std::ios::out | std::ios::trunc);
        fatal_if(!m_npsSwitchArbTraceFile->good(),
            "NocGarnetNetwork: cannot open NPS switch arbitration trace file "
            "'%s'", arb_path_str.c_str());
        *m_npsSwitchArbTraceFile
            << "tick,cycle,event,router_id,nocname,nps_type,outport,inport,vc,"
               "priority,tokens,lock_inport,lock_vc,packet_id,flit_id,src_ni,"
               "dest_ni,vnet,flit_type,axi_type\n";
        schedule(npsQueueTraceEvent, clockEdge(Cycles(1)));
        inform("NPS queue trace enabled, writing to %s\n", path.c_str());
        inform("NPS switch arbitration trace enabled, writing to %s\n",
            arb_path_str.c_str());
    }

    if (params().nsu_read_drain_trace_mode != 0) {
        std::string path = params().nsu_read_drain_trace_path;
        if (path.empty())
            path = kNsuReadDrainTracePath;
        std::filesystem::path fs_path(path);
        const std::filesystem::path parent = fs_path.parent_path();
        if (!parent.empty())
            std::filesystem::create_directories(parent);
        else
            std::filesystem::create_directories(kRuntimeTraceDir);
        m_nsuReadDrainTraceFile = std::make_unique<std::ofstream>(
            path, std::ios::out | std::ios::trunc);
        fatal_if(!m_nsuReadDrainTraceFile->good(),
            "NocGarnetNetwork: cannot open NSU read-drain trace file '%s'",
            path);
        *m_nsuReadDrainTraceFile
            << "tick,cycle,event,nsu_id,axi_id,src_ni,vc,packet_id,flit_idx,"
               "bytes_received,bytes_sent,total_bytes_needed,slave_finished,"
               "rrob_tag0,rrob_tag1,rrob_tag2,rrob_tag3,rrob_tag4,rrob_tag5,"
               "rrob_tag6,rrob_tag7\n";
        inform("NSU read-drain trace enabled, writing to %s\n", path.c_str());
    }

    // FaultModel: declare each router to the fault model
    if (isFaultModelEnabled()) {
        for (std::vector<NocRouter<NocMessage, NocRouteInfo>*>::const_iterator i= m_routers.begin();
           i != m_routers.end(); ++i) {
           NocRouter<NocMessage, NocRouteInfo>* router = safe_cast<NocRouter<NocMessage, NocRouteInfo>*>(*i);
            [[maybe_unused]] int router_id =
                fault_model->declare_router(router->get_num_inports(),
                                            router->get_num_outports(),
                                            router->get_vc_per_vnet(),
                                            getBuffersPerDataVC(),
                                            getBuffersPerCtrlVC());
            assert(router_id == router->get_id());
            router->printAggregateFaultProbability(std::cout);
            router->printFaultVector(std::cout);
        }
    }
}

/*
 * This function creates a link from the Network Interface (NI)
 * into the Network.
 * It creates a Network Link from the NI to a Router and a Credit Link from
 * the Router to the NI
*/

void
NocGarnetNetwork::makeExtInLink(gem5::ruby::NodeID global_src, gem5::ruby::SwitchID dest, NocBasicLink* link)
{
   gem5::ruby::NodeID local_src = getLocalNodeID(global_src);
    assert(local_src < m_nodes);


    NocGarnetExtLink* garnet_link = safe_cast<NocGarnetExtLink*>(link);

    DPRINTF(RubyNetwork, "makeExtInLink: linkid %d src %d, dest %d\n",garnet_link->get_id() ,local_src, dest);

    // GarnetExtLink is bi-directional
    gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo>* net_link = garnet_link->m_network_links[gem5::ruby::LinkDirection_In];
    net_link->setType(gem5::ruby::garnet::EXT_IN_);
    gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo>* credit_link = garnet_link->m_credit_links[gem5::ruby::LinkDirection_In];

    m_networklinks.push_back(net_link);
    m_creditlinks.push_back(credit_link);

    gem5::ruby::PortDirection dst_inport_dirn = "Local";

    m_max_vcs_per_vnet = std::max(m_max_vcs_per_vnet,
                             m_routers[dest]->get_vc_per_vnet());

    /*
     * We check if a bridge was enabled at any end of the link.
     * The bridge is enabled if either of clock domain
     * crossing (CDC) or Serializer-Deserializer(SerDes) unit is
     * enabled for the link at each end. The bridge encapsulates
     * the functionality for both CDC and SerDes and is a Consumer
     * object similiar to a NetworkLink.
     *
     * If a bridge was enabled we connect the NI and Routers to
     * bridge before connecting the link. Example, if an external
     * bridge is enabled, we would connect:
     * NI--->NetworkBridge--->GarnetExtLink---->Router
     */
    if (garnet_link->extBridgeEn) {
        DPRINTF(RubyNetwork, "Enable external bridge for %s\n",
            garnet_link->name());
        gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->extNetBridge[gem5::ruby::LinkDirection_In];
        m_nis[local_src]->
        addOutPort(n_bridge,
                   garnet_link->extCredBridge[gem5::ruby::LinkDirection_In],
                   dest, m_routers[dest]->get_vc_per_vnet());
        m_networkbridges.push_back(n_bridge);
    } else {
        m_nis[local_src]->addOutPort(net_link, credit_link, dest,
            m_routers[dest]->get_vc_per_vnet());
    }

    if (garnet_link->intBridgeEn) {
        DPRINTF(RubyNetwork, "Enable internal bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->intNetBridge[gem5::ruby::LinkDirection_In];
        m_routers[dest]->
            addInPort(dst_inport_dirn,
                      n_bridge,
                      garnet_link->intCredBridge[gem5::ruby::LinkDirection_In]);
        m_networkbridges.push_back(n_bridge);
    } else {
        m_routers[dest]->addInPort(dst_inport_dirn, net_link, credit_link);
    }

}

void
NocGarnetNetwork::makeNocExtInLink(gem5::ruby::NodeID global_src, gem5::ruby::SwitchID dest, NocBasicLink* link)
{
   gem5::ruby::NodeID local_src = global_src;
    assert(local_src < m_nodes);


    NocGarnetExtLink* garnet_link = safe_cast<NocGarnetExtLink*>(link);

    DPRINTF(RubyNetwork, "makeExtInLink: linkid %d src %d, dest %d\n",garnet_link->get_id() ,local_src, dest);

    // GarnetExtLink is bi-directional
    gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo>* net_link = garnet_link->m_network_links[gem5::ruby::LinkDirection_In];
    net_link->setType(gem5::ruby::garnet::EXT_IN_);
    gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo>* credit_link = garnet_link->m_credit_links[gem5::ruby::LinkDirection_In];

    m_networklinks.push_back(net_link);
    m_creditlinks.push_back(credit_link);

    gem5::ruby::PortDirection dst_inport_dirn = "Local";

    m_max_vcs_per_vnet = std::max(m_max_vcs_per_vnet,
                             m_routers[dest]->get_vc_per_vnet());

    /*
     * We check if a bridge was enabled at any end of the link.
     * The bridge is enabled if either of clock domain
     * crossing (CDC) or Serializer-Deserializer(SerDes) unit is
     * enabled for the link at each end. The bridge encapsulates
     * the functionality for both CDC and SerDes and is a Consumer
     * object similiar to a NetworkLink.
     *
     * If a bridge was enabled we connect the NI and Routers to
     * bridge before connecting the link. Example, if an external
     * bridge is enabled, we would connect:
     * NI--->NetworkBridge--->GarnetExtLink---->Router
     */
    if (garnet_link->extBridgeEn) {
        DPRINTF(RubyNetwork, "Enable external bridge for %s\n",
            garnet_link->name());
        gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->extNetBridge[gem5::ruby::LinkDirection_In];
        m_nis[local_src]->
        addOutPort(n_bridge,
                   garnet_link->extCredBridge[gem5::ruby::LinkDirection_In],
                   dest, m_routers[dest]->get_vc_per_vnet());
        m_networkbridges.push_back(n_bridge);
    } else {
        m_nis[local_src]->addOutPort(net_link, credit_link, dest,
            m_routers[dest]->get_vc_per_vnet());
    }

    if (garnet_link->intBridgeEn) {
        DPRINTF(RubyNetwork, "Enable internal bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->intNetBridge[gem5::ruby::LinkDirection_In];
        m_routers[dest]->
            addInPort(dst_inport_dirn,
                      n_bridge,
                      garnet_link->intCredBridge[gem5::ruby::LinkDirection_In]);
        m_networkbridges.push_back(n_bridge);
    } else {
        m_routers[dest]->addInPort(dst_inport_dirn, net_link, credit_link);
    }

}

/*
 * This function creates a link from the Network to a NI.
 * It creates a Network Link from a Router to the NI and
 * a Credit Link from NI to the Router
*/

void
NocGarnetNetwork::makeExtOutLink(gem5::ruby::SwitchID src, gem5::ruby::NodeID global_dest,
                              NocBasicLink* link,
                              std::vector<NocNetDest>& routing_table_entry)
{
   gem5::ruby::NodeID local_dest = getLocalNodeID(global_dest);
    assert(local_dest < m_nodes);
    assert(src < m_routers.size());
    assert(m_routers[src] != NULL);

    NocGarnetExtLink* garnet_link = safe_cast<NocGarnetExtLink*>(link);

    // GarnetExtLink is bi-directional
    gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo>* net_link = garnet_link->m_network_links[gem5::ruby::LinkDirection_Out];
    net_link->setType(gem5::ruby::garnet::EXT_OUT_);
    gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo>* credit_link = garnet_link->m_credit_links[gem5::ruby::LinkDirection_Out];

    m_networklinks.push_back(net_link);
    m_creditlinks.push_back(credit_link);

    gem5::ruby::PortDirection src_outport_dirn = "Local";

    m_max_vcs_per_vnet = std::max(m_max_vcs_per_vnet,
                             m_routers[src]->get_vc_per_vnet());

    /*
     * We check if a bridge was enabled at any end of the link.
     * The bridge is enabled if either of clock domain
     * crossing (CDC) or Serializer-Deserializer(SerDes) unit is
     * enabled for the link at each end. The bridge encapsulates
     * the functionality for both CDC and SerDes and is a Consumer
     * object similiar to a NetworkLink.
     *
     * If a bridge was enabled we connect the NI and Routers to
     * bridge before connecting the link. Example, if an external
     * bridge is enabled, we would connect:
     * NI<---NetworkBridge<---GarnetExtLink<----Router
     */
    if (garnet_link->extBridgeEn) {
        DPRINTF(RubyNetwork, "Enable external bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->extNetBridge[gem5::ruby::LinkDirection_Out];
        m_nis[local_dest]->
            addInPort(n_bridge,
                      garnet_link->extCredBridge[gem5::ruby::LinkDirection_Out],
                      src);
        m_networkbridges.push_back(n_bridge);
    } else {
        m_nis[local_dest]->addInPort(net_link, credit_link, src);
    }

    if (garnet_link->intBridgeEn) {
        DPRINTF(RubyNetwork, "Enable internal bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->intNetBridge[gem5::ruby::LinkDirection_Out];
        m_routers[src]->
            addOutPort(src_outport_dirn,
                       n_bridge,
                       routing_table_entry, link->m_weight,
                       garnet_link->intCredBridge[gem5::ruby::LinkDirection_Out],
                       m_routers[src]->get_vc_per_vnet(),
                       m_routers[src]->get_nps_type());
        m_networkbridges.push_back(n_bridge);
    } else {
        m_routers[src]->
            addOutPort(src_outport_dirn, net_link,
                       routing_table_entry,
                       link->m_weight, credit_link,
                       m_routers[src]->get_vc_per_vnet(),
                       m_routers[src]->get_nps_type());
    }
}

// this makeExtOutLink is overloaded to use NocRouteMapKey instead of NocNetDest
void
NocGarnetNetwork::makeNocExtOutLink(gem5::ruby::SwitchID src, gem5::ruby::NodeID global_dest,
                              NocBasicLink* link,
                              std::vector<gem5::noc::garnet::NocRouteMapKey>& routes)
{
   gem5::ruby::NodeID local_dest = global_dest;

    assert(local_dest < m_nodes);
    assert(src < m_routers.size());
    assert(m_routers[src] != NULL);

    NocGarnetExtLink* garnet_link = safe_cast<NocGarnetExtLink*>(link);

    DPRINTF(RubyNetwork, "makeExtOutLink: linkid %d src %d, dest %d\n",garnet_link->get_id(),  src, local_dest);

    // GarnetExtLink is bi-directional
    gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo>* net_link = garnet_link->m_network_links[gem5::ruby::LinkDirection_Out];
    net_link->setType(gem5::ruby::garnet::EXT_OUT_);
    gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo>* credit_link = garnet_link->m_credit_links[gem5::ruby::LinkDirection_Out];

    m_networklinks.push_back(net_link);
    m_creditlinks.push_back(credit_link);

    gem5::ruby::PortDirection src_outport_dirn = "Local";

    m_max_vcs_per_vnet = std::max(m_max_vcs_per_vnet,
                             m_routers[src]->get_vc_per_vnet());

    if (garnet_link->extBridgeEn) {
        DPRINTF(RubyNetwork, "Enable external bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->extNetBridge[gem5::ruby::LinkDirection_Out];
        m_nis[local_dest]->
            addInPort(n_bridge,
                      garnet_link->extCredBridge[gem5::ruby::LinkDirection_Out],
                      src);
        m_networkbridges.push_back(n_bridge);
    } else {
        m_nis[local_dest]->addInPort(net_link, credit_link, src);
    }

    if (garnet_link->intBridgeEn) {
        DPRINTF(RubyNetwork, "Enable internal bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->intNetBridge[gem5::ruby::LinkDirection_Out];
        m_routers[src]->
        addNocOutPort(src_outport_dirn,
                       n_bridge,
                       routes, link->m_weight,
                       garnet_link->intCredBridge[gem5::ruby::LinkDirection_Out],
                       m_routers[src]->get_vc_per_vnet(),
                       m_routers[src]->get_nps_type());
        m_networkbridges.push_back(n_bridge);
    } else {
        m_routers[src]->
        addNocOutPort(src_outport_dirn, net_link,
                       routes,
                       link->m_weight, credit_link,
                       m_routers[src]->get_vc_per_vnet(),
                       m_routers[src]->get_nps_type());
    }
}


Nps_Type
NocGarnetNetwork::getOutputCreditNpsType(
    gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest) const
{
    Nps_Type src_type = m_routers[src]->get_nps_type();
    Nps_Type dest_type = m_routers[dest]->get_nps_type();

    // RPTRs are pass-through pipeline elements; they do not represent the
    // downstream elastic storage that the output VC credit depth is modeling.
    if (dest_type == Nps_Type::RPTR && src_type != Nps_Type::RPTR) {
        return src_type;
    }

    return dest_type;
}


/*
 * This function creates an internal network link between two routers.
 * It adds both the network link and an opposite credit link.
*/

void
NocGarnetNetwork::makeInternalLink(gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest, NocBasicLink* link,
                                std::vector<NocNetDest>& routing_table_entry,
                                gem5::ruby::PortDirection src_outport_dirn,
                                gem5::ruby::PortDirection dst_inport_dirn)
{
    NocGarnetIntLink* garnet_link = safe_cast<NocGarnetIntLink*>(link);

    // GarnetIntLink is unidirectional
    gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo>* net_link = garnet_link->m_network_link;
    net_link->setType(gem5::ruby::garnet::INT_);
    gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo>* credit_link = garnet_link->m_credit_link;

    m_networklinks.push_back(net_link);
    m_creditlinks.push_back(credit_link);

    m_max_vcs_per_vnet = std::max(m_max_vcs_per_vnet,
                             std::max(m_routers[dest]->get_vc_per_vnet(),
                             m_routers[src]->get_vc_per_vnet()));
    Nps_Type output_credit_nps_type = getOutputCreditNpsType(src, dest);

    /*
     * We check if a bridge was enabled at any end of the link.
     * The bridge is enabled if either of clock domain
     * crossing (CDC) or Serializer-Deserializer(SerDes) unit is
     * enabled for the link at each end. The bridge encapsulates
     * the functionality for both CDC and SerDes and is a Consumer
     * object similiar to a NetworkLink.
     *
     * If a bridge was enabled we connect the NI and Routers to
     * bridge before connecting the link. Example, if a source
     * bridge is enabled, we would connect:
     * Router--->NetworkBridge--->GarnetIntLink---->Router
     */
    if (garnet_link->dstBridgeEn) {
        DPRINTF(RubyNetwork, "Enable destination bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->dstNetBridge;
        m_routers[dest]->addInPort(dst_inport_dirn, n_bridge,
                                   garnet_link->dstCredBridge);
        m_networkbridges.push_back(n_bridge);
    } else {
        m_routers[dest]->addInPort(dst_inport_dirn, net_link, credit_link);
    }

    if (garnet_link->srcBridgeEn) {
        DPRINTF(RubyNetwork, "Enable source bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->srcNetBridge;
        m_routers[src]->
            addOutPort(src_outport_dirn, n_bridge,
                       routing_table_entry,
                       link->m_weight, garnet_link->srcCredBridge,
                       m_routers[dest]->get_vc_per_vnet(),
                       output_credit_nps_type);
        m_networkbridges.push_back(n_bridge);
    } else {
        m_routers[src]->addOutPort(src_outport_dirn, net_link,
                        routing_table_entry,
                        link->m_weight, credit_link,
                        m_routers[dest]->get_vc_per_vnet(),
                        output_credit_nps_type);
    }
}

// this makeInternalLink is overloaded to use NocRouteMapKey instead of NocNetDest
void
NocGarnetNetwork::makeNocInternalLink(gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest, NocBasicLink* link,
                                std::vector<gem5::noc::garnet::NocRouteMapKey>& routes,
                                gem5::ruby::PortDirection src_outport_dirn,
                                gem5::ruby::PortDirection dst_inport_dirn)
{
    NocGarnetIntLink* garnet_link = safe_cast<NocGarnetIntLink*>(link);
    DPRINTF(RubyNetwork, "makeInternalLink: linkid %d src %d, dest %d\n",garnet_link->get_id() ,src, dest);
    // GarnetIntLink is unidirectional
    gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo>* net_link = garnet_link->m_network_link;
    net_link->setType(gem5::ruby::garnet::INT_);
    gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo>* credit_link = garnet_link->m_credit_link;

    m_networklinks.push_back(net_link);
    m_creditlinks.push_back(credit_link);

    m_max_vcs_per_vnet = std::max(m_max_vcs_per_vnet,
                             std::max(m_routers[dest]->get_vc_per_vnet(),
                             m_routers[src]->get_vc_per_vnet()));
    Nps_Type output_credit_nps_type = getOutputCreditNpsType(src, dest);

    /*
     * We check if a bridge was enabled at any end of the link.
     * The bridge is enabled if either of clock domain
     * crossing (CDC) or Serializer-Deserializer(SerDes) unit is
     * enabled for the link at each end. The bridge encapsulates
     * the functionality for both CDC and SerDes and is a Consumer
     * object similiar to a NetworkLink.
     *
     * If a bridge was enabled we connect the NI and Routers to
     * bridge before connecting the link. Example, if a source
     * bridge is enabled, we would connect:
     * Router--->NetworkBridge--->GarnetIntLink---->Router
     */
    if (garnet_link->dstBridgeEn) {
        DPRINTF(RubyNetwork, "Enable destination bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->dstNetBridge;
        m_routers[dest]->addInPort(dst_inport_dirn, n_bridge,
                                   garnet_link->dstCredBridge);
        m_networkbridges.push_back(n_bridge);
    } else {
        m_routers[dest]->addInPort(dst_inport_dirn, net_link, credit_link);
    }

    if (garnet_link->srcBridgeEn) {
        DPRINTF(RubyNetwork, "Enable source bridge for %s\n",
            garnet_link->name());
            gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *n_bridge = garnet_link->srcNetBridge;
        m_routers[src]->
        addNocOutPort(src_outport_dirn, n_bridge,
                        routes,
                        link->m_weight, garnet_link->srcCredBridge,
                        m_routers[dest]->get_vc_per_vnet(),
                        output_credit_nps_type);
        m_networkbridges.push_back(n_bridge);
    } else {
        m_routers[src]->addNocOutPort(src_outport_dirn, net_link,
                        routes,
                        link->m_weight, credit_link,
                        m_routers[dest]->get_vc_per_vnet(),
                        output_credit_nps_type);
    }
}


// Total routers in the network
int
NocGarnetNetwork::getNumRouters()
{
    return m_routers.size();
}

// Get ID of router connected to a NI.
int
NocGarnetNetwork::get_router_id(int global_ni, int vnet)
{
//    gem5::ruby::NodeID local_ni = getLocalNodeID(global_ni);
    gem5::ruby::NodeID local_ni = global_ni; //got rid of global ids?

    return m_nis[local_ni]->get_router_id(vnet);
}


bool
NocGarnetNetwork::functionalRead(Packet *pkt, gem5::ruby::WriteMask &mask)
{
    bool read = false;
    for (unsigned int i = 0; i < m_routers.size(); i++) {
        if (m_routers[i]->functionalRead(pkt, mask))
            read = true;
    }

    for (unsigned int i = 0; i < m_nis.size(); ++i) {
        if (m_nis[i]->functionalRead(pkt, mask))
            read = true;
    }

    for (unsigned int i = 0; i < m_networklinks.size(); ++i) {
        if (m_networklinks[i]->functionalRead(pkt, mask))
            read = true;
    }

    for (unsigned int i = 0; i < m_networkbridges.size(); ++i) {
        if (m_networkbridges[i]->functionalRead(pkt, mask))
            read = true;
    }

    return read;
}

uint32_t
NocGarnetNetwork::functionalWrite(Packet *pkt)
{
    uint32_t num_functional_writes = 0;

    for (unsigned int i = 0; i < m_routers.size(); i++) {
        num_functional_writes += m_routers[i]->functionalWrite(pkt);
    }

    for (unsigned int i = 0; i < m_nis.size(); ++i) {
        num_functional_writes += m_nis[i]->functionalWrite(pkt);
    }

    for (unsigned int i = 0; i < m_networklinks.size(); ++i) {
        num_functional_writes += m_networklinks[i]->functionalWrite(pkt);
    }

    return num_functional_writes;
}

gem5::ruby::NodeID NocGarnetNetwork::getDestFromAddress(Addr address) const {
    // Use std::upper_bound on the sorted vector
    auto it = std::upper_bound(m_parsed_address_map.begin(),
                               m_parsed_address_map.end(),
                               address, // Value to search for
                               [](Addr val, const AddressMapEntry& entry){
                                   return val < entry.start; // Compare value < entry.start
                               });

    // upper_bound finds the first element > address (comparing via start).
    // We need the element *before* it, whose range might contain address.
    if (it == m_parsed_address_map.begin()) {
        // Address is lower than the start of the first range
        warn("Address %#x is not mapped (below lowest range).\n", address);
        return -1; // Or some other invalid NodeID
    }

    // Check the previous entry
    --it;
    if (address >= it->start && address < it->end) {
        // Address falls within this range
        return it->dest_id;
    } else {
        // Address is between ranges or above the last range
        warn("Address %#x is not mapped (in gap or above highest range).\n", address);
        return -1; // Or some other invalid NodeID
    }
}

gem5::ruby::NodeID
NocGarnetNetwork::getDestFromAddress(gem5::ruby::NodeID src_id, Addr address) const
{
    if (!m_parsed_source_address_map.empty()) {
        gem5::ruby::NodeID matched_dest = -1;
        int matches = 0;
        for (const auto& entry : m_parsed_source_address_map) {
            if (entry.src_id == src_id &&
                address >= entry.start &&
                address < entry.end) {
                matched_dest = entry.dest_id;
                matches++;
            }
        }
        if (matches == 1) {
            return matched_dest;
        }
        if (matches > 1) {
            fatal("Source-aware address map is ambiguous for src=%d addr=%#x (%d matches).",
                  src_id, address, matches);
        }
    }

    return getDestFromAddress(address);
}

int NocGarnetNetwork::getPathVC(gem5::ruby::NodeID src_id,gem5::ruby::NodeID dst_id, int cmd) const {
    // get int from axi command, 0 for read, 1 for write
    int src_id_int = src_id;
    int dst_id_int = dst_id;
    std::tuple<int, int, int> key = {src_id_int, dst_id_int, cmd};
    auto it = m_route_to_vc_map.find(key);

    // Check if the key was found
    if (it != m_route_to_vc_map.end()) {
        // Key found, return the associated value (the VC ID)
        return it->second;
    } else {
        fatal("VC mapping not found for route src=%d, dst=%d, cmd=%d! Check NCR config.",
              src_id_int, dst_id_int, cmd);
    }
}

bool
NocGarnetNetwork::readResponsesUseMultipleVCs(gem5::ruby::NodeID nsu_id) const
{
    constexpr int kReadResponseCmd = 2;

    bool have_vc = false;
    int first_vc = -1;

    for (const auto& [key, vc] : m_route_to_vc_map) {
        const auto& [src_id, dst_id, cmd] = key;
        if (src_id != static_cast<int>(nsu_id) || cmd != kReadResponseCmd) {
            continue;
        }

        // Restrict the structural check to AXI-MM NMUs. This keeps unused
        // endpoint families from changing read-response pacing.
        if (dst_id < 0 || dst_id >= m_num_aximm_nmu) {
            continue;
        }

        if (!have_vc) {
            first_vc = vc;
            have_vc = true;
            continue;
        }

        if (vc != first_vc) {
            return true;
        }
    }

    return false;
}

template <typename T> // T should be an integer type like int, uint64_t
bool parseJsonListOfNumLists(const std::string& json_str,
                             std::vector<std::vector<T>>& out_table,
                             size_t expected_inner_size)
{
    // Ensure T is an integral type (optional safety check)
    static_assert(std::is_integral_v<T>, "Template type T must be integral.");

    out_table.clear();
    std::string current_num_str;
    std::vector<T> current_row;
    enum class State { OUTER_START, IN_OUTER_LIST, IN_INNER_LIST, AFTER_INNER_LIST };
    State state = State::OUTER_START;

    if (json_str.empty()) {
        DPRINTF(RubyNetwork, "JSON Parse: Input string is empty.\n");
        return true; // Empty input is valid
    }

    for (size_t i = 0; i < json_str.length(); ++i) {
        char c = json_str[i];

        if (std::isspace(c)) continue;

        switch (state) {
            case State::OUTER_START:
                if (c == '[') state = State::IN_OUTER_LIST;
                else { warn("JSON Parse Error: Expected '[' at start, got '%c'", c); return false; }
                break;

            case State::IN_OUTER_LIST:
                if (c == '[') {
                    state = State::IN_INNER_LIST;
                    current_row.clear();
                    current_num_str.clear();
                } else if (c == ']') { // End of outer list
                    for (size_t j = i + 1; j < json_str.length(); ++j) { // Check trailing
                        if (!std::isspace(json_str[j])) {
                             warn("JSON Parse Error: Unexpected char '%c' after outer ']'", json_str[j]); return false;
                        }
                    }
                    return true;
                } else { warn("JSON Parse Error: Expected '[' or ']' inside outer list, got '%c'", c); return false; }
                break;

            case State::IN_INNER_LIST:
                // Allow digits, hex prefix 'x'/'X', and leading '-' if signed type
                 if (std::isdigit(c) || c == 'x' || c == 'X' ||
                    (c == '-' && std::is_signed_v<T> && current_num_str.empty())) {
                    current_num_str += c;
                } else if (c == ',') { // End of number
                    if (current_num_str.empty()) { warn("JSON Parse Error: Empty number before comma."); return false; }
                    try {
                        // Use appropriate conversion based on type T
                        if constexpr (std::is_same_v<T, int> || std::is_same_v<T, long> ||
                                      std::is_same_v<T, short> || std::is_same_v<T, signed char>) {
                             current_row.push_back(std::stoi(current_num_str, nullptr, 0));
                        } else if constexpr (std::is_same_v<T, unsigned int> || std::is_same_v<T, unsigned long> ||
                                             std::is_same_v<T, unsigned short> || std::is_same_v<T, unsigned char>) {
                             current_row.push_back(std::stoul(current_num_str, nullptr, 0));
                        } else if constexpr (std::is_same_v<T, long long>) {
                             current_row.push_back(std::stoll(current_num_str, nullptr, 0));
                        } else if constexpr (std::is_same_v<T, unsigned long long> || std::is_same_v<T, uint64_t>) {
                             current_row.push_back(std::stoull(current_num_str, nullptr, 0));
                        } else {
                             // Fallback or error for unsupported types
                             warn("JSON Parse Error: Unsupported integer type in template.");
                             return false;
                        }
                    } catch (const std::exception& e) { warn("JSON Parse Error: Failed converting '%s': %s", current_num_str.c_str(), e.what()); return false; }
                    current_num_str.clear();
                } else if (c == ']') { // End of inner list
                     if (current_num_str.empty()) { warn("JSON Parse Error: Empty number before ']'."); return false; }
                     try {
                         // Use appropriate conversion based on type T
                        if constexpr (std::is_same_v<T, int> || std::is_same_v<T, long> ||
                                      std::is_same_v<T, short> || std::is_same_v<T, signed char>) {
                             current_row.push_back(std::stoi(current_num_str, nullptr, 0));
                        } else if constexpr (std::is_same_v<T, unsigned int> || std::is_same_v<T, unsigned long> ||
                                             std::is_same_v<T, unsigned short> || std::is_same_v<T, unsigned char>) {
                             current_row.push_back(std::stoul(current_num_str, nullptr, 0));
                        } else if constexpr (std::is_same_v<T, long long>) {
                             current_row.push_back(std::stoll(current_num_str, nullptr, 0));
                        } else if constexpr (std::is_same_v<T, unsigned long long> || std::is_same_v<T, uint64_t>) {
                             current_row.push_back(std::stoull(current_num_str, nullptr, 0));
                        } else {
                             warn("JSON Parse Error: Unsupported integer type in template.");
                             return false;
                        }
                     } catch (const std::exception& e) { warn("JSON Parse Error: Failed converting '%s': %s", current_num_str.c_str(), e.what()); return false; }
                     current_num_str.clear();

                     if (current_row.size() != expected_inner_size) {
                         warn("JSON Parse Error: Inner list has %lu elements, expected %lu.", current_row.size(), expected_inner_size);
                         return false;
                     }
                     out_table.push_back(current_row);
                     state = State::AFTER_INNER_LIST;
                } else { warn("JSON Parse Error: Unexpected char '%c' inside inner list", c); return false; }
                break;

            case State::AFTER_INNER_LIST:
                 if (c == ',') state = State::IN_OUTER_LIST;
                 else if (c == ']') { // End of outer list
                    for (size_t j = i + 1; j < json_str.length(); ++j) { // Check trailing
                        if (!std::isspace(json_str[j])) {
                             warn("JSON Parse Error: Unexpected char '%c' after outer ']'", json_str[j]); return false;
                        }
                    }
                    return true;
                 } else { warn("JSON Parse Error: Expected ',' or ']' after inner list, got '%c'", c); return false; }
                 break;
        } // end switch
    } // end for

    // Check final state
    if (state != State::AFTER_INNER_LIST && !(state == State::IN_OUTER_LIST && out_table.empty())) {
        warn("JSON Parse Error: Unexpected end of string in state %d", static_cast<int>(state));
        return false;
    }
    if (state == State::IN_OUTER_LIST && out_table.empty()) return true; // Allow "[]"

    return (state == State::AFTER_INNER_LIST);
}
// --- END TEMPLATE HELPER FUNCTION ---


// Function to parse the VC Map Info JSON and populate the member map
// (Uses the template helper)
void NocGarnetNetwork::parseVcMap() {
    DPRINTF(RubyNetwork, "Parsing VC Map Info JSON string.\n");

    constexpr int kWriteRequestCmd = 1;
    constexpr int kReadResponseCmd = 2;

    // Use the template helper function to parse the JSON string
    std::vector<std::vector<int>> temp_table; // VC map uses int
    // Expecting 4 elements: [src_id, dst_id, req_type, vc_id]
    if (!parseJsonListOfNumLists<int>(m_route_to_vc_json, temp_table, 4)) {
        fatal("Failed to parse VC Map Info JSON string:\n%s", m_route_to_vc_json);
    }

    // Clear the existing map before populating
    m_route_to_vc_map.clear();
    m_data_physical_vcs.clear();

    // Iterate through the parsed table and populate the map
    for (const auto& row : temp_table) {
        // Size check already done by parser
        int src_id = row[0];
        int dst_id = row[1];
        int req_type = row[2];
        int vc_id = row[3];

        std::tuple<int, int, int> key = {src_id, dst_id, req_type};
        m_route_to_vc_map[key] = vc_id;
        if (req_type == kWriteRequestCmd || req_type == kReadResponseCmd) {
            m_data_physical_vcs.insert(vc_id);
        }

        DPRINTF(RubyNetwork, "  Added VC Map: (%d, %d, %d) -> VC %d\n",
                src_id, dst_id, req_type, vc_id);
    }

    DPRINTF(RubyNetwork, "Parsed and stored %lu VC map entries.\n", m_route_to_vc_map.size());
}

// Function to parse the Address Map JSON (if needed elsewhere)
// (Uses the template helper)
void NocGarnetNetwork::parseAddressMap() {
    DPRINTF(RubyNetwork, "Parsing Address Map JSON string.\n");

    std::vector<std::vector<uint64_t>> temp_table; // Address map uses uint64_t
    // Expecting 3 elements: [start_addr, end_addr, dest_id]
    if (!parseJsonListOfNumLists<uint64_t>(m_address_map_json, temp_table, 3)) {
        fatal("Failed to parse address map JSON string:\n%s", m_address_map_json);
    }

    m_parsed_address_map.clear();
    m_parsed_address_map.reserve(temp_table.size());

    for (const auto& row : temp_table) {
        // Size check done by parser
        Addr start = row[0]; // Addr is likely uint64_t based
        Addr end = row[1];
        // Assuming NodeID can be constructed from uint64_t/int
        gem5::ruby::NodeID dest = static_cast<gem5::ruby::NodeID>(row[2]);

        if (start >= end) {
            warn("Skipping invalid address map range [%#x, %#x).", start, end);
            continue;
        }
        // Add validation for NodeID range if needed

        m_parsed_address_map.push_back({start, end, dest});
         DPRINTF(RubyNetwork, "  Added Addr Map: [%#x, %#x) -> %d\n", start, end, dest);
    }

    // Sort by start address for efficient lookup
    std::sort(m_parsed_address_map.begin(), m_parsed_address_map.end());

    // Optional: Check for overlaps after sorting
    for (size_t i = 0; i + 1 < m_parsed_address_map.size(); ++i) {
        if (m_parsed_address_map[i].end > m_parsed_address_map[i+1].start) {
            warn("Address map ranges overlap: [%#x, %#x) and [%#x, %#x)",
                 m_parsed_address_map[i].start, m_parsed_address_map[i].end,
                 m_parsed_address_map[i+1].start, m_parsed_address_map[i+1].end);
        }
    }
    DPRINTF(RubyNetwork, "Parsed and sorted %lu address map entries.\n", m_parsed_address_map.size());
}

void NocGarnetNetwork::parseSourceAddressMap() {
    DPRINTF(RubyNetwork, "Parsing source-aware Address Map JSON string.\n");

    if (m_source_address_map_json.empty()) {
        m_parsed_source_address_map.clear();
        return;
    }

    std::vector<std::vector<uint64_t>> temp_table;
    if (!parseJsonListOfNumLists<uint64_t>(m_source_address_map_json, temp_table, 4)) {
        fatal("Failed to parse source-aware address map JSON string:\n%s",
              m_source_address_map_json);
    }

    m_parsed_source_address_map.clear();
    m_parsed_source_address_map.reserve(temp_table.size());

    for (const auto& row : temp_table) {
        gem5::ruby::NodeID src = static_cast<gem5::ruby::NodeID>(row[0]);
        Addr start = row[1];
        Addr end = row[2];
        gem5::ruby::NodeID dest = static_cast<gem5::ruby::NodeID>(row[3]);

        if (start >= end) {
            warn("Skipping invalid source-aware address map range for src=%d [%#x, %#x).",
                 src, start, end);
            continue;
        }

        m_parsed_source_address_map.push_back({src, start, end, dest});
        DPRINTF(RubyNetwork,
                "  Added Source Addr Map: src=%d [%#x, %#x) -> %d\n",
                src, start, end, dest);
    }

    std::sort(m_parsed_source_address_map.begin(), m_parsed_source_address_map.end());
    DPRINTF(RubyNetwork, "Parsed and sorted %lu source-aware address map entries.\n",
            m_parsed_source_address_map.size());
}

// Parse AXIS tdest map: JSON format {"nmu_id": {"tdest": dest_ni, ...}, ...}
// Note: JSON serializes integer keys as strings, so we parse accordingly
void NocGarnetNetwork::parseAxisTdestMap() {
    m_axis_tdest_map.clear();

    if (m_axis_tdest_map_json.empty()) {
        DPRINTF(RubyNetwork, "AXIS tdest map JSON is empty, skipping parse.\n");
        return;
    }

    // Simple hand-parser for nested dict {str: {str: int, ...}, ...}
    // Expected format: {"1": {"0": 0}, "2": {"0": 1, "1": 3}}
    std::string json = m_axis_tdest_map_json;
    size_t pos = 0;

    // Skip whitespace and opening brace
    while (pos < json.size() && (std::isspace(json[pos]) || json[pos] == '{')) pos++;

    while (pos < json.size()) {
        // Skip to next quote (start of NMU ID key)
        while (pos < json.size() && json[pos] != '"' && json[pos] != '}') pos++;
        if (pos >= json.size() || json[pos] == '}') break;

        pos++; // skip opening quote
        // Parse NMU ID
        std::string nmu_id_str;
        while (pos < json.size() && json[pos] != '"') {
            nmu_id_str += json[pos++];
        }
        pos++; // skip closing quote
        int nmu_id = std::stoi(nmu_id_str);

        // Skip to opening brace of inner dict
        while (pos < json.size() && json[pos] != '{') pos++;
        pos++; // skip opening brace

        m_axis_tdest_map[nmu_id] = std::map<int, int>();

        // Parse inner dict entries
        while (pos < json.size() && json[pos] != '}') {
            // Skip to next quote
            while (pos < json.size() && json[pos] != '"' && json[pos] != '}') pos++;
            if (json[pos] == '}') break;

            pos++; // skip opening quote
            // Parse tdest key
            std::string tdest_str;
            while (pos < json.size() && json[pos] != '"') {
                tdest_str += json[pos++];
            }
            pos++; // skip closing quote
            int tdest = std::stoi(tdest_str);

            // Skip to colon and value
            while (pos < json.size() && json[pos] != ':') pos++;
            pos++; // skip colon
            while (pos < json.size() && std::isspace(json[pos])) pos++;

            // Parse dest_ni value
            std::string dest_ni_str;
            while (pos < json.size() && (std::isdigit(json[pos]) || json[pos] == '-')) {
                dest_ni_str += json[pos++];
            }
            int dest_ni = std::stoi(dest_ni_str);

            m_axis_tdest_map[nmu_id][tdest] = dest_ni;
            DPRINTF(RubyNetwork, "AXIS tdest map: NMU %d, tdest %d -> dest_ni %d\n",
                    nmu_id, tdest, dest_ni);

            // Skip comma if present
            while (pos < json.size() && (std::isspace(json[pos]) || json[pos] == ',')) pos++;
        }
        pos++; // skip closing brace of inner dict

        // Skip comma if present
        while (pos < json.size() && (std::isspace(json[pos]) || json[pos] == ',')) pos++;
    }

    DPRINTF(RubyNetwork, "Parsed AXIS tdest map with %lu NMU entries.\n",
            m_axis_tdest_map.size());
}

int NocGarnetNetwork::getAxisDestNi(int nmu_id, int tdest) const {
    auto nmu_it = m_axis_tdest_map.find(nmu_id);
    if (nmu_it == m_axis_tdest_map.end()) {
        warn("AXIS tdest lookup: NMU %d not found in tdest map!", nmu_id);
        return -1;
    }

    auto tdest_it = nmu_it->second.find(tdest);
    if (tdest_it == nmu_it->second.end()) {
        warn("AXIS tdest lookup: NMU %d has no mapping for tdest %d!", nmu_id, tdest);
        return -1;
    }

    return tdest_it->second;
}

gem5::Cycles NocGarnetNetwork::get_nps_latency(gem5::noc::garnet::Nps_Type nps_type) const {
    switch(nps_type) {
        case gem5::noc::garnet::Nps_Type::VNOC: return m_vnoc_latency;
        case gem5::noc::garnet::Nps_Type::HNOC: return m_hnoc_latency;
        case gem5::noc::garnet::Nps_Type::RPTR: return m_rptr_latency;
        case gem5::noc::garnet::Nps_Type::NCRB: return m_ncrb_latency;
        case gem5::noc::garnet::Nps_Type::NIDB: return m_nidb_latency;
        default: return m_vnoc_latency;
    }
}

uint32_t NocGarnetNetwork::get_nps_credits(gem5::noc::garnet::Nps_Type nps_type) const {
    switch(nps_type) {
        case gem5::noc::garnet::Nps_Type::VNOC: return m_vnoc_credits;
        case gem5::noc::garnet::Nps_Type::HNOC: return m_hnoc_credits;
        case gem5::noc::garnet::Nps_Type::RPTR: return m_rptr_credits;
        case gem5::noc::garnet::Nps_Type::NCRB: return m_ncrb_credits;
        case gem5::noc::garnet::Nps_Type::NIDB: return m_nidb_credits;
        default: return m_vnoc_credits;
    }
}

uint32_t
NocGarnetNetwork::get_effective_buffer_depth_for_class(
    bool is_data_vc, gem5::noc::garnet::Nps_Type nps_type) const
{
    if (is_data_vc && m_buffers_per_data_vc_overridden) {
        fatal_if(m_buffers_per_data_vc < 1,
                 "buffers_per_data_vc override must be at least 1");
        return m_buffers_per_data_vc;
    }

    if (!is_data_vc && m_buffers_per_ctrl_vc_overridden) {
        fatal_if(m_buffers_per_ctrl_vc < 1,
                 "buffers_per_ctrl_vc override must be at least 1");
        return m_buffers_per_ctrl_vc;
    }

    return get_nps_credits(nps_type);
}

uint32_t
NocGarnetNetwork::get_effective_vc_buffer_depth(
    int vnet, gem5::noc::garnet::Nps_Type nps_type) const
{
    const bool is_data_vnet =
        vnet >= 0 && vnet < static_cast<int>(m_vnet_type.size()) &&
        m_vnet_type[vnet] == gem5::ruby::garnet::DATA_VNET_;

    return get_effective_buffer_depth_for_class(is_data_vnet, nps_type);
}

uint32_t
NocGarnetNetwork::get_effective_physical_vc_buffer_depth(
    int physical_vc,
    uint32_t consumerVcs,
    gem5::noc::garnet::Nps_Type nps_type) const
{
    if (!m_data_physical_vcs.empty()) {
        return get_effective_buffer_depth_for_class(
            m_data_physical_vcs.count(physical_vc) > 0, nps_type);
    }

    const int vnet = consumerVcs > 0 ? physical_vc / consumerVcs : 0;
    return get_effective_vc_buffer_depth(vnet, nps_type);
}

void
NocGarnetNetwork::serialize(CheckpointOut &cp) const
{
    NocNetwork::serialize(cp);
    paramOut(cp, "ngn_next_packet_id", m_next_packet_id);
}

void
NocGarnetNetwork::unserialize(CheckpointIn &cp)
{
    NocNetwork::unserialize(cp);
    paramIn(cp, "ngn_next_packet_id", m_next_packet_id);
}

void
NocGarnetNetwork::trafficMonitorOutstandingPoll()
{
    m_traffic_monitor.pollOutstandingTransactions(curTick());
    const Tick p = m_traffic_monitor.outstandingPollPeriodTicks();
    if (p > 0) {
        schedule(m_trafficMonitorOutstandingPollEvent, curTick() + p);
    }
}

void
NocGarnetNetwork::trafficMonitorCsvHeartbeat()
{
    m_traffic_monitor.logCsvHeartbeatsIfIdle(curTick());
    const Tick hb_pd = m_traffic_monitor.csvHeartbeatPeriodTicks();
    if (hb_pd > 0) {
        schedule(m_trafficMonitorCsvHeartbeatEvent, curTick() + hb_pd);
    }
}

void
NocGarnetNetwork::traceNsuReadDrain(
    const char *event,
    int nsu_id,
    int axi_id,
    int src_ni,
    int vc,
    int packet_id,
    int flit_idx,
    uint32_t bytes_received,
    uint32_t bytes_sent,
    uint32_t total_bytes_needed,
    bool slave_finished,
    const std::array<uint8_t, 8> &rrob_tags)
{
    if (!m_nsuReadDrainTraceFile || !m_nsuReadDrainTraceFile->good())
        return;

    std::ostream &out = *m_nsuReadDrainTraceFile;
    const Tick t = curTick();
    const uint64_t cycle = static_cast<uint64_t>(ticksToCycles(t));

    out << t << ',' << cycle << ',';
    writeCsvField(out, event ? event : "");
    out << ',' << nsu_id << ',' << axi_id << ',' << src_ni << ',' << vc
        << ',' << packet_id << ',' << flit_idx << ',' << bytes_received
        << ',' << bytes_sent << ',' << total_bytes_needed << ','
        << (slave_finished ? 1 : 0);
    for (uint8_t tag : rrob_tags) {
        out << ',' << static_cast<unsigned>(tag);
    }
    out << '\n';
}

void
NocGarnetNetwork::traceNpsSwitchArb(
    const char *event,
    int router_id,
    const std::string &nocname,
    Nps_Type nps_type,
    int outport,
    int inport,
    int vc,
    int priority,
    int tokens,
    int lock_inport,
    int lock_vc,
    int packet_id,
    int flit_id,
    int src_ni,
    int dest_ni,
    int vnet,
    int flit_type,
    int axi_type)
{
    if (!m_npsSwitchArbTraceFile || !m_npsSwitchArbTraceFile->good())
        return;

    std::ostream &out = *m_npsSwitchArbTraceFile;
    const Tick t = curTick();
    const uint64_t cycle = static_cast<uint64_t>(ticksToCycles(t));

    out << t << ',' << cycle << ',';
    writeCsvField(out, event ? event : "");
    out << ',' << router_id << ',';
    writeCsvField(out, nocname);
    out << ',';
    writeCsvField(out, NpsTypeToString(nps_type));
    out << ',' << outport << ',' << inport << ',' << vc << ','
        << priority << ',' << tokens << ',' << lock_inport << ','
        << lock_vc << ',' << packet_id << ',' << flit_id << ','
        << src_ni << ',' << dest_ni << ',' << vnet << ','
        << flit_type << ',' << axi_type << '\n';
}

void
NocGarnetNetwork::npsQueueTraceSample()
{
    if (!m_npsQueueTraceFile || !m_npsQueueTraceFile->good())
        return;

    std::ostream &out = *m_npsQueueTraceFile;
    const Tick t = curTick();
    const uint64_t cycle = static_cast<uint64_t>(ticksToCycles(t));

    for (NocRouter<NocMessage, NocRouteInfo> *router : m_routers) {
        const int rid = router->get_id();
        const std::string nocname = router->get_name();
        const std::string nps_str = NpsTypeToString(router->get_nps_type());

        const int nin = router->get_num_inports();
        const int nvcs = router->get_num_vcs();

        bool any = false;
        for (int in = 0; in < nin; ++in) {
            auto *iu = router->getInputUnit(in);
            if (iu->getCreditQueue()->getSize() > 0)
                any = true;
            for (int vc = 0; vc < nvcs; ++vc) {
                if (iu->getVcOccupancy(vc) > 0)
                    any = true;
            }
        }
        if (!any)
            continue;

        for (int in = 0; in < nin; ++in) {
            auto *iu = router->getInputUnit(in);
            const int cdepth = iu->getCreditQueue()->getSize();
            if (cdepth > 0) {
                out << t << ',' << cycle << ',' << rid << ',';
                writeCsvField(out, nocname);
                out << ',' << nps_str << ",credit," << in << ",-1,"
                    << cdepth << '\n';
            }
            for (int vc = 0; vc < nvcs; ++vc) {
                const int d = iu->getVcOccupancy(vc);
                if (d > 0) {
                    out << t << ',' << cycle << ',' << rid << ',';
                    writeCsvField(out, nocname);
                    out << ',' << nps_str << ",data_vc," << in << ',' << vc
                        << ',' << d << '\n';
                }
            }
        }
    }

    if (params().nps_queue_trace_mode != 0)
        schedule(npsQueueTraceEvent, clockEdge(Cycles(1)));
}

} // namespace garnet
} // namespace noc
} // namespace gem5
