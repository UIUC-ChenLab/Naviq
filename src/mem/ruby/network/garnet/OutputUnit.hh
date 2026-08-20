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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_OUTPUTUNIT_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_OUTPUTUNIT_HH__

#include <iostream>
#include <vector>

#include "base/compiler.hh"
#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/NetworkLink.hh"
#include "mem/ruby/network/garnet/OutVcState.hh"
#include "noc/core/network/switch/NocOutVcState.hh"
#include "noc/lib/network/NocMessage.hh"
#include <type_traits>
#include "sim/serialize.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

template <typename T_Msg, typename T_RouteInfo> class CreditLink;
template <typename T_Msg, typename T_RouteInfo> class Router;

template <typename T_Msg, typename T_RouteInfo>
class OutputUnit : public Consumer
{
  public:

  using NetworkType = std::conditional_t<
        std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>,
        gem5::noc::garnet::NocGarnetNetwork,
        GarnetNetwork
    >;
    OutputUnit(int id, PortDirection direction, Router<T_Msg, T_RouteInfo> *router,
      uint32_t consumerVcs, gem5::noc::garnet::Nps_Type nps_type = gem5::noc::garnet::Nps_Type::INVALID);
    ~OutputUnit() = default;
    void set_out_link(NetworkLink<T_Msg, T_RouteInfo> *link);
    void set_credit_link(CreditLink<T_Msg, T_RouteInfo> *credit_link);
    void wakeup();
    flitBuffer<T_Msg, T_RouteInfo>* getOutQueue();
    void print(std::ostream& out) const {};
    void decrement_credit(int out_vc);
    void increment_credit(int out_vc);
    bool has_credit(int out_vc);
    bool has_noccredit(int out_vc);
    bool has_free_vc(int vnet);
    int select_free_vc(int vnet);
    bool check_vc_free(int vc);
    int select_given_vc(int vc);

    inline PortDirection get_direction() { return m_direction; }

    int
    get_credit_count(int vc)
    {
        return outVcState[vc].get_credit_count();
    }

    inline int
    get_outlink_id()
    {
        return m_out_link->get_id();
    }

    inline void
    set_vc_state(VC_state_type state, int vc, Tick curTime)
    {
      outVcState[vc].setState(state, curTime);
    }

    inline bool
    is_vc_idle(int vc, Tick curTime)
    {
        return (outVcState[vc].isInState(IDLE_, curTime));
    }

    void insert_flit(flit<T_Msg, T_RouteInfo> *t_flit);

    inline int
    getVcsPerVnet()
    {
        return m_vc_per_vnet;
    }

    bool functionalRead(Packet *pkt, WriteMask &mask);
    uint32_t functionalWrite(Packet *pkt);

    void serializeForNocNetworkCheckpoint(CheckpointOut &cp) const
    {
        paramOut(cp, "ou_direction", m_direction);
        paramOut(cp, "ou_vc_per_vnet", m_vc_per_vnet);
        // Persist downstream VC state (credits + VC state).
        paramOut(cp, "ou_outVcState_n", (uint64_t)outVcState.size());

        // IMPORTANT: Emit nested sections after all scalar keys. The IniFile
        // checkpoint format attributes paramOut lines to the most recently
        // written [section] header; writing scalars after a nested section can
        // strand them under the wrong header and break restore.
        {
            Serializable::ScopedCheckpointSection sec(cp, "ou_outBuffer");
            outBuffer.serializeForNocNetworkCheckpoint(cp);
        }
        for (size_t i = 0; i < outVcState.size(); i++) {
            Serializable::ScopedCheckpointSection sec(cp, csprintf("ou_vc%u", (unsigned)i));
            if constexpr (std::is_same_v<OutVcStateType, gem5::noc::garnet::NocOutVcState>) {
                outVcState[i].serialize(cp);
            } else {
                outVcState[i].serialize(cp);
            }
        }
    }

    void unserializeForNocNetworkCheckpoint(CheckpointIn &cp)
    {
        paramIn(cp, "ou_direction", m_direction);
        paramIn(cp, "ou_vc_per_vnet", m_vc_per_vnet);
        {
            Serializable::ScopedCheckpointSection sec(cp, "ou_outBuffer");
            outBuffer.unserializeForNocNetworkCheckpoint(cp);
        }
        uint64_t n = 0;
        paramIn(cp, "ou_outVcState_n", n);
        fatal_if(n != outVcState.size(),
            "OutputUnit vcstate count %lu != constructed %lu", n,
            (uint64_t)outVcState.size());
        for (size_t i = 0; i < outVcState.size(); i++) {
            Serializable::ScopedCheckpointSection sec(cp, csprintf("ou_vc%u", (unsigned)i));
            if constexpr (std::is_same_v<OutVcStateType, gem5::noc::garnet::NocOutVcState>) {
                outVcState[i].unserialize(cp);
            } else {
                outVcState[i].unserialize(cp);
            }
        }
    }

  private:
    Router<T_Msg, T_RouteInfo> *m_router;
    GEM5_CLASS_VAR_USED int m_id;
    PortDirection m_direction;
    int m_vc_per_vnet;
    NetworkLink<T_Msg, T_RouteInfo> *m_out_link;
    CreditLink<T_Msg, T_RouteInfo> *m_credit_link;

    // This is for the network link to consume
    flitBuffer<T_Msg, T_RouteInfo> outBuffer;
    // vc state of downstream router

    using OutVcStateType = std::conditional_t<
        std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>,
        gem5::noc::garnet::NocOutVcState,  // Use NocOutVcState if T_Msg and T_RouteInfo match
        OutVcState      // Default case
    >;
    std::vector<OutVcStateType> outVcState;
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_OUTPUTUNIT_HH__
