#include "noc/core/interface/NocInterface.hh"
#include "noc/core/interface/ProtocolHandler.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "base/cprintf.hh"
#include "noc/debug/NocProbe.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "base/logging.hh"
#include "debug/NocPacketFlow.hh"

#include <cstring>

namespace gem5 {
namespace noc {

NocInterface::NocInterface(const Params &p)
: ClockedObject(p), gem5::ruby::Consumer(this), 
    protocol(p.protocol), role(p.role), endpointName(p.endpoint_name), buffers(p.buffers), protocol_parameters(p.protocol_parameters),
    m_record_mode(p.record_mode),
    m_version(p.version),
    m_id(p.system->getRequestorId(this)), m_is_blocking(false),
    m_noc_system(p.noc_system),
    m_waiting_mem_retry(false),
    m_mem_ctrl_waiting_retry(false),
    m_nocProbe(p.noc_probe)
{
    m_machineID.type = gem5::ruby::MachineType_MiscNode;
    m_machineID.num = m_version;

    p.noc_system->m_num_controllers[gem5::ruby::MachineType_MiscNode]++;
    p.noc_system->registerNocInterface(this/*, std::make_unique<MI_exampleProtocolInfo>()*/);

    protocolHandler = ProtocolHandler::create(protocol, role, clockPeriod(), protocol_parameters);
    channels = protocolHandler->getChannelMap();
}

void
NocInterface::serialize(CheckpointOut &cp) const
{
    SERIALIZE_SCALAR(m_waiting_mem_retry);
    SERIALIZE_SCALAR(m_mem_ctrl_waiting_retry);
    SERIALIZE_SCALAR(m_is_blocking);

    // IMPORTANT: write all scalar keys for this SimObject section before any
    // sub-sections are created (INI checkpoint format does not "return" to the
    // parent section automatically).
    ::gem5::paramOut(cp, "numChannels", (uint64_t)channels.size());

    if (m_netwk_ptr && role == "Master") {
        m_netwk_ptr->getTrafficMonitor().serializeEndpointCheckpoint(cp, m_version);
    }

    // States
    {
        Serializable::ScopedCheckpointSection sec(cp, "currentState");
        protocolHandler->serializeInterfaceState(cp, currentState.get());
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "nextState");
        protocolHandler->serializeInterfaceState(cp, nextState.get());
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "nodeState");
        protocolHandler->serializeInterfaceState(cp, nodeState.get());
    }

    // CDC queues: serialized per-channel name to be robust to ordering.
    for (size_t i = 0; i < channels.size(); i++) {
        const auto &ch = channels[i];
        Serializable::ScopedCheckpointSection sec(cp, csprintf("ch%d", (int)i));
        ::gem5::paramOut(cp, "name", ch.name);
        ::gem5::paramOut(cp, "dir", ch.dir);
        ::gem5::paramOut(cp, "vnet", ch.vnet);
        ::gem5::paramOut(cp, "hasCdc", ch.cdcQueue != nullptr);
        if (ch.cdcQueue) {
            Serializable::ScopedCheckpointSection sec2(cp, "cdc");
            ch.cdcQueue->serialize(cp);
        }
    }
}

void
NocInterface::unserialize(CheckpointIn &cp)
{
    UNSERIALIZE_SCALAR(m_waiting_mem_retry);
    UNSERIALIZE_SCALAR(m_mem_ctrl_waiting_retry);
    UNSERIALIZE_SCALAR(m_is_blocking);

    if (role == "Master") {
        garnet::NocTrafficMonitor::unserializeEndpointCheckpointStash(cp, m_version);
    }

    {
        Serializable::ScopedCheckpointSection sec(cp, "currentState");
        currentState = protocolHandler->unserializeInterfaceState(cp);
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "nextState");
        nextState = protocolHandler->unserializeInterfaceState(cp);
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "nodeState");
        nodeState = protocolHandler->unserializeInterfaceState(cp);
    }

    uint64_t numChannels = 0;
    ::gem5::paramIn(cp, "numChannels", numChannels);
    for (size_t i = 0; i < numChannels && i < channels.size(); i++) {
        auto &ch = channels[i];
        Serializable::ScopedCheckpointSection sec(cp, csprintf("ch%d", (int)i));
        std::string name;
        ::gem5::paramIn(cp, "name", name);
        bool hasCdc = false;
        ::gem5::paramIn(cp, "hasCdc", hasCdc);
        if (hasCdc && ch.cdcQueue) {
            Serializable::ScopedCheckpointSection sec2(cp, "cdc");
            ch.cdcQueue->unserialize(cp);
        }
    }

    // After all NI state is loaded from the checkpoint, apply traffic-monitor
    // stash (AXIS write byte buffer, outstanding writes, etc.). registerNode()
    // already ran in init() above gem5's loadState() order.
    if (role == "Master" && m_netwk_ptr) {
        m_netwk_ptr->getTrafficMonitor().applyDeferredEndpointCheckpoint(m_version);
    }
}

