#include "noc/core/network/nsu_types/mmNocSlaveUnit.hh"
#include "debug/NocPacketFlow.hh"

#include "noc/core/network/NocMessageBuffer.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "sim/eventq.hh"
#include "sim/serialize.hh"
#include "base/cprintf.hh"
#include "debug/NocTiming.hh"
#include <algorithm>
#include <unordered_set>


namespace gem5 {
namespace noc {
namespace garnet {

namespace {

static std::vector<int32_t>
debugIdsForMmByteRange(const NocMemoryMsg& npp, int start_byte, int nbytes,
                       int32_t fallback)
{
    std::vector<int32_t> out;
    if (nbytes <= 0) {
        if (fallback >= 0) out.push_back(fallback);
        return out;
    }

    const std::vector<int32_t>& ids = npp.getNetworkProbeDebugIds();
    if (ids.empty()) {
        if (fallback >= 0) out.push_back(fallback);
        return out;
    }

    Payload pl = npp.getData();
    const auto* ap = std::get_if<aximmPayload>(&pl);
    if (!ap) {
        // If we can't interpret the payload beats, fall back to message-level id.
        if (fallback >= 0) out.push_back(fallback);
        return out;
    }

    // Interpret network payload as a sequence of variable-valid-byte beats, and
    // map [start_byte, start_byte+nbytes) to the set of contributing ids.
    const int end_byte = start_byte + nbytes;
    int cum = 0;
    std::unordered_set<int32_t> seen;
    const size_t nbeats = ap->size();
    if (ids.size() != nbeats) {
        if (fallback >= 0) out.push_back(fallback);
        return out;
    }

    for (size_t i = 0; i < nbeats; ++i) {
        const aximmRWData& beat = (*ap)[i];
        const int bsz = beat.valid ? static_cast<int>(__builtin_popcountll(beat.wstrb)) : 0;
        if (bsz <= 0) {
            continue;
        }
        const int beat_start = cum;
        const int beat_end = cum + bsz;
        const bool overlaps = (start_byte < beat_end) && (end_byte > beat_start);
        if (overlaps) {
            const int32_t id = ids[i];
            if (seen.insert(id).second) {
                out.push_back(id);
            }
        }
        cum += bsz;
        if (cum >= end_byte) {
            break;
        }
    }
    if (out.empty() && fallback >= 0) {
        out.push_back(fallback);
    }
    return out;
}

template <typename Map>
void
serializeU32TickMap(CheckpointOut &cp, const char *prefix, const Map &m)
{
    std::vector<uint32_t> keys;
    keys.reserve(m.size());
    for (const auto &p : m)
        keys.push_back(p.first);
    std::sort(keys.begin(), keys.end());
    ::gem5::paramOut(cp, csprintf("%sSize", prefix), (uint64_t)keys.size());
    for (size_t i = 0; i < keys.size(); i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("%sE%u", prefix, (unsigned)i));
        uint32_t k = keys[i];
        ::gem5::paramOut(cp, "k", k);
        ::gem5::paramOut(cp, "v", (uint64_t)m.at(k));
    }
}

template <typename Map>
void
unserializeU32TickMap(CheckpointIn &cp, const char *prefix, Map &m)
{
    m.clear();
    uint64_t sz = 0;
    ::gem5::paramIn(cp, csprintf("%sSize", prefix), sz);
    for (size_t i = 0; i < sz; i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("%sE%u", prefix, (unsigned)i));
        uint32_t k = 0;
        uint64_t v = 0;
        ::gem5::paramIn(cp, "k", k);
        ::gem5::paramIn(cp, "v", v);
        m[k] = (Tick)v;
    }
}

template <typename Map>
void
serializeU32BoolMap(CheckpointOut &cp, const char *prefix, const Map &m)
{
    std::vector<uint32_t> keys;
    keys.reserve(m.size());
    for (const auto &p : m)
        keys.push_back(p.first);
    std::sort(keys.begin(), keys.end());
    ::gem5::paramOut(cp, csprintf("%sSize", prefix), (uint64_t)keys.size());
    for (size_t i = 0; i < keys.size(); i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("%sE%u", prefix, (unsigned)i));
        uint32_t k = keys[i];
        ::gem5::paramOut(cp, "k", k);
        ::gem5::paramOut(cp, "v", m.at(k));
    }
}

template <typename Map>
void
unserializeU32BoolMap(CheckpointIn &cp, const char *prefix, Map &m)
{
    m.clear();
    uint64_t sz = 0;
    ::gem5::paramIn(cp, csprintf("%sSize", prefix), sz);
    for (size_t i = 0; i < sz; i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("%sE%u", prefix, (unsigned)i));
        uint32_t k = 0;
        bool v = false;
        ::gem5::paramIn(cp, "k", k);
        ::gem5::paramIn(cp, "v", v);
        m[k] = v;
    }
}

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

template <typename T>
void
paramInAnySection(CheckpointIn &cp, const std::vector<std::string> &sections,
    const std::string &name, T &param, const std::string &obj_name)
{
    for (const auto &section : sections) {
        if (optParamInSection(cp, section, name, param)) {
            return;
        }
    }
    fatal("Can't unserialize '%s:%s'", obj_name, name);
}

} // namespace

void
mmNocSlaveUnit::RequestTracker::serialize(CheckpointOut &cp) const
{
    ::gem5::paramOut(cp, "m_size", (uint64_t)m_size);
    ::gem5::paramOut(cp, "m_num_ids", (uint64_t)m_num_ids);

    std::vector<uint32_t> keys;
    keys.reserve(axiReads.size());
    for (const auto &p : axiReads)
        keys.push_back(p.first);
    std::sort(keys.begin(), keys.end());
    ::gem5::paramOut(cp, "numKeys", (uint64_t)keys.size());
    for (size_t ki = 0; ki < keys.size(); ki++) {
        uint32_t id = keys[ki];
        Serializable::ScopedCheckpointSection sec(cp, csprintf("rtKey%u", (unsigned)ki));
        ::gem5::paramOut(cp, "id", id);
        const auto &lst = axiReads.at(id);
        ::gem5::paramOut(cp, "listSize", (uint64_t)lst.size());
        size_t mi = 0;
        for (const auto &msg : lst) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("msg%u", (unsigned)mi++));
            serializeNocMsgPtr(cp, msg);
        }
    }
}

