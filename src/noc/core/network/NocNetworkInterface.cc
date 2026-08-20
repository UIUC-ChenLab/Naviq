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
#include "noc/core/network/NocNetworkInterface.hh"
#include "noc/core/network/NocNetwork.hh"
#include "noc/debug/NocProbe.hh"
#include <algorithm>
#include <cstring>
#include <cassert>
#include <cmath>
#include <string>
#include <vector>

#include "base/cast.hh"
// #include "debug/NocNetwork.hh"
#include "debug/NocDebugVerbose.hh"
#include "debug/NocNI.hh"
#include "noc/core/network/NocMessageBuffer.hh"
#include "mem/ruby/network/garnet/Credit.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "noc/lib/network/NocMessage.hh"
#include "noc/core/network/NocStreamMsg.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "noc/core/network/NocSystem.hh"
#include "mem/ruby/network/garnet/NetworkLink.hh"
#include "mem/ruby/network/garnet/flit.hh"
#include "debug/RubyNetwork.hh"
#include "base/str.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace noc
{

namespace garnet
{

namespace
{

template <typename T>
bool
optParamInSection(CheckpointIn &cp, const std::string &section,
    const std::string &name, T &param)
{
    std::string str;
    if (!cp.find(section, name, str)) {
        return false;
    }
    return ParseParam<T>::parse(str, param);
}

/** Older checkpoints wrote some NI scalars under the last opened subsection. */
template <typename T>
void
paramInNiScalarRootOrLegacy(CheckpointIn &cp, const std::string &ni_name,
    const std::string &key, T &param,
    const std::vector<std::string> &legacy_sections)
{
    if (optParamInSection(cp, ni_name, key, param)) {
        return;
    }
    for (const auto &sec : legacy_sections) {
        if (optParamInSection(cp, sec, key, param)) {
            return;
        }
    }
    fatal("Can't unserialize '%s:%s'", ni_name, key);
}

static void
appendOutpFlitBeatLegacySecs(std::vector<std::string> &leg,
    const std::string &ni_name, unsigned out_idx)
{
    const std::string outp = csprintf("%s.ni_outp_%u", ni_name.c_str(), out_idx);
    leg.push_back(outp);
    for (int j = 0; j < 64; j++) {
        for (int b = 0; b < 64; b++) {
            leg.push_back(outp + csprintf(
                ".fb_flit_%d.data.axisPayload.beat%d", j, b));
        }
    }
}

static void
paramInOutpVcrr(CheckpointIn &cp, const std::string &ni_name, unsigned i,
    int &vcrr)
{
    const std::string key = csprintf("ni_outp_%u_vcrr", i);
    if (optParamInSection(cp, ni_name, key, vcrr)) {
        return;
    }
    const std::string outp = csprintf("%s.ni_outp_%u", ni_name.c_str(), i);
    if (optParamInSection(cp, outp, key, vcrr)) {
        return;
    }
    // Legacy: paramOut ran after the last ni_niovcbuf_* ScopedCheckpointSection,
    // so the key landed in that subsection (see m5.cpt under ...ni_niovcbuf_19).
    for (int j = 0; j < 64; j++) {
        const std::string nv =
            csprintf("%s.ni_niovcbuf_%d", ni_name.c_str(), j);
        if (optParamInSection(cp, nv, key, vcrr)) {
            return;
        }
    }
    std::vector<std::string> leg;
    appendOutpFlitBeatLegacySecs(leg, ni_name, i);
    for (const auto &sec : leg) {
        if (optParamInSection(cp, sec, key, vcrr)) {
            return;
        }
    }
    fatal("Can't unserialize '%s:%s'", ni_name, key);
}

} // namespace

NetworkInterface::NetworkInterface(const Params &p)
  : ClockedObject(p), Consumer(this), m_id(p.id),
    m_virtual_networks(p.virt_nets), m_vc_per_vnet(0),
    m_vc_allocator(m_virtual_networks, 0),
    m_deadlock_threshold(p.garnet_deadlock_threshold),
    vc_busy_counter(m_virtual_networks, 0),
    m_nocProbe(p.noc_probe)
{
    niOutVcs.resize(0);

    // tile tick event happens before these are initialized by addNode
    //so set size to 0 so that the tile calling getAxiR/WAddrReady doesn't cause segfault with calling size
    // (maybe in future fix ordering of events instead)
    inNode_ptr.resize(0);
    outNode_ptr.resize(0);

}

void
NetworkInterface::addInPort(gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *in_link,
                            gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *credit_link,
                            int router_id)
{
    InputPort *newInPort = new InputPort(in_link, credit_link, router_id);
    if (!niOutVcs.empty()) {
        newInPort->resizeNppAssemblers(niOutVcs.size());
        DPRINTF(NocNI,
            "[NocNI debug] addInPort ni=%s resized_npp_assemblers=%lu "
            "num_vcs=%lu vc_per_vnet=%d\n",
            name(), newInPort->nppAssemblers().size(),
            niOutVcs.size(), m_vc_per_vnet);
    }
    inPorts.push_back(newInPort);
    DPRINTF(NocNI,
        "[NocNI debug] addInPort ni=%s in_ports=%lu link=%s credit_link=%s\n",
        name(), inPorts.size(), in_link->name(), credit_link->name());
    // DPRINTF(RubyNetwork, "Adding input port:%s with vnets %s\n",
    // in_link->name(), newInPort->printVnets());

    in_link->setLinkConsumer(this);
    credit_link->setSourceQueue(newInPort->outCreditQueue(), this);
    if (m_vc_per_vnet != 0) {
        in_link->setVcsPerVnet(m_vc_per_vnet);
        credit_link->setVcsPerVnet(m_vc_per_vnet);
    }
}

void
NetworkInterface::addOutPort(gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *out_link,
                            gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *credit_link,
                            gem5::ruby::SwitchID router_id, uint32_t consumerVcs)
{
    NetworkInterface::OutputPort *newOutPort = new OutputPort(out_link, credit_link, router_id);
    outPorts.push_back(newOutPort);

    assert(consumerVcs > 0);
    // We are not allowing different physical links to have different vcs
    // If it is required that the Network Interface support different VCs
    // for every physical link connected to it. Then they need to change
    // the logic within outport and inport.
    if (niOutVcs.size() == 0) {
        m_vc_per_vnet = consumerVcs;
        int m_num_vcs = 8;
        if (m_num_vcs <= 0)
            m_num_vcs = consumerVcs;
        niOutVcs.resize(m_num_vcs);
        outVcState.reserve(m_num_vcs);
        m_ni_out_vcs_enqueue_time.resize(m_num_vcs);
        // instantiating the NI flit buffers
        for (int i = 0; i < m_num_vcs; i++) {
            niOutVcs[i].setMaxSize(kNiOutVcMaxFlits);
            m_ni_out_vcs_enqueue_time[i] = Tick(INFINITE_);
            outVcState.emplace_back(i, m_net_ptr, consumerVcs);
        }

        // Reset VC Per VNET for input links already instantiated
        for (auto &iPort: inPorts) {
            gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *inNetLink = iPort->inNetLink();
            inNetLink->setVcsPerVnet(m_vc_per_vnet);
            iPort->outCreditLink()->setVcsPerVnet(m_vc_per_vnet);
            iPort->resizeNppAssemblers(m_num_vcs);
            DPRINTF(NocNI,
                "[NocNI debug] addOutPort ni=%s resized_existing_input_assemblers=%lu "
                "num_vcs=%d vc_per_vnet=%d\n",
                name(), iPort->nppAssemblers().size(),
                m_num_vcs, m_vc_per_vnet);
        }
    } else {
        fatal_if(consumerVcs != m_vc_per_vnet,
        "%s: Connected Physical links have different vc requests: %d and %d\n",
        name(), consumerVcs, m_vc_per_vnet);
    }

    // DPRINTF(RubyNetwork, "OutputPort:%s Vnet: %s\n",
    // out_link->name(), newOutPort->printVnets());

    out_link->setSourceQueue(newOutPort->outFlitQueue(), this);
    out_link->setVcsPerVnet(m_vc_per_vnet);
    credit_link->setLinkConsumer(this);
    credit_link->setVcsPerVnet(m_vc_per_vnet);
        DPRINTF(NocNI,
        "[NocNI debug] addOutPort ni=%s out_ports=%lu router_id=%d "
        "consumer_vcs=%u physical_vcs=%d link=%s credit_link=%s\n",
        name(), outPorts.size(), router_id, consumerVcs,
        static_cast<int>(niOutVcs.size()),
        out_link->name(), credit_link->name());
}


int
NetworkInterface::findOutPortIndexForFlitQueue(
    const gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *q) const
{
    for (size_t i = 0; i < outPorts.size(); i++) {
        if (outPorts[i]->outFlitQueue() == q) {
            return (int)i;
        }
    }
    return -1;
}

int
NetworkInterface::findInputPortIndexForCreditQueue(
    const gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *q) const
{
    for (size_t i = 0; i < inPorts.size(); i++) {
        if (inPorts[i]->outCreditQueue() == q) {
            return (int)i;
        }
    }
    return -1;
}

gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *
NetworkInterface::getOutPortFlitQueueByIndex(int out_idx) const
{
    assert(out_idx >= 0 && (size_t)out_idx < outPorts.size());
    return outPorts[out_idx]->outFlitQueue();
}

gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *
NetworkInterface::getInputPortCreditQueueByIndex(int in_idx) const
{
    assert(in_idx >= 0 && (size_t)in_idx < inPorts.size());
    return inPorts[in_idx]->outCreditQueue();
}

void
NetworkInterface::serialize(CheckpointOut &cp) const
{
    ClockedObject::serialize(cp);

    SERIALIZE_SCALAR(m_vc_per_vnet);
    SERIALIZE_SCALAR(m_deadlock_threshold);
    SERIALIZE_SCALAR(nmu_latency);
    SERIALIZE_CONTAINER(m_vc_allocator);
    SERIALIZE_CONTAINER(m_ni_out_vcs_enqueue_time);
    SERIALIZE_CONTAINER(vc_busy_counter);

    const uint32_t n_ovc = outVcState.size();
    const uint32_t n_niov = niOutVcs.size();
    const uint32_t nop = outPorts.size();
    const uint32_t nip = inPorts.size();

    // Emit all NI-root scalars before any subsection: paramOut only records
    // key=value lines; IniFile assigns them to the last [section] header, so
    // counts must not follow ScopedCheckpointSection blocks.
    paramOut(cp, "ni_outvcstate_n", n_ovc);
    paramOut(cp, "ni_nioutvcs_n", n_niov);
    paramOut(cp, "ni_outports_n", nop);
    paramOut(cp, "ni_inports_n", nip);

    for (uint32_t i = 0; i < n_ovc; i++) {
        gem5::Serializable::ScopedCheckpointSection sec(
            cp, csprintf("ni_outvc_%u", i).c_str());
        outVcState[i].serialize(cp);
    }

    for (uint32_t i = 0; i < n_niov; i++) {
        gem5::Serializable::ScopedCheckpointSection sec(
            cp, csprintf("ni_niovcbuf_%u", i).c_str());
        niOutVcs[i].serializeForNocNetworkCheckpoint(cp);
    }

    for (uint32_t i = 0; i < nop; i++) {
        paramOut(cp, csprintf("ni_outp_%u_vcrr", i), outPorts[i]->vcRoundRobin());
    }
    for (uint32_t i = 0; i < nop; i++) {
        gem5::Serializable::ScopedCheckpointSection sec(
            cp, csprintf("ni_outp_%u", i).c_str());
        outPorts[i]->outFlitQueue()->serializeForNocNetworkCheckpoint(cp);
    }

    for (uint32_t i = 0; i < nip; i++) {
        gem5::Serializable::ScopedCheckpointSection sec(
            cp, csprintf("ni_inp_%u", i).c_str());
        inPorts[i]->outCreditQueue()->serializeForNocNetworkCheckpoint(cp);
    }
}

void
NetworkInterface::unserialize(CheckpointIn &cp)
{
    ClockedObject::unserialize(cp);

    UNSERIALIZE_SCALAR(m_vc_per_vnet);
    UNSERIALIZE_SCALAR(m_deadlock_threshold);
    UNSERIALIZE_SCALAR(nmu_latency);
    UNSERIALIZE_CONTAINER(m_vc_allocator);
    UNSERIALIZE_CONTAINER(m_ni_out_vcs_enqueue_time);
    UNSERIALIZE_CONTAINER(vc_busy_counter);

    const std::string ni_name = name();

    uint32_t n_ovc = 0;
    paramIn(cp, "ni_outvcstate_n", n_ovc);
    fatal_if(n_ovc != outVcState.size(),
        "%s: checkpoint ni_outvcstate_n mismatch", name());
    for (uint32_t i = 0; i < n_ovc; i++) {
        gem5::Serializable::ScopedCheckpointSection sec(
            cp, csprintf("ni_outvc_%u", i).c_str());
        outVcState[i].unserialize(cp);
    }

    uint32_t n_niov = 0;
    std::vector<std::string> leg_niov;
    if (n_ovc > 0) {
        leg_niov.push_back(
            csprintf("%s.ni_outvc_%u", ni_name.c_str(), n_ovc - 1));
    }
    paramInNiScalarRootOrLegacy(
        cp, ni_name, "ni_nioutvcs_n", n_niov, leg_niov);
    fatal_if(n_niov != niOutVcs.size(),
        "%s: checkpoint ni_nioutvcs_n mismatch", name());
    for (uint32_t i = 0; i < n_niov; i++) {
        gem5::Serializable::ScopedCheckpointSection sec(
            cp, csprintf("ni_niovcbuf_%u", i).c_str());
        niOutVcs[i].unserializeForNocNetworkCheckpoint(cp);
    }

    uint32_t nop = 0;
    std::vector<std::string> leg_nop;
    if (n_niov > 0) {
        leg_nop.push_back(
            csprintf("%s.ni_niovcbuf_%u", ni_name.c_str(), n_niov - 1));
    }
    paramInNiScalarRootOrLegacy(
        cp, ni_name, "ni_outports_n", nop, leg_nop);
    fatal_if(nop != outPorts.size(),
        "%s: checkpoint ni_outports_n mismatch", name());
    for (uint32_t i = 0; i < nop; i++) {
        gem5::Serializable::ScopedCheckpointSection sec(
            cp, csprintf("ni_outp_%u", i).c_str());
        outPorts[i]->outFlitQueue()->unserializeForNocNetworkCheckpoint(cp);
        int vcrr = 0;
        paramInOutpVcrr(cp, ni_name, i, vcrr);
        outPorts[i]->vcRoundRobin(vcrr);
    }

    uint32_t nip = 0;
    std::vector<std::string> leg_nip;
    if (nop > 0) {
        appendOutpFlitBeatLegacySecs(leg_nip, ni_name, nop - 1);
    }
    paramInNiScalarRootOrLegacy(
        cp, ni_name, "ni_inports_n", nip, leg_nip);
    fatal_if(nip != inPorts.size(),
        "%s: checkpoint ni_inports_n mismatch", name());

    for (uint32_t i = 0; i < nip; i++) {
        gem5::Serializable::ScopedCheckpointSection sec(
            cp, csprintf("ni_inp_%u", i).c_str());
        inPorts[i]->outCreditQueue()->unserializeForNocNetworkCheckpoint(cp);
    }
}

void
NetworkInterface::dequeueCallback()
{
    // An output MessageBuffer has dequeued something this cycle and there
    // is now space to enqueue a stalled message. However, we cannot wake
    // on the same cycle as the dequeue. Schedule a wake at the soonest
    // possible time (next cycle).
    DPRINTF(NocNI,
        "[NocNI debug] dequeueCallback ni=%s tick=%llu locked_port=%d "
        "locked_vc=%d scheduling_next_cycle\n",
        name(), (unsigned long long)curTick(),
        m_locked_assembler_input_port, m_locked_assembler_vc);
    scheduleEventAbsolute(clockEdge(Cycles(1)));
}

MessageBuffer *
NetworkInterface::getOutNodeQueue(int vnet) const
{
    if (vnet < 0 || static_cast<size_t>(vnet) >= outNode_ptr.size()) {
        return nullptr;
    }
    return outNode_ptr[vnet];
}

void
NetworkInterface::registerStallCallbackForVnet(int vnet)
{
    MessageBuffer *queue = getOutNodeQueue(vnet);
    panic_if(
        queue == nullptr,
        "%s: cannot register stall callback for vnet %d. "
        "outNode_ptr size=%zu, NI id=%d, virtual_networks=%d",
        name(), vnet, outNode_ptr.size(), m_id, m_virtual_networks);
    queue->registerDequeueCallback([this]() { dequeueCallback(); });
}

/*
 * The NI wakeup checks whether there are any ready messages in the protocol
 * buffer. If yes, it picks that up, flitisizes it into a number of flits and
 * puts it into an output buffer and schedules the output link. On a wakeup
 * it also checks whether there are flits in the input link. If yes, it picks
 * them up and if the flit is a tail, the NI inserts the corresponding message
 * into the protocol buffer. It also checks for credits being sent by the
 * downstream router.
 */

void
NetworkInterface::wakeup()
{
    std::ostringstream oss;
    for (auto &oPort: outPorts) {
        oss << oPort->routerID() << "[" << oPort->printVnets() << "] ";
    }
    // printf("Network Interface %d connected to router:%s "
            // "woke up. Period: %ld\n", m_id, oss.str(), clockPeriod());

    assert(curTick() == clockEdge());
    MsgPtr msg_ptr;
    Tick curTime = clockEdge();
    DPRINTF(NocNI,
        "[NocNI debug] wakeup ni=%s id=%u tick=%llu clock_edge=%llu "
        "in_ports=%lu out_ports=%lu locked_port=%d locked_vc=%d routers=\"%s\"\n",
        name(), (unsigned)m_id,
        (unsigned long long)curTick(), (unsigned long long)curTime,
        inPorts.size(), outPorts.size(),
        m_locked_assembler_input_port, m_locked_assembler_vc,
        oss.str().c_str());

    // Checking for messages coming from the protocol
    // can pick up a message/cycle for each virtual net
    for (int vnet = 0; vnet < inNode_ptr.size(); ++vnet) {
        MessageBuffer *b = inNode_ptr[vnet];
        if (b == nullptr) {
            continue;
        }

        if (b->isReady(curTime)) { // Is there a message waiting
            msg_ptr = b->peekMsgPtr();
            DPRINTF(NocNI,
                "[NocNI debug] protocol_msg_ready ni=%s tick=%llu vnet=%d "
                "msgbuf_size=%u\n",
                name(), (unsigned long long)curTick(), vnet,
                b->getSize(curTime));
            DPRINTF(NocDebugVerbose,
                "[NI inNode→NMU] ni=%u vnet=%d msgbuf_size=%u tick=%llu\n",
                (unsigned)m_id, vnet, b->getSize(curTime),
                (unsigned long long)curTime);
            if (flitisizeMessage(msg_ptr, vnet)) {
                nocProbeEvent("ni.msg.to_flit", msg_ptr);
                b->dequeue(curTime);
                DPRINTF(NocNI,
                    "[NocNI debug] protocol_msg_flitisized ni=%s tick=%llu "
                    "vnet=%d remaining_msgbuf_size=%u\n",
                    name(), (unsigned long long)curTick(), vnet,
                    b->getSize(curTime));
            } else {
                DPRINTF(NocNI,
                    "[NocNI debug] protocol_msg_flitisize_failed ni=%s "
                    "tick=%llu vnet=%d msgbuf_size=%u\n",
                    name(), (unsigned long long)curTick(), vnet,
                    b->getSize(curTime));
                DPRINTF(NocDebugVerbose,
                    "[NI inNode→NMU stall] ni=%u vnet=%d msgbuf_size=%u "
                    "(flitisizeMessage deferred) tick=%llu\n",
                    (unsigned)m_id, vnet, b->getSize(curTime),
                    (unsigned long long)curTime);
            }
            // flitisizeMessage may return false (e.g., RROB full, SSID check pending):
            // leave message in buffer to retry on next wakeup (backpressure).
        }
    }

    scheduleOutputLink();
    DPRINTF(NocNI,
        "[NocNI debug] after_scheduleOutputLink ni=%s tick=%llu "
        "locked_port=%d locked_vc=%d\n",
        name(), (unsigned long long)curTick(),
        m_locked_assembler_input_port, m_locked_assembler_vc);

    /*********** Check the incoming flit link **********/
    // DPRINTF(RubyNetwork, "Number of input ports: %d\n", inPorts.size());
    for (int in_port_idx = 0; in_port_idx < static_cast<int>(inPorts.size());
         in_port_idx++) {
        InputPort *iPort = inPorts[in_port_idx];
        gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *inNetLink =
            iPort->inNetLink();
        auto &assemblers = iPort->nppAssemblers();

        DPRINTF(NocNI,
            "[NocNI debug] input_port_scan ni=%s tick=%llu in_port=%d "
            "next_assembler_vc=%d num_assemblers=%lu locked_port=%d locked_vc=%d\n",
            name(), (unsigned long long)curTick(), in_port_idx,
            iPort->nextAssemblerVc(), assemblers.size(),
            m_locked_assembler_input_port, m_locked_assembler_vc);

        while (inNetLink->isReady(curTick())) {
            auto *peek_flit = inNetLink->peekLink();
            const int vc = peek_flit->get_vc();
            auto &assembler = iPort->nppAssemblerForVc(vc);
            if (assembler.size() >= kNppAssemblerMaxFlits) {
                DPRINTF(NocNI,
                    "[NocNI debug] assembler_full_link_stall ni=%s tick=%llu "
                    "in_port=%d vc=%d assembler_size=%lu max=%u\n",
                    name(), (unsigned long long)curTick(), in_port_idx, vc,
                    assembler.size(), kNppAssemblerMaxFlits);
                scheduleEventAbsolute(clockEdge(Cycles(1)));
                break;
            }

            auto *t_flit = inNetLink->consumeLink();
            nocProbeEvent("ni.flit.from_link", t_flit);
            DPRINTF(RubyNetwork, "Recieved flit:%s\n", *t_flit);
            assert(t_flit->m_width == iPort->bitWidth());
            if (iPort->routerID() >= 0) {
                t_flit->get_msg_ptr()->setIncomingLink(iPort->routerID());
            }

            t_flit->set_dequeue_time(curTick());
            assembler.push_back(t_flit);
            DPRINTF(NocNI,
                "[NocNI debug] assembler_enqueue ni=%s tick=%llu in_port=%d "
                "vc=%d vnet=%d type=%d assembler_size=%lu max=%u\n",
                name(), (unsigned long long)curTick(), in_port_idx, vc,
                t_flit->get_vnet(), t_flit->get_type(),
                assembler.size(), kNppAssemblerMaxFlits);
        }

        std::string lengths;
        for (int vc = 0; vc < static_cast<int>(assemblers.size()); vc++) {
            lengths += csprintf("%d:%lu", vc, assemblers[vc].size());
            if (vc + 1 < static_cast<int>(assemblers.size())) {
                lengths += ",";
            }
        }
        DPRINTF(NocNI,
            "[NocNI debug] assembler_lengths ni=%s tick=%llu in_port=%d "
            "lengths=%s\n",
            name(), (unsigned long long)curTick(), in_port_idx,
            lengths.c_str());
    }

    if (m_locked_assembler_input_port == -1) {
        for (int port_off = 0;
             port_off < static_cast<int>(inPorts.size()) &&
             m_locked_assembler_input_port == -1;
             port_off++) {
            const int in_port_idx =
                (m_next_assembler_input_port + port_off) % inPorts.size();
            InputPort *iPort = inPorts[in_port_idx];
            auto &assemblers = iPort->nppAssemblers();
            const int num_assemblers = static_cast<int>(assemblers.size());
            for (int vc_off = 0; vc_off < num_assemblers; vc_off++) {
                const int vc = (iPort->nextAssemblerVc() + vc_off) %
                    num_assemblers;
                if (assemblers[vc].empty()) {
                    continue;
                }

                m_locked_assembler_input_port = in_port_idx;
                m_locked_assembler_vc = vc;
                m_next_assembler_input_port =
                    (in_port_idx + 1) % inPorts.size();
                iPort->setNextAssemblerVc((vc + 1) % num_assemblers);
                DPRINTF(NocNI,
                    "[NocNI debug] assembler_lock ni=%s tick=%llu in_port=%d "
                    "vc=%d queue_size=%lu next_lru_port=%d next_lru_vc=%d\n",
                    name(), (unsigned long long)curTick(), in_port_idx, vc,
                    assemblers[vc].size(), m_next_assembler_input_port,
                    iPort->nextAssemblerVc());
                break;
            }
        }
    }

    if (m_locked_assembler_input_port != -1) {
        panic_if(m_locked_assembler_input_port < 0 ||
            static_cast<size_t>(m_locked_assembler_input_port) >= inPorts.size(),
            "%s: locked assembler input port %d out of range (inPorts %u)",
            name(), m_locked_assembler_input_port,
            static_cast<unsigned>(inPorts.size()));

        InputPort *locked_port = inPorts[m_locked_assembler_input_port];
        auto &assembler = locked_port->nppAssemblerForVc(m_locked_assembler_vc);
        if (assembler.empty()) {
            DPRINTF(NocNI,
                "[NocNI debug] locked_assembler_empty ni=%s tick=%llu "
                "in_port=%d vc=%d reschedule=1\n",
                name(), (unsigned long long)curTick(),
                m_locked_assembler_input_port, m_locked_assembler_vc);
            scheduleEventAbsolute(clockEdge(Cycles(1)));
        } else {
            bool bypassed_control_flit = false;
            auto *locked_front_flit = assembler.front();
            const bool locked_front_is_tail =
                locked_front_flit->get_type() == gem5::ruby::garnet::TAIL_ ||
                locked_front_flit->get_type() == gem5::ruby::garnet::HEAD_TAIL_;

            if (!locked_front_is_tail) {
                for (int port_off = 0;
                     port_off < static_cast<int>(inPorts.size()) &&
                     !bypassed_control_flit;
                     port_off++) {
                    const int in_port_idx =
                        (m_locked_assembler_input_port + port_off) %
                        inPorts.size();
                    InputPort *candidate_port = inPorts[in_port_idx];
                    auto &candidate_assemblers =
                        candidate_port->nppAssemblers();
                    const int num_assemblers =
                        static_cast<int>(candidate_assemblers.size());

                    for (int vc_off = 0; vc_off < num_assemblers; vc_off++) {
                        const int vc =
                            (candidate_port->nextAssemblerVc() + vc_off) %
                            num_assemblers;
                        if (in_port_idx == m_locked_assembler_input_port &&
                            vc == m_locked_assembler_vc) {
                            continue;
                        }

                        auto &candidate_assembler =
                            candidate_port->nppAssemblerForVc(vc);
                        if (candidate_assembler.empty()) {
                            continue;
                        }

                        auto *candidate = candidate_assembler.front();
                        const int candidate_vnet = candidate->get_vnet();
                        const bool candidate_is_control =
                            candidate->get_type() ==
                                gem5::ruby::garnet::HEAD_TAIL_ &&
                            (candidate_vnet == AR_VNET ||
                             candidate_vnet == AW_VNET);
                        if (!candidate_is_control) {
                            continue;
                        }

                        if (!depacketizeFlit(candidate)) {
                            continue;
                        }

                        nocProbeEvent("ni.flit.to_protocol", candidate);
                        auto *cFlit =
                            new gem5::ruby::garnet::Credit<NocMessage,
                                                            NocRouteInfo>(
                                candidate->get_vc(), true, curTick());
                        candidate_port->sendCredit(cFlit);
                        DPRINTF(NocNI,
                            "[NocNI debug] control_bypass ni=%s tick=%llu "
                            "locked_in_port=%d locked_vc=%d locked_flit_vc=%d "
                            "locked_vnet=%d locked_type=%d bypass_in_port=%d "
                            "bypass_vc=%d bypass_flit_vc=%d bypass_vnet=%d "
                            "bypass_type=%d bypass_pkt=%d\n",
                            name(), (unsigned long long)curTick(),
                            m_locked_assembler_input_port,
                            m_locked_assembler_vc,
                            locked_front_flit->get_vc(),
                            locked_front_flit->get_vnet(),
                            locked_front_flit->get_type(),
                            in_port_idx, vc, candidate->get_vc(),
                            candidate_vnet, candidate->get_type(),
                            candidate->getPacketID());

                        delete candidate;
                        candidate_assembler.pop_front();
                        scheduleEventAbsolute(clockEdge(Cycles(1)));
                        bypassed_control_flit = true;
                        break;
                    }
                }
            }

            if (bypassed_control_flit) {
                // Keep the existing packet lock. The bypass only borrows this
                // cycle for a single-flit control packet from another VC.
            } else {
                auto *front_flit = assembler.front();
                const bool is_tail =
                    front_flit->get_type() == gem5::ruby::garnet::TAIL_ ||
                    front_flit->get_type() == gem5::ruby::garnet::HEAD_TAIL_;

                DPRINTF(NocNI,
                    "[NocNI debug] locked_assembler_front ni=%s tick=%llu "
                    "in_port=%d vc=%d queue_size=%lu flit_vc=%d vnet=%d type=%d "
                    "is_tail=%d\n",
                    name(), (unsigned long long)curTick(),
                    m_locked_assembler_input_port, m_locked_assembler_vc,
                    assembler.size(), front_flit->get_vc(),
                    front_flit->get_vnet(), front_flit->get_type(),
                    is_tail ? 1 : 0);

                if (depacketizeFlit(front_flit)) {
                    nocProbeEvent("ni.flit.to_protocol", front_flit);
                    auto *cFlit =
                        new gem5::ruby::garnet::Credit<NocMessage, NocRouteInfo>(
                            front_flit->get_vc(), is_tail, curTick());
                    locked_port->sendCredit(cFlit);
                    DPRINTF(NocNI,
                        "[NocNI debug] depacketized ni=%s tick=%llu in_port=%d "
                        "vc=%d flit_vc=%d vnet=%d type=%d is_tail=%d "
                        "credit_queue_size=%u\n",
                        name(), (unsigned long long)curTick(),
                        m_locked_assembler_input_port, m_locked_assembler_vc,
                        front_flit->get_vc(), front_flit->get_vnet(),
                        front_flit->get_type(), is_tail ? 1 : 0,
                        locked_port->outCreditQueue()->getSize());

                    delete front_flit;
                    assembler.pop_front();
                    DPRINTF(NocNI,
                        "[NocNI debug] assembler_pop ni=%s tick=%llu in_port=%d "
                        "vc=%d queue_size_after_pop=%lu\n",
                        name(), (unsigned long long)curTick(),
                        m_locked_assembler_input_port, m_locked_assembler_vc,
                        assembler.size());

                    if (is_tail) {
                        DPRINTF(NocNI,
                            "[NocNI debug] assembler_unlock_tail ni=%s tick=%llu "
                            "in_port=%d vc=%d\n",
                            name(), (unsigned long long)curTick(),
                            m_locked_assembler_input_port,
                            m_locked_assembler_vc);
                        m_locked_assembler_input_port = -1;
                        m_locked_assembler_vc = -1;
                    } else {
                        DPRINTF(NocNI,
                            "[NocNI debug] assembler_reschedule_locked ni=%s "
                            "tick=%llu in_port=%d vc=%d queue_size=%lu\n",
                            name(), (unsigned long long)curTick(),
                            m_locked_assembler_input_port,
                            m_locked_assembler_vc, assembler.size());
                        scheduleEventAbsolute(clockEdge(Cycles(1)));
                    }
                } else {
                    const int vnet = front_flit->get_vnet();
                    DPRINTF(NocNI,
                        "[NocNI debug] depacketize_failed ni=%s tick=%llu "
                        "in_port=%d vc=%d flit_vc=%d vnet=%d type=%d queue_size=%lu\n",
                        name(), (unsigned long long)curTick(),
                        m_locked_assembler_input_port, m_locked_assembler_vc,
                        front_flit->get_vc(), vnet, front_flit->get_type(),
                        assembler.size());
                    panic_if(vnet < 0 ||
                        static_cast<size_t>(vnet) >= outNode_ptr.size(),
                        "%s: stalled flit vnet %d out of range (outNode %u)",
                        name(), vnet, static_cast<unsigned>(outNode_ptr.size()));
                    MessageBuffer *const obuf = outNode_ptr[vnet];
                    panic_if(!obuf,
                        "%s: stalled flit vnet %d: null outNode "
                        "(queue not wired for this vnet?)", name(), vnet);
                    obuf->registerDequeueCallback([this]() {
                        dequeueCallback(); });
                    DPRINTF(NocNI,
                        "[NocNI debug] registered_dequeue_callback ni=%s tick=%llu "
                        "vnet=%d\n", name(),
                        (unsigned long long)curTick(), vnet);
                }
            }
        }
    } else {
        DPRINTF(NocNI,
            "[NocNI debug] no_assembler_ready ni=%s tick=%llu\n",
            name(), (unsigned long long)curTick());
    }

    /****************** Check the incoming credit link *******/

    for (auto &oPort: outPorts) {
        gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *inCreditLink = oPort->inCreditLink();
        if (inCreditLink->isReady(curTick())) {
            gem5::ruby::garnet::Credit<NocMessage, NocRouteInfo> *t_credit = (gem5::ruby::garnet::Credit<NocMessage, NocRouteInfo>*) inCreditLink->consumeLink();
            DPRINTF(NocNI,
                "[NocNI debug] credit_from_router ni=%s tick=%llu vc=%d "
                "free_signal=%d\n",
                name(), (unsigned long long)curTick(), t_credit->get_vc(),
                t_credit->is_free_signal() ? 1 : 0);
            outVcState[t_credit->get_vc()].increment_credit();
            if (t_credit->is_free_signal()) {
                outVcState[t_credit->get_vc()].setState(gem5::ruby::garnet::IDLE_,
                    curTick());
            }
            delete t_credit;
        }
    }


    // It is possible to enqueue multiple outgoing credit flits if a message
    // was unstalled in the same cycle as a new message arrives. In this
    // case, we should schedule another wakeup to ensure the credit is sent
    // back.
    for (auto &iPort: inPorts) {
        if (iPort->outCreditQueue()->getSize() > 0) {
            DPRINTF(NocNI,
                "[NocNI debug] credit_link_schedule ni=%s tick=%llu "
                "credit_queue_size=%u\n",
                name(), (unsigned long long)curTick(),
                iPort->outCreditQueue()->getSize());
            // DPRINTF(NocNetwork, "Sending a credit %s via %s at %ld\n",
            // *(iPort->outCreditQueue()->peekTopFlit()),
            // iPort->outCreditLink()->name(), clockEdge(Cycles(1)));
            iPort->outCreditLink()->scheduleEventAbsolute(clockEdge(Cycles(1)));
        }
    }
    checkReschedule();
}

// Looking for a free output vc
int
NetworkInterface::calculateVC(int vnet)
{
    for (int i = 0; i < m_vc_per_vnet; i++) {
        int delta = m_vc_allocator[vnet];
        m_vc_allocator[vnet]++;
        if (m_vc_allocator[vnet] == m_vc_per_vnet)
            m_vc_allocator[vnet] = 0;

        if (outVcState[(vnet*m_vc_per_vnet) + delta].isInState(
            gem5::ruby::garnet::IDLE_, curTick())) {
            vc_busy_counter[vnet] = 0;
            return ((vnet*m_vc_per_vnet) + delta);
        }
    }

    vc_busy_counter[vnet] += 1;
    panic_if(vc_busy_counter[vnet] > m_deadlock_threshold,
        "%s: Possible network deadlock in vnet: %d at time: %llu \n",
        name(), vnet, curTick());

    return -1;
}

void
NetworkInterface::scheduleOutputPort(NetworkInterface::OutputPort *oPort)
{
   int vc = oPort->vcRoundRobin();

   for (int i = 0; i < niOutVcs.size(); i++) {
       vc++;
       if (vc == niOutVcs.size())
           vc = 0;

       if (niOutVcs[vc].isReady(curTick()) && outVcState[vc].has_credit()) {
               gem5::ruby::garnet::flit<NocMessage, NocRouteInfo> *candidate_flit =
                   niOutVcs[vc].peekTopFlit();
               const auto route = candidate_flit->get_route();
               if (route.src_router >= 0 &&
                   route.src_router != oPort->routerID()) {
                   continue;
               }

           const int prev_vc_rr = oPort->vcRoundRobin();
           const int credit_count = outVcState[vc].get_credit_count();

           // Update the round robin arbiter
           oPort->vcRoundRobin(vc);

           outVcState[vc].decrement_credit();

           // Just removing the top flit
           gem5::ruby::garnet::flit<NocMessage, NocRouteInfo> *t_flit =
               niOutVcs[vc].getTopFlit();
           t_flit->set_time(clockEdge(Cycles(1)));

           if (m_net_ptr) {
               const auto scheduled_route = t_flit->get_route();
               m_net_ptr->traceNpsSwitchArb(
                   "ni_send",
                   oPort->routerID(),
                   name(),
                   Nps_Type::VNOC,
                   oPort->routerID(),
                   -1,
                   vc,
                   prev_vc_rr,
                   credit_count,
                   -1,
                   -1,
                   t_flit->getPacketID(),
                   t_flit->get_id(),
                   scheduled_route.src_ni,
                   scheduled_route.dest_ni,
                   t_flit->get_vnet(),
                   static_cast<int>(t_flit->get_type()),
                   static_cast<int>(t_flit->get_axi_type()));
           }

            //    if (auto strm =
            //            std::dynamic_pointer_cast<NocStreamMsg>(t_flit->get_msg_ptr())) {
            //        const int src_ni = strm->getSourceNiID();
            //        const int net_flit = t_flit->get_id();
            //        std::cout << "[AXIS-DBG] NI(" << name() << ")"
            //                  << " curTick=" << curTick()
            //                  << " stage=SCHEDULE_OUT_LINK"
            //                  << " src_ni=" << src_ni
            //                  << " flit_id(net)=" << net_flit
            //                  << " pkt_id=" << t_flit->getPacketID()
            //                  << " NPPMsg.numFlits=" << (unsigned)strm->getNumFlits()
            //                  << " vc=" << vc
            //                  << " vnet=" << t_flit->get_vnet()
            //                  << " sendTick=" << t_flit->get_time()
            //                  << std::endl;
            //    }

           // Scheduling the flit
           scheduleFlit(t_flit);

           if (t_flit->get_type() ==  gem5::ruby::garnet::TAIL_ ||
              t_flit->get_type() ==  gem5::ruby::garnet::HEAD_TAIL_) {
               m_ni_out_vcs_enqueue_time[vc] = Tick(INFINITE_);
           }

           // Done with this port, continue to schedule
           // other ports
           return;
       }
   }
}

bool
NetworkInterface::injectFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* fl, int vnet, MsgPtr msg_ptr, int vc){
    if (niOutVcs[vc].isFull()) {
        return false;
    }
    nocProbeEvent("ni.flit.inject", fl);
    // save the source and destination network interface ids in the Message
    // so that the endpoint can recover these without flits
    msg_ptr->setSourceNiID(fl->get_src_ni_id());

    // m_net_ptr->increment_injected_flits(vnet);
    fl->set_src_delay(curTick() - msg_ptr->getTime());
    niOutVcs[vc].insert(fl);

    // AXIS flits are produced by the NMU's intermediate dequeue event rather
    // than the normal NI wakeup path. Schedule the output link here so the
    // newly inserted flit actually leaves the NI.
    scheduleOutputLink();

    return true;
}


/** This function looks at the NI buffers
 *  if some buffer has flits which are ready to traverse the link in the next
 *  cycle, and the downstream output vc associated with this flit has buffers
 *  left, the link is scheduled for the next cycle
 */

void
NetworkInterface::scheduleOutputLink()
{
    // Schedule each output link
    for (auto &oPort: outPorts) {
        scheduleOutputPort(oPort);
    }
}

NetworkInterface::InputPort*
NetworkInterface::getInportForVnet(int vnet)
{
    for (auto &iPort : inPorts) {
        if (iPort->isVnetSupported(vnet)) {
            return iPort;
        }
    }

    return nullptr;
}

/*
 * This function returns the outport which supports the given vnet.
 * Currently, HeteroGarnet does not support multiple outports to
 * support same vnet. Thus, this function returns the first-and
 * only outport which supports the vnet.
 */
NetworkInterface::OutputPort *
NetworkInterface::getOutportForVnet(int vnet)
{
    for (auto &oPort : outPorts) {
        if (oPort->isVnetSupported(vnet)) {
            return oPort;
        }
    }

    return nullptr;
}
void
NetworkInterface::scheduleFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo> *t_flit)
{
    nocProbeEvent("ni.flit.to_link", t_flit);
    NetworkInterface::OutputPort *oPort = nullptr;
    const auto route = t_flit->get_route();

    if (route.src_router >= 0) {
        for (auto &cand : outPorts) {
            if (cand->isVnetSupported(t_flit->get_vnet()) &&
                cand->routerID() == route.src_router) {
                oPort = cand;
                break;
            }
        }
    }

    if (!oPort) {
        oPort = getOutportForVnet(t_flit->get_vnet());
    }

    if (oPort) {
        // if (auto strm =
        //         std::dynamic_pointer_cast<NocStreamMsg>(t_flit->get_msg_ptr())) {
        //     const int src_ni = strm->getSourceNiID();
        //     std::cout << "[AXIS-DBG] NI(" << name() << ")"
        //               << " curTick=" << curTick()
        //               << " stage=SCHEDULE_FLIT_ENQUEUE_LINK_SRCQ"
        //               << " src_ni=" << src_ni
        //               << " flit_id(net)=" << t_flit->get_id()
        //               << " pkt_id=" << t_flit->getPacketID()
        //               << " NPPMsg.numFlits=" << (unsigned)strm->getNumFlits()
        //               << " vc=" << t_flit->get_vc()
        //               << " vnet=" << t_flit->get_vnet()
        //               << " link=" << oPort->outNetLink()->name()
        //               << " flitQueueTick=" << t_flit->get_time()
        //               << std::endl;
        // }
        // DPRINTF(RubyNetwork, "Scheduling at %s time:%ld flit:%s Message:%s\n",
        // oPort->outNetLink()->name(), clockEdge(Cycles(1)),
        // *t_flit, *(t_flit->get_msg_ptr()));
        oPort->outFlitQueue()->insert(t_flit);
        oPort->outNetLink()->scheduleEventAbsolute(clockEdge(Cycles(1)));
        return;
    }

    panic("No output port found for vnet:%d\n", t_flit->get_vnet());
    return;
}

