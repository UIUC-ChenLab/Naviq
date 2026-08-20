#include "noc/core/interface/protocols/AXIMMHandler.hh"
#include "noc/lib/debug/ProbeTypes.hh"

#include <cstring>
#include "noc/core/network/NocMasterUnit.hh"
#include "sim/core.hh"
#include "sim/serialize.hh"

namespace gem5 {
namespace noc {

static CDCQueue* getCDCQueue(std::vector<ChannelDesc>& channelMap, const std::string& name) {
    for (auto& ch : channelMap) {
        if (ch.name == name) return ch.cdcQueue.get();
    }
    panic("Channel not found: %s", name.c_str());
    return nullptr;
}

AXIMMHandler::AXIMMHandler(const std::string& type) {
    assert( type == "Master" || type == "Slave" );
    role = type;
    write_delay = 0;
    nsu_read_base_delay = 1;
    nmu = nullptr;
    nsu = nullptr;
    initChannelMap();
}


void
AXIMMHandler::init() {
}

void
AXIMMHandler::setNMU(garnet::NetworkInterface* ni) {
    nmu = dynamic_cast<garnet::mmNocMasterUnit*>(ni);
    panic_if(!nmu, "AXIMMHandler::setNMU: dynamic_cast to NocMasterUnit failed! 'nmu' is nullptr.");
}

void
AXIMMHandler::setNSU(garnet::NetworkInterface* ni) {
    nsu = dynamic_cast<garnet::mmNocSlaveUnit*>(ni);
    panic_if(!nsu, "AXIMMHandler::setNSU: dynamic_cast to NocSlaveUnit failed! 'nsu' is nullptr.");
}


std::unique_ptr<State>
AXIMMHandler::createNodeInterfaceState() {
    if (role == "Master") {
        auto s = std::make_unique<aximmSlaveState>();
        s->r.valid = false;
        s->b.valid = false;
        return s;
    } else {
        auto s = std::make_unique<aximmMasterState>();
        s->ar.valid = false;
        s->aw.valid = false;
        s->w.valid = false;
        return s;
    }
}

std::unique_ptr<State>
AXIMMHandler::createNodeState() {
    if (role == "Master") {
        auto s = std::make_unique<aximmMasterState>();
        s->ar.valid = false;
        return s;
    } else {
        auto s = std::make_unique<aximmSlaveState>();
        s->r.valid = false;
        s->b.valid = false;
        return s;
    }
}

void
AXIMMHandler::initChannelMap() {
    if (role == "Master") {
        channelMap = {
            {"AR", garnet::AR_VNET, "request", 0, nullptr, std::make_shared<CDCQueue>(8)},
            {"AW", garnet::AW_VNET, "request", 0, nullptr, std::make_shared<CDCQueue>(8)},
            {"R",  garnet::R_VNET,  "response", 1, nullptr, std::make_shared<CDCQueue>(8)},
            {"W",  garnet::W_VNET,  "request", 0, nullptr, std::make_shared<CDCQueue>(8)},
            {"B",  garnet::B_VNET,  "response", 1, nullptr, std::make_shared<CDCQueue>(8)}
        };
    } else { // Slave
        channelMap = {
            {"AR", garnet::AR_VNET, "request", 1, nullptr, std::make_shared<CDCQueue>(8)},
            {"AW", garnet::AW_VNET, "request", 1, nullptr, std::make_shared<CDCQueue>(8)},
            {"R",  garnet::R_VNET,  "response", 0, nullptr, std::make_shared<CDCQueue>(8)},
            {"W",  garnet::W_VNET,  "request", 1, nullptr, std::make_shared<CDCQueue>(8)},
            {"B",  garnet::B_VNET,  "response", 0, nullptr, std::make_shared<CDCQueue>(8)}
        };
    }
}

std::vector<ChannelDesc>
AXIMMHandler::getChannelMap() {
    return std::vector<ChannelDesc>(channelMap);  // copy so handler keeps its channelMap
}

bool
AXIMMHandler::isRequestQueue(std::string channel) {
    return (role == "Master" && (channel == "AR")) || (role == "Slave" && (channel == "R"));
}

bool AXIMMHandler::isTransactionReady(std::string channel, State* sendingState, State* receivingState) {
    switch (channel[0]) { // quick switch on first letter
        case 'R': { // R channel
            aximmSlaveState* slave = dynamic_cast<aximmSlaveState*>(sendingState);
            aximmMasterState* master = dynamic_cast<aximmMasterState*>(receivingState);
            assert(slave && master);
            return slave->r.valid && master->rReady; //TODO ready should not allways be true, need backpressure
        }
        case 'B': { // B channel
            aximmSlaveState* slave = dynamic_cast<aximmSlaveState*>(sendingState);
            aximmMasterState* master = dynamic_cast<aximmMasterState*>(receivingState);
            assert(slave && master);
            return slave->b.valid && master->bReady;
        }
        case 'A': { // AR/AW
            aximmMasterState* master = dynamic_cast<aximmMasterState*>(sendingState);
            aximmSlaveState* slave = dynamic_cast<aximmSlaveState*>(receivingState);
            assert(master && slave);
            if (channel == "AR") return master->ar.valid && slave->arReady;
            else return master->aw.valid && slave->awReady;
        }
        case 'W': { // W channel
            aximmMasterState* master = dynamic_cast<aximmMasterState*>(sendingState);
            aximmSlaveState* slave = dynamic_cast<aximmSlaveState*>(receivingState);
            assert(master && slave);
            return master->w.valid && slave->wReady;
        }
        default:
            panic("Invalid channel transaction check: " + channel);
    }
}

bool AXIMMHandler::cdcEnqueueReady(std::string channel) {
    return !getCDCQueue(channelMap, channel)->isFull();
}

bool AXIMMHandler::cdcDequeueReady(std::string channel) {
    return getCDCQueue(channelMap, channel)->canDequeueToNoC(curTick());
}

bool
AXIMMHandler::cdcDequeueNiReady(
    std::string channel, State* interfaceState)
{
    if (role == "Master") {
        CDCQueue* q = getCDCQueue(channelMap, channel);
        const Tick t = curTick();
        aximmMasterState upstream{};
        bool upstreamValid = false;
        if (q->canDequeueToNoC(t)) {
            const State* pst = q->peekFrontState(t);
            auto* pm = dynamic_cast<const aximmMasterState*>(pst);
            panic_if(!pm,
                "AXIMMHandler::cdcDequeueNiReady: expected aximmMasterState in CDC "
                "for channel %s",
                channel.c_str());
            upstream = *pm;
            upstreamValid = true;
        }
        if (channel == "AR")
            return nmu->getAxiRAddrReady(upstreamValid, upstream);
        if (channel == "AW")
            return nmu->getAxiWAddrReady(upstreamValid, upstream);
        if (channel == "W")
            return nmu->getAxiWReady(upstreamValid, upstream);
        panic("AXIMMHandler::cdcDequeueNiReady: unexpected channel %s",
            channel.c_str());
    } else {
        CDCQueue* q = getCDCQueue(channelMap, channel);
        const Tick t = curTick();
        aximmSlaveState upstream{};
        bool upstreamValid = false;
        if (q->canDequeueToNoC(t)) {
            const State* pst = q->peekFrontState(t);
            auto* ps = dynamic_cast<const aximmSlaveState*>(pst);
            panic_if(!ps,
                "AXIMMHandler::cdcDequeueNiReady: expected aximmSlaveState in CDC "
                "for channel %s",
                channel.c_str());
            upstream = *ps;
            upstreamValid = true;
        }
        panic_if(!dynamic_cast<aximmMasterState*>(interfaceState),
            "AXIMM Slave NI: expected aximmMasterState interface state");
        if (channel == "R")
            return nsu->getAxiRReady(upstreamValid);
        if (channel == "B")
            return nsu->getAxiBReady(upstreamValid, upstream);
        panic("AXIMMHandler::cdcDequeueNiReady: unexpected channel %s",
            channel.c_str());
    }
}

bool
AXIMMHandler::channelBufferReady(MessageBuffer* queue) {
    return !queue->isEmpty() && queue->isReady(curTick() + 1);
}

ResponseInfo*
AXIMMHandler::optionalResponseInfoForCdcEnqueue(
    std::string channel, State* staged, MessageBuffer* queue, ResponseInfo* storage) {
    if (channel != "R" && channel != "B")
        return nullptr;
    *storage = getResponseInfoFromChannelQueue(staged, channel, queue);
    return storage;
}

bool
AXIMMHandler::currChannelValid(std::string channel, State* state) {
    switch (channel[0]) {
        case 'R': {
            aximmSlaveState* slave = dynamic_cast<aximmSlaveState*>(state);
            return slave && slave->r.valid;
        }
        case 'B': {
            aximmSlaveState* slave = dynamic_cast<aximmSlaveState*>(state);
            return slave && slave->b.valid;
        }
        case 'A': {
            aximmMasterState* master = dynamic_cast<aximmMasterState*>(state);
            if (!master) return false;
            return (channel == "AR") ? master->ar.valid : master->aw.valid;
        }
        case 'W': {
            aximmMasterState* master = dynamic_cast<aximmMasterState*>(state);
            return master && master->w.valid;
        }
        default:
            return false;
    }
}

void
AXIMMHandler::updateChannelNextState(
    std::string channel, State* nextState, Tick tick) {
    cdcDequeueToNode(nextState, channel, tick);
}

void
AXIMMHandler::setChannelNextValidFalse(
    std::string channel, std::unique_ptr<State>& nextState, State* currentState) {
    (void)currentState;
    switch (channel[0]) {
        case 'R': {
            if (auto* s = dynamic_cast<aximmSlaveState*>(nextState.get()))
                s->r.valid = false;
            break;
        }
        case 'B': {
            if (auto* s = dynamic_cast<aximmSlaveState*>(nextState.get()))
                s->b.valid = false;
            break;
        }
        case 'A': {
            if (auto* m = dynamic_cast<aximmMasterState*>(nextState.get())) {
                if (channel == "AR")
                    m->ar.valid = false;
                else
                    m->aw.valid = false;
            }
            break;
        }
        case 'W': {
            if (auto* m = dynamic_cast<aximmMasterState*>(nextState.get()))
                m->w.valid = false;
            break;
        }
        default:
            break;
    }
}

void
AXIMMHandler::copyChannelFromCurrentState(
    std::string channel, State* nextState, const State* currentState)
{
    auto* curM = dynamic_cast<const aximmMasterState*>(currentState);
    auto* nexM = dynamic_cast<aximmMasterState*>(nextState);
    auto* curS = dynamic_cast<const aximmSlaveState*>(currentState);
    auto* nexS = dynamic_cast<aximmSlaveState*>(nextState);

    if (curM && nexM) {
        if (channel == "AR") {
            nexM->ar = curM->ar;
        } else if (channel == "AW") {
            nexM->aw = curM->aw;
        } else if (channel == "W") {
            nexM->w = curM->w;
        } else {
            panic("AXIMMHandler::copyChannelFromCurrentState: unknown master "
                  "channel %s",
                channel.c_str());
        }
        return;
    }
    if (curS && nexS) {
        if (channel == "R") {
            nexS->r = curS->r;
        } else if (channel == "B") {
            nexS->b = curS->b;
        } else {
            panic("AXIMMHandler::copyChannelFromCurrentState: unknown slave "
                  "channel %s",
                channel.c_str());
        }
        return;
    }
    panic("AXIMMHandler::copyChannelFromCurrentState: state type mismatch");
}

std::unique_ptr<State>
AXIMMHandler::cdcDequeueToNoC(std::string channel, Tick tick) {
    return getCDCQueue(channelMap, channel)->dequeue(tick);
}

void
AXIMMHandler::cdcDequeueToNode(State* nextState, std::string channel, Tick tick) {
    std::unique_ptr<State> dequeued = getCDCQueue(channelMap, channel)->dequeue(tick);
    if (!dequeued) return;
    switch (channel[0]) {
        case 'R': {
            auto* slave = dynamic_cast<aximmSlaveState*>(nextState);
            auto* from = dynamic_cast<aximmSlaveState*>(dequeued.get());
            assert(slave && from);
            slave->r = from->r;
            // Preserve probe tracking across CDC dequeue-to-node "copy".
            slave->setDebugId(from->getDebugId());
            break;
        }
        case 'B': {
            auto* slave = dynamic_cast<aximmSlaveState*>(nextState);
            auto* from = dynamic_cast<aximmSlaveState*>(dequeued.get());
            assert(slave && from);
            slave->b = from->b;
            slave->setDebugId(from->getDebugId());
            break;
        }
        case 'A': {
            auto* master = dynamic_cast<aximmMasterState*>(nextState);
            auto* from = dynamic_cast<aximmMasterState*>(dequeued.get());
            assert(master && from);
            if (channel == "AR") master->ar = from->ar;
            else master->aw = from->aw;
            master->setDebugId(from->getDebugId());
            break;
        }
        case 'W': {
            auto* master = dynamic_cast<aximmMasterState*>(nextState);
            auto* from = dynamic_cast<aximmMasterState*>(dequeued.get());
            assert(master && from);
            master->w = from->w;
            master->setDebugId(from->getDebugId());
            break;
        }
        default:
            panic("Invalid channel cdcDequeueToNode: %s", channel.c_str());
    }
}

std::optional<ResponseInfo>
AXIMMHandler::peekResponseInfoFromCdcQueue(std::string channel) {
    return getCDCQueue(channelMap, channel)->peekResponseInfo();
}

void AXIMMHandler::cdcEnqueue(std::string channel, std::unique_ptr<State> state, ResponseInfo* info) {
    CDCQueue* q = getCDCQueue(channelMap, channel);
    if (info != nullptr) {
        q->enqueue(std::move(state), *info, curTick());
    } else {
        q->enqueue(std::move(state), curTick());
    }
}

State* AXIMMHandler::getStateFromChannelQueue(State* state, std::string channel, MessageBuffer* queue) {
    switch (channel[0]) { // quick switch on first letter
        case 'R': { // R channel - aximmSlaveState has r
            aximmSlaveState* slave = dynamic_cast<aximmSlaveState*>(state);
            assert(slave);
            aximmRWData resp;
            if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
                const NocMemoryMsg* msg = dynamic_cast<const NocMemoryMsg*>(queue->peek());
                if (msg) {
                    slave->setDebugId(msg->getDebugId());
                }
                Payload temp = msg->getData();
                if (auto p = std::get_if<aximmPayload>(&temp)) {
                    resp = (*p)[0]; // just holds a single read resp beat at index 0
                } else {
                    panic("AXIMMHandler::getNextReadResponse: Expected aximmPayload in Payload variant");
                }
            }
            else resp.valid = false;
            slave->r = resp;
            break;
        }
        case 'B': { // B channel - aximmSlaveState has b
            aximmSlaveState* slave = dynamic_cast<aximmSlaveState*>(state);
            assert(slave);
            aximmWResp resp;
            if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
                const NocMemoryMsg* msg = dynamic_cast<const NocMemoryMsg*>(queue->peek());
                if (msg) {
                    slave->setDebugId(msg->getDebugId());
                }
                MessagePayload respPayload = msg->getPayload();
                if(aximmWResp* p = std::get_if<aximmWResp>(&respPayload))
                    resp = *p;
                else
                    panic("NodeInterface::getNextWriteResponse unsupported payload type");
            } else resp.valid = false;
            slave->b = resp;
            break;
        }
        case 'A': { // AR/AW - aximmMasterState has ar, aw
            aximmMasterState* master = dynamic_cast<aximmMasterState*>(state);
            assert(master);
            aximmRWAddr req;
            if (channel == "AR") {
                if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
                    const NocMemoryMsg* msg = dynamic_cast<const NocMemoryMsg*>(queue->peek());
                    if (msg) {
                        master->setDebugId(msg->getDebugId());
                    }
                    MessagePayload reqPayload = msg->getPayload();
                    if(aximmRWAddr* p = std::get_if<aximmRWAddr>(&reqPayload)) {
                        req = *p;
                    } else {
                        panic("AXIMMHandler::getNextReadRequest: Unsupported payload type");
                    }
                } else req.valid = false;
                master->ar = req;
                if (req.valid)
                    readBeatSize[req.id] = req.size;
            }
            else {
                if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
                    const NocMemoryMsg* msg = dynamic_cast<const NocMemoryMsg*>(queue->peek());
                    if (msg) {
                        master->setDebugId(msg->getDebugId());
                    }
                    MessagePayload reqPayload = msg->getPayload();
                    if(aximmRWAddr* p = std::get_if<aximmRWAddr>(&reqPayload)) {
                        req = *p;
                    } else {
                        panic("AXIMMHandler::getNextWriteRequest: Unsupported payload type");
                    }
                } else req.valid = false;
                master->aw = req;
            }
            break;
        }
        case 'W': { // W channel - aximmMasterState has w
            aximmMasterState* master = dynamic_cast<aximmMasterState*>(state);
            assert(master);
            aximmRWData data;
            if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
                const NocMemoryMsg* msg = dynamic_cast<const NocMemoryMsg*>(queue->peek());
                if (msg) {
                    master->setDebugId(msg->getDebugId());
                }
                MessagePayload reqPayload = msg->getPayload();
                if(aximmRWData* p = std::get_if<aximmRWData>(&reqPayload)) {
                    data = *p;
                } else {
                    panic("AXIMMHandler::getNextWriteData: Unsupported payload type");
                }
            } else {
                data.valid = false;
            }
            master->w = data;
            break;
        }
        default:
            panic("Invalid channel getStateFromChannelQueue: " + channel);
    }
    return state;
}