void
mmNocSlaveUnit::RequestTracker::unserialize(CheckpointIn &cp)
{
    axiReads.clear();
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "m_size", tmp);
    ::gem5::paramIn(cp, "m_num_ids", tmp);

    uint64_t nk = 0;
    ::gem5::paramIn(cp, "numKeys", nk);
    for (size_t ki = 0; ki < nk; ki++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("rtKey%u", (unsigned)ki));
        uint32_t id = 0;
        ::gem5::paramIn(cp, "id", id);
        uint64_t ls = 0;
        ::gem5::paramIn(cp, "listSize", ls);
        std::list<MsgPtr> lst;
        for (size_t j = 0; j < ls; j++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("msg%u", (unsigned)j));
            lst.push_back(unserializeNocMsgPtr(cp));
        }
        axiReads[id] = std::move(lst);
    }

    m_num_ids = (uint8_t)axiReads.size();
    m_size = 0;
    for (const auto &p : axiReads)
        m_size += (uint16_t)p.second.size();
}

mmNocSlaveUnit::mmNocSlaveUnit(const Params &p) : NocSlaveUnit(p),
    dequeueIntermediateEvent(*this)
{
    if (p.data_width == 0) {
        panic("mmNocSlaveUnit: data_width is 0 (expected bits, e.g., 512)");
    }
    if ((p.data_width % 8) != 0) {
        panic("mmNocSlaveUnit: data_width must be a multiple of 8 bits");
    }
    S_DATA_WIDTH = static_cast<uint32_t>(p.data_width / 8); // bytes
    if (S_DATA_WIDTH == 0) {
        panic("mmNocSlaveUnit: computed S_DATA_WIDTH is 0 bytes");
    }
    m_read_response_gap_cycles = p.read_response_gap_cycles;
    m_read_response_per_flit_gap_cycles =
        p.read_response_per_flit_gap_cycles;
    internal_r_ready = true;
}

bool
mmNocSlaveUnit::enqueueReadRequestToTile(MsgPtr NPPMsg, MsgPtr tileMsg,
    Tick curTime)
{
    auto nppMem = std::dynamic_pointer_cast<NocMemoryMsg>(NPPMsg);
    panic_if(!nppMem,
        "mmNocSlaveUnit::enqueueReadRequestToTile expected NocMemoryMsg");

    const int vnet = nppMem->getVnet();
    MessageBuffer *obuf = outNode_ptr[vnet];
    panic_if(!obuf, "mmNocSlaveUnit::enqueueReadRequestToTile: outNode vnet %d null",
        vnet);

    if (!obuf->areNSlotsAvailable(1, curTime)) {
        return false;
    }

    if (!readTracker.add(NPPMsg)) {
        return false;
    }

    obuf->enqueue(tileMsg, curTime, 0, m_net_ptr->getRandomization(),
        m_net_ptr->getWarmupEnabled());
    return true;
}

bool
mmNocSlaveUnit::flitisizeMessage(MsgPtr msg_ptr, int vnet)
{
    //save vnet for receiving interface
    msg_ptr->setVnet(vnet);

    //check if a write or read response
    auto mem_msg_ptr = dynamic_cast<NocMemoryMsg*>(msg_ptr.get());
    if (!mem_msg_ptr) {
        panic("Failed to cast MsgPtr to NocMemoryMsg");
    }

    aximmRWData axi_rdata_payload;
    aximmWResp axi_bresp_payload;
    bool is_data = false;

    OutputPort *oPort = getOutportForVnet(vnet);
    assert(oPort);


    MessagePayload payload = mem_msg_ptr->getPayload();
    if(aximmRWData* p = std::get_if<aximmRWData>(&payload)) {
        axi_rdata_payload = *p;
        is_data = true;
    } else if(aximmWResp* p = std::get_if<aximmWResp>(&payload)) {
        axi_bresp_payload = *p;
    } else {
        panic("mmNocSlaveUnit::flitisizeMessage: Unsupported payload type");
    }


    if (is_data){
        if (!flitisizeReadResponse(msg_ptr, oPort, vnet)){
            DPRINTF(NocTiming, "Failed to flitisize read response\n");
            return false; //failed to flitisize read response
        }
    }
    else {
        if (!flitisizeWriteResponse(msg_ptr, axi_bresp_payload, oPort)) {
            panic("Failed to flitisize write response");
            return false; //failed to flitisize write response
        }
    }
    DPRINTF(NocTiming, "NSU sending out response\n");

    return true;
}

bool
mmNocSlaveUnit::flitisizeWriteResponse(MsgPtr base_msg_ptr, aximmWResp axi_payload, OutputPort *oPort){

    auto msg_ptr = std::dynamic_pointer_cast<NocMemoryMsg>(base_msg_ptr);
    if (!msg_ptr) {
        panic("mmNocSlaveUnit::flitisizeWriteResponse: expected NocMemoryMsg");
    }
    
    MsgPtr write_req_msg_ptr = writeTracker.readAndRemove(axi_payload.id);
    int vc = m_net_ptr->getPathVC(m_id, write_req_msg_ptr->getSourceNiID(), 3);  // 3 corresponds to write response

    gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit;

     // packet id per NPP (this write response corresonds to an NPP write request)
     int packet_id = m_net_ptr->getNextPacketID();
     NocRouteInfo route;
     route.vnet = B_VNET;
     // route.net_dest = // unused
     route.src_ni = m_id;
     route.src_router = write_req_msg_ptr->getIncomingLink() >= 0 ?
         write_req_msg_ptr->getIncomingLink() : oPort->routerID();
     route.dest_ni = write_req_msg_ptr->getSourceNiID();
     // route.dest_router = m_net_ptr->get_router_id(destID, vnet); //unused
     route.hops_traversed = -1;

     Tick inject_tick = curTick();
     if (bram_penalty_due.count(axi_payload.id) && bram_penalty_due[axi_payload.id]) {
         inject_tick += clockPeriod();
         bram_penalty_due.erase(axi_payload.id);
     }

     // Empirically, the NSU write-response path adds one extra cycle
     // every 16 completed B responses: 1-16 take the base latency,
     // 17th takes +1 cycle, then the pattern repeats.
     if (m_write_resp_total > 0 &&
         (m_write_resp_total % WRITE_RESP_STICKY_GAP_THRESHOLD) == 0) {
         inject_tick += clockPeriod();
     }

     flit = new gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>(
         packet_id,
         0, // flit id
         vc, // virtual channel
         B_VNET,
         route,
         1, // total size, will group this many flits together
         msg_ptr,
         0, //MsgSize - needed??
         oPort->bitWidth(), //change bWidth if need to serialize/deserialize
         inject_tick,
         true // head_tail flit
     );

    m_write_resp_total++;

    if (!injectFlit(flit, B_VNET, msg_ptr, vc)) {
        delete flit;
        return false;
    }

    return true;

}


