#include "noc/core/interface/protocols/AXISHandler.hh"
#include "noc/lib/debug/ProbeTypes.hh"
#include "noc/core/network/NocStreamMsg.hh"

#include "sim/core.hh"
#include "sim/serialize.hh"
#include <memory>
#include <algorithm>
#include <cstring>

namespace gem5 {
namespace noc {

static void
appendU64(std::vector<uint8_t>& out, uint64_t v)
{
    for (int i = 0; i < 8; ++i)
        out.push_back(static_cast<uint8_t>((v >> (i * 8)) & 0xFF));
}

static void
appendU8(std::vector<uint8_t>& out, uint8_t v)
{
    out.push_back(v);
}

static void
fillAxisWriteTrafficFields(const axisData& axiData, MessageParams& params)
{
    params.data = axiData;
    params.beatBytes.clear();
    params.beatBytes.reserve(axiData.getTotalByteSize());
    for (size_t i = 0; i < axiData.tdata.size(); ++i) {
        if (axiData.tkeep & (1ULL << i)) {
            params.beatBytes.push_back(axiData.tdata[i]);
        }
    }
}

static CDCQueue* getCDCQueue(std::vector<ChannelDesc>& channelMap, const std::string& name) {
    for (auto& ch : channelMap) {
        if (ch.name == name) return ch.cdcQueue.get();
    }
    panic("Channel not found: %s", name.c_str());
    return nullptr;
}

AXISHandler::AXISHandler(const std::string& type, const std::vector<uint32_t>& protocol_parameters, Tick clockPeriod) {
    assert( type == "Master" || type == "Slave" );
    role = type;
    write_delay = 0;
    // m_delay = 1;
    nmu = nullptr;
    initChannelMap();
    axisDataWidth = protocol_parameters[0];
    axisIdWidth = protocol_parameters[1];
    axisDestWidth = protocol_parameters[2];
    clock_period = clockPeriod;
    last_enqueue_tick = 0;
}

std::vector<ChannelDesc>
AXISHandler::getChannelMap() {
    return std::vector<ChannelDesc>(channelMap);  // copy so handler keeps its channelMap
}

void
AXISHandler::initChannelMap() {
    if (role == "Master") {
        channelMap = {
            {"W",  garnet::W_VNET,  "request", 0, nullptr, std::make_shared<CDCQueue>(8)}
        };
    } else { // Slave
        channelMap = {
            {"W",  garnet::W_VNET,  "request", 1, nullptr, std::make_shared<CDCQueue>(8)}
        };
    }
}

void
AXISHandler::init() { }

void
AXISHandler::setNMU(garnet::NetworkInterface* ni) {
    nmu = dynamic_cast<garnet::sNocMasterUnit*>(ni);
    if (!nmu)
        panic("AXISHandler::setNMU expected garnet::sNocMasterUnit");
}

void
AXISHandler::setNSU(garnet::NetworkInterface* /*ni*/) {
    // AXIS handler doesn't require NSU-specific behavior.
    // here to satisfy abstract interface.
}

std::unique_ptr<State>
AXISHandler::createNodeInterfaceState() {
    if (role == "Master") {
        auto s = std::make_unique<axisSlaveState>();
        return s;
    } else {
        auto s = std::make_unique<axisMasterState>(axisDataWidth, axisIdWidth, axisDestWidth);
        s->data.tvalid = false;
        return s;
    }
}

std::unique_ptr<State>
AXISHandler::createNodeState() {
    if (role == "Master") {
        auto s = std::make_unique<axisMasterState>(axisDataWidth, axisIdWidth, axisDestWidth);
        s->data.tvalid = false;
        return s;
    } else {
        auto s = std::make_unique<axisSlaveState>();
        return s;
    }
}

bool
AXISHandler::isRequestQueue(std::string channel) {
    return role == "Master"; // only master makes "requests"
}

bool
AXISHandler::isTransactionReady(std::string channel, State* sendingState, State* receivingState) {
    axisMasterState* master = dynamic_cast<axisMasterState*>(sendingState);
    axisSlaveState* slave = dynamic_cast<axisSlaveState*>(receivingState);
    assert(slave && master);
    return slave->tready && master->data.tvalid;
}

std::optional<StreamObservation>
AXISHandler::observeStream(std::string channel, State* sendingState, State* receivingState)
{
    if (channel != "W")
        return std::nullopt;

    auto* master = dynamic_cast<axisMasterState*>(sendingState);
    auto* slave = dynamic_cast<axisSlaveState*>(receivingState);
    if (!master || !slave)
        return std::nullopt;

    const axisData& d = master->data;
    StreamObservation o;
    o.valid = d.tvalid;
    o.ready = slave->tready;
    o.last = d.tlast;
    o.dest = d.tdest;

    // Payload fingerprint for stability checking while stalled.
    // Include all "payload-ish" signals except ready/valid.
    o.payload.reserve(d.tdata.size() + 64);
    o.payload.insert(o.payload.end(), d.tdata.begin(), d.tdata.end());
    appendU64(o.payload, d.tkeep);
    appendU64(o.payload, d.tid);
    appendU64(o.payload, d.tdest);
    appendU8(o.payload, d.tuser);
    appendU8(o.payload, static_cast<uint8_t>(d.tlast ? 1 : 0));

    return o;
}


bool
AXISHandler::cdcEnqueueReady(std::string channel) {
    return !getCDCQueue(channelMap, channel)->isFull();
}

bool
AXISHandler::cdcDequeueReady(std::string channel) {
    return getCDCQueue(channelMap, channel)->canDequeueToNoC(curTick());
}

bool
AXISHandler::cdcDequeueNiReady(
    std::string channel, State* interfaceState)
{
    (void)interfaceState;
    if (role != "Master")
        return true;
    panic_if(channel != "W",
        "AXISHandler::cdcDequeueNiReady: unexpected channel %s", channel.c_str());
    CDCQueue* q = getCDCQueue(channelMap, channel);
    const Tick t = curTick();
    axisMasterState upstream(axisDataWidth, axisIdWidth, axisDestWidth);
    bool upstreamValid = false;
    if (q->canDequeueToNoC(t)) {
        const State* pst = q->peekFrontState(t);
        auto* pm = dynamic_cast<const axisMasterState*>(pst);
        panic_if(!pm,
            "AXISHandler::cdcDequeueNiReady: expected axisMasterState in CDC");
        upstream = *pm;
        upstreamValid = true;
    }
    return nmu->getAxiWReady(upstreamValid, upstream);
}

bool
AXISHandler::channelBufferReady(MessageBuffer* queue) {
    return !queue->isEmpty() && queue->isReady(curTick() + 1);
}

ResponseInfo*
AXISHandler::optionalResponseInfoForCdcEnqueue(
    std::string channel, State* staged, MessageBuffer* queue, ResponseInfo* storage) {
    if (channel != "W" || role != "Slave")
        return nullptr;
    *storage = getResponseInfoFromChannelQueue(staged, channel, queue);
    return storage;
}

bool
AXISHandler::currChannelValid(std::string channel, State* state) {
    axisMasterState* master = dynamic_cast<axisMasterState*>(state);
    return master && master->data.tvalid;
}

void
AXISHandler::updateChannelNextState(
    std::string channel, State* nextState, Tick tick) {
    cdcDequeueToNode(nextState, channel, tick);
}

std::unique_ptr<State>
AXISHandler::cdcDequeueToNoC(std::string channel, Tick tick) {
    return getCDCQueue(channelMap, channel)->dequeue(tick);
}

void
AXISHandler::setChannelNextValidFalse(
    std::string channel, std::unique_ptr<State>& nextState, State* currentState) {
    (void)currentState;
    if (channel != "W")
        return;
    if (auto* m = dynamic_cast<axisMasterState*>(nextState.get()))
        m->data.tvalid = false;
}

void
AXISHandler::copyChannelFromCurrentState(
    std::string channel, State* nextState, const State* currentState)
{
    if (channel != "W") {
        panic("AXISHandler::copyChannelFromCurrentState: unexpected channel %s",
              channel.c_str());
    }
    auto* cur = dynamic_cast<const axisMasterState*>(currentState);
    auto* nex = dynamic_cast<axisMasterState*>(nextState);
    panic_if(!cur || !nex,
        "AXISHandler::copyChannelFromCurrentState: expected axisMasterState");
    nex->data = cur->data;
    nex->setDebugId(cur->getDebugId());
}

void
AXISHandler::cdcDequeueToNode(State* nextState, std::string channel, Tick tick) {
    std::unique_ptr<State> dequeued = getCDCQueue(channelMap, channel)->dequeue(tick);
    if (!dequeued) return;
    if (channel == "W") {
        auto* master = dynamic_cast<axisMasterState*>(nextState);
        auto* from = dynamic_cast<axisMasterState*>(dequeued.get());
        assert(master && from);
        master->data = from->data;
        // Preserve probe tracking across CDC dequeue-to-node "copy".
        // The dequeued State may have a debugId assigned by NocProbe; nextState is
        // a persistent object whose payload fields are overwritten here.
        master->setDebugId(from->getDebugId());
    } else {
        panic("Invalid channel cdcDequeueToNode: %s", channel.c_str());
    }
}

std::optional<ResponseInfo>
AXISHandler::peekResponseInfoFromCdcQueue(std::string channel) {
    return getCDCQueue(channelMap, channel)->peekResponseInfo();
}

void AXISHandler::cdcEnqueue(std::string channel, std::unique_ptr<State> state, ResponseInfo* info) {
    CDCQueue* q = getCDCQueue(channelMap, channel);
    if (info != nullptr) {
        q->enqueue(std::move(state), *info, curTick());
    } else {
        q->enqueue(std::move(state), curTick());
    }
}

State*
AXISHandler::getStateFromChannelQueue(State* state, std::string channel, MessageBuffer* queue) {
    if (channel == "W") {
        axisMasterState* master = dynamic_cast<axisMasterState*>(state);
        assert(master);
        axisData data;

        if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
            const NocStreamMsg* msg = dynamic_cast<const NocStreamMsg*>(queue->peek());
            // Preserve probe tracking across MsgPtr -> State reconstruction.
            // The message traversed the network; carry its debugId into this state.
            if (msg) {
                master->setDebugId(msg->getDebugId());
            }
            MessagePayload reqPayload = msg->getPayload();
            if(axisData* p = std::get_if<axisData>(&reqPayload)) {
                data = *p;
            } else {
                panic("AXISHandler::getNextWriteData: Unsupported payload type");
            }
        } else {
            data.tvalid = false;
        }
        master->data = data;
        return state;
    } else {
        panic("Invalid channel getStateFromChannelQueue: " + channel);
    }
}

ResponseInfo
AXISHandler::getResponseInfoFromChannelQueue(State* state, std::string channel, MessageBuffer* queue) {
    if (channel == "W") {
        ResponseInfo info;
        info.delay = Cycles(0);
        axisData data;
    
        if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
            const NocStreamMsg* msg = dynamic_cast<const NocStreamMsg*>(queue->peek());
            MessagePayload reqPayload = msg->getPayload();
            axisData axi_payload;
    
            if(axisData* p = std::get_if<axisData>(&reqPayload)) {
                axi_payload = *p;
            } else {
                panic("AXISHandler::getNextWriteData: Unsupported payload type");
            }
    
            data = axi_payload;
            info.src = static_cast<uint32_t>(msg->getSourceNiID());
    
            // if interface is currently receiving data and it's a slave node, it is the end of a transaction
            if(role == "Slave") {
                info.dataValid = true;
                info.dataBytes.clear();
                info.dataBytes.reserve(axi_payload.getTotalByteSize());
                // Iterate over full bus width; push only lanes enabled by tkeep
                for (size_t i = 0; i < axi_payload.tdata.size(); ++i) {
                    if (axi_payload.tkeep & (1ULL << i)) {
                        info.dataBytes.push_back(axi_payload.tdata[i]);
                    }
                }
                info.type = ResponseInfo::Type::WRITE;
                info.responseEnd = true;
                info.tlast = axi_payload.tlast;
                info.tdest = axi_payload.tdest;
            }
        } else {
            panic("AXISHandler::getResponseInfoFromChannelQueue: No data available in queue");
        }
    
        return info;
    } else {
        panic("Invalid channel CDC getResponseInfoFromChannelQueue channel: " + channel); // should never reach here
    }
}