ResponseInfo AXIMMHandler::getResponseInfoFromChannelQueue(State* state, std::string channel, MessageBuffer* queue) {
    if (channel == "R") {

        ResponseInfo info;
        aximmRWData resp;

        //if response buffer not empty and the head will be ready next cycle, get the next response
        if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
            // peek at the top of the response buffer for the next message
            const NocMemoryMsg* msg = dynamic_cast<const NocMemoryMsg*>(queue->peek());
            Payload temp = msg->getData();
            if (auto p = std::get_if<aximmPayload>(&temp)) {
                resp = (*p)[0]; // just holds a single read resp beat at index 0
            } else {
                panic("AXIMMHandler::getNextReadResponse: Expected aximmPayload in Payload variant");
            }
            if (resp.last) {
                DPRINTF(NocTiming, "%s NodeInterface finished sending out read data\n", role);
                info.responseEnd = true;
                info.id = resp.id;
                info.type = ResponseInfo::Type::READ;
                info.delay = Cycles(1);
            }
        } else {
            panic("AXIMMHandler::getResponseInfoFromChannelQueue: No data available in queue");
        }
        return info;
    } else if (channel == "B") {

        ResponseInfo info;
        aximmWResp resp;

        //if response buffer not empty and the head will be ready next cycle, get the next response
        if (!queue->isEmpty() && queue->isReady(curTick() + 1)){
            // peek at the top of the response buffer for the next message
            const NocMemoryMsg* msg = dynamic_cast<const NocMemoryMsg*>(queue->peek());
            MessagePayload respPayload = msg->getPayload();

            if(aximmWResp* p = std::get_if<aximmWResp>(&respPayload))
                resp = *p;
            else
                panic("NodeInterface::getNextWriteResponse unsupported payload type");
            info.responseEnd = true;
            info.id = resp.id;
            info.type = ResponseInfo::Type::WRITE;
            info.delay = Cycles(0);
        } else {
            panic("AXIMMHandler::getResponseInfoFromChannelQueue: No data available in queue");
        }
        return info;
    }
    panic("Invalid channel getResponseInfoFromChannelQueue: %s", channel.c_str());
    return ResponseInfo{};  // unreachable
}

