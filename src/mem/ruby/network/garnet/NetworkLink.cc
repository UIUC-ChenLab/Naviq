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


#include "mem/ruby/network/garnet/NetworkLink.hh"

#include <iostream>

#include "base/str.hh"
#include "base/trace.hh"
#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "noc/lib/network/NocMessage.hh"
#include "mem/ruby/network/garnet/NetworkBridge.hh"
#include "mem/ruby/network/garnet/InputUnit.hh"
#include "mem/ruby/network/garnet/OutputUnit.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "noc/core/network/NocStreamMsg.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "noc/debug/NocProbe.hh"
#include "sim/serialize.hh"
#include <string>
#include <type_traits>

namespace gem5
{

namespace ruby
{

namespace garnet
{

template class NetworkLink<Message, RouteInfo>;
template class NetworkLink<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;

template <typename T_Msg, typename T_RouteInfo>
NetworkLink<T_Msg, T_RouteInfo>::NetworkLink(const Params &p)
    : ClockedObject(p), Consumer(this), m_id(p.link_id),
      m_type(NUM_LINK_TYPES_),
      m_latency(p.link_latency), m_link_utilized(0),
      m_virt_nets(p.virt_nets), linkBuffer(),
      link_consumer(nullptr), link_srcQueue(nullptr),
      m_nocProbe(p.noc_probe)
{
    int num_vnets = (p.supported_vnets).size();
    mVnets.resize(num_vnets);
    bitWidth = p.width;
    for (int i = 0; i < num_vnets; i++) {
        mVnets[i] = p.supported_vnets[i];
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::setLinkConsumer(Consumer *consumer)
{
    link_consumer = consumer;
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::setVcsPerVnet(uint32_t consumerVcs)
{
    m_vc_load.resize(m_virt_nets * consumerVcs);
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::setSourceQueue(flitBuffer<T_Msg, T_RouteInfo> *src_queue, ClockedObject *srcClockObj)
{
    link_srcQueue = src_queue;
    src_object = srcClockObj;
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::wakeup()
{
    DPRINTF(RubyNetwork, "Woke up to transfer flits from %s\n",
        src_object->name());
    assert(link_srcQueue != nullptr);
    assert(curTick() == clockEdge());
    if (link_srcQueue->isReady(curTick())) {
        flit<T_Msg, T_RouteInfo> *t_flit = link_srcQueue->getTopFlit();
        // if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        //     std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        //     if (auto strm =
        //             std::dynamic_pointer_cast<gem5::noc::NocStreamMsg>(
        //                 t_flit->get_msg_ptr())) {
        //         const int src_ni = strm->getSourceNiID();
        //         std::cout << "[AXIS-DBG] NL(" << name() << ")"
        //                   << " curTick=" << curTick()
        //                   << " stage=LINK_POP_SRCQ"
        //                   << " src_obj=" << src_object->name()
        //                   << " src_ni=" << src_ni
        //                   << " flit_id(net)=" << t_flit->get_id()
        //                   << " pkt_id=" << t_flit->getPacketID()
        //                   << " NPPMsg.numFlits=" << (unsigned)strm->getNumFlits()
        //                   << " vc=" << t_flit->get_vc()
        //                   << " vnet=" << t_flit->get_vnet()
        //                   << " link_bitWidth=" << bitWidth
        //                   << " flit_bitWidth=" << t_flit->m_width
        //                   << " msgSizeB=" << t_flit->msgSize
        //                   << std::endl;
        //     }
        // }
        DPRINTF(RubyNetwork, "Transmission will finish at %ld :%s\n",
                clockEdge(m_latency), *t_flit);
        if (m_type != NUM_LINK_TYPES_) {
            // Only for assertions and debug messages
            assert(t_flit->m_width == bitWidth);
            assert((std::find(mVnets.begin(), mVnets.end(),
                t_flit->get_vnet()) != mVnets.end()) ||
                (mVnets.size() == 0));
        }
        t_flit->set_time(clockEdge(m_latency));
        nocProbeEvent("link.flit.enqueue", t_flit);
        linkBuffer.insert(t_flit);
        // if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        //     std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        //     if (auto strm =
        //             std::dynamic_pointer_cast<gem5::noc::NocStreamMsg>(
        //                 t_flit->get_msg_ptr())) {
        //         const int src_ni = strm->getSourceNiID();
        //         std::cout << "[AXIS-DBG] NL(" << name() << ")"
        //                   << " curTick=" << curTick()
        //                   << " stage=LINK_ENQUEUE_LINKBUF"
        //                   << " src_obj=" << src_object->name()
        //                   << " dst_obj=" << link_consumer->getObject()->name()
        //                   << " src_ni=" << src_ni
        //                   << " flit_id(net)=" << t_flit->get_id()
        //                   << " pkt_id=" << t_flit->getPacketID()
        //                   << " NPPMsg.numFlits=" << (unsigned)strm->getNumFlits()
        //                   << " vc=" << t_flit->get_vc()
        //                   << " vnet=" << t_flit->get_vnet()
        //                   << " arriveTick=" << t_flit->get_time()
        //                   << std::endl;
        //     }
        // }
        link_consumer->scheduleEventAbsolute(clockEdge(m_latency));
        m_link_utilized++;
        m_vc_load[t_flit->get_vc()]++;
    }

    if (!link_srcQueue->isEmpty()) {
        scheduleEvent(Cycles(1));
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::resetStats()
{
    for (int i = 0; i < m_vc_load.size(); i++) {
        m_vc_load[i] = 0;
    }

    m_link_utilized = 0;
}

template <typename T_Msg, typename T_RouteInfo>
bool
NetworkLink<T_Msg, T_RouteInfo>::functionalRead(Packet *pkt, WriteMask &mask)
{
    return linkBuffer.functionalRead(pkt, mask);
}

template <typename T_Msg, typename T_RouteInfo>
uint32_t
NetworkLink<T_Msg, T_RouteInfo>::functionalWrite(Packet *pkt)
{
    return linkBuffer.functionalWrite(pkt);
}

namespace
{

using NocMsg = gem5::noc::NocMessage;
using NocRI = gem5::noc::garnet::NocRouteInfo;
using NocLink = gem5::ruby::garnet::NetworkLink<NocMsg, NocRI>;
using NocFlitBuf = gem5::ruby::garnet::flitBuffer<NocMsg, NocRI>;
using NocNI = gem5::noc::garnet::NetworkInterface;
using NocRouterT = gem5::ruby::garnet::Router<NocMsg, NocRI>;
using NocBridge = gem5::ruby::garnet::NetworkBridge<NocMsg, NocRI>;

enum NocLinkSrcKind : int
{
    NL_SRC_ERR = 0,
    NL_SRC_NI_OUTPORT = 1,
    NL_SRC_NI_IN_CREDIT = 2,
    NL_SRC_ROUTER_OUT = 3,
    NL_SRC_ROUTER_IN_CREDIT = 4,
    NL_SRC_PEER_LINK = 5,
    NL_SRC_BRIDGE_LOCAL = 6,
    /** No NetworkLink-style external source (e.g. OBJECT_LINK bridge). */
    NL_SRC_NONE = 7,
};

static void
serializeNocLinkSource(CheckpointOut &cp, const NocLink *link,
    NocFlitBuf *q, ClockedObject *src)
{
    if (q == nullptr || src == nullptr) {
        paramOut(cp, "nl_src_kind", (int)NL_SRC_NONE);
        paramOut(cp, "nl_src_object", std::string());
        paramOut(cp, "nl_src_unit_idx", -1);
        return;
    }

    NocLink *mut_link = const_cast<NocLink *>(link);

    int kind = NL_SRC_ERR;
    int unit_idx = -1;
    std::string src_name = src->name();

    if (dynamic_cast<const NocBridge *>(link) &&
        (void *)src == (void *)link && q == mut_link->getBuffer()) {
        kind = NL_SRC_BRIDGE_LOCAL;
    } else if (auto *peer = dynamic_cast<NocLink *>(src)) {
        if (q == peer->getBuffer()) {
            kind = NL_SRC_PEER_LINK;
        }
    }

    if (kind == NL_SRC_ERR) {
        if (auto *ni = dynamic_cast<NocNI *>(src)) {
            unit_idx = ni->findOutPortIndexForFlitQueue(q);
            if (unit_idx >= 0) {
                kind = NL_SRC_NI_OUTPORT;
            } else {
                unit_idx = ni->findInputPortIndexForCreditQueue(q);
                if (unit_idx >= 0) {
                    kind = NL_SRC_NI_IN_CREDIT;
                }
            }
        }
    }

    if (kind == NL_SRC_ERR) {
        if (auto *r = dynamic_cast<NocRouterT *>(src)) {
            unit_idx = r->findOutputUnitIndexByOutQueue(q);
            if (unit_idx >= 0) {
                kind = NL_SRC_ROUTER_OUT;
            } else {
                unit_idx = r->findInputUnitIndexByCreditQueue(q);
                if (unit_idx >= 0) {
                    kind = NL_SRC_ROUTER_IN_CREDIT;
                }
            }
        }
    }

    fatal_if(kind == NL_SRC_ERR,
        "%s: unsupported NetworkLink source queue (src=%s)", link->name(),
        src_name.c_str());

    paramOut(cp, "nl_src_kind", kind);
    paramOut(cp, "nl_src_object", src_name);
    paramOut(cp, "nl_src_unit_idx", unit_idx);
}

static void
unserializeNocLinkSource(CheckpointIn &cp, NocLink *link)
{
    int kind = 0;
    std::string src_name;
    int unit_idx = -1;

    paramIn(cp, "nl_src_kind", kind);
    paramIn(cp, "nl_src_object", src_name);
    paramIn(cp, "nl_src_unit_idx", unit_idx);

    if (kind == NL_SRC_NONE) {
        return;
    }

    SimObject *src_obj = SimObject::find(src_name.c_str());
    fatal_if(!src_obj, "%s: nl_src_object not found: %s", link->name(),
        src_name.c_str());
    auto *src_clk = dynamic_cast<ClockedObject *>(src_obj);
    fatal_if(!src_clk, "%s: nl_src_object is not a ClockedObject",
        link->name());

    NocFlitBuf *q = nullptr;

    switch (kind) {
    case NL_SRC_NI_OUTPORT: {
        auto *ni = dynamic_cast<NocNI *>(src_clk);
        fatal_if(!ni || unit_idx < 0, "%s: bad NI out-port source",
            link->name());
        q = ni->getOutPortFlitQueueByIndex(unit_idx);
        break;
    }
    case NL_SRC_NI_IN_CREDIT: {
        auto *ni = dynamic_cast<NocNI *>(src_clk);
        fatal_if(!ni || unit_idx < 0, "%s: bad NI credit-queue source",
            link->name());
        q = ni->getInputPortCreditQueueByIndex(unit_idx);
        break;
    }
    case NL_SRC_ROUTER_OUT: {
        auto *r = dynamic_cast<NocRouterT *>(src_clk);
        fatal_if(!r || unit_idx < 0 ||
                unit_idx >= r->get_num_outports(),
            "%s: bad router output-queue source", link->name());
        q = r->getOutputUnit(unit_idx)->getOutQueue();
        break;
    }
    case NL_SRC_ROUTER_IN_CREDIT: {
        auto *r = dynamic_cast<NocRouterT *>(src_clk);
        fatal_if(!r || unit_idx < 0 ||
                unit_idx >= r->get_num_inports(),
            "%s: bad router credit-queue source", link->name());
        q = r->getInputUnit(unit_idx)->getCreditQueue();
        break;
    }
    case NL_SRC_PEER_LINK: {
        auto *peer = dynamic_cast<NocLink *>(src_clk);
        fatal_if(!peer, "%s: peer NetworkLink missing", link->name());
        q = peer->getBuffer();
        break;
    }
    case NL_SRC_BRIDGE_LOCAL: {
        auto *br = dynamic_cast<NocBridge *>(link);
        fatal_if(!br, "%s: expected NetworkBridge", link->name());
        q = br->getBuffer();
        break;
    }
    default:
        panic("%s: bad nl_src_kind %d", link->name(), kind);
    }

    link->setSourceQueue(q, src_clk);
}

static Consumer *
resolveNocLinkConsumer(SimObject *o)
{
    if (auto *c = dynamic_cast<NocNI *>(o)) {
        return c;
    }
    if (auto *c = dynamic_cast<NocRouterT *>(o)) {
        return c;
    }
    if (auto *c = dynamic_cast<NocLink *>(o)) {
        return c;
    }
    panic("NetworkLink consumer: unsupported SimObject %s", o->name());
}

static void
serializeNocLinkConsumer(CheckpointOut &cp, Consumer *cons)
{
    if (!cons || !cons->getObject()) {
        paramOut(cp, "nl_consumer_object", std::string());
        return;
    }
    paramOut(cp, "nl_consumer_object", cons->getObject()->name());
}

static void
unserializeNocLinkConsumer(CheckpointIn &cp, NocLink *link)
{
    std::string cons_name;
    paramIn(cp, "nl_consumer_object", cons_name);
    if (cons_name.empty()) {
        return;
    }
    SimObject *o = SimObject::find(cons_name.c_str());
    fatal_if(!o, "%s: nl_consumer_object not found: %s", link->name(),
        cons_name.c_str());
    link->setLinkConsumer(resolveNocLinkConsumer(o));
}

} // namespace

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::serialize(CheckpointOut &cp) const
{
    ClockedObject::serialize(cp);

    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        const auto *nlink = static_cast<const NocLink *>(this);
        paramOut(cp, "nl_m_link_utilized", m_link_utilized);
        arrayParamOut(cp, "nl_m_vc_load", m_vc_load);
        paramOut(cp, "nl_m_type", (int)m_type);
        paramOut(cp, "nl_bitWidth", bitWidth);
        arrayParamOut(cp, "nl_mVnets", mVnets);

        {
            Serializable::ScopedCheckpointSection sec(cp, "nl_linkBuffer");
            linkBuffer.serializeForNocNetworkCheckpoint(cp);
            // Source/consumer must be serialized while this scope is active:
            // paramOut does not record a section name, so keys land under the
            // most recent [*.nl_linkBuffer] header in the checkpoint file.
            serializeNocLinkSource(cp, nlink, link_srcQueue, src_object);
            serializeNocLinkConsumer(cp, link_consumer);
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::unserialize(CheckpointIn &cp)
{
    ClockedObject::unserialize(cp);

    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        auto *nlink = static_cast<NocLink *>(this);
        paramIn(cp, "nl_m_link_utilized", m_link_utilized);
        arrayParamIn(cp, "nl_m_vc_load", m_vc_load);
        int m_type_i = 0;
        paramIn(cp, "nl_m_type", m_type_i);
        m_type = (gem5::ruby::garnet::link_type)m_type_i;
        paramIn(cp, "nl_bitWidth", bitWidth);
        arrayParamIn(cp, "nl_mVnets", mVnets);

        {
            Serializable::ScopedCheckpointSection sec(cp, "nl_linkBuffer");
            linkBuffer.unserializeForNocNetworkCheckpoint(cp);
            unserializeNocLinkSource(cp, nlink);
            unserializeNocLinkConsumer(cp, nlink);
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::nocProbeEvent(const char* hookId)
{
    if (m_nocProbe && m_nocProbe->needsHookEvents()) {
        m_nocProbe->onHookEvent(hookId, name().c_str(), clockPeriod());
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkLink<T_Msg, T_RouteInfo>::nocProbeEvent(const char* hookId,
                                               flit<T_Msg, T_RouteInfo>* fl)
{
    if (m_nocProbe && m_nocProbe->needsHookEvents()) {
        if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
                      std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
            m_nocProbe->onHookEvent(hookId,
                static_cast<gem5::noc::NocProbe::FlitType*>(fl), name().c_str(),
                clockPeriod());
        } else {
            (void)hookId;
            (void)fl;
        }
    }
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