// think of this function as being called on every beat of a read response
bool
mmNocSlaveUnit::flitisizeReadResponse(MsgPtr base_msg_ptr, OutputPort *oPort, int vnet){

    if (currDrainEntry.valid) {
        return false;
    }

    // Cast to NocMemoryMsg for proper method access
    auto msg_ptr = std::dynamic_pointer_cast<NocMemoryMsg>(base_msg_ptr);
    if (!msg_ptr) {
        panic("mmNocSlaveUnit::flitisizeReadResponse: expected NocMemoryMsg");
    }

    // Extract the beat from the incoming message
    MessagePayload payload = msg_ptr->getPayload();
    aximmRWData* beat_data = std::get_if<aximmRWData>(&payload);
    if (!beat_data) {
        panic("mmNocSlaveUnit::flitisizeReadResponse: Expected aximmRWData payload");
    }
    
    uint32_t axi_id = beat_data->id;
    
    if (axi_id >= NUM_SUPPORTED_AXI_IDS) {
        panic("mmNocSlaveUnit: AXI ID %d exceeds supported max %d", axi_id, NUM_SUPPORTED_AXI_IDS);
    }
    
    ReadResponseState& state = m_read_response_state[axi_id];
    
    // Initialize state on first beat
    if (!state.active) {
        MsgPtr original_req = readTracker.read(axi_id);
        MessagePayload req_payload = original_req->getPayload();
        aximmRWAddr* p = std::get_if<aximmRWAddr>(&req_payload);
        
        state.reset();
        state.active = true;
        state.packet_id = m_net_ptr->getNextPacketID();
        const uint32_t chunk_bytes = p->getTotalByteSize();
        auto original_mem = std::dynamic_pointer_cast<NocMemoryMsg>(original_req);
        state.original_read_bytes =
            original_mem && original_mem->hasOriginalReadBytes() ?
            original_mem->getOriginalReadBytes() : chunk_bytes;
        state.total_bytes_needed = static_cast<uint16_t>(chunk_bytes);
        state.bytes_received = 0;
        state.bytes_sent = 0;
        state.num_flits = (state.total_bytes_needed + 15) / 16;
        state.original_beat_size = (1 << p->size);
        state.auto_per_flit_gap = false;
        
        // Create the NPP message
        aximmPayload npp_payload{};
        npp_payload[0].id = axi_id;
        MessagePayload cmd = *beat_data;
        state.nppMsg = std::make_shared<NocMemoryMsg>(curTick(), nullptr, AxiMsgSizeType::R, cmd, npp_payload);
        state.nppMsg->setBeatSize(6);  // 64-byte NPP beats (log2(64) = 6)
        state.nppMsg->setNumFlits(state.num_flits);
        
        // Clone RROB tags from original request
        NocMemoryMsg::cloneRROBTags(original_req, state.nppMsg);
    }
    
    // Accumulate narrow beat into 64-byte buffer
    // uint8_t beat_size = state.original_beat_size;
    uint8_t beat_size = S_DATA_WIDTH;
    std::copy(beat_data->data.begin(),
              beat_data->data.begin() + beat_size,
              state.accumBuffer.begin() + state.accumOffset);
    state.accumStrobe |= (beat_data->wstrb << state.accumOffset);
    state.accumOffset += beat_size;
    state.bytes_received += beat_size;
    
    bool is_64B_ready = (state.accumOffset >= NPP_BEAT_SIZE);
    bool is_last = beat_data->last;
    
    // When 64 bytes ready or last beat, append to NPP message
    if (is_64B_ready || is_last) {
        aximmRWData upsized_beat;
        upsized_beat.id = axi_id;
        upsized_beat.cmd = beat_data->cmd;
        upsized_beat.last = is_last;
        upsized_beat.data = state.accumBuffer;
        upsized_beat.wstrb = state.accumStrobe;
        upsized_beat.valid = true;

        state.nppMsg->appendData(upsized_beat);
        
        // Reset accumulator for next 64-byte chunk
        state.accumBuffer.fill(0);
        state.accumStrobe = 0;
        state.accumOffset = 0;
    }
    
    // Emit flits when ready
    MsgPtr original_req = readTracker.read(axi_id);
    int vc = m_net_ptr->getPathVC(m_id, original_req->getSourceNiID(), 2);
    bool slave_finished = (state.bytes_received >= state.total_bytes_needed);

    const bool need_inject =
        (state.bytes_received - state.bytes_sent) >= 16 ||
        (slave_finished && state.bytes_received > state.bytes_sent);

    if (need_inject) {
        if (currDrainEntry.valid && currDrainEntry.axi_id != axi_id) {
            DPRINTF (NocPacketFlow, "mmNocSlaveUnit::flitisizeReadResponse: drain already pending "
                  "for AXI id %u, cannot start id %u",
                  currDrainEntry.axi_id, axi_id);
            std::array<uint8_t, 8> tags{};
            if (state.nppMsg) {
                tags = state.nppMsg->getRrobTags();
            }
            m_net_ptr->traceNsuReadDrain(
                "busy", m_id, axi_id, original_req->getSourceNiID(), vc,
                state.packet_id, -1, state.bytes_received, state.bytes_sent,
                state.total_bytes_needed, slave_finished, tags);
            return false; // drain already pending, cannot start new drain
        }
        currDrainEntry.valid = true;
        currDrainEntry.axi_id = axi_id;
        currDrainEntry.drain_vnet = vnet;
        currDrainEntry.oPort = oPort;
        currDrainEntry.vc = vc;
        currDrainEntry.slave_finished = slave_finished;
        currDrainEntry.original_req = original_req;
        state.auto_per_flit_gap = m_net_ptr->readResponsesUseMultipleVCs(m_id);

        m_net_ptr->traceNsuReadDrain(
            "select", m_id, axi_id, original_req->getSourceNiID(), vc,
            state.packet_id, -1, state.bytes_received, state.bytes_sent,
            state.total_bytes_needed, slave_finished,
            state.nppMsg ? state.nppMsg->getRrobTags()
                         : std::array<uint8_t, 8>{});
        
        if (!dequeueIntermediateEvent.scheduled()) {
            dequeueIntermediate();
        } else {
            panic("mmNocSlaveUnit::flitisizeReadResponse: dequeueIntermediateEvent already scheduled");
        }
    } else if (state.bytes_sent >= state.total_bytes_needed) {
        readTracker.readAndRemove(axi_id);
        state.active = false;
    }

    return true;
}