void
NocInterface::wakeup()
{
    // printf("In MTileController::wakeup()\n");
}


void
NocInterface::init()
{
    for (auto &ch : channels) {
        if (ch.dir == 1) ch.queue->setConsumer(this, nullptr);
    }

    currentState = protocolHandler->createNodeInterfaceState();
    nextState = protocolHandler->createNodeInterfaceState();
    nodeState    = protocolHandler->createNodeState();

    // std::cout<<"Initializing NocInterface"<<std::endl;

    for (auto &ch : channels) {
        if(protocolHandler->isRequestQueue(ch.name)) m_consumerNI = ch.queue->getConsumerNI();
    }

    for (auto &ch : channels) {
        if (ch.cdcQueue)
            ch.cdcQueue->setDebugContext(m_version, endpointName, ch.name);
    }

    // commenting this out because AXIS interfaces don't necessarily have one
    // if (!m_consumerNI) {
    //     panic("Cannot grab m_consumerNI!");
    // }

    if (role == "Master") {
        protocolHandler->setNMU(m_consumerNI);
        m_netwk_ptr->getTrafficMonitor().registerNode(m_version, protocol, role, m_record_mode);
        // Deferred traffic-monitor checkpoint is applied at the end of unserialize():
        // gem5 calls init() before loadState()/unserialize(), so the stash is empty
        // during init().
    } else {
        protocolHandler->setNSU(m_consumerNI);
    }

}

void
NocInterface::tick()
{

    for (auto &ch : channels) {
        // Mode 2: per-cycle ready/valid logging (no protocol/role string checks here)
        if (m_record_mode == 2) {
            m_netwk_ptr->getTrafficMonitor().recordReadyValidSignals(
                curTick(), protocol, m_version, role, ch.name, currentState.get(), nodeState.get());
        }
    }

    currentState = nextState->clone();
}

void
NocInterface::nocSideUpdate() {
    for (auto &ch : channels) {

        // enqueue from buffers to CDC queue
        if (ch.dir == 1) {
            if (protocolHandler->cdcEnqueueReady(ch.name) && protocolHandler->channelBufferReady(ch.queue)) {
                protocolHandler->updateBookkeeping(ch.name, ch.queue);
                std::unique_ptr<State> staged = protocolHandler->createNodeInterfaceState();
                protocolHandler->getStateFromChannelQueue(staged.get(), ch.name, ch.queue);
                ResponseInfo info;
                ResponseInfo* info_ptr = protocolHandler->optionalResponseInfoForCdcEnqueue(ch.name, staged.get(), ch.queue, &info);
                nocProbeComparatorEvent("noc_if.net.to_cdc", staged.get());
                protocolHandler->cdcEnqueue(ch.name, std::move(staged), info_ptr);
                ch.queue->dequeue(curTick());
            }
        }

        // dequeue from CDC queue to buffers
        else if (ch.dir == 0) {
            bool transaction = false;
            int beatBytesSize = 0;
            if (protocolHandler->cdcDequeueReady(ch.name) && protocolHandler->cdcDequeueNiReady(ch.name, currentState.get())) {
                std::unique_ptr<State> fromCdc = protocolHandler->cdcDequeueToNoC(ch.name, curTick());
                if (fromCdc) {
                    nocProbeComparatorEvent("noc_if.cdc.to_net", fromCdc.get());
                    MessageParams params = protocolHandler->createMessage(ch.name, fromCdc.get(), clockEdge(), m_noc_system);
                    beatBytesSize = static_cast<int>(params.beatBytes.size());
                    enqueueMessageToBuffer(std::move(params), ch.queue);
                    transaction = true;
                }
            }
            protocolHandler->tickBookkeeping(ch.name, transaction, beatBytesSize);
        }
    }
    nocProbeNocSnooperEvent();
}