void
AXIMMHandler::fillTrafficMonitorParamsOnNodeCdcEnqueue(
    std::string channel, State* nodeState, MessageParams& out)
{
    if (role != "Master")
        return;
    auto* master = dynamic_cast<aximmMasterState*>(nodeState);
    if (!master)
        return;
    if (channel == "AR" && master->ar.valid)
        out.data = master->ar;
    else if (channel == "AW" && master->aw.valid)
        out.data = master->aw;
}

void
AXIMMHandler::snapshotNodeStateForToCdcProbe(
    std::string channel, State* nodeState, State* interfaceState)
{
    if (auto* m = dynamic_cast<aximmMasterState*>(nodeState)) {
        m->cdc_enqueue_ready = cdcEnqueueReady(channel);
    }
    (void)interfaceState;
}

MessageParams
AXIMMHandler::createMessage(std::string channel, State* nodeState, Tick clockEdge, NocSystem* nocSystem) {
    this->checkTickAssertions(channel);

    const auto inheritMsgDebugId = [&](MessageParams& p) {
        if (!p.msg || !nodeState) return;
        if (nodeState->hasDebugId()) {
            p.msg->setDebugId(nodeState->getDebugId());
        }
    };

    switch (channel[0]) {
        case 'R': {
            auto* slave = dynamic_cast<aximmSlaveState*>(nodeState);
            assert(slave && "nodeState must be aximmSlaveState for R channels");
            auto p = generateReadRespToNoC(slave->r, clockEdge, nocSystem);
            inheritMsgDebugId(p);
            return p;
        }
        case 'B': {
            auto* slave = dynamic_cast<aximmSlaveState*>(nodeState);
            assert(slave && "nodeState must be aximmSlaveState for B channels");
            auto p = generateWriteRespToNoC(slave->b, clockEdge, nocSystem);
            inheritMsgDebugId(p);
            return p;
        }
        case 'A': {
            auto* master = dynamic_cast<aximmMasterState*>(nodeState);
            assert(master && "nodeState must be aximmMasterState for AR/AW channels");
            if (channel == "AR") {
                auto p = generateReadAddrToNoC(master->ar, clockEdge, nocSystem);
                inheritMsgDebugId(p);
                return p;
            } else {
                auto p = generateWriteAddrToNoC(master->aw, clockEdge, nocSystem);
                inheritMsgDebugId(p);
                return p;
            }
        }
        case 'W': {
            auto* master = dynamic_cast<aximmMasterState*>(nodeState);
            assert(master && "nodeState must be aximmMasterState for W channels");
            auto p = generateWriteDataToNoC(master->w, clockEdge, nocSystem);
            inheritMsgDebugId(p);
            return p;
        }
        default:
            panic("Invalid channel message generation: " + channel);
    }

    // should never reach here
    return MessageParams{};
}