void
mmNocSlaveUnit::dequeueIntermediate()
{
    if (!currDrainEntry.valid) {
        return;
    }

    ReadResponseState& state = m_read_response_state[currDrainEntry.axi_id];
    NetworkInterface::OutputPort* oPort = currDrainEntry.oPort;
    assert(oPort);

    const bool slave_finished = currDrainEntry.slave_finished;

    if ((state.bytes_received - state.bytes_sent) >= 16 ||
           (slave_finished && state.bytes_received > state.bytes_sent)) {

        int flit_idx = state.bytes_sent / 16;

        NocRouteInfo route;
        route.vnet = R_VNET;
        route.src_ni = m_id;
        route.src_router = currDrainEntry.original_req->getIncomingLink() >= 0 ?
            currDrainEntry.original_req->getIncomingLink() : oPort->routerID();
        route.dest_ni = currDrainEntry.original_req->getSourceNiID();
        route.hops_traversed = -1;

        // --- Calculate flit injection delay for gap rules ---
        // Cool-down check: if idle long enough (> 2 cycles), reset transient burst counter
        if (m_last_read_flit_inject_tick > 0 &&
            curTick() > m_last_read_flit_inject_tick &&
            (curTick() - m_last_read_flit_inject_tick) > cyclesToTicks(Cycles(COOL_DOWN_CYCLES))) {
            // DPRINTF(NocTiming, "NSU BUBBLE TRACE: curTick=%lu, last_inject=%lu, idle for %d ticks, cool down cycles %d cycles\n", 
            //         curTick(), m_last_read_flit_inject_tick, (curTick() - m_last_read_flit_inject_tick), cyclesToTicks(Cycles(COOL_DOWN_CYCLES)));
            m_read_flits_in_burst = 0;
        }
        
        // Base inject tick: either now, or 1 cycle after the last injected flit
        Tick inject_tick = std::max(curTick(),
            (m_last_read_flit_inject_tick == 0) ? curTick()
                                                  : m_last_read_flit_inject_tick + clockPeriod());

        // Optional per-flit rule: one or more extra idle cycles after every
        // read-response flit in a continuous burst. The parameter remains a
        // diagnostic override; the auto rule latches when this NSU has
        // read-response routes to AXI-MM NMUs on multiple VCs.
        const uint32_t per_flit_gap_cycles = std::max(
            m_read_response_per_flit_gap_cycles,
            state.auto_per_flit_gap ? 1u : 0u);
        const bool need_per_flit_gap =
            (per_flit_gap_cycles > 0 && m_read_flits_in_burst > 0);

        if (need_per_flit_gap) {
            inject_tick = std::max(
                inject_tick,
                m_last_read_flit_inject_tick +
                    (1 + per_flit_gap_cycles) * clockPeriod());
        }

        // 4-flit rule (transient): one extra idle cycle after every 4th flit in a burst.
        // 16-flit rule (sticky): one extra idle cycle after every 16th cumulative flit.
        //
        // Use max(last + 2*period), not inject_tick += period. The old += form interacted
        // badly with event-driven dequeue: while total_flits % 16 == 0 we had not yet
        // incremented counters, so every reschedule added another period and inject_tick
        // stayed forever one cycle ahead of curTick().
        const bool need_transient_gap =
            (m_read_flits_in_burst > 0 &&
             (m_read_flits_in_burst % FLITS_PER_BURST) == 0);
        const bool need_sticky_gap =
            (m_read_flits_total > 0 &&
             (m_read_flits_total % STICKY_GAP_THRESHOLD) == 0);

        if (m_read_response_gap_cycles > 0 &&
            (need_transient_gap || need_sticky_gap)) {
            inject_tick = std::max(
                inject_tick,
                m_last_read_flit_inject_tick +
                    (1 + m_read_response_gap_cycles) * clockPeriod());
        }

        // Wait until simulation time catches up to the earliest legal inject time.
        if (inject_tick > curTick()) {
            schedule(dequeueIntermediateEvent, inject_tick);
            DPRINTF(NocPacketFlow,
                    "NSU RESCHEDULED FLIT until inject_tick=%lu (curTick=%lu)\n",
                    inject_tick, curTick());
            return;
        }
        
        auto cur_flit = new gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>(
            state.packet_id,
            flit_idx,
            currDrainEntry.vc,
            R_VNET,
            route,
            state.num_flits,
            state.nppMsg,
            0,
            oPort->bitWidth(),
            inject_tick,
            true);

        uint16_t rrob_tag_index = flit_idx / 2;
        cur_flit->set_rrob_tag(state.nppMsg->getRROBTag(rrob_tag_index));
        cur_flit->set_rrob_flit_idx(flit_idx % 2);
        
        DPRINTF(NocPacketFlow, "NSU SENDING FLIT: PktID=%d, FlitID=%d/%d, InjectTick=%lu\n",
                state.packet_id, flit_idx, state.num_flits, inject_tick);
        DPRINTF(NocTiming, "NSU BUBBLE TRACE: FlitID=%d, burst_cnt=%d, inject_tick=%lu, last_inject=%lu\n",
                flit_idx, m_read_flits_in_burst, inject_tick, m_last_read_flit_inject_tick);

        if (!injectFlit(cur_flit, R_VNET, state.nppMsg, currDrainEntry.vc)) {
            delete cur_flit;
            DPRINTF(NocPacketFlow, "NSU FAILED TO INJECT FLIT, rescheduling for next cycle\n");
            schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));
            return;
        }

        m_net_ptr->traceNsuReadDrain(
            "inject", m_id, currDrainEntry.axi_id,
            currDrainEntry.original_req->getSourceNiID(), currDrainEntry.vc,
            state.packet_id, flit_idx, state.bytes_received, state.bytes_sent,
            state.total_bytes_needed, currDrainEntry.slave_finished,
            state.nppMsg ? state.nppMsg->getRrobTags()
                         : std::array<uint8_t, 8>{});

        state.bytes_sent += 16;

        m_read_flits_in_burst++;
        m_read_flits_total++;
        m_last_read_flit_inject_tick = inject_tick;
        
    }

    if (state.bytes_sent >= state.total_bytes_needed) {
        m_net_ptr->traceNsuReadDrain(
            "complete", m_id, currDrainEntry.axi_id,
            currDrainEntry.original_req->getSourceNiID(), currDrainEntry.vc,
            state.packet_id, -1, state.bytes_received, state.bytes_sent,
            state.total_bytes_needed, currDrainEntry.slave_finished,
            state.nppMsg ? state.nppMsg->getRrobTags()
                         : std::array<uint8_t, 8>{});
        readTracker.readAndRemove(currDrainEntry.axi_id);
        state.active = false;
        currDrainEntry.valid = false;
    } else if ((state.bytes_received - state.bytes_sent) >= 16 ||
               (currDrainEntry.slave_finished &&
                state.bytes_received > state.bytes_sent)) {
        schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));
        // keep currDrainEntry.valid == true
    } else {
        // Same as falling out of the while: caught up with what has been *received*
        // but total transfer not done — wait for more R beats from flitisizeReadResponse.
        currDrainEntry.valid = false;
        // do NOT readAndRemove; leave state.active true and m_read_response_state intact
    }
}

