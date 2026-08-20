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


#include "mem/ruby/network/garnet/flit.hh"

#include "base/intmath.hh"
#include "debug/RubyNetwork.hh"
#include "noc/lib/network/NocMessage.hh"
#include "mem/ruby/network/garnet/Credit.hh"
#include "noc/core/network/NocMessageBuffer.hh"
#include "sim/serialize.hh"
#include <type_traits>

namespace gem5
{

namespace ruby
{

namespace garnet
{

template class flit<Message, RouteInfo>;
template class flit<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;

// Constructor for the flit
template <typename T_Msg, typename T_RouteInfo>
flit<T_Msg, T_RouteInfo>::flit(int packet_id, int id, int  vc, int vnet, T_RouteInfo route, int size,
    MsgPtrType msg_ptr, int MsgSize, uint32_t bWidth, Tick curTime): m_route(make_routeinfo())
{
    m_size = size;
    m_msg_ptr = msg_ptr;
    m_enqueue_time = curTime;
    m_dequeue_time = curTime;
    m_time = curTime;
    m_packet_id = packet_id;
    m_id = id;
    m_vnet = vnet;
    m_vc = vc;
    m_route = route;
    m_stage.first = I_;
    m_stage.second = curTime;
    m_width = bWidth;
    msgSize = MsgSize;

    // If this flit wraps a NocMessage, inherit its debugId so probes can track
    // across msg->flit creation. (Other message types may not have debugId.)
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage>) {
        if (m_msg_ptr && m_msg_ptr->hasDebugId()) {
            setDebugId(m_msg_ptr->getDebugId());
        }
    }

    if (size == 1) {
        m_type = HEAD_TAIL_;
        return;
    }
    if (id == 0)
        m_type = HEAD_;
    else if (id == (size - 1))
        m_type = TAIL_;
    else
        m_type = BODY_;
}

template <typename T_Msg, typename T_RouteInfo>
flit<T_Msg, T_RouteInfo>::flit(int packet_id, int id, int  vc, int vnet, T_RouteInfo route, int size,
    MsgPtrType msg_ptr, int MsgSize, uint32_t bWidth, Tick curTime, bool headtail): m_route(make_routeinfo())
{
    m_size = size;
    m_msg_ptr = msg_ptr;
    m_enqueue_time = curTime;
    m_dequeue_time = curTime;
    m_time = curTime;
    m_packet_id = packet_id;
    m_id = id;
    m_vnet = vnet;
    m_vc = vc;
    m_route = route;
    m_stage.first = I_;
    m_stage.second = curTime;
    m_width = bWidth;
    msgSize = MsgSize;
    // m_transaction_id = transaction_id;

    // If this flit wraps a NocMessage, inherit its debugId so probes can track
    // across msg->flit creation.
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage>) {
        if (m_msg_ptr && m_msg_ptr->hasDebugId()) {
            setDebugId(m_msg_ptr->getDebugId());
        }
    }

    if (headtail) {
        m_type = HEAD_TAIL_;
    } else if (size == 1) {
        m_type = HEAD_TAIL_;
    } else if (id == 0)
        m_type = HEAD_;
    else if (id == (size - 1))
        m_type = TAIL_;
    else
        m_type = BODY_;

}


template <typename T_Msg, typename T_RouteInfo>
flit<T_Msg, T_RouteInfo> *
flit<T_Msg, T_RouteInfo>::serialize(int ser_id, int parts, uint32_t bWidth)
{
    assert(m_width > bWidth);

    int ratio = (int)divCeil(m_width, bWidth);
    int new_id = (m_id*ratio) + ser_id;
    int new_size = (int)divCeil((float)msgSize, (float)bWidth);
    assert(new_id < new_size);

    flit *fl = new flit(m_packet_id, new_id, m_vc, m_vnet, m_route,
                    new_size, m_msg_ptr, msgSize, bWidth, m_time);
    fl->set_enqueue_time(m_enqueue_time);
    fl->set_src_delay(src_delay);
    fl->setDebugId(getDebugId());
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage>) {
        if (fl->hasDebugId() && fl->get_msg_ptr() && !fl->get_msg_ptr()->hasDebugId()) {
            fl->get_msg_ptr()->setDebugId(fl->getDebugId());
        }
    }
    return fl;
}

template <typename T_Msg, typename T_RouteInfo>
flit<T_Msg, T_RouteInfo> *
flit<T_Msg, T_RouteInfo>::deserialize(int des_id, int num_flits, uint32_t bWidth)
{
    int ratio = (int)divCeil((float)bWidth, (float)m_width);
    int new_id = ((int)divCeil((float)(m_id+1), (float)ratio)) - 1;
    int new_size = (int)divCeil((float)msgSize, (float)bWidth);
    assert(new_id < new_size);

    flit *fl = new flit(m_packet_id, new_id, m_vc, m_vnet, m_route,
                    new_size, m_msg_ptr, msgSize, bWidth, m_time);
    fl->set_enqueue_time(m_enqueue_time);
    fl->set_src_delay(src_delay);
    fl->setDebugId(getDebugId());
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage>) {
        if (fl->hasDebugId() && fl->get_msg_ptr() && !fl->get_msg_ptr()->hasDebugId()) {
            fl->get_msg_ptr()->setDebugId(fl->getDebugId());
        }
    }
    return fl;
}

