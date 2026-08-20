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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_CROSSBARSWITCH_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_CROSSBARSWITCH_HH__

#include <iostream>
#include <vector>

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

template <typename T_Msg, typename T_RouteInfo> class Router;

template <typename T_Msg, typename T_RouteInfo>
class CrossbarSwitch : public Consumer
{
  public:
    CrossbarSwitch(Router<T_Msg, T_RouteInfo> *router);
    ~CrossbarSwitch() = default;
    void wakeup();
    void init();
    void print(std::ostream& out) const {};

    inline void
    update_sw_winner(int inport, flit<T_Msg, T_RouteInfo> *t_flit)
    {
        switchBuffers[inport].insert(t_flit);
    }

    /** Sum current occupancy and configured max depth of all ST-stage buffers. */
    void
    sumSwitchBufferStats(int& occSum, int& maxCapSum) const
    {
        for (const auto& sb : switchBuffers) {
            occSum += sb.getSize();
            maxCapSum += sb.getMaxSize();
        }
    }

    inline double get_crossbar_activity() { return m_crossbar_activity; }

    bool functionalRead(Packet *pkt, WriteMask &mask);
    uint32_t functionalWrite(Packet *pkt);
    void resetStats();

    void serializeForNocNetworkCheckpoint(CheckpointOut &cp) const
    {
        paramOut(cp, "xbar_n", (uint64_t)switchBuffers.size());
        // IMPORTANT: emit scalars before nested sections so they are attributed
        // to the correct [section] header in IniFile checkpoints.
        paramOut(cp, "xbar_activity", m_crossbar_activity);
        for (size_t i = 0; i < switchBuffers.size(); i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("xbar_buf%u", (unsigned)i));
            switchBuffers[i].serializeForNocNetworkCheckpoint(cp);
        }
    }

    void unserializeForNocNetworkCheckpoint(CheckpointIn &cp)
    {
        uint64_t n = 0;
        paramIn(cp, "xbar_n", n);
        fatal_if(n != switchBuffers.size(),
            "%s: crossbar buffer count %lu != constructed %lu",
            m_router->name(), n, (uint64_t)switchBuffers.size());
        for (size_t i = 0; i < switchBuffers.size(); i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("xbar_buf%u", (unsigned)i));
            switchBuffers[i].unserializeForNocNetworkCheckpoint(cp);
        }
        paramIn(cp, "xbar_activity", m_crossbar_activity);
    }

  private:
    Router<T_Msg, T_RouteInfo> *m_router;
    int m_num_vcs;
    double m_crossbar_activity;
    std::vector<flitBuffer<T_Msg, T_RouteInfo>> switchBuffers;
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_CROSSBARSWITCH_HH__
