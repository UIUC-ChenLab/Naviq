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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_INPUTUNIT_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_INPUTUNIT_HH__

#include <iostream>
#include <vector>

#include "base/str.hh"
#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "mem/ruby/network/garnet/NetworkLink.hh"
#include "mem/ruby/network/garnet/VirtualChannel.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

template <typename T_Msg, typename T_RouteInfo> class Router;

void logNpsFlitTraceRefresh(Tick tick, uint64_t cycle, Tick min_gap);

template <typename T_Msg, typename T_RouteInfo>
class InputUnit : public Consumer
{
  public:
    InputUnit(int id, PortDirection direction, Router<T_Msg, T_RouteInfo> *router);
    ~InputUnit() = default;

    void wakeup();
    void nocwakeup();
    void print(std::ostream& out) const {};

    inline PortDirection get_direction() { return m_direction; }

    inline void
    set_vc_idle(int vc, Tick curTime)
    {
        virtualChannels[vc].set_idle(curTime);
    }

    inline void
    set_vc_active(int vc, Tick curTime)
    {
        virtualChannels[vc].set_active(curTime);
    }

    inline void
    grant_outport(int vc, int outport)
    {
        virtualChannels[vc].set_outport(outport);
    }

    inline void
    grant_outvc(int vc, int outvc)
    {
        virtualChannels[vc].set_outvc(outvc);
    }

    inline int
    get_outport(int invc)
    {
        return virtualChannels[invc].get_outport();
    }

    inline int
    get_outvc(int invc)
    {
        return virtualChannels[invc].get_outvc();
    }

    inline Tick
    get_enqueue_time(int invc)
    {
        return virtualChannels[invc].get_enqueue_time();
    }

    void increment_credit(int in_vc, bool free_signal, Tick curTime);

    inline flit<T_Msg, T_RouteInfo>*
    peekTopFlit(int vc)
    {
        return virtualChannels[vc].peekTopFlit();
    }

    inline flit<T_Msg, T_RouteInfo>*
    getTopFlit(int vc)
    {
        auto *t_flit = virtualChannels[vc].getTopFlit();
        logNpsFlitTrace("dequeue", vc, t_flit, getVcOccupancy(vc));
        return t_flit;
    }

    inline bool
    need_stage(int vc, flit_stage stage, Tick time)
    {
        return virtualChannels[vc].need_stage(stage, time);
    }

    inline bool
    isReady(int invc, Tick curTime)
    {
        return virtualChannels[invc].isReady(curTime);
    }

    flitBuffer<T_Msg, T_RouteInfo>* getCreditQueue() { return &creditQueue; }

    inline void
    set_in_link(NetworkLink<T_Msg, T_RouteInfo> *link)
    {
        m_in_link = link;
    }

    inline int get_inlink_id() { return m_in_link->get_id(); }

    inline void
    set_credit_link(CreditLink<T_Msg, T_RouteInfo> *credit_link)
    {
        m_credit_link = credit_link;
    }

    double get_buf_read_activity(unsigned int vnet) const
    { return m_num_buffer_reads[vnet]; }
    double get_buf_write_activity(unsigned int vnet) const
    { return m_num_buffer_writes[vnet]; }

    /** Flit count in the input buffer for virtual channel `vc`. */
    int
    getVcOccupancy(int vc) const
    {
        assert(vc >= 0 && vc < (int)virtualChannels.size());
        return virtualChannels[vc].getInputBufferSize();
    }

    /** Sum of per-VC input flitBuffer occupancy and sum of per-VC max sizes. */
    void sumInputVcBufferStats(int& occupancySum, int& simMaxDepthSum) const;

    bool functionalRead(Packet *pkt, WriteMask &mask);
    uint32_t functionalWrite(Packet *pkt);

    void resetStats();

    void serializeForNocNetworkCheckpoint(CheckpointOut &cp) const
    {
        paramOut(cp, "iu_id", m_id);
        paramOut(cp, "iu_direction", m_direction);
        paramOut(cp, "iu_vc_per_vnet", m_vc_per_vnet);
        // IMPORTANT: Write scalar keys before emitting any nested checkpoint
        // sections. The IniFile checkpoint writer assigns subsequent paramOut
        // lines to the most recently written [section] header, and leaving a
        // ScopedCheckpointSection does not automatically restore the parent
        // section header.
        {
        }
        paramOut(cp, "iu_num_vcs", (uint64_t)virtualChannels.size());

        {
            Serializable::ScopedCheckpointSection sec(cp, "iu_creditQueue");
            creditQueue.serializeForNocNetworkCheckpoint(cp);
        }
        for (size_t i = 0; i < virtualChannels.size(); i++) {
            Serializable::ScopedCheckpointSection sec(cp, csprintf("iu_vc%u", (unsigned)i));
            virtualChannels[i].serializeForNocNetworkCheckpoint(cp);
        }
    }

    void unserializeForNocNetworkCheckpoint(CheckpointIn &cp)
    {
        // ID/direction/vc_per_vnet are expected to match constructed topology,
        // but we still load them for sanity/debugging.
        int tmp_i = 0;
        uint64_t tmp_u = 0;
        paramIn(cp, "iu_id", tmp_i);
        m_id = tmp_i;
        paramIn(cp, "iu_direction", m_direction);
        paramIn(cp, "iu_vc_per_vnet", m_vc_per_vnet);
        {
            Serializable::ScopedCheckpointSection sec(cp, "iu_creditQueue");
            creditQueue.unserializeForNocNetworkCheckpoint(cp);
        }
        paramIn(cp, "iu_num_vcs", tmp_u);
        const size_t n = (size_t)tmp_u;
        virtualChannels.clear();
        virtualChannels.reserve(n);
        for (size_t i = 0; i < n; i++) {
            virtualChannels.emplace_back();
            Serializable::ScopedCheckpointSection sec(cp, csprintf("iu_vc%u", (unsigned)i));
            virtualChannels.back().unserializeForNocNetworkCheckpoint(cp);
        }
    }

  private:
    void logNpsFlitTrace(const char *event, int vc,
        flit<T_Msg, T_RouteInfo> *t_flit, int occupancy_after);

    Router<T_Msg, T_RouteInfo> *m_router;
    int m_id;
    PortDirection m_direction;
    int m_vc_per_vnet;
    NetworkLink<T_Msg, T_RouteInfo> *m_in_link;
    CreditLink<T_Msg, T_RouteInfo> *m_credit_link;
    flitBuffer<T_Msg, T_RouteInfo> creditQueue;

    // Input Virtual channels
    std::vector<VirtualChannel<T_Msg, T_RouteInfo>> virtualChannels;

    // Statistical variables
    std::vector<double> m_num_buffer_writes;
    std::vector<double> m_num_buffer_reads;
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_INPUTUNIT_HH__