// Flit can be printed out for debugging purposes
template <typename T_Msg, typename T_RouteInfo>
void
flit<T_Msg, T_RouteInfo>::print(std::ostream& out) const
{
    out << "[flit:: ";
    out << "PacketId=" << m_packet_id << " ";
    out << "Id=" << m_id << " ";
    out << "Type=" << m_type << " ";
    out << "Size=" << m_size << " ";
    out << "Vnet=" << m_vnet << " ";
    out << "VC=" << m_vc << " ";
    out << "Src NI=" << m_route.src_ni << " ";
    out << "Src Router=" << m_route.src_router << " ";
    out << "Dest NI=" << m_route.dest_ni << " ";
    out << "Dest Router=" << m_route.dest_router << " ";
    out << "Set Time=" << m_time << " ";
    out << "Width=" << m_width<< " ";
    out << "]";
}

template <typename T_Msg, typename T_RouteInfo>
bool
flit<T_Msg, T_RouteInfo>::functionalRead(Packet *pkt, WriteMask &mask)
{
    T_Msg *msg = m_msg_ptr.get();
    return msg->functionalRead(pkt, mask);
}

template <typename T_Msg, typename T_RouteInfo>
bool
flit<T_Msg, T_RouteInfo>::functionalWrite(Packet *pkt)
{
    T_Msg *msg = m_msg_ptr.get();
    return msg->functionalWrite(pkt);
}

template <typename T_Msg, typename T_RouteInfo>
void
flit<T_Msg, T_RouteInfo>::serializeForNocNetworkCheckpoint(CheckpointOut &cp)
    const
{
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        const bool is_credit = (m_type == CREDIT_);
        paramOut(cp, "flt_is_credit", is_credit);
        paramOut(cp, "flt_m_packet_id", m_packet_id);
        paramOut(cp, "flt_m_id", m_id);
        paramOut(cp, "flt_m_vnet", m_vnet);
        paramOut(cp, "flt_m_vc", m_vc);
        paramOut(cp, "flt_m_size", m_size);
        paramOut(cp, "flt_m_enqueue_time", m_enqueue_time);
        paramOut(cp, "flt_m_dequeue_time", m_dequeue_time);
        paramOut(cp, "flt_m_time", m_time);
        paramOut(cp, "flt_m_type", (int)m_type);
        paramOut(cp, "flt_m_axi_type", (int)m_axi_type);
        paramOut(cp, "flt_msgSize", msgSize);
        paramOut(cp, "flt_m_width", m_width);
        paramOut(cp, "flt_m_outport", m_outport);
        paramOut(cp, "flt_src_delay", src_delay);
        paramOut(cp, "flt_m_stage_first", (int)m_stage.first);
        paramOut(cp, "flt_m_stage_second", m_stage.second);
        paramOut(cp, "flt_m_rrob_tag", (int)m_rrob_tag);
        paramOut(cp, "flt_m_rrob_flit_idx", m_rrob_flit_idx);
        paramOut(cp, "flt_m_transaction_id", m_transaction_id);
        paramOut(cp, "flt_debug_id", getDebugId());

        paramOut(cp, "flt_route_vnet", m_route.vnet);
        paramOut(cp, "flt_route_src_ni", m_route.src_ni);
        paramOut(cp, "flt_route_src_router", m_route.src_router);
        paramOut(cp, "flt_route_dest_ni", m_route.dest_ni);
        paramOut(cp, "flt_route_dest_router", m_route.dest_router);
        paramOut(cp, "flt_route_hops", m_route.hops_traversed);

        if (is_credit) {
            const auto *c =
                static_cast<const Credit<T_Msg, T_RouteInfo>*>(this);
            paramOut(cp, "flt_credit_free", c->is_free_signal());
        } else {
            paramOut(cp, "flt_credit_free", false);
        }
        gem5::noc::serializeNocMsgPtrOptional(cp, m_msg_ptr);

        {
            Serializable::ScopedCheckpointSection sec(cp, "flt_route_net_dest");
            m_route.net_dest.serialize(cp);
        }
    } else {
        panic("serializeForNocNetworkCheckpoint used on non-Noc flit");
    }
}