bool
mmNocSlaveUnit::depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit)
{
    std::vector<uint8_t> raw_data;
    MsgPtr msg = flit->get_msg_ptr();

    MessagePayload payload = flit->get_msg_ptr()->getPayload();
    aximmRWAddr axi_payload;
    aximmRWData axi_data_payload;
    bool is_data = false;

    if(aximmRWAddr* p = std::get_if<aximmRWAddr>(&payload)) {
        axi_payload = *p;
    } else if(aximmRWData* p = std::get_if<aximmRWData>(&payload)) {
        axi_data_payload = *p;
        is_data = true;
    } else {
        panic("mmNocSlaveUnit::depacketizeFlit: Unsupported payload type");
    }

    if (is_data) {
        if (!depacketizeWriteDataFlit(flit)) {
            return false; //failed to depacketize write data
        }
    } else if (axi_payload.cmd == gem5::noc::AximmCommand::READ){
        if (!depacketizeReadRequestFlit(flit))
            return false; //failed to depacketize read request
    } else if (axi_payload.cmd == gem5::noc::AximmCommand::WRITE) {
        if (!depacketizeWriteRequestFlit(flit))
            return false; //failed to flitisize write request
    } else {
        panic("mmNocSlaveUnit::depacketizeFlit: Unsupported AXI command");
    }
    DPRINTF(NocTiming,"NSU %d depacketized flit %s\n",m_id, *flit);
    return true;
}

bool
mmNocSlaveUnit::depacketizeReadRequestFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit){
    // printf("in NocSlaveUnit::depacketizeReadRequestFlit adding flit to outport %s\n", *flit)

    auto NPPMsgBase = flit->get_msg_ptr();
    auto NPPMsg = std::dynamic_pointer_cast<NocMemoryMsg>(NPPMsgBase);
    if (!NPPMsg)
        panic("Expected NocMemoryMsg inside depacketizeReadRequestFlit");

    Tick curTime = clockEdge();

    // 1. Check Output Buffer Space FIRST
    if (!outNode_ptr[garnet::AR_VNET]->areNSlotsAvailable(1, curTime)) {
        return false; // Buffer full, retry later
    }

    // 2. Prepare the Message for the Tile (The Adapter Logic)
    MsgPtr tileMsg = NPPMsg;
    MessagePayload payload = NPPMsg->getPayload();

    if (aximmRWAddr* p = std::get_if<aximmRWAddr>(&payload)) {
        uint16_t total_bytes = p->getTotalByteSize();
        
        // Create a modified payload
        aximmRWAddr adapted_payload = *p;
        adapted_payload.size = static_cast<uint8_t>(std::log2(S_DATA_WIDTH));
        adapted_payload.len = (total_bytes + S_DATA_WIDTH - 1) / S_DATA_WIDTH - 1;
        adapted_payload.sourceNiDebug = NPPMsg->getSourceNiID();
        adapted_payload.originalReadBytesDebug =
            NPPMsg->hasOriginalReadBytes() ? NPPMsg->getOriginalReadBytes() : 0;
        adapted_payload.debugId = NPPMsg->hasDebugId() ? NPPMsg->getDebugId() : -1;
        adapted_payload.finalReadChunkDebug = NPPMsg->isFinalReadChunk();
       
        tileMsg = std::shared_ptr<NocMemoryMsg>(new NocMemoryMsg(
            curTime, 
            nullptr, // or NPPMsg->getNocSystem() if available
            AxiMsgSizeType::AR, 
            adapted_payload
        ));

        tileMsg->setVnet(NPPMsg->getVnet());
        tileMsg->setSourceNiID(NPPMsg->getSourceNiID());

        // DPRINTF(NocTiming, "NSU Adapter: Upsized Req ID:%d to Size=6, Len=0 for Tile\n", p->id);
        
    }
    // 3. Send the adapted request to the tile immediately. Delaying this until
    // a full original AXI read is reconstructed was useful diagnostically, but
    // is not the retained model until the contiguous-read investigation is
    // resolved.
    if (!enqueueReadRequestToTile(NPPMsg, tileMsg, curTime)) {
        return false;
    }

    MessagePayload t_load = tileMsg->getPayload();
    // FIX: Use aximmRWAddr* (Address), not aximmRWData* (Data)
    aximmRWAddr* t_p = std::get_if<aximmRWAddr>(&t_load);

    MessagePayload n_load = NPPMsg->getPayload();
    // FIX: Use aximmRWAddr*
    aximmRWAddr* n_p = std::get_if<aximmRWAddr>(&n_load);

    if (t_p && n_p) {
        DPRINTF(NocPacketFlow,"[TRACE-2] NSU Request: Net(Size=%d, Len=%d) -> Tile(Size=%d, Len=%d)\n",
               n_p->size, n_p->len,
               t_p->size, t_p->len);
    }

    return true;
}