MessageParams
AXISHandler::createMessage(std::string channel, State* nodeState, Tick clockEdge, NocSystem* nocSystem) {
    axisMasterState* master = dynamic_cast<axisMasterState*>(nodeState);
    assert(master && "nodeState must be aximmMasterState for W channels");
    MessageParams params = generateWriteDataToNoC(master->data, clockEdge, nocSystem);
    // Preserve probe tracking across the State -> MsgPtr conversion boundary.
    if (params.msg && master->hasDebugId()) {
        params.msg->setDebugId(master->getDebugId());
    }
    return params;
}

void
AXISHandler::fillTrafficMonitorParamsOnNodeCdcEnqueue(
    std::string channel, State* nodeState, MessageParams& out)
{
    if (role != "Master" || channel != "W")
        return;
    auto* master = dynamic_cast<axisMasterState*>(nodeState);
    if (!master || !master->data.tvalid)
        return;
    fillAxisWriteTrafficFields(master->data, out);
}

void
AXISHandler::snapshotNodeStateForToCdcProbe(
    std::string channel, State* nodeState, State* interfaceState)
{
    if (auto* m = dynamic_cast<axisMasterState*>(nodeState)) {
        m->cdc_enqueue_ready = cdcEnqueueReady(channel);
        if (auto* s = dynamic_cast<axisSlaveState*>(interfaceState)) {
            m->ni_tready = s->tready;
        } else {
            m->ni_tready = false;
        }
    }
}

