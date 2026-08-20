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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_VIRTUALCHANNEL_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_VIRTUALCHANNEL_HH__

#include <utility>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

template <typename T_Msg, typename T_RouteInfo>
class VirtualChannel
{
  public:
    VirtualChannel();
    ~VirtualChannel() = default;

    bool need_stage(flit_stage stage, Tick time);
    void set_idle(Tick curTime);
    void set_active(Tick curTime);
    void set_outvc(int outvc)               { m_output_vc = outvc; }
    inline int get_outvc()                  { return m_output_vc; }
    void set_outport(int outport)           { m_output_port = outport; };
    inline int get_outport()                  { return m_output_port; }

    inline Tick get_enqueue_time()          { return m_enqueue_time; }
    inline void set_enqueue_time(Tick time) { m_enqueue_time = time; }
    inline VC_state_type get_state()        { return m_vc_state.first; }

    inline bool
    isReady(Tick curTime)
    {
        return inputBuffer.isReady(curTime);
    }

    inline void
    insertFlit(flit<T_Msg, T_RouteInfo> *t_flit)
    {
        inputBuffer.insert(t_flit);
    }

    inline void
    set_state(VC_state_type m_state, Tick curTime)
    {
        m_vc_state.first = m_state;
        m_vc_state.second = curTime;
    }

    inline flit<T_Msg, T_RouteInfo>*
    peekTopFlit()
    {
        return inputBuffer.peekTopFlit();
    }

    inline flit<T_Msg, T_RouteInfo>*
    getTopFlit()
    {
        return inputBuffer.getTopFlit();
    }

    /** Current occupancy of the input VC buffer (flits). */
    inline int
    getInputBufferSize() const
    {
        return inputBuffer.getSize();
    }

    bool functionalRead(Packet *pkt, WriteMask &mask);
    uint32_t functionalWrite(Packet *pkt);

    void serializeForNocNetworkCheckpoint(CheckpointOut &cp) const
    {
        // Persist the input buffer and VC bookkeeping.
        paramOut(cp, "vc_state", (int)m_vc_state.first);
        paramOut(cp, "vc_state_time", m_vc_state.second);
        paramOut(cp, "vc_outport", m_output_port);
        paramOut(cp, "vc_enqueue_time", m_enqueue_time);
        paramOut(cp, "vc_outvc", m_output_vc);
        // Serialize nested buffer last so subsequent scalar keys don't get
        // attributed to the buffer's last [section] header.
        inputBuffer.serializeForNocNetworkCheckpoint(cp);
    }

    void unserializeForNocNetworkCheckpoint(CheckpointIn &cp)
    {
        inputBuffer.unserializeForNocNetworkCheckpoint(cp);
        int st = 0;
        paramIn(cp, "vc_state", st);
        m_vc_state.first = (VC_state_type)st;
        paramIn(cp, "vc_state_time", m_vc_state.second);
        paramIn(cp, "vc_outport", m_output_port);
        paramIn(cp, "vc_enqueue_time", m_enqueue_time);
        paramIn(cp, "vc_outvc", m_output_vc);
    }
    int getInputBufferOccupancy() const { return inputBuffer.getSize(); }
    int getInputBufferMaxSize() const { return inputBuffer.getMaxSize(); }
    void setInputBufferMaxSize(int maxSize) { inputBuffer.setMaxSize(maxSize); }

  private:
    flitBuffer<T_Msg, T_RouteInfo> inputBuffer;
    std::pair<VC_state_type, Tick> m_vc_state;
    int m_output_port;
    Tick m_enqueue_time;
    int m_output_vc;
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_VIRTUALCHANNEL_HH__