int
NetworkInterface::get_vnet(int vc)
{
    for (int i = 0; i < m_virtual_networks; i++) {
        if (vc >= (i*m_vc_per_vnet) && vc < ((i+1)*m_vc_per_vnet)) {
            return i;
        }
    }
    fatal("Could not determine vc");
}


// Wakeup the NI in the next cycle if there are waiting
// messages in the protocol buffer, or waiting flits in the
// output VC buffer.
// Also check if we have to reschedule because of a clock period
// difference.
void
NetworkInterface::checkReschedule()
{
    for (const auto& it : inNode_ptr) {
        if (it == nullptr) {
            continue;
        }

        while (it->isReady(clockEdge())) { // Is there a message waiting
            // printf("NocNI, schedule an NI wakeup \n");
            scheduleEvent(Cycles(1));
            return;
        }
    }

    for (auto& ni_out_vc : niOutVcs) {
        if (ni_out_vc.isReady(clockEdge(Cycles(1)))) {
            scheduleEvent(Cycles(1));
            return;
        }
    }

    // Write flits injected by the NMU carry a future m_time (pipeline delay),
    // so they are never "ready" at clockEdge(Cycles(1)).  Without this check
    // the NI sleeps forever and the flits never enter the network.
    Tick earliest = MaxTick;
    for (auto& ni_out_vc : niOutVcs) {
        if (!ni_out_vc.isEmpty()) {
            earliest = std::min(earliest, ni_out_vc.peekTopFlit()->get_time());
        }
    }
    if (earliest != MaxTick && earliest > curTick()) {
        scheduleEventAbsolute(earliest);
        return;
    }

    if (m_locked_assembler_input_port != -1) {
        scheduleEvent(Cycles(1));
        return;
    }

    for (auto &iPort : inPorts) {
        for (const auto &assembler : iPort->nppAssemblers()) {
            if (!assembler.empty()) {
                scheduleEvent(Cycles(1));
                return;
            }
        }
    }

    // Check if any input links have flits to be popped.
    // This can happen if the links are operating at
    // a higher frequency.
    for (auto &iPort : inPorts) {
        gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *inNetLink = iPort->inNetLink();
        if (inNetLink->isReady(curTick())) {
            scheduleEvent(Cycles(1));
            return;
        }
    }

    for (auto &oPort : outPorts) {
        gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *inCreditLink = oPort->inCreditLink();
        if (inCreditLink->isReady(curTick())) {
            scheduleEvent(Cycles(1));
            return;
        }
    }
}