MessageParams
AXISHandler::generateWriteDataToNoC(axisData axiData, Tick clockEdge, NocSystem* nocSystem) {
    auto payload = std::make_unique<MessagePayload>(axiData);
    MsgPtr message = std::shared_ptr<NocMessage>(new NocStreamMsg(clockEdge, nocSystem, std::move(payload)));
    DPRINTF(NocTiming, "%s NodeInterface enqueuing write data to NMU.\n", role);

    int num_flits = (axiData.getTotalByteSize() + 15)/16; // TODO: verify this is the proper num flits if byte sizes change
    uint32_t temp = 8 + (num_flits < 15 ? num_flits-(num_flits+3)/4 : 15 -4);
    uint64_t delta_cycles = 0;
    if (last_enqueue_tick != 0 && clock_period != 0) {
        Tick delta_ticks = clockEdge - last_enqueue_tick;
        delta_cycles = (static_cast<uint64_t>(delta_ticks) + (clock_period - 1)) / clock_period; // ceil div
    }
    write_delay = std::max<uint64_t>(temp, (delta_cycles > 0 ? (delta_cycles - 1) : 0) + write_delay);

    last_enqueue_tick = clockEdge;

    MessageParams params;
    params.msg = message;
    params.delay = 9; // TODO: find proper write delay      // the arrival time of the message, that is, the first cycle the message can be dequeued.

    fillAxisWriteTrafficFields(axiData, params);
    return params;
}

