/*
 * Copyright (c) 2020 Advanced Micro Devices, Inc.
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


#include "mem/ruby/network/garnet/Router.hh"

#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh"
#include "mem/ruby/network/garnet/InputUnit.hh"
#include "mem/ruby/network/garnet/NetworkLink.hh"
#include "mem/ruby/network/garnet/OutputUnit.hh"
#include "noc/lib/network/NocMessage.hh"
#include "debug/NocTiming.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

template class Router<Message, RouteInfo>;
template class Router<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;

// template class CreditLink<Message, RouteInfo>;
// template class CreditLink<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;
// template class NetworkLink<Message, RouteInfo>;
// template class NetworkLink<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;
// template class InputUnit<Message, RouteInfo>;
// template class InputUnit<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;
// template class OutputUnit<Message, RouteInfo>;
// template class OutputUnit<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;

template <typename T_Msg, typename T_RouteInfo>
Router<T_Msg, T_RouteInfo>::Router(const Params &p)
  : BasicRouter(p), Consumer(this), m_latency(p.latency),
    m_virtual_networks(p.virt_nets), m_vc_per_vnet(p.vcs_per_vnet),
    m_num_vcs(m_virtual_networks * m_vc_per_vnet), m_bit_width(p.width),
    m_network_ptr(nullptr), routingUnit(this), switchAllocator(this),
    crossbarSwitch(this)
{
    m_input_unit.clear();
    m_output_unit.clear();
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::init()
{
    BasicRouter::init();

    switchAllocator.init();
    crossbarSwitch.init();
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::sumInternalFlitBufferStats(
    int& occSum, int& maxCapSum)
{
    occSum = 0;
    maxCapSum = 0;

    for (int pi = 0; pi < get_num_inports(); pi++) {
        InputUnit<T_Msg, T_RouteInfo>* iu = getInputUnit(pi);
        int o = 0;
        int c = 0;
        iu->sumInputVcBufferStats(o, c);
        occSum += o;
        maxCapSum += c;
        flitBuffer<T_Msg, T_RouteInfo>* cred_q = iu->getCreditQueue();
        if (cred_q) {
            occSum += cred_q->getSize();
            maxCapSum += cred_q->getMaxSize();
        }
    }

    int xo = 0;
    int xc = 0;
    crossbarSwitch.sumSwitchBufferStats(xo, xc);
    occSum += xo;
    maxCapSum += xc;

    for (int po = 0; po < get_num_outports(); po++) {
        flitBuffer<T_Msg, T_RouteInfo>* ob = getOutputUnit(po)->getOutQueue();
        if (ob) {
            occSum += ob->getSize();
            maxCapSum += ob->getMaxSize();
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::wakeup()
{
    DPRINTF(RubyNetwork, "Router %d woke up\n", m_id);
    // DPRINTF(NocTiming, "Router %d woke up\n", m_id);
    assert(clockEdge() == curTick());

    // check for incoming flits
    for (int inport = 0; inport < m_input_unit.size(); inport++) {
        m_input_unit[inport]->wakeup();
    }

    // check for incoming credits
    // Note: the credit update is happening before SA
    // buffer turnaround time =
    //     credit traversal (1-cycle) + SA (1-cycle) + Link Traversal (1-cycle)
    // if we want the credit update to take place after SA, this loop should
    // be moved after the SA request
    for (int outport = 0; outport < m_output_unit.size(); outport++) {
        m_output_unit[outport]->wakeup();
    }

    // Switch Allocation
    switchAllocator.wakeup();

    // Switch Traversal
    crossbarSwitch.wakeup();
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::addInPort(PortDirection inport_dirn,
                  NetworkLink<T_Msg, T_RouteInfo> *in_link, CreditLink<T_Msg, T_RouteInfo> *credit_link)
{
    fatal_if(in_link->bitWidth != m_bit_width, "Widths of link %s(%d)does"
            " not match that of Router%d(%d). Consider inserting SerDes "
            "Units.", in_link->name(), in_link->bitWidth, m_id, m_bit_width);

    int port_num = m_input_unit.size();
    InputUnit<T_Msg, T_RouteInfo> *input_unit = new InputUnit(port_num, inport_dirn, this);

    input_unit->set_in_link(in_link);
    input_unit->set_credit_link(credit_link);
    in_link->setLinkConsumer(this);
    in_link->setVcsPerVnet(get_vc_per_vnet());
    credit_link->setSourceQueue(input_unit->getCreditQueue(), this);
    credit_link->setVcsPerVnet(get_vc_per_vnet());

    m_input_unit.push_back(std::shared_ptr<InputUnit<T_Msg, T_RouteInfo>>(input_unit));

    routingUnit.addInDirection(inport_dirn, port_num);
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::addOutPort(PortDirection outport_dirn,
                   NetworkLink<T_Msg, T_RouteInfo> *out_link,
                   std::vector<NetDest>& routing_table_entry, int link_weight,
                   CreditLink<T_Msg, T_RouteInfo> *credit_link, uint32_t consumerVcs)
{
    fatal_if(out_link->bitWidth != m_bit_width, "Widths of units do not match."
            " Consider inserting SerDes Units");

    int port_num = m_output_unit.size();
    OutputUnit<T_Msg, T_RouteInfo> *output_unit = new OutputUnit(port_num, outport_dirn, this,
                                             consumerVcs);

    output_unit->set_out_link(out_link);
    output_unit->set_credit_link(credit_link);
    credit_link->setLinkConsumer(this);
    credit_link->setVcsPerVnet(consumerVcs);
    out_link->setSourceQueue(output_unit->getOutQueue(), this);
    out_link->setVcsPerVnet(consumerVcs);

    m_output_unit.push_back(std::shared_ptr<OutputUnit<T_Msg, T_RouteInfo>>(output_unit));

    routingUnit.addRoute(routing_table_entry);
    routingUnit.addWeight(link_weight);
    routingUnit.addOutDirection(outport_dirn, port_num);
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::addOutPort(PortDirection outport_dirn,
                   NetworkLink<T_Msg, T_RouteInfo> *out_link,
                   std::vector<gem5::noc::NocNetDest>& routing_table_entry, int link_weight,
                   CreditLink<T_Msg, T_RouteInfo> *credit_link, uint32_t consumerVcs)
{
    fatal_if(out_link->bitWidth != m_bit_width, "Widths of units do not match."
            " Consider inserting SerDes Units");

    int port_num = m_output_unit.size();
    OutputUnit<T_Msg, T_RouteInfo> *output_unit = new OutputUnit(port_num, outport_dirn, this,
                                             consumerVcs);

    output_unit->set_out_link(out_link);
    output_unit->set_credit_link(credit_link);
    credit_link->setLinkConsumer(this);
    credit_link->setVcsPerVnet(consumerVcs);
    out_link->setSourceQueue(output_unit->getOutQueue(), this);
    out_link->setVcsPerVnet(consumerVcs);

    m_output_unit.push_back(std::shared_ptr<OutputUnit<T_Msg, T_RouteInfo>>(output_unit));

    routingUnit.addRoute(routing_table_entry);
    routingUnit.addWeight(link_weight);
    routingUnit.addOutDirection(outport_dirn, port_num);
}

template <typename T_Msg, typename T_RouteInfo>
PortDirection
Router<T_Msg, T_RouteInfo>::getOutportDirection(int outport)
{
    return m_output_unit[outport]->get_direction();
}

template <typename T_Msg, typename T_RouteInfo>
PortDirection
Router<T_Msg, T_RouteInfo>::getInportDirection(int inport)
{
    return m_input_unit[inport]->get_direction();
}

template <typename T_Msg, typename T_RouteInfo>
int
Router<T_Msg, T_RouteInfo>::route_compute(T_RouteInfo route, int inport, PortDirection inport_dirn, int vc)
{
    return routingUnit.outportCompute(route, inport, inport_dirn, vc);
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::grant_switch(int inport, flit<T_Msg, T_RouteInfo> *t_flit)
{
    crossbarSwitch.update_sw_winner(inport, t_flit);
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::schedule_wakeup(Cycles time)
{
    // wake up after time cycles
    scheduleEvent(time);
}

template <typename T_Msg, typename T_RouteInfo>
std::string
Router<T_Msg, T_RouteInfo>::getPortDirectionName(PortDirection direction)
{
    // PortDirection is actually a string
    // If not, then this function should add a switch
    // statement to convert direction to a string
    // that can be printed out
    return direction;
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::regStats()
{
    BasicRouter::regStats();
    // printf("Registering stats for router %s\n", name());
    m_buffer_reads
        .name(name() + ".buffer_reads")
        .flags(statistics::nozero)
    ;

    m_buffer_writes
        .name(name() + ".buffer_writes")
        .flags(statistics::nozero)
    ;

    m_crossbar_activity
        .name(name() + ".crossbar_activity")
        .flags(statistics::nozero)
    ;

    m_sw_input_arbiter_activity
        .name(name() + ".sw_input_arbiter_activity")
        .flags(statistics::nozero)
    ;

    m_sw_output_arbiter_activity
        .name(name() + ".sw_output_arbiter_activity")
        .flags(statistics::nozero)
    ;
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::collateStats()
{
    for (int j = 0; j < m_virtual_networks; j++) {
        for (int i = 0; i < m_input_unit.size(); i++) {
            m_buffer_reads += m_input_unit[i]->get_buf_read_activity(j);
            m_buffer_writes += m_input_unit[i]->get_buf_write_activity(j);
        }
    }

    m_sw_input_arbiter_activity = switchAllocator.get_input_arbiter_activity();
    m_sw_output_arbiter_activity =
        switchAllocator.get_output_arbiter_activity();
    m_crossbar_activity = crossbarSwitch.get_crossbar_activity();
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::resetStats()
{
    for (int i = 0; i < m_input_unit.size(); i++) {
            m_input_unit[i]->resetStats();
    }

    crossbarSwitch.resetStats();
    switchAllocator.resetStats();
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::printFaultVector(std::ostream& out)
{
    int temperature_celcius = BASELINE_TEMPERATURE_CELCIUS;
    int num_fault_types = m_network_ptr->fault_model->number_of_fault_types;
    float fault_vector[num_fault_types];
    get_fault_vector(temperature_celcius, fault_vector);
    out << "Router-" << m_id << " fault vector: " << std::endl;
    for (int fault_type_index = 0; fault_type_index < num_fault_types;
         fault_type_index++) {
        out << " - probability of (";
        out <<
        m_network_ptr->fault_model->fault_type_to_string(fault_type_index);
        out << ") = ";
        out << fault_vector[fault_type_index] << std::endl;
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::printAggregateFaultProbability(std::ostream& out)
{
    int temperature_celcius = BASELINE_TEMPERATURE_CELCIUS;
    float aggregate_fault_prob;
    get_aggregate_fault_probability(temperature_celcius,
                                    &aggregate_fault_prob);
    out << "Router-" << m_id << " fault probability: ";
    out << aggregate_fault_prob << std::endl;
}

template <typename T_Msg, typename T_RouteInfo>
bool
Router<T_Msg, T_RouteInfo>::functionalRead(Packet *pkt, WriteMask &mask)
{
    bool read = false;
    if (crossbarSwitch.functionalRead(pkt, mask))
        read = true;

    for (uint32_t i = 0; i < m_input_unit.size(); i++) {
        if (m_input_unit[i]->functionalRead(pkt, mask))
            read = true;
    }

    for (uint32_t i = 0; i < m_output_unit.size(); i++) {
        if (m_output_unit[i]->functionalRead(pkt, mask))
            read = true;
    }

    return read;
}

template <typename T_Msg, typename T_RouteInfo>
uint32_t
Router<T_Msg, T_RouteInfo>::functionalWrite(Packet *pkt)
{
    uint32_t num_functional_writes = 0;
    num_functional_writes += crossbarSwitch.functionalWrite(pkt);

    for (uint32_t i = 0; i < m_input_unit.size(); i++) {
        num_functional_writes += m_input_unit[i]->functionalWrite(pkt);
    }

    for (uint32_t i = 0; i < m_output_unit.size(); i++) {
        num_functional_writes += m_output_unit[i]->functionalWrite(pkt);
    }

    return num_functional_writes;
}

template <typename T_Msg, typename T_RouteInfo>
int
Router<T_Msg, T_RouteInfo>::findOutputUnitIndexByOutQueue(
    flitBuffer<T_Msg, T_RouteInfo> *q) const
{
    for (uint32_t i = 0; i < m_output_unit.size(); i++) {
        if (m_output_unit[i]->getOutQueue() == q) {
            return (int)i;
        }
    }
    return -1;
}

template <typename T_Msg, typename T_RouteInfo>
int
Router<T_Msg, T_RouteInfo>::findInputUnitIndexByCreditQueue(
    flitBuffer<T_Msg, T_RouteInfo> *q) const
{
    for (uint32_t i = 0; i < m_input_unit.size(); i++) {
        if (m_input_unit[i]->getCreditQueue() == q) {
            return (int)i;
        }
    }
    return -1;
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::serialize(CheckpointOut &cp) const
{
    BasicRouter::serialize(cp);

    // Checkpoint router-internal flit/credit holding state.
    paramOut(cp, "rtr_num_inports", (uint64_t)m_input_unit.size());
    paramOut(cp, "rtr_num_outports", (uint64_t)m_output_unit.size());

    for (size_t i = 0; i < m_input_unit.size(); i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("inputUnit%u", (unsigned)i));
        m_input_unit[i]->serializeForNocNetworkCheckpoint(cp);
    }
    for (size_t i = 0; i < m_output_unit.size(); i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("outputUnit%u", (unsigned)i));
        m_output_unit[i]->serializeForNocNetworkCheckpoint(cp);
    }

    // Switch allocator round-robin state affects which flits are selected next.
    {
        Serializable::ScopedCheckpointSection sec(cp, "switchAllocator");
        switchAllocator.serializeForNocNetworkCheckpoint(cp);
    }
    // Crossbar switch buffers hold flits between SA and output unit insertion.
    {
        Serializable::ScopedCheckpointSection sec(cp, "crossbarSwitch");
        crossbarSwitch.serializeForNocNetworkCheckpoint(cp);
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
Router<T_Msg, T_RouteInfo>::unserialize(CheckpointIn &cp)
{
    BasicRouter::unserialize(cp);

    uint64_t nin = 0, nout = 0;
    paramIn(cp, "rtr_num_inports", nin);
    paramIn(cp, "rtr_num_outports", nout);

    // Topology should be identical; still, load unit state into existing objects.
    fatal_if(nin != m_input_unit.size(),
        "%s: checkpoint input ports %lu != constructed %lu",
        name(), nin, (uint64_t)m_input_unit.size());
    fatal_if(nout != m_output_unit.size(),
        "%s: checkpoint output ports %lu != constructed %lu",
        name(), nout, (uint64_t)m_output_unit.size());

    for (size_t i = 0; i < m_input_unit.size(); i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("inputUnit%u", (unsigned)i));
        m_input_unit[i]->unserializeForNocNetworkCheckpoint(cp);
    }
    for (size_t i = 0; i < m_output_unit.size(); i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("outputUnit%u", (unsigned)i));
        m_output_unit[i]->unserializeForNocNetworkCheckpoint(cp);
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "switchAllocator");
        switchAllocator.unserializeForNocNetworkCheckpoint(cp);
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "crossbarSwitch");
        crossbarSwitch.unserializeForNocNetworkCheckpoint(cp);
    }
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