void
NocInterface::nodeSideUpdate(State* inputNodeState) {
    nextState = currentState->clone();
    nodeState = inputNodeState->clone();

    for (auto &ch : channels) {

        // dequeue state to node
        if (ch.dir == 1) {
            if (auto obs = protocolHandler->observeStream(ch.name, currentState.get(), inputNodeState)) {
                m_streamCheckers[ch.name].protocolCheck(curTick(), name(), m_version, ch.name, *obs);
            }
            if ( protocolHandler->cdcDequeueReady(ch.name) && ( !protocolHandler->currChannelValid(ch.name, currentState.get()) || protocolHandler->isTransactionReady(ch.name, currentState.get(), inputNodeState))) {
                auto optInfo = protocolHandler->peekResponseInfoFromCdcQueue(ch.name);
                if (optInfo.has_value()) {
                    const ResponseInfo& info = optInfo.value();
                    if (info.dataValid && !info.dataBytes.empty()) {
                        m_netwk_ptr->getTrafficMonitor().checkWriteData(protocol, info.src, info.dataBytes);
                    }
                    if (info.responseEnd) {
                        if (info.type == ResponseInfo::Type::WRITE) { m_netwk_ptr->getTrafficMonitor().recordWriteResponseEnd(protocol, info.src, info.tlast, info.tdest, static_cast<int>(info.dataBytes.size()), m_version, info.id, curTick() + cyclesToTicks(info.delay)); }
                        else if (info.type == ResponseInfo::Type::READ) { m_netwk_ptr->getTrafficMonitor().recordReadResponseEnd(m_version, info.id, curTick() + cyclesToTicks(info.delay)); }
                        else { panic("Unknown traffic monitor end type"); }
                    }
                }
                protocolHandler->updateChannelNextState(ch.name, nextState.get(), curTick());
                if (auto* m = dynamic_cast<axisMasterState*>(nextState.get())) {
                    if (auto* sl = dynamic_cast<axisSlaveState*>(inputNodeState)) {
                        m->node_input_tready = sl->tready;
                    } else {
                        m->node_input_tready = false;
                    }
                }
                nocProbeComparatorEvent("noc_if.cdc.to_node", nextState.get());
            } else if (protocolHandler->isTransactionReady(ch.name, currentState.get(), inputNodeState)) {
                protocolHandler->setChannelNextValidFalse(ch.name, nextState, currentState.get());
            } else {
                protocolHandler->copyChannelFromCurrentState(
                    ch.name, nextState.get(), currentState.get());
            }

                        
            if (ch.queue->isReady(curTick())) {
                 if (ch.name == "B" || ch.name == "R") {
                     DPRINTF(NocPacketFlow, "DEBUG: NocInterface %d update: Channel %s has message ready. cdcDequeueReady=%d\n", m_id, ch.name,
                             (int)protocolHandler->cdcDequeueReady(ch.name));
                 }
            }

        }

        // enqueue state from node to CDC queue
        else if (ch.dir == 0) {
            if (auto obs = protocolHandler->observeStream(ch.name, inputNodeState, currentState.get())) {
                m_streamCheckers[ch.name].protocolCheck(curTick(), name(), m_version, ch.name, *obs);
            }
            protocolHandler->snapshotNodeStateForToCdcProbe(ch.name, inputNodeState, currentState.get());
            if (protocolHandler->cdcEnqueueReady(ch.name) && protocolHandler->isTransactionReady(ch.name, inputNodeState, currentState.get())) {
                MessageParams tm_params;
                protocolHandler->fillTrafficMonitorParamsOnNodeCdcEnqueue(
                    ch.name, inputNodeState, tm_params);
                recordTrafficMonitorForOutgoing(tm_params);
                std::unique_ptr<State> staged = inputNodeState->clone();
                nocProbeComparatorEvent("noc_if.state.to_cdc", staged.get());
                protocolHandler->cdcEnqueue(ch.name, std::move(staged), nullptr);
            }
            protocolHandler->updateChannelNextReady(nextState.get(), ch.name, currentState.get(), inputNodeState);
        }
    }
    nocProbeNodeSnooperEvent(inputNodeState);
}

