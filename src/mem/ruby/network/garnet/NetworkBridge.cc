/*
 * Copyright (c) 2020 Advanced Micro Devices, Inc.
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice,
 * this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 * this list of conditions and the following disclaimer in the documentation
 * and/or other materials provided with the distribution.
 *
 * 3. Neither the name of the copyright holder nor the names of its
 * contributors may be used to endorse or promote products derived from this
 * software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */


#include "mem/ruby/network/garnet/NetworkBridge.hh"

#include <cmath>
#include <type_traits>

#include "base/str.hh"
#include "debug/RubyNetwork.hh"
#include "params/GarnetIntLink.hh"
#include "params/NocGarnetIntLink.hh"
#include "noc/lib/network/NocMessage.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/slicc_interface/Message.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{
template class NetworkBridge<Message, RouteInfo>;
template class NetworkBridge<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;

template class CreditLink<Message, RouteInfo>;
template class CreditLink<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;
template class NetworkLink<Message, RouteInfo>;
template class NetworkLink<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;

template <typename T_Msg, typename T_RouteInfo>
NetworkBridge<T_Msg, T_RouteInfo>::NetworkBridge(const Params &p)
    :CreditLink<T_Msg, T_RouteInfo>(p)
{
    // These are wired up later (e.g. via initBridge / topology setup). They
    // must be initialized to avoid checkpoint-time dereferences of garbage.
    coBridge = nullptr;
    nLink = nullptr;

    enCdc = true;
    enSerDes = true;
    mType = p.vtype;

    cdcLatency = p.cdc_latency;
    serDesLatency = p.serdes_latency;
    lastScheduledAt = 0;

    nLink = p.link;
    if (mType == enums::LINK_OBJECT) {
        nLink->setLinkConsumer(this);
        setSourceQueue(nLink->getBuffer(), nLink);
    } else if (mType == enums::OBJECT_LINK) {
        nLink->setSourceQueue(&linkBuffer, this);
        setLinkConsumer(nLink);
    } else {
        // CDC type must be set
        panic("CDC type must be set");
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkBridge<T_Msg, T_RouteInfo>::setVcsPerVnet(uint32_t consumerVcs)
{
    DPRINTF(RubyNetwork, "VcsPerVnet VC: %d\n", consumerVcs);
    NetworkLink<T_Msg, T_RouteInfo>::setVcsPerVnet(consumerVcs);
    lenBuffer.resize(consumerVcs * m_virt_nets);
    sizeSent.resize(consumerVcs * m_virt_nets);
    flitsSent.resize(consumerVcs * m_virt_nets);
    extraCredit.resize(consumerVcs * m_virt_nets);

    nLink->setVcsPerVnet(consumerVcs);
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkBridge<T_Msg, T_RouteInfo>::initBridge(NetworkBridge<T_Msg, T_RouteInfo> *coBrid, bool cdc_en, bool serdes_en)
{
    coBridge = coBrid;
    enCdc = cdc_en;
    enSerDes = serdes_en;
}

template <typename T_Msg, typename T_RouteInfo>
NetworkBridge<T_Msg, T_RouteInfo>::~NetworkBridge()
{
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkBridge<T_Msg, T_RouteInfo>::scheduleFlit(flit<T_Msg, T_RouteInfo> *t_flit, Cycles latency)
{
    Cycles totLatency = latency;

    if (enCdc) {
        // Add the CDC latency
        totLatency = latency + cdcLatency;
    }

    Tick sendTime = link_consumer->getObject()->clockEdge(totLatency);
    Tick nextAvailTick = lastScheduledAt + link_consumer->getObject()->\
            cyclesToTicks(Cycles(1));
    sendTime = std::max(nextAvailTick, sendTime);
    t_flit->set_time(sendTime);
    lastScheduledAt = sendTime;
    linkBuffer.insert(t_flit);
    link_consumer->scheduleEventAbsolute(sendTime);
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkBridge<T_Msg, T_RouteInfo>::neutralize(int vc, int eCredit)
{
    extraCredit[vc].push(eCredit);
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkBridge<T_Msg, T_RouteInfo>::flitisizeAndSend(flit<T_Msg, T_RouteInfo> *t_flit)
{
    // Serialize-Deserialize only if it is enabled
    if (enSerDes) {
        // Calculate the target-width
        int target_width = bitWidth;
        int cur_width = nLink->bitWidth;
        if (mType == enums::OBJECT_LINK) {
            target_width = nLink->bitWidth;
            cur_width = bitWidth;
        }

        DPRINTF(RubyNetwork, "Target width: %d Current: %d\n",
            target_width, cur_width);
        assert(target_width != cur_width);

        int vc = t_flit->get_vc();

        if (target_width > cur_width) {
            // Deserialize
            // This deserializer combines flits from the
            // same message together
            int num_flits = 0;
            int flitPossible = 0;
            if (t_flit->get_type() == CREDIT_) {
                lenBuffer[vc]++;
                assert(extraCredit[vc].front());
                if (lenBuffer[vc] == extraCredit[vc].front()) {
                    flitPossible = 1;
                    extraCredit[vc].pop();
                    lenBuffer[vc] = 0;
                }
            } else if (t_flit->get_type() == TAIL_ ||
                       t_flit->get_type() == HEAD_TAIL_) {
                // If its the end of packet, then send whatever
                // is available.
                int sizeAvail = (t_flit->msgSize - sizeSent[vc]);
                flitPossible = ceil((float)sizeAvail/(float)target_width);
                assert (flitPossible < 2);
                num_flits = (t_flit->get_id() + 1) - flitsSent[vc];
                // Stop tracking the packet.
                flitsSent[vc] = 0;
                sizeSent[vc] = 0;
            } else {
                // If we are yet to receive the complete packet
                // track the size recieved and flits deserialized.
                int sizeAvail =
                    ((t_flit->get_id() + 1)*cur_width) - sizeSent[vc];
                flitPossible = floor((float)sizeAvail/(float)target_width);
                assert (flitPossible < 2);
                num_flits = (t_flit->get_id() + 1) - flitsSent[vc];
                if (flitPossible) {
                    sizeSent[vc] += target_width;
                    flitsSent[vc] = t_flit->get_id() + 1;
                }
            }

            DPRINTF(RubyNetwork, "Deserialize :%dB -----> %dB "
                " vc:%d\n", cur_width, target_width, vc);

            flit<T_Msg, T_RouteInfo> *fl = NULL;
            if (flitPossible) {
                fl = t_flit->deserialize(lenBuffer[vc], num_flits,
                    target_width);
            }

            // Inform the credit serializer about the number
            // of flits that were generated.
            if (t_flit->get_type() != CREDIT_ && fl) {
                coBridge->neutralize(vc, num_flits);
            }

            // Schedule only if we are done deserializing
            if (fl) {
                DPRINTF(RubyNetwork, "Scheduling a flit\n");
                lenBuffer[vc] = 0;
                scheduleFlit(fl, serDesLatency);
            }
            // Delete this flit, new flit is sent in any case
            delete t_flit;
        } else {
            // Serialize
            DPRINTF(RubyNetwork, "Serializing flit :%d -----> %d "
            "(vc:%d, Original Message Size: %d)\n",
                cur_width, target_width, vc, t_flit->msgSize);

            int flitPossible = 0;
            if (t_flit->get_type() == CREDIT_) {
                // We store the deserialization ratio and then
                // access it when serializing credits in the
                // oppposite direction.
                assert(extraCredit[vc].front());
                flitPossible = extraCredit[vc].front();
                extraCredit[vc].pop();
            } else if (t_flit->get_type() == HEAD_ ||
                    t_flit->get_type() == BODY_) {
                int sizeAvail =
                    ((t_flit->get_id() + 1)*cur_width) - sizeSent[vc];
                flitPossible = floor((float)sizeAvail/(float)target_width);
                if (flitPossible) {
                    sizeSent[vc] += flitPossible*target_width;
                    flitsSent[vc] += flitPossible;
                }
            } else {
                int sizeAvail = t_flit->msgSize - sizeSent[vc];
                flitPossible = ceil((float)sizeAvail/(float)target_width);
                sizeSent[vc] = 0;
                flitsSent[vc] = 0;
            }
            assert(flitPossible > 0);

            // Schedule all the flits
            // num_flits could be zero for credits
            for (int i = 0; i < flitPossible; i++) {
                // Ignore neutralized credits
                flit<T_Msg, T_RouteInfo> *fl = t_flit->serialize(i, flitPossible, target_width);
                scheduleFlit(fl, serDesLatency);
                DPRINTF(RubyNetwork, "Serialized to flit[%d of %d parts]:"
                " %s\n", i+1, flitPossible, *fl);
            }

            if (t_flit->get_type() != CREDIT_) {
                coBridge->neutralize(vc, flitPossible);
            }
            // Delete this flit, new flit is sent in any case
            delete t_flit;
        }
        return;
    }

    // If only CDC is enabled schedule it
    scheduleFlit(t_flit, Cycles(0));
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkBridge<T_Msg, T_RouteInfo>::wakeup()
{
    flit<T_Msg, T_RouteInfo> *t_flit;

    if (link_srcQueue->isReady(curTick())) {
        t_flit = link_srcQueue->getTopFlit();
        DPRINTF(RubyNetwork, "Recieved flit %s\n", *t_flit);
        flitisizeAndSend(t_flit);
    }

    // Reschedule in case there is a waiting flit.
    if (!link_srcQueue->isEmpty()) {
        scheduleEvent(Cycles(1));
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkBridge<T_Msg, T_RouteInfo>::serialize(CheckpointOut &cp) const
{
    NetworkLink<T_Msg, T_RouteInfo>::serialize(cp);
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        // Keys must use the same nl_linkBuffer section as NetworkLink's
        // noc extras (see NetworkLink::serialize).
        {
            Serializable::ScopedCheckpointSection sec(cp, "nl_linkBuffer");
            paramOut(cp, "nb_lastScheduledAt", lastScheduledAt);
            paramOut(cp, "nb_enCdc", enCdc);
            paramOut(cp, "nb_enSerDes", enSerDes);
            paramOut(cp, "nb_mType", mType);
            paramOut(cp, "nb_cdc_latency", (uint64_t)cdcLatency);
            paramOut(cp, "nb_serdes_latency", (uint64_t)serDesLatency);
            arrayParamOut(cp, "nb_lenBuffer", lenBuffer);
            arrayParamOut(cp, "nb_sizeSent", sizeSent);
            arrayParamOut(cp, "nb_flitsSent", flitsSent);
            const std::string co_name = coBridge ? coBridge->name() : "";
            paramOut(cp, "nb_coBridge_name", co_name);
        }
        for (size_t i = 0; i < extraCredit.size(); i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("nb_extraCredit_%zu", i));
            std::queue<int> qcopy = extraCredit[i];
            paramOut(cp, "nb_ec_qsize", (int)qcopy.size());
            int j = 0;
            while (!qcopy.empty()) {
                paramOut(cp, csprintf("nb_ec_%d", j), qcopy.front());
                qcopy.pop();
                j++;
            }
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NetworkBridge<T_Msg, T_RouteInfo>::unserialize(CheckpointIn &cp)
{
    NetworkLink<T_Msg, T_RouteInfo>::unserialize(cp);
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        {
            Serializable::ScopedCheckpointSection sec(cp, "nl_linkBuffer");
            paramIn(cp, "nb_lastScheduledAt", lastScheduledAt);
            paramIn(cp, "nb_enCdc", enCdc);
            paramIn(cp, "nb_enSerDes", enSerDes);
            paramIn(cp, "nb_mType", mType);
            uint64_t cdc = 0, sd = 0;
            paramIn(cp, "nb_cdc_latency", cdc);
            paramIn(cp, "nb_serdes_latency", sd);
            cdcLatency = Cycles(cdc);
            serDesLatency = Cycles(sd);
            arrayParamIn(cp, "nb_lenBuffer", lenBuffer);
            arrayParamIn(cp, "nb_sizeSent", sizeSent);
            arrayParamIn(cp, "nb_flitsSent", flitsSent);
            std::string co_name;
            paramIn(cp, "nb_coBridge_name", co_name);
            if (co_name.empty()) {
                coBridge = nullptr;
            } else {
                SimObject *o = SimObject::find(co_name.c_str());
                fatal_if(!o, "%s: nb_coBridge_name not found: %s", name(),
                    co_name.c_str());
                coBridge = dynamic_cast<NetworkBridge<T_Msg, T_RouteInfo> *>(o);
                fatal_if(!coBridge,
                    "%s: nb_coBridge_name is not a NetworkBridge",
                    name());
            }
        }
        for (size_t i = 0; i < extraCredit.size(); i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("nb_extraCredit_%zu", i));
            int qsz = 0;
            paramIn(cp, "nb_ec_qsize", qsz);
            while (!extraCredit[i].empty()) {
                extraCredit[i].pop();
            }
            for (int j = 0; j < qsz; j++) {
                int v = 0;
                paramIn(cp, csprintf("nb_ec_%d", j), v);
                extraCredit[i].push(v);
            }
        }
    }
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
