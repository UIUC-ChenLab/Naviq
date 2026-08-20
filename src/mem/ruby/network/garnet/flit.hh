/*
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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_FLIT_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_FLIT_HH__

#include <cassert>
#include <iostream>

#include "base/types.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/slicc_interface/Message.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

template <typename T_Msg, typename T_RouteInfo>
class flit
{
  public:
    using MsgPtrType = std::shared_ptr<T_Msg>;


    flit()
        : m_route(make_routeinfo())
    {}
    flit(int packet_id, int id, int vc, int vnet, T_RouteInfo route, int size,
        MsgPtrType msg_ptr, int MsgSize, uint32_t bWidth, Tick curTime);
    flit(int packet_id, int id, int  vc, int vnet, T_RouteInfo route, int size,
        MsgPtrType msg_ptr, int MsgSize, uint32_t bWidth, Tick curTime, bool headtail);

    virtual ~flit(){};

    static T_RouteInfo make_routeinfo() {
        if constexpr (std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
            return T_RouteInfo();
        } else {
            return T_RouteInfo();  // default constructor
        }
    }

    int get_outport() {return m_outport; }
    int get_size() { return m_size; }
    Tick get_enqueue_time() { return m_enqueue_time; }
    Tick get_dequeue_time() { return m_dequeue_time; }
    int getPacketID() { return m_packet_id; }
    int get_id() { return m_id; }
    Tick get_time() { return m_time; }
    int get_vnet() { return m_vnet; }
    int get_vc() { return m_vc; }
    T_RouteInfo get_route() { return m_route; }
    MsgPtrType& get_msg_ptr() { return m_msg_ptr; }
    flit_type get_type() { return m_type; }
    axi_flit_type get_axi_type() { return m_axi_type; }
    int get_transaction_id() { return m_transaction_id; }
    std::pair<flit_stage, Tick> get_stage() { return m_stage; }
    Tick get_src_delay() { return src_delay; }

    void set_outport(int port) { m_outport = port; }
    void set_time(Tick time) { m_time = time; }
    void set_vc(int vc) { m_vc = vc; }
    void set_route(T_RouteInfo route) { m_route = route; }
    void set_src_delay(Tick delay) { src_delay = delay; }
    void set_dequeue_time(Tick time) { m_dequeue_time = time; }
    void set_enqueue_time(Tick time) { m_enqueue_time = time; }

    int32_t getDebugId() const { return debugId; }
    void setDebugId(int32_t id) { debugId = id; }
    bool hasDebugId() const { return debugId >= 0; }

    void set_rrob_tag(uint8_t tag) { m_rrob_tag = tag; }
    uint8_t get_rrob_tag() { return m_rrob_tag; }
    void set_rrob_flit_idx(int idx) { m_rrob_flit_idx = idx; }
    int get_rrob_flit_idx() { return m_rrob_flit_idx; }

    int get_src_ni_id() const
    {
        return m_route.src_ni;
    }

    void increment_hops() { m_route.hops_traversed++; }
    virtual void print(std::ostream& out) const;

    bool
    is_stage(flit_stage stage, Tick time)
    {
        return (stage == m_stage.first &&
                time >= m_stage.second);
    }

    void
    advance_stage(flit_stage t_stage, Tick newTime)
    {
        m_stage.first = t_stage;
        m_stage.second = newTime;
    }

    static bool
    greater(flit* n1, flit* n2)
    {
        if (n1->get_time() == n2->get_time()) {
            //assert(n1->flit_id != n2->flit_id);
            return (n1->get_id() > n2->get_id());
        } else {
            return (n1->get_time() > n2->get_time());
        }
    }

    bool functionalRead(Packet *pkt, WriteMask &mask);
    bool functionalWrite(Packet *pkt);

    virtual flit* serialize(int ser_id, int parts, uint32_t bWidth);
    virtual flit* deserialize(int des_id, int num_flits, uint32_t bWidth);

    void serializeForNocNetworkCheckpoint(CheckpointOut &cp) const;
    static flit* unserializeForNocNetworkCheckpoint(CheckpointIn &cp);

    uint32_t m_width;
    int msgSize;
    private:
        int32_t debugId = -1;
    protected:
    int m_packet_id;
    int m_id;
    int m_vnet;
    int m_vc;
    T_RouteInfo m_route;
    int m_size;
    Tick m_enqueue_time, m_dequeue_time;
    Tick m_time;
    flit_type m_type;
    axi_flit_type m_axi_type;
    MsgPtrType m_msg_ptr;
    int m_outport;
    Tick src_delay;
    std::pair<flit_stage, Tick> m_stage;
    uint8_t m_rrob_tag;
    int m_rrob_flit_idx; // index of the flit in the RROB entry
    int m_transaction_id; // internal use only, used to identify which unique axi transaction this flit belongs to. only used for write requests
};

template <typename T_Msg, typename T_RouteInfo>
inline std::ostream&
operator<<(std::ostream& out, const flit<T_Msg, T_RouteInfo> & obj)
{
    obj.print(out);
    out << std::flush;
    return out;
}

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_FLIT_HH__
