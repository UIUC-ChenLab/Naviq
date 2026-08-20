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


#include "mem/ruby/network/garnet/OutputUnit.hh"

#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/Credit.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "noc/lib/network/NocMessage.hh"
#include "noc/debug/NocProbeHook.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

template class OutputUnit<Message, RouteInfo>;
template class OutputUnit<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;


template <typename T_Msg, typename T_RouteInfo>
OutputUnit<T_Msg, T_RouteInfo>::OutputUnit(int id, PortDirection direction, Router<T_Msg, T_RouteInfo> *router,
    uint32_t consumerVcs, gem5::noc::garnet::Nps_Type nps_type)
  : Consumer(router), m_router(router), m_id(id), m_direction(direction),
    m_vc_per_vnet(consumerVcs)
{
    const int m_num_vcs = consumerVcs * m_router->get_num_vnets();
    outVcState.reserve(m_num_vcs);
    using MyOutVcStateType = typename OutputUnit<T_Msg, T_RouteInfo>::OutVcStateType;
    NetworkType *net_ptr = m_router->get_net_ptr(); // Get base network ptr
    for (int i = 0; i < m_num_vcs; i++) {
        // Use compile-time check to call the correct constructor
        if constexpr (std::is_same_v<MyOutVcStateType, gem5::noc::garnet::NocOutVcState>) {
            // We are creating NocOutVcState instances
            // Requires NocGarnetNetwork* and Nps_Type

            // Attempt to cast the network pointer
            gem5::noc::garnet::NocGarnetNetwork* noc_net_ptr = dynamic_cast<gem5::noc::garnet::NocGarnetNetwork*>(net_ptr);
            fatal_if(!noc_net_ptr, "Router network pointer is not compatible with NocGarnetNetwork for NocOutputUnit VC state");

            // Ensure a valid Nps_Type was passed for this configuration
            // fatal_if(nps_type == gem5::noc::garnet::Nps_Type::INVALID, "Nps_Type cannot be INVALID when creating NocOutVcState");

            outVcState.emplace_back(i, noc_net_ptr, consumerVcs, nps_type); // Call NocOutVcState constructor
        } else {
            // We are creating standard OutVcState instances
            // Requires GarnetNetwork*
            fatal_if(!net_ptr, "Network pointer is null for standard OutputUnit VC state");
            outVcState.emplace_back(i, net_ptr, consumerVcs); // Call standard OutVcState constructor
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
OutputUnit<T_Msg, T_RouteInfo>::decrement_credit(int out_vc)
{
    DPRINTF(RubyNetwork, "Router %d OutputUnit %s decrementing credit:%d for "
            "outvc %d at time: %lld for %s\n", m_router->get_id(),
            m_router->getPortDirectionName(get_direction()),
            outVcState[out_vc].get_credit_count(),
            out_vc, m_router->curCycle(), m_credit_link->name());

    outVcState[out_vc].decrement_credit();
}

template <typename T_Msg, typename T_RouteInfo>
void
OutputUnit<T_Msg, T_RouteInfo>::increment_credit(int out_vc)
{
    DPRINTF(RubyNetwork, "Router %d OutputUnit %s incrementing credit:%d for "
            "outvc %d at time: %lld from:%s\n", m_router->get_id(),
            m_router->getPortDirectionName(get_direction()),
            outVcState[out_vc].get_credit_count(),
            out_vc, m_router->curCycle(), m_credit_link->name());

    outVcState[out_vc].increment_credit();
}

// Check if the output VC (i.e., input VC at next router)
// has free credits (i..e, buffer slots).
// This is tracked by OutVcState
template <typename T_Msg, typename T_RouteInfo>
bool
OutputUnit<T_Msg, T_RouteInfo>::has_credit(int out_vc)
{
    assert(outVcState[out_vc].isInState(ACTIVE_, curTick()));
    return outVcState[out_vc].has_credit();
}

template <typename T_Msg, typename T_RouteInfo>
bool
OutputUnit<T_Msg, T_RouteInfo>::has_noccredit(int out_vc)
{
    return outVcState[out_vc].has_credit();
}



// Check if the output port (i.e., input port at next router) has free VCs.
template <typename T_Msg, typename T_RouteInfo>
bool
OutputUnit<T_Msg, T_RouteInfo>::has_free_vc(int vnet)
{
    int vc_base = vnet*m_vc_per_vnet;
    for (int vc = vc_base; vc < vc_base + m_vc_per_vnet; vc++) {
        if (is_vc_idle(vc, curTick()))
            return true;
    }

    return false;
}

// Assign a free output VC to the winner of Switch Allocation
template <typename T_Msg, typename T_RouteInfo>
int
OutputUnit<T_Msg, T_RouteInfo>::select_free_vc(int vnet)
{
    int vc_base = vnet*m_vc_per_vnet;
    for (int vc = vc_base; vc < vc_base + m_vc_per_vnet; vc++) {
        if (is_vc_idle(vc, curTick())) {
            outVcState[vc].setState(ACTIVE_, curTick());
            return vc;
        }
    }

    return -1;
}

// Check if the output port (i.e., input port at next router) has free VCs.
template <typename T_Msg, typename T_RouteInfo>
bool
OutputUnit<T_Msg, T_RouteInfo>::check_vc_free(int vc)
{

    if (is_vc_idle(vc, curTick()))
        return true;
    else
        return false;
}

// Assign a free output VC to the winner of Switch Allocation
template <typename T_Msg, typename T_RouteInfo>
int
OutputUnit<T_Msg, T_RouteInfo>::select_given_vc(int vc)
{

    if (is_vc_idle(vc, curTick())) {
        outVcState[vc].setState(ACTIVE_, curTick());
        return vc;
    }

    return -1;
}
/*
 * The wakeup function of the OutputUnit reads the credit signal from the
 * downstream router for the output VC (i.e., input VC at downstream router).
 * It increments the credit count in the appropriate output VC state.
 * If the credit carries is_free_signal as true,
 * the output VC is marked IDLE.
 */
template <typename T_Msg, typename T_RouteInfo>
void
OutputUnit<T_Msg, T_RouteInfo>::wakeup()
{
    if (m_credit_link->isReady(curTick())) {
        Credit<T_Msg, T_RouteInfo> *t_credit = (Credit<T_Msg, T_RouteInfo>*) m_credit_link->consumeLink();
        increment_credit(t_credit->get_vc());

        if (t_credit->is_free_signal())
            set_vc_state(IDLE_, t_credit->get_vc(), curTick());

        delete t_credit;

        if (m_credit_link->isReady(curTick())) {
            scheduleEvent(Cycles(1));
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
flitBuffer<T_Msg, T_RouteInfo>*
OutputUnit<T_Msg, T_RouteInfo>::getOutQueue()
{
    return &outBuffer;
}

template <typename T_Msg, typename T_RouteInfo>
void
OutputUnit<T_Msg, T_RouteInfo>::set_out_link(NetworkLink<T_Msg, T_RouteInfo> *link)
{
    m_out_link = link;
}

template <typename T_Msg, typename T_RouteInfo>
void
OutputUnit<T_Msg, T_RouteInfo>::set_credit_link(CreditLink<T_Msg, T_RouteInfo> *credit_link)
{
    m_credit_link = credit_link;
}

template <typename T_Msg, typename T_RouteInfo>
void
OutputUnit<T_Msg, T_RouteInfo>::insert_flit(flit<T_Msg, T_RouteInfo> *t_flit)
{
   gem5::noc::garnet::nocProbeFromRouter(m_router, "router.flit.out", t_flit);
    outBuffer.insert(t_flit);
    m_out_link->scheduleEventAbsolute(m_router->clockEdge(Cycles(1)));
}

template <typename T_Msg, typename T_RouteInfo>
bool
OutputUnit<T_Msg, T_RouteInfo>::functionalRead(Packet *pkt, WriteMask &mask)
{
    return outBuffer.functionalRead(pkt, mask);
}

template <typename T_Msg, typename T_RouteInfo>
uint32_t
OutputUnit<T_Msg, T_RouteInfo>::functionalWrite(Packet *pkt)
{
    return outBuffer.functionalWrite(pkt);
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