void
AXISHandler::updateBookkeeping(std::string channel, MessageBuffer* queue) { }

void
AXISHandler::tickBookkeeping(std::string channel, bool ready, int beatBytesSize) { 
    if (ready && (channel == "W")) {
        auto* nmuCasted = dynamic_cast<gem5::noc::garnet::sNocMasterUnit*>(nmu);
        if (nmuCasted) {
            nmuCasted->enqueueBytes(beatBytesSize);
        }
    }
}

void
AXISHandler::updateChannelNextReady(State* nextState, std::string channel, State* currentState, State* nodeState) {
    axisSlaveState* castedNextState = dynamic_cast<axisSlaveState*>(nextState);
    axisSlaveState* castedCurrentState = dynamic_cast<axisSlaveState*>(currentState);
    axisMasterState* castedNodeState = dynamic_cast<axisMasterState*>(nodeState);
    assert(castedNextState && "nextState must be axisSlaveState");
    assert(castedCurrentState && "currentState must be axisSlaveState");
    assert(castedNodeState && "nodeState must be axisMasterState");

    castedNextState->tready = cdcEnqueueReady(channel);
}

static void
copyAxisDataPrefix(const axisData& d, std::array<uint8_t, 16>& prefix)
{
    prefix.fill(0);
    const size_t n = std::min(prefix.size(), d.tdata.size());
    for (size_t i = 0; i < n; ++i)
        prefix[i] = d.tdata[i];
}