void
NetworkInterface::print(std::ostream& out) const
{
    out << "[Network Interface]";
}

bool
NetworkInterface::functionalRead(Packet *pkt, gem5::ruby::WriteMask &mask)
{
    bool read = false;
    for (auto& ni_out_vc : niOutVcs) {
        if (ni_out_vc.functionalRead(pkt, mask))
            read = true;
    }

    for (auto &oPort: outPorts) {
        if (oPort->outFlitQueue()->functionalRead(pkt, mask))
            read = true;
    }

    return read;
}

uint32_t
NetworkInterface::functionalWrite(Packet *pkt)
{
    uint32_t num_functional_writes = 0;
    for (auto& ni_out_vc : niOutVcs) {
        num_functional_writes += ni_out_vc.functionalWrite(pkt);
    }

    for (auto &oPort: outPorts) {
        num_functional_writes += oPort->outFlitQueue()->functionalWrite(pkt);
    }
    return num_functional_writes;
}

int
NetworkInterface::MachineType_base_number(const gem5::ruby::MachineType& obj)
{
    return m_net_ptr->getNocSystem()->MachineType_base_number(obj);
}

void
NetworkInterface::nocProbeEvent(const char* hookId)
{
    if (m_nocProbe && m_nocProbe->needsHookEvents()) {
        m_nocProbe->onHookEvent(hookId, name().c_str(), clockPeriod());
    }
}

void
NetworkInterface::nocProbeEvent(const char* hookId,
    gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* fl)
{
    if (m_nocProbe && m_nocProbe->needsHookEvents()) {
        m_nocProbe->onHookEvent(hookId, fl, name().c_str(), clockPeriod());
    }
}

void
NetworkInterface::nocProbeEvent(const char* hookId, const MsgPtr& msg)
{
    if (m_nocProbe && m_nocProbe->needsHookEvents()) {
        m_nocProbe->onHookEvent(hookId, msg, name().c_str(), clockPeriod());
    }
}

} // namespace garnet
} // namespace noc
} // namespace gem5