void
AXIMMHandler::checkTickAssertions(std::string channel) {
    if (role == "Master")       assert( channel == "AR" ||
                                        channel == "AW" ||
                                        channel == "W");
    else if (role == "Slave")   assert( channel == "R" ||
                                        channel == "B");
}

MessageParams
AXIMMHandler::generateReadAddrToNoC(aximmRWAddr axiReq, Tick clockEdge, NocSystem* nocSystem){
    MsgPtr message = std::shared_ptr<NocMessage>(new NocMemoryMsg(clockEdge, nocSystem, AxiMsgSizeType::AR, axiReq));
    DPRINTF(NocTiming, "%s NodeInterface enqueuing read request to NMU.\n", role);

    MessageParams params;
    params.delay = 5;
    params.msg = message;
    params.data = axiReq;

    return params;
}

MessageParams
AXIMMHandler::generateWriteAddrToNoC(aximmRWAddr axiReq, Tick clockEdge, NocSystem* nocSystem){
    MsgPtr message = std::shared_ptr<NocMessage>(new NocMemoryMsg(clockEdge, nocSystem, AxiMsgSizeType::AW, axiReq));
    DPRINTF(NocTiming, "%s NodeInterface enqueuing write request to NMU.\n", role);

    // Write delay is handled by mmNocMasterUnit::bufferHeadReadyHandler
    MessageParams params;
    params.msg = message;
    params.delay = 0;
    params.data = axiReq;
    return params;
}

