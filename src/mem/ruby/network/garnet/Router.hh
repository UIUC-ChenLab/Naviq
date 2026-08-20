/*
 * Copyright (c) 2020 Inria
 * Copyright (c) 2016 Georgia Institute of Technology
 * Copyright (c) 2008 Princeton University
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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_ROUTER_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_ROUTER_HH__

#include <iostream>
#include <memory>
#include <vector>

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/common/NetDest.hh"
#include "mem/ruby/network/BasicRouter.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "sim/serialize.hh"
#include "mem/ruby/network/garnet/CrossbarSwitch.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh"
#include "mem/ruby/network/garnet/RoutingUnit.hh"
#include "mem/ruby/network/garnet/SwitchAllocator.hh"
#include "mem/ruby/network/garnet/flit.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "params/GarnetRouter.hh"
#include "params/NocGarnetRouter.hh"

#include "noc/core/network/NocGarnetNetwork.hh"
#include "noc/core/network/NocNetDest.hh"

namespace gem5 {
  namespace noc {
    class NocNetDest;
    namespace garnet
    {
        class NocGarnetNetwork;
    }
  }
}

namespace gem5
{

namespace ruby
{

class FaultModel;

namespace garnet
{

// template <typename T_Msg, typename T_RouteInfo> class NetworkLink;
// template <typename T_Msg, typename T_RouteInfo> class CreditLink;
// template <typename T_Msg, typename T_RouteInfo> class InputUnit;
// template <typename T_Msg, typename T_RouteInfo> class OutputUnit;

template <typename T_Msg, typename T_RouteInfo>
class Router : public BasicRouter, public Consumer
{
  public:
    using Params = std::conditional_t<
    std::is_same_v<T_Msg, gem5::noc::NocMessage> && std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>,
    NocGarnetRouterParams,
    GarnetRouterParams>;

    using NetworkType = std::conditional_t<
        std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>,
        gem5::noc::garnet::NocGarnetNetwork,
        GarnetNetwork
    >;

    Router(const Params &p);

    ~Router() = default;

    void wakeup();
    void print(std::ostream& out) const {};

    void init();
    void addInPort(PortDirection inport_dirn, NetworkLink<T_Msg, T_RouteInfo> *link,
                   CreditLink<T_Msg, T_RouteInfo> *credit_link);
    void addOutPort(PortDirection outport_dirn, NetworkLink<T_Msg, T_RouteInfo> *link,
                    std::vector<NetDest>& routing_table_entry,
                    int link_weight, CreditLink<T_Msg, T_RouteInfo> *credit_link,
                    uint32_t consumerVcs);

    // version that uses NocNetDest instead
    void addOutPort(PortDirection outport_dirn, NetworkLink<T_Msg, T_RouteInfo> *link,
                        std::vector<gem5::noc::NocNetDest>& routing_table_entry,
                        int link_weight, CreditLink<T_Msg, T_RouteInfo> *credit_link,
                        uint32_t consumerVcs);

    Cycles get_pipe_stages(){ return m_latency; }
    void set_latency(Cycles latency) {m_latency=  latency;}
    uint32_t get_num_vcs()       { return m_num_vcs; }
    uint32_t get_num_vnets()     { return m_virtual_networks; }
    uint32_t get_vc_per_vnet()   { return m_vc_per_vnet; }
    int get_num_inports()   { return m_input_unit.size(); }
    int get_num_outports()  { return m_output_unit.size(); }
    int get_id()            { return m_id; }

    /**
     * Sum flit counts and buffer capacities across all modeled in-router
     * queues: per-VC input buffers, per-input credit queues, crossbar
     * switch (ST) buffers, and per-output link staging buffers.
     */
    void sumInternalFlitBufferStats(int& occSum, int& maxCapSum);

    int findOutputUnitIndexByOutQueue(
        flitBuffer<T_Msg, T_RouteInfo> *q) const;
    int findInputUnitIndexByCreditQueue(
        flitBuffer<T_Msg, T_RouteInfo> *q) const;
    void crossbar_wakeup() { crossbarSwitch.wakeup(); }
    void output_unit_wakeup(int outport)
    {
        assert(outport < m_output_unit.size());
        m_output_unit[outport]->wakeup();
    }
    void input_unit_wakeup(int inport)
    {
        assert(inport < m_input_unit.size());
        m_input_unit[inport]->nocwakeup();
    }

    void init_net_ptr(NetworkType* net_ptr)
    {
        m_network_ptr = net_ptr;
    }

    NetworkType* get_net_ptr()                    { return m_network_ptr; }

    InputUnit<T_Msg, T_RouteInfo>*
    getInputUnit(unsigned port)
    {
        assert(port < m_input_unit.size());
        return m_input_unit[port].get();
    }

    OutputUnit<T_Msg, T_RouteInfo>*
    getOutputUnit(unsigned port)
    {
        assert(port < m_output_unit.size());
        return m_output_unit[port].get();
    }

    void addOutputUnit(std::shared_ptr<OutputUnit<T_Msg, T_RouteInfo>> output_unit)
    {
        m_output_unit.push_back(output_unit);
    }

    int getBitWidth() { return m_bit_width; }

    PortDirection getOutportDirection(int outport);
    PortDirection getInportDirection(int inport);

    int route_compute(T_RouteInfo route, int inport, PortDirection direction, int vc);
    void grant_switch(int inport, flit<T_Msg, T_RouteInfo> *t_flit);
    void schedule_wakeup(Cycles time);

    std::string getPortDirectionName(PortDirection direction);
    void printFaultVector(std::ostream& out);
    void printAggregateFaultProbability(std::ostream& out);

    void regStats();
    void collateStats();
    void resetStats();

    // For Fault Model:
    bool get_fault_vector(int temperature, float fault_vector[]) {
        return m_network_ptr->fault_model->fault_vector(m_id, temperature,
                                                        fault_vector);
    }
    bool get_aggregate_fault_probability(int temperature,
                                         float *aggregate_fault_prob) {
        return m_network_ptr->fault_model->fault_prob(m_id, temperature,
                                                      aggregate_fault_prob);
    }

    bool functionalRead(Packet *pkt, WriteMask &mask);
    uint32_t functionalWrite(Packet *);
    void set_sw_input_arbiter_activity(double sw_input_arbiter_activity)
    {
        m_sw_input_arbiter_activity = sw_input_arbiter_activity;
    }
    void set_sw_output_arbiter_activity(double sw_output_arbiter_activity)
    {
        m_sw_output_arbiter_activity = sw_output_arbiter_activity;
    }
    void add_routing_unit_entry(std::vector<gem5::noc::NocNetDest>& routing_table_entry,
        int link_weight, PortDirection outport_dirn, int outport)
    {
        routingUnit.addRoute(routing_table_entry);
        routingUnit.addWeight(link_weight);
        routingUnit.addOutDirection(outport_dirn, outport);
    }
    void add_custom_routing_unit_entry(std::vector<gem5::noc::garnet::NocRouteMapKey>& routes,
        int link_weight, PortDirection outport_dirn, int outport)
    {
        routingUnit.addCustomRoutes(outport, routes);
        routingUnit.addWeight(link_weight);
        routingUnit.addOutDirection(outport_dirn, outport);
    }

    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;

  private:
    Cycles m_latency;
    uint32_t m_virtual_networks, m_vc_per_vnet, m_num_vcs;
    uint32_t m_bit_width;
    NetworkType *m_network_ptr;

    RoutingUnit<T_Msg, T_RouteInfo> routingUnit;
    SwitchAllocator<T_Msg, T_RouteInfo> switchAllocator;
    CrossbarSwitch<T_Msg, T_RouteInfo> crossbarSwitch;

    std::vector<std::shared_ptr<InputUnit<T_Msg, T_RouteInfo>>> m_input_unit;
    std::vector<std::shared_ptr<OutputUnit<T_Msg, T_RouteInfo>>> m_output_unit;

    // Statistical variables required for power computations
    statistics::Scalar m_buffer_reads;
    statistics::Scalar m_buffer_writes;

    statistics::Scalar m_sw_input_arbiter_activity;
    statistics::Scalar m_sw_output_arbiter_activity;

    statistics::Scalar m_crossbar_activity;
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_ROUTER_HH__
