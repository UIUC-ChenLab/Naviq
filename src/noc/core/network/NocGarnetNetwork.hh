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

 //copied and modified from src/mem/ruby/network/garnet/GarnetNetwork.hh

#ifndef __NOCGARNETNETWORK_HH__
#define __NOCGARNETNETWORK_HH__

#include <array>
#include <fstream>
#include <iostream>
#include <memory>
#include <vector>
#include <tuple>
#include <map>
#include <set>
//  #include "mem/ruby/network/Network.hh"
#include "noc/core/network/NocNetwork.hh"
#include "mem/ruby/network/fault_model/FaultModel.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/common/WriteMask.hh"
#include "noc/core/network/NocNetDest.hh"
#include "noc/lib/network/NocMessage.hh"
#include "params/NocGarnetNetwork.hh"
#include "noc/monitors/NocTrafficMonitor.hh"
#include "sim/serialize.hh"
#include "sim/eventq.hh"


namespace gem5{
    namespace ruby{
        class FaultModel;
        // class NetDest;
        class WriteMask;

        namespace garnet{
            template <typename T_Msg, typename T_RouteInfo> class Router;
            template <typename T_Msg, typename T_RouteInfo> class NetworkLink;
            template <typename T_Msg, typename T_RouteInfo> class NetworkBridge;
            template <typename T_Msg, typename T_RouteInfo> class CreditLink;
        }
    }
}


namespace gem5
{

namespace noc
{

namespace garnet
{
    typedef uint64_t Addr;
    struct AddressMapEntry {
        Addr start;
        Addr end;
        gem5::ruby::NodeID dest_id; // Use NodeID type

        // For sorting
        bool operator<(const AddressMapEntry& other) const {
            return start < other.start;
        }
    };

    struct SourceAddressMapEntry {
        gem5::ruby::NodeID src_id;
        Addr start;
        Addr end;
        gem5::ruby::NodeID dest_id;

        bool operator<(const SourceAddressMapEntry& other) const {
            return std::tie(src_id, start, end, dest_id) <
                   std::tie(other.src_id, other.start, other.end, other.dest_id);
        }
    };

    template <typename T_Msg, typename T_RouteInfo> class NocRouter;

class NetworkInterface;

/**
 * Concrete routed NoC built on the gem5 Garnet transport model.
 *
 * Topology setup creates routers, links, and network interfaces here.  The
 * class parses address, source-address, route-to-VC, and AXIS TDEST maps used
 * by endpoint units; it does not implement AXI protocol semantics itself.
 * Endpoint packetization and ordering belong to the NMU/NSU classes.
 */
class NocGarnetNetwork : public gem5::noc::NocNetwork
{
  public:
    PARAMS(NocGarnetNetwork);
    NocGarnetNetwork(const Params &p);
    ~NocGarnetNetwork() = default;

    void init();

    const char *garnetVersion = "3.0";

    // Configuration (set externally)

    // for 2D topology
    int getNumRows() const { return m_num_rows; }
    int getNumCols() { return m_num_cols; }

    // for network
    uint32_t getNiFlitSize() const { return m_ni_flit_size; }
    uint32_t getBuffersPerDataVC() { return m_buffers_per_data_vc; }
    uint32_t getBuffersPerCtrlVC() { return m_buffers_per_ctrl_vc; }
    bool hasDataVcBufferOverride() const
    {
        return m_buffers_per_data_vc_overridden;
    }
    bool hasCtrlVcBufferOverride() const
    {
        return m_buffers_per_ctrl_vc_overridden;
    }
    int getRoutingAlgorithm() const { return m_routing_algorithm; }

    bool isFaultModelEnabled() const { return m_enable_fault_model; }
    gem5::ruby::FaultModel* fault_model;


    // Internal configuration
    bool isVNetOrdered(int vnet) const { return m_ordered[vnet]; }
    gem5::ruby::garnet::VNET_type
    get_vnet_type(int vnet)
    {
        return m_vnet_type[vnet];
    }
    int getNumRouters();
    int get_router_id(int ni, int vnet);


    // Methods used by Topology to setup the network
    void makeExtOutLink(gem5::ruby::SwitchID src, gem5::ruby::NodeID dest, NocBasicLink* link,
                     std::vector<NocNetDest>& routing_table_entry);
    void makeExtInLink(gem5::ruby::NodeID src, gem5::ruby::SwitchID dest, NocBasicLink* link);
    void makeInternalLink(gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest, NocBasicLink* link,
                          std::vector<NocNetDest>& routing_table_entry,
                          gem5::ruby::PortDirection src_outport_dirn,
                          gem5::ruby::PortDirection dest_inport_dirn);
    void makeNocExtOutLink(gem5::ruby::SwitchID src, gem5::ruby::NodeID dest, NocBasicLink* link,
                            std::vector<gem5::noc::garnet::NocRouteMapKey>& routes);
    void makeNocExtInLink(gem5::ruby::NodeID src, gem5::ruby::SwitchID dest, NocBasicLink* link);
    void makeNocInternalLink(gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest, NocBasicLink* link,
                            std::vector<gem5::noc::garnet::NocRouteMapKey>& routes,
                            gem5::ruby::PortDirection src_outport_dirn,
                            gem5::ruby::PortDirection dest_inport_dirn);

    bool functionalRead(Packet *pkt, gem5::ruby::WriteMask &mask);
    //! Function for performing a functional write. The return value
    //! indicates the number of messages that were written.
    uint32_t functionalWrite(Packet *pkt);