MessageParams
AXIMMHandler::generateWriteDataToNoC(aximmRWData axiData, Tick clockEdge, NocSystem* nocSystem){
    MsgPtr message = std::shared_ptr<NocMessage>(new NocMemoryMsg(clockEdge, nocSystem, AxiMsgSizeType::W, axiData));
    DPRINTF(NocTiming, "%s NodeInterface enqueuing write data to NMU.\n", role);

    MessageParams params;
    params.msg = message;
    params.delay = 0;
    return params;
}

MessageParams
AXIMMHandler::generateReadRespToNoC(aximmRWData axiData, Tick clockEdge, NocSystem* nocSystem){
    
    MsgPtr message = std::make_shared<NocMemoryMsg>(clockEdge, nocSystem, AxiMsgSizeType::R, axiData);

    DPRINTF(NocTiming,"%s NodeInterface enqueuing a read response beat to NSU, delay = %d\n",role, nsu_read_base_delay);

    MessageParams params;
    params.msg = message;
    params.delay = nsu_read_base_delay;

    return params;
}


MessageParams
AXIMMHandler::generateWriteRespToNoC(aximmWResp resp, Tick clockEdge, NocSystem* nocSystem){
    MsgPtr message = std::shared_ptr<NocMessage>(new NocMemoryMsg(clockEdge, nocSystem, AxiMsgSizeType::B, resp));
    DPRINTF(NocTiming, "%s NodeInterface enqueuing a write response to NSU.\n", role);

    MessageParams params;
    params.msg = message;
    params.delay = 0;
    return params;
}


void
AXIMMHandler::updateBookkeeping(std::string channel, MessageBuffer* queue) {
    // Leave bookkeeping to the NMU implementation for now (no direct calls here)
    if(channel == "R")
        nmu->msgReadCallback(queue->peek());
}

void
AXIMMHandler::tickBookkeeping(std::string channel, bool ready, int beatBytesSize) {
    // Read response delay is now constant (nsu_read_base_delay = 1).
    // Flit-level gaps are handled in mmNocSlaveUnit::flitisizeReadResponse().
}


void
AXIMMHandler::updateChannelNextReady(State* nextState, std::string channel, State* currentState, State* nodeState) {
    switch (channel[0]) {
        case 'R': {
            aximmMasterState* castedNextState = dynamic_cast<aximmMasterState*>(nextState);
            aximmMasterState* castedCurrentState = dynamic_cast<aximmMasterState*>(currentState);
            aximmSlaveState* castedNodeState = dynamic_cast<aximmSlaveState*>(nodeState);
            assert(castedNextState && "nextState must be aximmMasterState for R channels");
            assert(castedCurrentState && "currentState must be aximmMasterState for R channels");
            assert(castedNodeState && "nodeState must be aximmSlaveState for R channels");

            castedNextState->rReady = cdcEnqueueReady(channel);
            break;
        }
        case 'B': {
            aximmMasterState* castedNextState = dynamic_cast<aximmMasterState*>(nextState);
            aximmMasterState* castedCurrentState = dynamic_cast<aximmMasterState*>(currentState);
            aximmSlaveState* castedNodeState = dynamic_cast<aximmSlaveState*>(nodeState);
            assert(castedNextState && "nextState must be aximmMasterState for R channels");
            assert(castedCurrentState && "currentState must be aximmMasterState for R channels");
            assert(castedNodeState && "nodeState must be aximmSlaveState for R channels");

            castedNextState->bReady = cdcEnqueueReady(channel);
            break;
        }
        case 'A': {
            aximmSlaveState* castedNextState = dynamic_cast<aximmSlaveState*>(nextState);
            aximmSlaveState* castedCurrentState = dynamic_cast<aximmSlaveState*>(currentState);
            aximmMasterState* castedNodeState = dynamic_cast<aximmMasterState*>(nodeState);
            assert(castedNextState && "nextState must be aximmSlaveState for AR/AW channels");
            assert(castedCurrentState && "currentState must be aximmSlaveState for AR/AW channels");
            assert(castedNodeState && "nodeState must be aximmMasterState for AR/AW channels");
            if (channel == "AR") {
                castedNextState->arReady = cdcEnqueueReady(channel);
            } else {
                castedNextState->awReady = cdcEnqueueReady(channel);
            }
            break;
        }
        case 'W': {
            aximmSlaveState* castedNextState = dynamic_cast<aximmSlaveState*>(nextState);
            aximmSlaveState* castedCurrentState = dynamic_cast<aximmSlaveState*>(currentState);
            aximmMasterState* castedNodeState = dynamic_cast<aximmMasterState*>(nodeState);
            assert(castedNextState && "nextState must be aximmSlaveState for R channels");
            assert(castedCurrentState && "currentState must be aximmSlaveState for R channels");
            assert(castedNodeState && "nodeState must be aximmMasterState for R channels");

            castedNextState->wReady = cdcEnqueueReady(channel);
            break;
        }
        default:
            panic("Invalid channel message generation: " + channel);
    }
}