bool
mmNocSlaveUnit::depacketizeWriteDataFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit){

    std::vector<aximmRWData> payloads;
    std::vector<std::vector<int32_t>> dbg_ids;

    auto msgBase = flit->get_msg_ptr();
    auto msg = std::dynamic_pointer_cast<NocMemoryMsg>(msgBase);
    if (!msg)
        panic("Expected NocMemoryMsg inside write request flit");
    const int32_t fallback_dbg = msg->getDebugId();

    const int packet_id = flit->getPacketID();
    const uint8_t packet_flit_id = static_cast<uint8_t>(flit->get_id());
    panic_if(packet_flit_id == 0,
        "mmNocSlaveUnit::depacketizeWriteDataFlit received write-data body "
        "flit with packet_flit_id 0 for packet %d", packet_id);
    // AXI-MM write packets carry an AW head flit at packet index 0. The
    // associated W-body message only stores the data flits, so translate the
    // packet-global flit index into a body-local index before reading payload
    // bytes or testing for the last data flit.
    const uint8_t flit_id = packet_flit_id - 1;
    const bool is_tail_flit = ((msg->getNumFlits() - 1) == flit_id);
    uint8_t axi_id = msg->getRespAXIID(); // misleading name, but axi id should be stored
                                                        // in this case since we are using p_load
                                                        // field of msg to store write data

    // Do not accept W data until the AW for this ID has been depacketized (same ID in tracker).
    if (!writeTracker.has(axi_id)) {
        return false;
    }

    Tick curTime = clockEdge();
    if (flit_id == 0) {
        // Determine if this NPP is back-to-back with the previous NPP of the SAME transaction
        is_back_to_back[axi_id] = false;
        if (last_tail_flit_tick.count(axi_id)) {
            if (curTime == last_tail_flit_tick[axi_id] + clockPeriod()) {
                is_back_to_back[axi_id] = true;
            }
        }
    }

    DPRINTF(NocPacketFlow,"NSU RECEIVED WRITE DATA FLIT: FlitID=%d, Tail=%d, TotalFlits=%d\n",
           flit_id,
           is_tail_flit ? 1 : 0, 
           msg->getNumFlits());

    std::array<uint8_t, 16> flit_data = msg->getFlitData(flit_id);
    uint64_t flit_strobe = msg->getFlitStrobe(flit_id);
    MmWriteDataAssemblyState stagedAssembly;
    if (auto it = writeDataAssemblyByPacket.find(packet_id);
        it != writeDataAssemblyByPacket.end()) {
        stagedAssembly = it->second;
    }

    uint64_t write_addr = 0;
    if (S_DATA_WIDTH > 16) {
        MsgPtr aw_req = writeTracker.read(axi_id);
        MessagePayload aw_p = aw_req->getPayload();
        aximmRWAddr* p = std::get_if<aximmRWAddr>(&aw_p);
        panic_if(!p,
            "mmNocSlaveUnit::depacketizeWriteDataFlit expected tracked AW "
            "payload for AXI id %u", axi_id);
        write_addr = p->addr;
    }

    MmWriteDataDepacketizedFlit depacketized = depacketizeMmWriteDataFlit(
        S_DATA_WIDTH, axi_id, write_addr, stagedAssembly, flit_id,
        msg->getNumFlits(), flit_data, flit_strobe);
    payloads = std::move(depacketized.payloads);
    for (const MmWriteDataDebugRange& range : depacketized.debugRanges) {
        dbg_ids.push_back(debugIdsForMmByteRange(
            *msg, range.startByte, range.validBytes, fallback_dbg));
    }

    if (!payloads.empty()) {
        DPRINTF(NocPacketFlow,"[TRACE-W] NSU Generated %lu Write Data Beats. Enqueuing to Tile Buffer.\n", payloads.size());
        if (payloads.back().last) {
            DPRINTF(NocPacketFlow,"[TRACE-W] ... Includes LAST beat.\n");
        }
    }

    panic_if(payloads.size() != dbg_ids.size(),
             "mmNocSlaveUnit: payload vs debugIds size mismatch (%zu vs %zu)",
             payloads.size(), dbg_ids.size());

    if (!sendNWriteDataMsgs(createNWriteDataMsgs(payloads, dbg_ids, fallback_dbg)))
        return false;

    if (S_DATA_WIDTH > 16) {
        if (is_tail_flit) {
            writeDataAssemblyByPacket.erase(packet_id);
        } else {
            writeDataAssemblyByPacket[packet_id] = stagedAssembly;
        }
    }


    if (is_tail_flit) {
        last_tail_flit_tick[axi_id] = curTime;

        bool has_axi_last = false;
        for (const auto& p : payloads) {
            if (p.last) has_axi_last = true;
        }

        if (has_axi_last) {
            if (is_back_to_back[axi_id] && msg->getNumFlits() < 4) {
                bram_penalty_due[axi_id] = true;
            }
            last_tail_flit_tick.erase(axi_id);
            is_back_to_back.erase(axi_id);
        }
    }

    return true;
}

std::vector<MsgPtr>
mmNocSlaveUnit::createNWriteDataMsgs(
    std::vector<aximmRWData> payloads,
    const std::vector<std::vector<int32_t>>& per_payload_debug_ids,
    int32_t fallback_debug_id)
{

    std::vector<MsgPtr> ret;

    for (size_t i = 0; i < payloads.size(); ++i) {
        MsgPtr msg = std::shared_ptr<NocMemoryMsg>(new
            NocMemoryMsg(clockEdge(), nullptr, AxiMsgSizeType::W, payloads[i]));
        const std::vector<int32_t> dbg_ids = (i < per_payload_debug_ids.size())
            ? per_payload_debug_ids[i]
            : std::vector<int32_t>{};
        if (!dbg_ids.empty()) {
            msg->setDebugIds(dbg_ids);
            msg->setDebugId(dbg_ids.front());
        } else {
            msg->setDebugId(fallback_debug_id);
        }
        ret.push_back(msg);
    }

    return ret;
}

bool
mmNocSlaveUnit::sendNWriteDataMsgs(std::vector<MsgPtr> Msgs){

    Tick curTime = clockEdge();

    if (Msgs.size() == 0)
        return true;

    //TODO change out buffer to a different size?
    if (!outNode_ptr[garnet::W_VNET]->areNSlotsAvailable(Msgs.size(), curTime))
        return false;

    // Space is available. Enqueue messages to output buffer to tile controller.
    for (int i=0; i<Msgs.size(); i++){
        outNode_ptr[garnet::W_VNET]->enqueue(Msgs[i], curTime,
                    0,// cyclesToTicks(Cycles(1)),
                    m_net_ptr->getRandomization(),
                    m_net_ptr->getWarmupEnabled());
    }

    return true;

}

bool
mmNocSlaveUnit::depacketizeWriteRequestFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit){

    auto NPPMsgBase = flit->get_msg_ptr();
    auto NPPMsg = std::dynamic_pointer_cast<NocMemoryMsg>(NPPMsgBase);
    if (!NPPMsg)
        panic("Expected NocMemoryMsg inside write request flit");

    Tick curTime = clockEdge();

    if (!outNode_ptr[garnet::AW_VNET]->areNSlotsAvailable(1, curTime)){
        return false;
    }

    MsgPtr tileMsg = NPPMsg; 
    MessagePayload payload = NPPMsg->getPayload();
    
    if(aximmRWAddr* p = std::get_if<aximmRWAddr>(&payload)) {
        uint16_t total_bytes = p->getTotalByteSize(); 
        aximmRWAddr adapted_payload = *p;
        
        // Calculate new Size/Len for the Slave
        adapted_payload.size = static_cast<uint8_t>(std::log2(S_DATA_WIDTH));
        adapted_payload.len = (total_bytes + S_DATA_WIDTH - 1) / S_DATA_WIDTH - 1;

        // Create modified message
        tileMsg = std::shared_ptr<NocMemoryMsg>(new NocMemoryMsg(
            curTime, nullptr, AxiMsgSizeType::AW, adapted_payload));
        
        tileMsg->setVnet(NPPMsg->getVnet());
        tileMsg->setSourceNiID(NPPMsg->getSourceNiID());
    }

    // Track ORIGINAL (Narrow) Request
    if (!writeTracker.add(NPPMsg)) {
        return false;
    }

    MessagePayload tilepayload = tileMsg->getPayload();
    if(aximmRWAddr* ptile = std::get_if<aximmRWAddr>(&tilepayload)) {
        DPRINTF(NocPacketFlow,"[TRACE-AW] NSU Depacketized Write Req ID:%d. Enqueuing to Tile Buffer.\n", ptile->id);
    }

    // Send ADAPTED (Wide) Request to Tile
    outNode_ptr[garnet::AW_VNET]->enqueue(
        tileMsg, curTime, 0, 
        m_net_ptr->getRandomization(), m_net_ptr->getWarmupEnabled()
    );

    return true;
}