    int getNextPacketID() { return m_next_packet_id++; }

    void parseAddressMap();
    void parseSourceAddressMap();
    void parseVcMap();
    gem5::ruby::NodeID getDestFromAddress(Addr address) const;
    gem5::ruby::NodeID getDestFromAddress(gem5::ruby::NodeID src_id, Addr address) const;
    int getPathVC(gem5::ruby::NodeID src_id,gem5::ruby::NodeID dst_id, int cmd_int) const;
    bool readResponsesUseMultipleVCs(gem5::ruby::NodeID nsu_id) const;

    NocTrafficMonitor& getTrafficMonitor() { return m_traffic_monitor; }
    const NocTrafficMonitor& getTrafficMonitor() const { return m_traffic_monitor; }

    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;

   protected:
     // Configuration
     int m_num_rows;
     int m_num_cols;
     uint32_t m_ni_flit_size;
     uint32_t m_max_vcs_per_vnet;
     uint32_t m_buffers_per_ctrl_vc;
     uint32_t m_buffers_per_data_vc;
     bool m_buffers_per_ctrl_vc_overridden;
     bool m_buffers_per_data_vc_overridden;
     int m_routing_algorithm;
     bool m_enable_fault_model;

     gem5::Cycles m_rptr_latency;
     gem5::Cycles m_vnoc_latency;
     gem5::Cycles m_hnoc_latency;
     gem5::Cycles m_ncrb_latency;
     gem5::Cycles m_nidb_latency;

     uint32_t m_rptr_credits;
     uint32_t m_vnoc_credits;
     uint32_t m_hnoc_credits;
     uint32_t m_ncrb_credits;
     uint32_t m_nidb_credits;


   private:
     NocGarnetNetwork(const NocGarnetNetwork& obj);
     NocGarnetNetwork& operator=(const NocGarnetNetwork& obj);

     std::vector<gem5::ruby::garnet::VNET_type > m_vnet_type;
     std::vector<gem5::noc::garnet::NocRouter<NocMessage, NocRouteInfo> *> m_routers;   // All Routers in Network
     std::vector<gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *> m_networklinks; // All flit links in the network
     std::vector<gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo> *> m_networkbridges; // All network bridges
     std::vector<gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *> m_creditlinks; // All credit links in the network
     std::vector<NetworkInterface *> m_nis;   // All NI's in Network
     int m_next_packet_id; // static vairable for packet id allocation
     const std::string m_custom_routing_table_json;
     const std::string m_address_map_json;
     std::vector<AddressMapEntry> m_parsed_address_map;
     const std::string m_source_address_map_json;
     std::vector<SourceAddressMapEntry> m_parsed_source_address_map;
     const std::string m_route_to_vc_json;
     std::map<std::tuple<int, int, int>, int> m_route_to_vc_map;
     std::set<int> m_data_physical_vcs;
     NocTrafficMonitor m_traffic_monitor;
     int m_num_aximm_nmu;
     int m_num_aximm_nsu;
     int m_num_axis_nmu;
     int m_num_axis_nsu;
     bool m_enable_detailed_metrics;
     gem5::noc::garnet::Nps_Type getOutputCreditNpsType(
         gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest) const;

     // AXIS tdest-to-dest_ni routing map: nmu_id -> (tdest -> dest_ni)
     const std::string m_axis_tdest_map_json;
     std::map<int, std::map<int, int>> m_axis_tdest_map;

  public:
     // Look up dest_ni for an AXIS packet based on source NMU id and tdest
     int getAxisDestNi(int nmu_id, int tdest) const;
     void parseAxisTdestMap();

     gem5::Cycles get_nps_latency(gem5::noc::garnet::Nps_Type nps_type) const;
     uint32_t get_nps_credits(gem5::noc::garnet::Nps_Type nps_type) const;
     uint32_t get_effective_vc_buffer_depth(
         int vnet, gem5::noc::garnet::Nps_Type nps_type) const;
     uint32_t get_effective_physical_vc_buffer_depth(
         int physical_vc,
         uint32_t consumerVcs,
         gem5::noc::garnet::Nps_Type nps_type) const;
     void traceNsuReadDrain(
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
         const std::array<uint8_t, 8> &rrob_tags);
     void traceNpsSwitchArb(
         const char *event,
         int router_id,
         const std::string &nocname,
         gem5::noc::garnet::Nps_Type nps_type,
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
         int axi_type);

  private:
     uint32_t get_effective_buffer_depth_for_class(
         bool is_data_vc, gem5::noc::garnet::Nps_Type nps_type) const;
     void npsQueueTraceSample();
     void trafficMonitorOutstandingPoll();
     void trafficMonitorCsvHeartbeat();

     EventFunctionWrapper npsQueueTraceEvent;
     EventFunctionWrapper m_trafficMonitorOutstandingPollEvent;
     EventFunctionWrapper m_trafficMonitorCsvHeartbeatEvent;
     std::unique_ptr<std::ofstream> m_npsQueueTraceFile;
     std::unique_ptr<std::ofstream> m_npsSwitchArbTraceFile;
     std::unique_ptr<std::ofstream> m_nsuReadDrainTraceFile;
 };

//  inline std::ostream&
//  operator<<(std::ostream& out, const NocGarnetNetwork& obj)
//  {
//      obj.print(out);
//      out << std::flush;
//      return out;
//  }

 } // namespace garnet
 } // namespace noc
 } // namespace gem5

 #endif