void
AXIMMHandler::serializeInterfaceState(CheckpointOut &cp, const State *s) const
{
    panic_if(!s, "AXIMMHandler::serializeInterfaceState: null State");
    if (auto a = dynamic_cast<const aximmSlaveState*>(s)) {
        ::gem5::paramOut(cp, "kind", std::string("aximmSlaveState"));
        ::gem5::paramOut(cp, "arReady", a->arReady);
        ::gem5::paramOut(cp, "awReady", a->awReady);
        ::gem5::paramOut(cp, "wReady", a->wReady);
        ::gem5::paramOut(cp, "bReady", true);
        {
            Serializable::ScopedCheckpointSection sec1(cp, "r");
            ::gem5::paramOut(cp, "cmd", (int)a->r.cmd);
            ::gem5::paramOut(cp, "id", a->r.id);
            ::gem5::paramOut(cp, "resp", (int)a->r.resp);
            ::gem5::paramOut(cp, "last", a->r.last);
            ::gem5::paramOut(cp, "user", (uint64_t)a->r.user);
            ::gem5::paramOut(cp, "valid", a->r.valid);
            ::gem5::paramOut(cp, "ready", a->r.ready);
            ::gem5::arrayParamOut(cp, "data", a->r.data.data(), a->r.data.size());
            ::gem5::paramOut(cp, "wstrb", a->r.wstrb);
        }
        {
            Serializable::ScopedCheckpointSection sec2(cp, "b");
            ::gem5::paramOut(cp, "id", a->b.id);
            ::gem5::paramOut(cp, "resp", (int)a->b.resp);
            ::gem5::paramOut(cp, "user", (uint64_t)a->b.user);
            ::gem5::paramOut(cp, "valid", a->b.valid);
        }
        return;
    }
    if (auto a = dynamic_cast<const aximmMasterState*>(s)) {
        ::gem5::paramOut(cp, "kind", std::string("aximmMasterState"));
        ::gem5::paramOut(cp, "rReady", a->rReady);
        ::gem5::paramOut(cp, "bReady", a->bReady);
        ::gem5::paramOut(cp, "cdc_enqueue_ready", a->cdc_enqueue_ready);
        auto serAddr = [&](const char *sec_name, const aximmRWAddr &addr) {
            Serializable::ScopedCheckpointSection sec(cp, sec_name);
            ::gem5::paramOut(cp, "cmd", (int)addr.cmd);
            ::gem5::paramOut(cp, "id", addr.id);
            ::gem5::paramOut(cp, "addr", addr.addr);
            ::gem5::paramOut(cp, "len", (uint64_t)addr.len);
            ::gem5::paramOut(cp, "size", (uint64_t)addr.size);
            ::gem5::paramOut(cp, "burst", (int)addr.burst);
            ::gem5::paramOut(cp, "lock", addr.lock);
            ::gem5::paramOut(cp, "cache", (uint64_t)addr.cache);
            ::gem5::paramOut(cp, "prot", (uint64_t)addr.prot);
            ::gem5::paramOut(cp, "qos", (uint64_t)addr.qos);
            ::gem5::paramOut(cp, "region", (uint64_t)addr.region);
            ::gem5::paramOut(cp, "user", (uint64_t)addr.user);
            ::gem5::paramOut(cp, "valid", addr.valid);
        };
        serAddr("ar", a->ar);
        serAddr("aw", a->aw);
        Serializable::ScopedCheckpointSection sec3(cp, "w");
        ::gem5::paramOut(cp, "cmd", (int)a->w.cmd);
        ::gem5::paramOut(cp, "id", a->w.id);
        ::gem5::paramOut(cp, "resp", (int)a->w.resp);
        ::gem5::paramOut(cp, "last", a->w.last);
        ::gem5::paramOut(cp, "user", (uint64_t)a->w.user);
        ::gem5::paramOut(cp, "valid", a->w.valid);
        ::gem5::paramOut(cp, "ready", a->w.ready);
        ::gem5::arrayParamOut(cp, "data", a->w.data.data(), a->w.data.size());
        ::gem5::paramOut(cp, "wstrb", a->w.wstrb);
        return;
    }
    panic("AXIMMHandler::serializeInterfaceState: unsupported State type");
}