void
NocInterface::print(std::ostream& out) const
{
    out << "[NocInterface " << m_version << ": " << protocol << " " << role << "]";
}

void NocInterface::initNetQueues() {

    if (buffers.size() != channels.size()) {
        panic("Mismatch: %d buffers vs %d channels in setting up queues", (int)buffers.size(), (int)channels.size());
    }
    
    for (size_t i = 0; i < channels.size(); ++i) {
        auto &ch = channels[i];
        auto *buf = buffers[i];

        if(ch.dir == 0) {
            m_netwk_ptr->setToNetQueue(m_version, true, ch.vnet, ch.vnet_type, buf);
        } else if(ch.dir == 1) {
            m_netwk_ptr->setFromNetQueue(m_version, true, ch.vnet, ch.vnet_type, buf);
        }
        else panic("Unknown channel direction! channel: " + ch.name + " direction: " + std::to_string(ch.dir) + "\n");

        ch.queue = buf;
    }
}


void
NocInterface::recordTrafficMonitorForOutgoing(const MessageParams& params) {
    nocProbeComparatorEvent("noc_if.node.to_cdc", params.msg);
    if (params.data.has_value()) {
        m_netwk_ptr->getTrafficMonitor().recordRequestStart(
            protocol,
            m_version,
            curTick(),
            params.data.value());
    }
    if (!params.beatBytes.empty()) {
        m_netwk_ptr->getTrafficMonitor().logWriteData(
            protocol, m_version, params.beatBytes);
    }
}

void
NocInterface::enqueueMessageToBuffer(MessageParams params, MessageBuffer* queue) {
    queue->enqueue(params.msg, clockEdge(), cyclesToTicks(Cycles(params.delay)),
                   m_noc_system->getRandomization(), false);
}

void
NocInterface::nocProbeEvent(const char* hookId)
{
    if (m_nocProbe && m_nocProbe->needsHookEvents()) {
        m_nocProbe->onHookEvent(hookId, name().c_str(), clockPeriod());
    }
}

void
NocInterface::nocProbeEvent(const char* hookId, State* st)
{
    if (m_nocProbe && m_nocProbe->needsHookEvents()) {
        m_nocProbe->onHookEvent(hookId, st, name().c_str(), clockPeriod());
    }
}

void
NocInterface::nocProbeEvent(const char* hookId, const MsgPtr& msg)
{
    if (m_nocProbe && m_nocProbe->needsHookEvents()) {
        m_nocProbe->onHookEvent(hookId, msg, name().c_str(), clockPeriod());
    }
}

bool
NocInterface::nocProbeSnoopMode() const
{
    return m_nocProbe && m_nocProbe->isEnabled() &&
           m_nocProbe->getProbeMode() == "snooper";
}

bool
NocInterface::nocProbeComparatorMode() const
{
    return m_nocProbe && m_nocProbe->isEnabled() &&
           m_nocProbe->getProbeMode() == "comparator";
}

void
NocInterface::nocProbeComparatorEvent(const char* hookId)
{
    if (!nocProbeComparatorMode())
        return;
    m_nocProbe->onHookEvent(hookId, name().c_str(), clockPeriod());
}

void
NocInterface::nocProbeComparatorEvent(const char* hookId, State* st)
{
    if (!nocProbeComparatorMode())
        return;
    m_nocProbe->onHookEvent(hookId, st, name().c_str(), clockPeriod());
}

void
NocInterface::nocProbeComparatorEvent(const char* hookId, const MsgPtr& msg)
{
    if (!nocProbeComparatorMode())
        return;
    m_nocProbe->onHookEvent(hookId, msg, name().c_str(), clockPeriod());
}