bool
mmNocSlaveUnit::getAxiRReady(bool upstreamValid) {
    (void)upstreamValid;
    internal_r_ready = readTracker.getSize() > 0;
    return readTracker.getSize() > 0;
}

bool
mmNocSlaveUnit::getAxiBReady(bool upstreamValid, aximmSlaveState upstreamState) {
    // If tile has a valid B response pending, check if we can send it
    if (!upstreamValid || !upstreamState.b.valid) {
        return true;  // No response pending, we're ready
    }

    if (writeTracker.getSize() == 0) {
        return true;  // No outstanding writes, ignore the spurious valid
    }
    
    // Look up the original write request to find the destination NMU
    uint32_t axi_id = upstreamState.b.id;
    MsgPtr original_req = writeTracker.read(axi_id);
    gem5::ruby::NodeID dest_nmu = original_req->getSourceNiID();
    
    // Get the specific VC for this (NSU -> NMU, WRITE_RESP) path
    int vc = m_net_ptr->getPathVC(m_id, dest_nmu, 3);  // 3 = WRITE_RESP
    
    // Check if THAT specific VC has credits
    return outVcState[vc].has_credit();
}

void
mmNocSlaveUnit::print(std::ostream& out) const
{
    out << "[mmNocSlaveUnit " << m_id << "]";
}

void
mmNocSlaveUnit::serialize(CheckpointOut &cp) const
{
    NocSlaveUnit::serialize(cp);

    {
        Serializable::ScopedCheckpointSection sec(cp, "mm_nsu_state");
        ::gem5::paramOut(cp, "S_DATA_WIDTH", (uint64_t)S_DATA_WIDTH);
        std::vector<int> write_packet_ids;
        write_packet_ids.reserve(writeDataAssemblyByPacket.size());
        for (const auto &entry : writeDataAssemblyByPacket)
            write_packet_ids.push_back(entry.first);
        std::sort(write_packet_ids.begin(), write_packet_ids.end());
        ::gem5::paramOut(cp, "writeDataAssemblyByPacketSize",
                         (uint64_t)write_packet_ids.size());
        for (size_t i = 0; i < write_packet_ids.size(); i++) {
            Serializable::ScopedCheckpointSection state_sec(
                cp, csprintf("writeDataAssembly%u", (unsigned)i));
            const int packet_id = write_packet_ids[i];
            const auto &state = writeDataAssemblyByPacket.at(packet_id);
            ::gem5::paramOut(cp, "packet_id", packet_id);
            ::gem5::arrayParamOut(cp, "aggregateData",
                                  state.aggregateData.data(),
                                  state.aggregateData.size());
            ::gem5::paramOut(cp, "aggregateStrobe", state.aggregateStrobe);
        }

        for (size_t i = 0; i < NUM_SUPPORTED_AXI_IDS; i++) {
            Serializable::ScopedCheckpointSection state_sec(
                cp, csprintf("readRespState%u", (unsigned)i));
            const auto &st = m_read_response_state[i];
            ::gem5::paramOut(cp, "active", st.active);
            ::gem5::arrayParamOut(cp, "accumBuffer", st.accumBuffer.data(),
                                  st.accumBuffer.size());
            ::gem5::paramOut(cp, "accumStrobe", st.accumStrobe);
            ::gem5::paramOut(cp, "accumOffset", (uint64_t)st.accumOffset);
            ::gem5::paramOut(cp, "packet_id", st.packet_id);
            ::gem5::paramOut(cp, "num_flits", (uint64_t)st.num_flits);
            ::gem5::paramOut(cp, "total_bytes_needed", st.total_bytes_needed);
            ::gem5::paramOut(cp, "bytes_received", st.bytes_received);
            ::gem5::paramOut(cp, "bytes_sent", st.bytes_sent);
            ::gem5::paramOut(cp, "original_beat_size",
                             (uint64_t)st.original_beat_size);
            ::gem5::paramOut(cp, "original_read_bytes",
                             st.original_read_bytes);
            ::gem5::paramOut(cp, "auto_per_flit_gap",
                             st.auto_per_flit_gap);
            serializeNocMsgPtrOptional(cp, st.nppMsg);
        }

        {
            Serializable::ScopedCheckpointSection timing_sec(
                cp, "writeRespTimingState");
            serializeU32TickMap(cp, "last_tail", last_tail_flit_tick);
            serializeU32BoolMap(cp, "is_b2b", is_back_to_back);
            serializeU32BoolMap(cp, "bram_pen", bram_penalty_due);

            ::gem5::paramOut(cp, "m_read_flits_in_burst", m_read_flits_in_burst);
            ::gem5::paramOut(cp, "m_read_flits_total", m_read_flits_total);
            ::gem5::paramOut(cp, "m_last_read_flit_inject_tick",
                             (uint64_t)m_last_read_flit_inject_tick);
            ::gem5::paramOut(cp, "m_write_resp_total", m_write_resp_total);
        }

        {
            Serializable::ScopedCheckpointSection drain_sec(cp, "drainEntry");
            ::gem5::paramOut(cp, "valid", currDrainEntry.valid);
            ::gem5::paramOut(cp, "axi_id", currDrainEntry.axi_id);
            ::gem5::paramOut(cp, "drain_vnet", currDrainEntry.drain_vnet);
            ::gem5::paramOut(cp, "vc", currDrainEntry.vc);
            ::gem5::paramOut(cp, "slave_finished",
                             currDrainEntry.slave_finished);
            ::gem5::paramOut(cp, "request_tick",
                             (uint64_t)currDrainEntry.request_tick);
            if (currDrainEntry.valid) {
                serializeNocMsgPtr(cp, currDrainEntry.original_req);
            }
        }

        {
            Serializable::ScopedCheckpointSection tracker_sec(cp, "readTracker");
            readTracker.serialize(cp);
        }
        {
            Serializable::ScopedCheckpointSection tracker_sec(cp, "writeTracker");
            writeTracker.serialize(cp);
        }
    }
}