template <typename T_Msg, typename T_RouteInfo>
flit<T_Msg, T_RouteInfo> *
flit<T_Msg, T_RouteInfo>::unserializeForNocNetworkCheckpoint(CheckpointIn &cp)
{
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        bool is_credit = false;
        paramIn(cp, "flt_is_credit", is_credit);

        int m_packet_id = 0, m_id = 0, m_vnet = 0, m_vc = 0, m_size = 0;
        Tick m_enqueue_time = 0, m_dequeue_time = 0, m_time = 0;
        int m_type_i = 0, m_axi_type_i = 0, msgSize = 0;
        uint32_t m_width = 0;
        int m_outport = 0, m_transaction_id = 0;
        Tick src_delay = 0;
        int m_stage_first_i = 0;
        Tick m_stage_second = 0;
        int m_rrob_tag = 0;
        int m_rrob_flit_idx = 0;
        bool credit_free = false;
        int32_t debug_id = -1;

        paramIn(cp, "flt_m_packet_id", m_packet_id);
        paramIn(cp, "flt_m_id", m_id);
        paramIn(cp, "flt_m_vnet", m_vnet);
        paramIn(cp, "flt_m_vc", m_vc);
        paramIn(cp, "flt_m_size", m_size);
        paramIn(cp, "flt_m_enqueue_time", m_enqueue_time);
        paramIn(cp, "flt_m_dequeue_time", m_dequeue_time);
        paramIn(cp, "flt_m_time", m_time);
        paramIn(cp, "flt_m_type", m_type_i);
        paramIn(cp, "flt_m_axi_type", m_axi_type_i);
        paramIn(cp, "flt_msgSize", msgSize);
        paramIn(cp, "flt_m_width", m_width);
        paramIn(cp, "flt_m_outport", m_outport);
        paramIn(cp, "flt_src_delay", src_delay);
        paramIn(cp, "flt_m_stage_first", m_stage_first_i);
        paramIn(cp, "flt_m_stage_second", m_stage_second);
        paramIn(cp, "flt_m_rrob_tag", m_rrob_tag);
        paramIn(cp, "flt_m_rrob_flit_idx", m_rrob_flit_idx);
        paramIn(cp, "flt_m_transaction_id", m_transaction_id);
        optParamIn(cp, "flt_debug_id", debug_id, -1);

        gem5::noc::garnet::NocRouteInfo route;
        paramIn(cp, "flt_route_vnet", route.vnet);
        paramIn(cp, "flt_route_src_ni", route.src_ni);
        paramIn(cp, "flt_route_src_router", route.src_router);
        paramIn(cp, "flt_route_dest_ni", route.dest_ni);
        paramIn(cp, "flt_route_dest_router", route.dest_router);
        paramIn(cp, "flt_route_hops", route.hops_traversed);

        gem5::noc::MsgPtr msg;
        if (optParamIn(cp, "flt_credit_free", credit_free, false)) {
            msg = gem5::noc::unserializeNocMsgPtrOptional(cp);
            {
                Serializable::ScopedCheckpointSection sec(cp, "flt_route_net_dest");
                route.net_dest.unserialize(cp);
            }
        } else {
            {
                Serializable::ScopedCheckpointSection sec(cp, "flt_route_net_dest");
                route.net_dest.unserialize(cp);
                paramIn(cp, "flt_credit_free", credit_free);
                msg = gem5::noc::unserializeNocMsgPtrOptional(cp);
            }
        }

        if (is_credit) {
            Credit<T_Msg, T_RouteInfo> *c =
                new Credit<T_Msg, T_RouteInfo>(m_vc, credit_free, m_time);
            c->set_enqueue_time(m_enqueue_time);
            c->set_dequeue_time(m_dequeue_time);
            c->set_time(m_time);
            c->set_route(route);
            c->set_outport(m_outport);
            c->set_src_delay(src_delay);
            c->set_vc(m_vc);
            c->advance_stage((flit_stage)m_stage_first_i, m_stage_second);
            c->set_rrob_tag((uint8_t)m_rrob_tag);
            c->set_rrob_flit_idx(m_rrob_flit_idx);
            c->m_width = m_width;
            c->msgSize = msgSize;
            c->get_msg_ptr() = msg;
            c->setDebugId(debug_id);
            if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage>) {
                if (c->hasDebugId() && c->get_msg_ptr() && !c->get_msg_ptr()->hasDebugId()) {
                    c->get_msg_ptr()->setDebugId(c->getDebugId());
                }
            }
            return c;
        }

        flit<T_Msg, T_RouteInfo> *f = new flit<T_Msg, T_RouteInfo>();
        f->m_packet_id = m_packet_id;
        f->m_id = m_id;
        f->m_vnet = m_vnet;
        f->m_vc = m_vc;
        f->m_size = m_size;
        f->m_enqueue_time = m_enqueue_time;
        f->m_dequeue_time = m_dequeue_time;
        f->m_time = m_time;
        f->m_type = (flit_type)m_type_i;
        f->m_axi_type = (axi_flit_type)m_axi_type_i;
        f->msgSize = msgSize;
        f->m_width = m_width;
        f->m_outport = m_outport;
        f->src_delay = src_delay;
        f->m_stage.first = (flit_stage)m_stage_first_i;
        f->m_stage.second = m_stage_second;
        f->m_rrob_tag = (uint8_t)m_rrob_tag;
        f->m_rrob_flit_idx = m_rrob_flit_idx;
        f->m_transaction_id = m_transaction_id;
        f->m_route = route;
        f->m_msg_ptr = msg;
        f->setDebugId(debug_id);
        if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage>) {
            if (f->hasDebugId() && f->m_msg_ptr && !f->m_msg_ptr->hasDebugId()) {
                f->m_msg_ptr->setDebugId(f->getDebugId());
            }
        }
        return f;
    } else {
        panic("unserializeForNocNetworkCheckpoint used on non-Noc flit");
    }
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