std::unique_ptr<State>
AXIMMHandler::unserializeInterfaceState(CheckpointIn &cp)
{
    std::string kind;
    ::gem5::paramIn(cp, "kind", kind);
    if (kind == "aximmSlaveState") {
        auto s = std::make_unique<aximmSlaveState>();
        ::gem5::paramIn(cp, "arReady", s->arReady);
        ::gem5::paramIn(cp, "awReady", s->awReady);
        ::gem5::paramIn(cp, "wReady", s->wReady);
        {
            Serializable::ScopedCheckpointSection sec1(cp, "r");
            int cmd = 0, resp = 0;
            ::gem5::paramIn(cp, "cmd", cmd);
            s->r.cmd = (AximmCommand)cmd;
            ::gem5::paramIn(cp, "id", s->r.id);
            ::gem5::paramIn(cp, "resp", resp);
            s->r.resp = (AximmResp)resp;
            ::gem5::paramIn(cp, "last", s->r.last);
            uint64_t tmp = 0;
            ::gem5::paramIn(cp, "user", tmp);
            s->r.user = (uint8_t)tmp;
            ::gem5::paramIn(cp, "valid", s->r.valid);
            ::gem5::paramIn(cp, "ready", s->r.ready);
            ::gem5::arrayParamIn(cp, "data", s->r.data.data(), s->r.data.size());
            ::gem5::paramIn(cp, "wstrb", s->r.wstrb);
        }
        {
            Serializable::ScopedCheckpointSection sec2(cp, "b");
            ::gem5::paramIn(cp, "id", s->b.id);
            int resp = 0;
            ::gem5::paramIn(cp, "resp", resp);
            s->b.resp = (AximmResp)resp;
            uint64_t tmp = 0;
            ::gem5::paramIn(cp, "user", tmp);
            s->b.user = (uint8_t)tmp;
            ::gem5::paramIn(cp, "valid", s->b.valid);
        }
        return s;
    }
    if (kind == "aximmMasterState") {
        auto s = std::make_unique<aximmMasterState>();
        ::gem5::paramIn(cp, "rReady", s->rReady);
        ::gem5::paramIn(cp, "bReady", s->bReady);
        if (!::gem5::optParamIn(cp, "cdc_enqueue_ready", s->cdc_enqueue_ready, false)) {
            s->cdc_enqueue_ready = false;
        }
        auto unserAddr = [&](const char *sec_name, aximmRWAddr &addr) {
            Serializable::ScopedCheckpointSection sec(cp, sec_name);
            int cmd = 0, burst = 0;
            ::gem5::paramIn(cp, "cmd", cmd);
            addr.cmd = (AximmCommand)cmd;
            ::gem5::paramIn(cp, "burst", burst);
            addr.burst = (BurstType)burst;
            ::gem5::paramIn(cp, "id", addr.id);
            ::gem5::paramIn(cp, "addr", addr.addr);
            uint64_t tmp = 0;
            ::gem5::paramIn(cp, "len", tmp);
            addr.len = (uint8_t)tmp;
            ::gem5::paramIn(cp, "size", tmp);
            addr.size = (uint8_t)tmp;
            ::gem5::paramIn(cp, "lock", addr.lock);
            ::gem5::paramIn(cp, "cache", tmp);
            addr.cache = (uint8_t)tmp;
            ::gem5::paramIn(cp, "prot", tmp);
            addr.prot = (uint8_t)tmp;
            ::gem5::paramIn(cp, "qos", tmp);
            addr.qos = (uint8_t)tmp;
            ::gem5::paramIn(cp, "region", tmp);
            addr.region = (uint8_t)tmp;
            ::gem5::paramIn(cp, "user", tmp);
            addr.user = (uint8_t)tmp;
            ::gem5::paramIn(cp, "valid", addr.valid);
        };
        unserAddr("ar", s->ar);
        unserAddr("aw", s->aw);
        {
            Serializable::ScopedCheckpointSection sec3(cp, "w");
            int cmd = 0, resp = 0;
            ::gem5::paramIn(cp, "cmd", cmd);
            s->w.cmd = (AximmCommand)cmd;
            ::gem5::paramIn(cp, "id", s->w.id);
            ::gem5::paramIn(cp, "resp", resp);
            s->w.resp = (AximmResp)resp;
            ::gem5::paramIn(cp, "last", s->w.last);
            uint64_t tmp = 0;
            ::gem5::paramIn(cp, "user", tmp);
            s->w.user = (uint8_t)tmp;
            ::gem5::paramIn(cp, "valid", s->w.valid);
            ::gem5::paramIn(cp, "ready", s->w.ready);
            ::gem5::arrayParamIn(cp, "data", s->w.data.data(), s->w.data.size());
            ::gem5::paramIn(cp, "wstrb", s->w.wstrb);
        }
        return s;
    }
    panic("AXIMMHandler::unserializeInterfaceState: bad kind '%s'", kind);
}

namespace {

static void
copyAddrFields(const aximmRWAddr& a, NocInterfaceAximmBeatData::Ar& o)
{
    o.addr = a.addr;
    o.id = a.id;
    o.len = a.len;
    o.size = a.size;
    o.burst = static_cast<uint8_t>(a.burst);
    o.lock = a.lock;
    o.cache = a.cache;
    o.prot = a.prot;
    o.qos = a.qos;
    o.region = a.region;
    o.user = a.user;
    o.tvalid = a.valid;
}

static void
copyAddrFields(const aximmRWAddr& a, NocInterfaceAximmBeatData::Aw& o)
{
    o.addr = a.addr;
    o.id = a.id;
    o.len = a.len;
    o.size = a.size;
    o.burst = static_cast<uint8_t>(a.burst);
    o.lock = a.lock;
    o.cache = a.cache;
    o.prot = a.prot;
    o.qos = a.qos;
    o.region = a.region;
    o.user = a.user;
    o.tvalid = a.valid;
}

static void
copyWChan(const aximmRWData& w, NocInterfaceAximmBeatData::W& o)
{
    o.id = w.id;
    o.resp = static_cast<uint8_t>(w.resp);
    o.last = w.last;
    o.user = w.user;
    o.tvalid = w.valid;
    o.tready = w.ready;
    o.wstrb = w.wstrb;
    o.data = w.data;
}

static void
copyRChan(const aximmRWData& r, NocInterfaceAximmBeatData::R& o)
{
    o.id = r.id;
    o.resp = static_cast<uint8_t>(r.resp);
    o.last = r.last;
    o.user = r.user;
    o.tvalid = r.valid;
    o.tready = r.ready;
    o.wstrb = r.wstrb;
    o.data = r.data;
}

static void
copyBChan(const aximmWResp& b, NocInterfaceAximmBeatData::B& o)
{
    o.id = b.id;
    o.resp = static_cast<uint8_t>(b.resp);
    o.user = b.user;
    o.tvalid = b.valid;
}

} // namespace