void
NocInterface::nocProbeNodeSnooperEvent(State* inputNodeState)
{
    if (!nocProbeSnoopMode())
        return;
    if (protocol == "AXIS") {
        protocolHandler->fillNocIfProbeFromNode(
            currentState.get(), inputNodeState, &m_axisProbeNode);
        m_nocProbe->onHookEvent(
            "noc_if.state.node_side", &m_axisProbeNode,
            name().c_str(), clockPeriod());
    } else if (protocol == "AXIMM") {
        protocolHandler->fillNocIfProbeFromNode(
            currentState.get(), inputNodeState, &m_aximmProbeNode);
        m_nocProbe->onHookEvent(
            "noc_if.state.node_side", &m_aximmProbeNode,
            name().c_str(), clockPeriod());
    } else {
        panic("NocInterface::nocProbeNodeSnooperEvent: unsupported protocol %s",
              protocol.c_str());
    }
}

void
NocInterface::nocProbeNocSnooperEvent()
{
    if (!nocProbeSnoopMode())
        return;
    bool valid = false;
    if (protocol == "AXIS") {
        protocolHandler->fillNocIfProbeFromCdcPeek(
            curTick(), currentState.get(), &m_axisProbeNoc, valid);
        (void)valid;
        m_nocProbe->onHookEvent(
            "noc_if.state.noc_side", &m_axisProbeNoc,
            name().c_str(), clockPeriod());
    } else if (protocol == "AXIMM") {
        protocolHandler->fillNocIfProbeFromCdcPeek(
            curTick(), currentState.get(), &m_aximmProbeNoc, valid);
        (void)valid;
        m_nocProbe->onHookEvent(
            "noc_if.state.noc_side", &m_aximmProbeNoc,
            name().c_str(), clockPeriod());
    } else {
        panic("NocInterface::nocProbeNocSnooperEvent: unsupported protocol %s",
              protocol.c_str());
    }
}

void
NocInterface::ProtocolChecker::protocolCheck(
    Tick now, const std::string& ifName, gem5::ruby::NodeID ifVersion,
    const std::string& channel, const StreamObservation& cur)
{
    const bool handshake = cur.valid && cur.ready;

    if (hasPrev) {
        const bool prevHandshake = prevValid && prevReady;

        // If valid was asserted and handshake had not happened yet, it must stay high.
        if (prevValid && !prevHandshake) {
            panic_if(!cur.valid,
                     "[%s v%d ch=%s @%llu] Contract violation: valid deasserted before handshake",
                     ifName.c_str(), ifVersion, channel.c_str(),
                     static_cast<unsigned long long>(now));
        }

        // If last was asserted (when defined) and handshake had not happened yet, it must stay high.
        if (prevValid && !prevHandshake && prevLast.has_value() && prevLast.value()) {
            panic_if(!cur.last.has_value() || !cur.last.value(),
                     "[%s v%d ch=%s @%llu] Contract violation: last deasserted before handshake",
                     ifName.c_str(), ifVersion, channel.c_str(),
                     static_cast<unsigned long long>(now));
        }

        // While stalled (valid && !ready), the payload must remain stable.
        if (prevValid && !prevReady && cur.valid && !cur.ready) {
            panic_if(cur.payload != prevPayload,
                     "[%s v%d ch=%s @%llu] Contract violation: payload changed while stalled (valid && !ready)",
                     ifName.c_str(), ifVersion, channel.c_str(),
                     static_cast<unsigned long long>(now));
        }
    }

    // Track packet dest stability when dest/last are defined.
    if (cur.dest.has_value()) {
        if (inPacket && cur.valid) {
            panic_if(cur.dest.value() != packetDest,
                     "[%s v%d ch=%s @%llu] Contract violation: dest changed mid-packet (expected %llu got %llu)",
                     ifName.c_str(), ifVersion, channel.c_str(),
                     static_cast<unsigned long long>(now),
                     static_cast<unsigned long long>(packetDest),
                     static_cast<unsigned long long>(cur.dest.value()));
        }

        if (handshake) {
            if (!inPacket) {
                inPacket = true;
                packetDest = cur.dest.value();
            }

            if (cur.last.has_value() && cur.last.value()) {
                inPacket = false;
            }
        }
    }

    // Update history after checks.
    hasPrev = true;
    prevValid = cur.valid;
    prevReady = cur.ready;
    prevLast = cur.last;
    prevDest = cur.dest;
    prevPayload = cur.payload;
}


}} // namespace