void
AXISHandler::fillNocIfProbeFromNode(
    State* towardNi, State* towardTile, ProbeData* out)
{
    auto* beat = dynamic_cast<NocInterfaceAxisBeatData*>(out);
    panic_if(!beat, "AXISHandler::fillNocIfProbeFromNode: expected "
                    "NocInterfaceAxisBeatData");

    if (role == "Master") {
        auto* tile_m = dynamic_cast<axisMasterState*>(towardTile);
        auto* ni_s = dynamic_cast<axisSlaveState*>(towardNi);
        panic_if(!tile_m || !ni_s,
            "AXISHandler::fillNocIfProbeFromNode: Master NI expects "
            "axisMasterState tile + axisSlaveState NI");

        axisMasterState snap = *tile_m;
        snapshotNodeStateForToCdcProbe("W", &snap, ni_s);

        beat->tvalid = snap.data.tvalid;
        beat->tready = ni_s->tready;
        beat->tlast = snap.data.tlast;
        beat->tkeep = snap.data.tkeep;
        beat->tid = snap.data.tid;
        beat->tdest = snap.data.tdest;
        beat->tuser = snap.data.tuser;
        copyAxisDataPrefix(snap.data, beat->tdata_prefix);
        beat->ni_tready = snap.ni_tready;
        beat->cdc_enqueue_ready = snap.cdc_enqueue_ready;
        beat->node_input_tready = snap.node_input_tready;
    } else {
        auto* ni_m = dynamic_cast<axisMasterState*>(towardNi);
        auto* tile_s = dynamic_cast<axisSlaveState*>(towardTile);
        panic_if(!ni_m || !tile_s,
            "AXISHandler::fillNocIfProbeFromNode: Slave NI expects "
            "axisMasterState NI + axisSlaveState tile");

        axisMasterState snap = *ni_m;
        snapshotNodeStateForToCdcProbe("W", &snap, tile_s);

        beat->tvalid = snap.data.tvalid;
        beat->tready = tile_s->tready;
        beat->tlast = snap.data.tlast;
        beat->tkeep = snap.data.tkeep;
        beat->tid = snap.data.tid;
        beat->tdest = snap.data.tdest;
        beat->tuser = snap.data.tuser;
        copyAxisDataPrefix(snap.data, beat->tdata_prefix);
        beat->ni_tready = snap.ni_tready;
        beat->cdc_enqueue_ready = snap.cdc_enqueue_ready;
        beat->node_input_tready = snap.node_input_tready;
    }
}

void
AXISHandler::fillNocIfProbeFromCdcPeek(
    Tick t, State* interfaceState, ProbeData* out, bool& valid)
{
    auto* beat = dynamic_cast<NocInterfaceAxisBeatData*>(out);
    panic_if(!beat, "AXISHandler::fillNocIfProbeFromCdcPeek: expected "
                    "NocInterfaceAxisBeatData");

    valid = false;
    beat->tvalid = false;
    beat->tready = false;
    beat->tlast = false;
    beat->tkeep = 0;
    beat->tid = 0;
    beat->tdest = 0;
    beat->tuser = 0;
    beat->tdata_prefix.fill(0);
    beat->ni_tready = false;
    beat->cdc_enqueue_ready = false;
    beat->node_input_tready = false;

    if (role != "Master")
        return;

    CDCQueue* q = getCDCQueue(channelMap, "W");
    if (!q->canDequeueToNoC(t) || !cdcDequeueNiReady("W", interfaceState))
        return;

    const State* pst = q->peekFrontState(t);
    const auto* pm = dynamic_cast<const axisMasterState*>(pst);
    panic_if(!pm,
        "AXISHandler::fillNocIfProbeFromCdcPeek: expected axisMasterState");

    beat->tvalid = pm->data.tvalid;
    beat->tready = false;
    beat->tlast = pm->data.tlast;
    beat->tkeep = pm->data.tkeep;
    beat->tid = pm->data.tid;
    beat->tdest = pm->data.tdest;
    beat->tuser = pm->data.tuser;
    copyAxisDataPrefix(pm->data, beat->tdata_prefix);
    beat->ni_tready = pm->ni_tready;
    beat->cdc_enqueue_ready = pm->cdc_enqueue_ready;
    beat->node_input_tready = pm->node_input_tready;
    valid = true;
}