void
AXIMMHandler::fillNocIfProbeFromNode(
    State* towardNi, State* towardTile, ProbeData* out)
{
    auto* beat = dynamic_cast<NocInterfaceAximmBeatData*>(out);
    panic_if(!beat,
        "AXIMMHandler::fillNocIfProbeFromNode: expected NocInterfaceAximmBeatData");

    *beat = NocInterfaceAximmBeatData{};

    if (role == "Master") {
        auto* tm = dynamic_cast<aximmMasterState*>(towardTile);
        auto* ts = dynamic_cast<aximmSlaveState*>(towardNi);
        panic_if(!tm || !ts,
            "AXIMMHandler::fillNocIfProbeFromNode: Master NI expects "
            "aximmMasterState tile + aximmSlaveState NI");

        aximmMasterState mcopy = *tm;
        static const char* const kCh[] = {"AR", "AW", "W"};
        for (auto ch : kCh) {
            snapshotNodeStateForToCdcProbe(ch, &mcopy, ts);
        }
        beat->cdc_enqueue_ready = mcopy.cdc_enqueue_ready;

        copyAddrFields(tm->ar, beat->ar);
        beat->ar.tready = ts->arReady;
        copyAddrFields(tm->aw, beat->aw);
        beat->aw.tready = ts->awReady;
        copyWChan(tm->w, beat->w);
        beat->w.tready = ts->wReady;
        copyRChan(ts->r, beat->r);
        beat->r.tready = tm->rReady;
        copyBChan(ts->b, beat->b);
        beat->b.tready = tm->bReady;
    } else {
        auto* nm = dynamic_cast<aximmMasterState*>(towardNi);
        auto* tt = dynamic_cast<aximmSlaveState*>(towardTile);
        panic_if(!nm || !tt,
            "AXIMMHandler::fillNocIfProbeFromNode: Slave NI expects "
            "aximmMasterState NI + aximmSlaveState tile");

        static const char* const kCh[] = {"R", "B"};
        for (auto ch : kCh) {
            snapshotNodeStateForToCdcProbe(ch, nm, tt);
        }
        beat->cdc_enqueue_ready = nm->cdc_enqueue_ready;

        copyAddrFields(nm->ar, beat->ar);
        beat->ar.tready = tt->arReady;
        copyAddrFields(nm->aw, beat->aw);
        beat->aw.tready = tt->awReady;
        copyWChan(nm->w, beat->w);
        beat->w.tready = tt->wReady;
        copyRChan(tt->r, beat->r);
        beat->r.tready = nm->rReady;
        copyBChan(tt->b, beat->b);
        beat->b.tready = nm->bReady;
    }
}

void
AXIMMHandler::fillNocIfProbeFromCdcPeek(
    Tick t, State* interfaceState, ProbeData* out, bool& valid)
{
    auto* beat = dynamic_cast<NocInterfaceAximmBeatData*>(out);
    panic_if(!beat,
        "AXIMMHandler::fillNocIfProbeFromCdcPeek: expected "
        "NocInterfaceAximmBeatData");

    *beat = NocInterfaceAximmBeatData{};
    valid = false;

    if (role == "Master") {
        bool any = false;
        for (auto& ch : channelMap) {
            if (ch.dir != 0)
                continue;
            if (!cdcDequeueReady(ch.name))
                continue;
            if (!cdcDequeueNiReady(ch.name, interfaceState))
                continue;
            CDCQueue* q = getCDCQueue(channelMap, ch.name);
            const State* pst = q->peekFrontState(t);
            const auto* pm = dynamic_cast<const aximmMasterState*>(pst);
            panic_if(!pm,
                "AXIMMHandler::fillNocIfProbeFromCdcPeek: expected "
                "aximmMasterState for channel %s",
                ch.name.c_str());
            if (ch.name == "AR") {
                copyAddrFields(pm->ar, beat->ar);
                any = true;
            } else if (ch.name == "AW") {
                copyAddrFields(pm->aw, beat->aw);
                any = true;
            } else if (ch.name == "W") {
                copyWChan(pm->w, beat->w);
                any = true;
            }
        }
        valid = any;
    } else {
        bool any = false;
        for (auto& ch : channelMap) {
            if (ch.dir != 0)
                continue;
            if (!cdcDequeueReady(ch.name))
                continue;
            if (!cdcDequeueNiReady(ch.name, interfaceState))
                continue;
            CDCQueue* q = getCDCQueue(channelMap, ch.name);
            const State* pst = q->peekFrontState(t);
            const auto* ps = dynamic_cast<const aximmSlaveState*>(pst);
            panic_if(!ps,
                "AXIMMHandler::fillNocIfProbeFromCdcPeek: expected "
                "aximmSlaveState for channel %s",
                ch.name.c_str());
            if (ch.name == "R") {
                copyRChan(ps->r, beat->r);
                any = true;
            } else if (ch.name == "B") {
                copyBChan(ps->b, beat->b);
                any = true;
            }
        }
        valid = any;
    }
}

}} // namespace