void
mmNocSlaveUnit::unserialize(CheckpointIn &cp)
{
    NocSlaveUnit::unserialize(cp);

    const std::string obj = name();
    const bool has_state_section =
        cp.entryExists(obj + ".mm_nsu_state", "S_DATA_WIDTH");

    auto unserialize_drain_entry = [&](bool legacy_layout) {
        const std::string drain_section = legacy_layout ?
            obj + ".drainEntry" : obj + ".mm_nsu_state.drainEntry";
        if (!cp.entryExists(drain_section, "valid")) {
            currDrainEntry = DrainEntry{};
            return;
        }

        Serializable::ScopedCheckpointSection sec(cp, "drainEntry");
        ::gem5::paramIn(cp, "valid", currDrainEntry.valid);
        ::gem5::paramIn(cp, "axi_id", currDrainEntry.axi_id);
        ::gem5::paramIn(cp, "drain_vnet", currDrainEntry.drain_vnet);
        ::gem5::paramIn(cp, "vc", currDrainEntry.vc);
        ::gem5::paramIn(cp, "slave_finished", currDrainEntry.slave_finished);

        uint64_t request_tick = 0;
        optParamIn(cp, "request_tick", request_tick, 0);
        currDrainEntry.request_tick = (Tick)request_tick;

        if (currDrainEntry.valid) {
            currDrainEntry.original_req = unserializeNocMsgPtr(cp);
            currDrainEntry.oPort =
                getOutportForVnet(currDrainEntry.drain_vnet);
            if (!currDrainEntry.oPort) {
                panic("mmNocSlaveUnit::unserialize: no output port for "
                      "drain_vnet %d",
                      currDrainEntry.drain_vnet);
            }
        } else {
            currDrainEntry.original_req.reset();
            currDrainEntry.oPort = nullptr;
        }
    };

    auto unserialize_state = [&](bool legacy_layout) {
        uint64_t tmp = 0;
        if (legacy_layout) {
            std::vector<std::string> lead_sections = {obj};
            if (!inPorts.empty()) {
                lead_sections.push_back(
                    csprintf("%s.ni_inp_%u", obj.c_str(), (unsigned)inPorts.size() - 1));
            }
            paramInAnySection(cp, lead_sections, "S_DATA_WIDTH", tmp, obj);
        } else {
            ::gem5::paramIn(cp, "S_DATA_WIDTH", tmp);
        }
        S_DATA_WIDTH = (uint32_t)tmp;

        writeDataAssemblyByPacket.clear();
        uint64_t write_data_assembly_size = 0;
        if (legacy_layout) {
            std::vector<std::string> lead_sections = {obj};
            if (!inPorts.empty()) {
                lead_sections.push_back(
                    csprintf("%s.ni_inp_%u", obj.c_str(), (unsigned)inPorts.size() - 1));
            }
            optParamInSection(cp, lead_sections.back(),
                              "writeDataAssemblyByPacketSize",
                              write_data_assembly_size) ||
            optParamInSection(cp, lead_sections.front(),
                              "writeDataAssemblyByPacketSize",
                              write_data_assembly_size);
        } else {
            optParamIn(cp, "writeDataAssemblyByPacketSize",
                       write_data_assembly_size, false);
        }
        for (size_t i = 0; i < write_data_assembly_size; i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("writeDataAssembly%u", (unsigned)i));
            int packet_id = 0;
            MmWriteDataAssemblyState state;
            ::gem5::paramIn(cp, "packet_id", packet_id);
            ::gem5::arrayParamIn(cp, "aggregateData",
                                 state.aggregateData.data(),
                                 state.aggregateData.size());
            ::gem5::paramIn(cp, "aggregateStrobe", state.aggregateStrobe);
            writeDataAssemblyByPacket[packet_id] = state;
        }
        for (size_t i = 0; i < NUM_SUPPORTED_AXI_IDS; i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("readRespState%u", (unsigned)i));
            auto &st = m_read_response_state[i];
            ::gem5::paramIn(cp, "active", st.active);
            ::gem5::arrayParamIn(cp, "accumBuffer", st.accumBuffer.data(),
                                 st.accumBuffer.size());
            ::gem5::paramIn(cp, "accumStrobe", st.accumStrobe);
            ::gem5::paramIn(cp, "accumOffset", tmp);
            st.accumOffset = (uint8_t)tmp;
            st.nppMsg = std::dynamic_pointer_cast<NocMemoryMsg>(
                unserializeNocMsgPtrOptional(cp));
            ::gem5::paramIn(cp, "packet_id", st.packet_id);
            ::gem5::paramIn(cp, "num_flits", tmp);
            st.num_flits = (uint8_t)tmp;
            ::gem5::paramIn(cp, "total_bytes_needed", st.total_bytes_needed);
            ::gem5::paramIn(cp, "bytes_received", st.bytes_received);
            ::gem5::paramIn(cp, "bytes_sent", st.bytes_sent);
            ::gem5::paramIn(cp, "original_beat_size", tmp);
            st.original_beat_size = (uint8_t)tmp;
            optParamIn(cp, "original_read_bytes",
                       st.original_read_bytes, 0);
            optParamIn(cp, "auto_per_flit_gap",
                       st.auto_per_flit_gap, false);
        }

        if (legacy_layout) {
            unserializeU32TickMap(cp, "last_tail", last_tail_flit_tick);
            unserializeU32BoolMap(cp, "is_b2b", is_back_to_back);
            unserializeU32BoolMap(cp, "bram_pen", bram_penalty_due);

            std::vector<std::string> tail_sections = {
                obj,
                csprintf("%s.readRespState%u", obj.c_str(),
                         (unsigned)NUM_SUPPORTED_AXI_IDS - 1),
            };
            paramInAnySection(cp, tail_sections, "m_read_flits_in_burst",
                              m_read_flits_in_burst, obj);
            paramInAnySection(cp, tail_sections, "m_read_flits_total",
                              m_read_flits_total, obj);
            paramInAnySection(cp, tail_sections, "m_last_read_flit_inject_tick",
                              tmp, obj);
            m_last_read_flit_inject_tick = (Tick)tmp;
            optParamInSection(cp, tail_sections.front(), "m_write_resp_total",
                              m_write_resp_total) ||
            optParamInSection(cp, tail_sections.back(), "m_write_resp_total",
                              m_write_resp_total);
        } else {
            Serializable::ScopedCheckpointSection timing_sec(
                cp, "writeRespTimingState");
            unserializeU32TickMap(cp, "last_tail", last_tail_flit_tick);
            unserializeU32BoolMap(cp, "is_b2b", is_back_to_back);
            unserializeU32BoolMap(cp, "bram_pen", bram_penalty_due);

            ::gem5::paramIn(cp, "m_read_flits_in_burst", m_read_flits_in_burst);
            ::gem5::paramIn(cp, "m_read_flits_total", m_read_flits_total);
            ::gem5::paramIn(cp, "m_last_read_flit_inject_tick", tmp);
            m_last_read_flit_inject_tick = (Tick)tmp;
            optParamIn(cp, "m_write_resp_total", m_write_resp_total, 0);
        }

        unserialize_drain_entry(legacy_layout);

        {
            Serializable::ScopedCheckpointSection sec(cp, "readTracker");
            readTracker.unserialize(cp);
        }
        {
            Serializable::ScopedCheckpointSection sec(cp, "writeTracker");
            writeTracker.unserialize(cp);
        }
    };

    if (has_state_section) {
        Serializable::ScopedCheckpointSection sec(cp, "mm_nsu_state");
        unserialize_state(false);
    } else {
        unserialize_state(true);
    }
}

}
}
}