void
AXISHandler::serializeInterfaceState(CheckpointOut &cp, const State *s) const
{
    panic_if(!s, "AXISHandler::serializeInterfaceState: null State");
    if (auto a = dynamic_cast<const axisSlaveState*>(s)) {
        ::gem5::paramOut(cp, "kind", std::string("axisSlaveState"));
        ::gem5::paramOut(cp, "tready", a->tready);
        return;
    }
    if (auto a = dynamic_cast<const axisMasterState*>(s)) {
        ::gem5::paramOut(cp, "kind", std::string("axisMasterState"));
        Serializable::ScopedCheckpointSection sec(cp, "axisData");
        ::gem5::paramOut(cp, "DATA_WIDTH", a->data.DATA_WIDTH);
        ::gem5::paramOut(cp, "DST_ID_WIDTH", a->data.DST_ID_WIDTH);
        ::gem5::paramOut(cp, "ID_WIDTH", a->data.ID_WIDTH);
        ::gem5::arrayParamOut(cp, "tdata", a->data.tdata);
        ::gem5::paramOut(cp, "tid", a->data.tid);
        ::gem5::paramOut(cp, "tdest", a->data.tdest);
        ::gem5::paramOut(cp, "tkeep", a->data.tkeep);
        ::gem5::paramOut(cp, "tuser", (uint64_t)a->data.tuser);
        ::gem5::paramOut(cp, "tlast", a->data.tlast);
        ::gem5::paramOut(cp, "tvalid", a->data.tvalid);
        ::gem5::paramOut(cp, "ni_tready", a->ni_tready);
        ::gem5::paramOut(cp, "cdc_enqueue_ready", a->cdc_enqueue_ready);
        ::gem5::paramOut(cp, "node_input_tready", a->node_input_tready);
        return;
    }
    panic("AXISHandler::serializeInterfaceState: unsupported State type");
}

std::unique_ptr<State>
AXISHandler::unserializeInterfaceState(CheckpointIn &cp)
{
    std::string kind;
    ::gem5::paramIn(cp, "kind", kind);
    if (kind == "axisSlaveState") {
        auto s = std::make_unique<axisSlaveState>();
        ::gem5::paramIn(cp, "tready", s->tready);
        return s;
    }
    if (kind == "axisMasterState") {
        Serializable::ScopedCheckpointSection sec(cp, "axisData");
        uint32_t w = 512, id = 6, dst = 4;
        ::gem5::paramIn(cp, "DATA_WIDTH", w);
        ::gem5::paramIn(cp, "ID_WIDTH", id);
        ::gem5::paramIn(cp, "DST_ID_WIDTH", dst);
        axisData d(w, id, dst);
        ::gem5::arrayParamIn(cp, "tdata", d.tdata);
        ::gem5::paramIn(cp, "tid", d.tid);
        ::gem5::paramIn(cp, "tdest", d.tdest);
        ::gem5::paramIn(cp, "tkeep", d.tkeep);
        uint64_t tmp = 0;
        ::gem5::paramIn(cp, "tuser", tmp);
        d.tuser = (uint8_t)tmp;
        ::gem5::paramIn(cp, "tlast", d.tlast);
        ::gem5::paramIn(cp, "tvalid", d.tvalid);
        auto s = std::make_unique<axisMasterState>(w, id, dst);
        s->data = std::move(d);
        if (!::gem5::optParamIn(cp, "ni_tready", s->ni_tready, false)) {
            s->ni_tready = false;
        }
        if (!::gem5::optParamIn(cp, "cdc_enqueue_ready", s->cdc_enqueue_ready, false)) {
            s->cdc_enqueue_ready = false;
        }
        if (!::gem5::optParamIn(cp, "node_input_tready", s->node_input_tready, false)) {
            s->node_input_tready = false;
        }
        return s;
    }
    panic("AXISHandler::unserializeInterfaceState: bad kind '%s'", kind);
}

}} // namespace
