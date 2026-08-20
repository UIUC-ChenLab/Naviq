#include "noc/core/network/nmu_types/mmNocMasterUnit.hh"
#include "base/logging.hh"
#include "debug/NocDebugVerbose.hh"
#include "debug/NocTiming.hh"
#include "debug/NocPacketFlow.hh"
#include <algorithm>
#include <bit> // For std::countl_zero
#include <cstdlib>
#include <string>
#include <vector>

namespace gem5 {
namespace noc {
namespace garnet {

namespace {

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


mmNocMasterUnit::mmNocMasterUnit(const Params &p) : NocMasterUnit(p),
    m_rrob(p.rrob),
    writeRequestSSIDDelayed(false),
    lastNppReadyTick(0),
    dequeueIntermediateEvent(*this)
{
    if (!m_rrob) {
        panic("mmNocMasterUnit: required parameter 'rrob' is null. "
              "Instantiate and pass an rrob SimObject (ReadReorderBuffer) to this NMU.");
    }
    m_rrob->setWakeupHandler([this](AxiID axi_id) { this->rrobWriteCallback(axi_id); });
    writeBuffer.setHeadReadyHandler([this](aximmRWAddr nppRequest, std::array<aximmRWData, 4> nppData){
        this->bufferHeadReadyHandler(nppRequest, nppData);});
    writeTracker.setWriteRespReadyHandler([this](uint8_t axi_id){this->writeRespReadyHandler(axi_id);});
    internal_ar_ready = true;
    internal_aw_ready = true;
    m_read_response_delay_cycles = p.read_response_delay_cycles;
    if (const char *env = std::getenv("NOC_LEGACY_SPLIT_READ_REQ_CHUNKS")) {
        m_packetize_read_req_chunks =
            std::string(env) == "0" || std::string(env) == "false";
    }
}

// void
// NocMasterUnit::init()
// {
//     // Initialization code
// }

bool
mmNocMasterUnit::flitisizeMessage(MsgPtr msg_ptr, int vnet)
{
// Convert a high-level message into flits for transmission
    // Implement flit creation and enqueue into the appropriate VC

    //save vnet for receiving interface
    msg_ptr->setVnet(vnet);

    auto mem_msg_ptr = dynamic_cast<NocMemoryMsg*>(msg_ptr.get());
    if (!mem_msg_ptr) {
        panic("Failed to cast MsgPtr to NocMemoryMsg");
    }

    aximmRWAddr axi_payload;
    aximmRWData axi_data_payload;
    bool is_data = false;

    MessagePayload payload = mem_msg_ptr->getPayload();

    if(aximmRWAddr* p = std::get_if<aximmRWAddr>(&payload)) {
        axi_payload = *p;
    } else if(aximmRWData* p = std::get_if<aximmRWData>(&payload)) {
        axi_data_payload = *p;
        is_data = true;
    } else {
        panic("mmNocMasterUnit::flitisizeMessage: Unsupported payload type");
    }

    OutputPort *oPort = getOutportForVnet(vnet);
    assert(oPort);


    int vc = 0;
    int cmd_int = static_cast<int>(axi_payload.cmd);

    if (is_data) {
        // if this is a write data message, flitisize it
        const int32_t dbg =
            mem_msg_ptr->hasDebugId() ? mem_msg_ptr->getDebugId() : -1;
        if (!flitisizeWriteData(axi_data_payload, dbg)) {
            return false; //failed to flitisize write data
        }
    } else if (axi_payload.cmd == gem5::noc::AximmCommand::READ){
        gem5::ruby::NodeID destID = m_net_ptr->getDestFromAddress(m_id, axi_payload.addr);
        if (destID == -1) {
            return handleReadDecErr(axi_payload);
        }

        vc = m_net_ptr->getPathVC(m_id, destID, cmd_int);
        if (!flitisizeReadRequest(msg_ptr, vnet, axi_payload, oPort, destID, vc))
            return false; //failed to flitisize read request
    } else if (axi_payload.cmd == gem5::noc::AximmCommand::WRITE) {
        gem5::ruby::NodeID destID = m_net_ptr->getDestFromAddress(m_id, axi_payload.addr);
        if (destID == -1) {
            return handleWriteDecErr(axi_payload);
        }

        vc = m_net_ptr->getPathVC(m_id, destID, cmd_int);

        if (!flitisizeWriteRequest(msg_ptr, axi_payload, oPort, destID, vc))
            return false; //failed to flitisize write request
    } else {
        panic("mmNocMasterUnit::flitisizeMessage: Unsupported AXI command");
    }

    m_ni_out_vcs_enqueue_time[vc] = curTick();
    outVcState[vc].setState(gem5::ruby::garnet::ACTIVE_, curTick());
    DPRINTF(NocTiming, "AXI MM NMU %d Queued data to be sent out\n", m_id);

    return true;
}

bool
mmNocMasterUnit::flitisizeReadRequest(MsgPtr msg_ptr, int vnet, aximmRWAddr axi_payload, NetworkInterface::OutputPort *oPort, gem5::ruby::NodeID destID, int vc) {

    std::vector<aximmRWAddr> NPP_read_payloads = chopInto256BRequests(axi_payload);
    uint16_t total_size = axi_payload.getTotalByteSize();

    bool need_next_entry;
    bool contains_last;
    uint8_t last_beat_idx;

    uint16_t total_AXI_rrob_entries = ceil((double)total_size / 32.0);
    // Check if request exceeds maximum RROB capacity (max_entries × 32 bytes)
    uint16_t max_read_size_bytes = m_rrob->getMaxEntries() * 32;
    if (total_size > max_read_size_bytes) {
        panic("mmNocMasterUnit::flitisizeReadRequest: Read request size (%d bytes) exceeds "
              "maximum RROB capacity (%d bytes). Reduce transaction size (size=%d, len=%d).",
              total_size, max_read_size_bytes, axi_payload.size, axi_payload.len);
    }

    // make sure there's enough room in rrob for all these NPP reads.
    // if not, fail before any flitisizing is done
    // TODO always correct that total_size/32 will match # of RROB entries you'd get
    // if you loop through all chopped NPP read reqeuests and calculate?
    if (m_rrob->getNumRemainingEntries() < total_AXI_rrob_entries) {
        return false;
    }

    int beat_size_bytes = axi_payload.getBeatByteSize();

    uint16_t row_base = 0;
    const bool packetize_read_req_chunks =
        m_packetize_read_req_chunks &&
        NPP_read_payloads.size() > 1 &&
        NPP_read_payloads.size() <= NetworkInterface::kNppAssemblerMaxFlits;
    const int read_req_packet_id =
        packetize_read_req_chunks ? m_net_ptr->getNextPacketID() : -1;

    for (int i=0; i<NPP_read_payloads.size(); i++){
        // do per NPP read request packet id
        int packet_id =
            packetize_read_req_chunks ? read_req_packet_id :
            m_net_ptr->getNextPacketID();

        aximmRWAddr NPP_read_payload = NPP_read_payloads[i];
        uint32_t npp_bytes = NPP_read_payload.getTotalByteSize();
        uint16_t total_NPP_rrob_entries = ceil((double)NPP_read_payload.getTotalByteSize() / 32.0);

        // printf("[TRACE-1] NMU Request: Orig(Addr=0x%lx, Size=%d, Len=%d) -> Net(Addr=0x%lx, Size=%d, Len=%d)\n",
        // axi_payload.addr, axi_payload.size, axi_payload.len,
        // NPP_read_payload.addr, NPP_read_payload.size, NPP_read_payload.len);

        // create a new NocMemoryMsg
        auto NPPMsg = std::shared_ptr<NocMemoryMsg>(
            new NocMemoryMsg(clockEdge(),
            msg_ptr->getNocSystem(),
            AxiMsgSizeType::AR,
            NPP_read_payload));

        //save vnet for receiving interface
        NPPMsg->setVnet(vnet);
        NPPMsg->setOriginalReadBytes(total_size);
        NPPMsg->setFinalReadChunk(i == (NPP_read_payloads.size() - 1));
        if (msg_ptr->hasDebugId()) {
            const int32_t dbg = msg_ptr->getDebugId();
            NPPMsg->setDebugId(dbg);
            NPPMsg->setNetworkProbeDebugIds({dbg});
        }
        uint8_t rrob_tag;

        // reserve a RROB entry for every 32 bytes of this request
        for (int r=0; r<total_NPP_rrob_entries; r++){
            // if a 64-byte beat, need to mark each of first RROB entry pairs as needing next entry
            // to be filled in order to read out data once response received from NSU
            need_next_entry = beat_size_bytes > 32 && (r%2 == 0);
            uint16_t global_row_index = row_base + r;
            // Marks only the final row across all NPP chunks.
            contains_last = (global_row_index == (total_AXI_rrob_entries - 1));

            // Size this row by actual NPP payload bytes, not always a full 32B line.
            uint32_t bytes_consumed = r * 32;
            uint32_t bytes_in_row = std::min<uint32_t>(32, npp_bytes - bytes_consumed);
            if (beat_size_bytes <= 32) {
                panic_if((bytes_in_row % beat_size_bytes) != 0,
                    "RROB row bytes (%u) not divisible by beat size (%d) for AXI ID %u",
                    bytes_in_row, beat_size_bytes, NPP_read_payload.id);
                uint32_t beats_in_row = bytes_in_row / beat_size_bytes;
                panic_if(beats_in_row == 0,
                    "RROB row has zero beats for AXI ID %u", NPP_read_payload.id);
                last_beat_idx = static_cast<uint8_t>(beats_in_row - 1);
            } else {
                // 64B beat path uses paired entries (need_next_entry), beat index stays 0.
                last_beat_idx = 0;
            }

            rrob_tag = m_rrob->reserve( NPP_read_payload.id,
                                        beat_size_bytes,
                                        contains_last,
                                        last_beat_idx,
                                        vnet,
                                        need_next_entry);
            NPPMsg->setRROBTag(r, rrob_tag);
        }
        row_base += total_NPP_rrob_entries;

        // each NPP read request will need 1 flit sent out
        NocRouteInfo route;
        route.vnet = vnet;
        route.net_dest = msg_ptr->getDestination();
        route.src_ni = m_id;
        route.src_router = oPort->routerID();
        route.dest_ni = destID; //doesn't seem to matter, just used for printing
        // route.dest_ni = 1-m_id; // for now, just set to 0
        route.dest_router = m_net_ptr->get_router_id(destID, vnet);

        // initialize hops_traversed to -1
        // so that the first router increments it to 0
        route.hops_traversed = -1;
        // create flit
        MsgPtr messagePtr = NPPMsg;
        gem5::ruby::garnet::flit<NocMessage, NocRouteInfo> *fl = new gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>(
            packet_id,
            packetize_read_req_chunks ? i : 0,
            vc, // virtual channel
            vnet, route,
            packetize_read_req_chunks ? NPP_read_payloads.size() : 1,
            messagePtr,
            0, //change bWidth if need to serialize/deserialize
            oPort->bitWidth(), curTick());

        if (!injectFlit(fl, vnet, messagePtr, vc)) {
            delete fl;
            panic(
                "mmNocMasterUnit::flitisizeReadRequest: niOutVc full (vnet=%d vc=%d)",
                vnet, vc);
        }

    }

    m_rrob->incrementNumAxiReads();

    return true;
}

std::vector<aximmRWAddr>
mmNocMasterUnit::chopInto256BRequests(aximmRWAddr og_payload) {

    std::vector<aximmRWAddr> new_payloads;

    uint64_t current_addr = og_payload.addr;
    uint8_t beat_size_log2 = og_payload.size;          // Keep original size (e.g., 1 for 2 bytes)
    uint16_t bytes_per_beat = (1 << beat_size_log2);

    // Total bytes to transfer
    uint32_t bytes_left = (og_payload.len + 1) * bytes_per_beat;

    // keep axi id the same as it ensures ordering
    while (bytes_left > 0) {
        // Create a new payload starting at current address
        aximmRWAddr new_payload = og_payload;
        new_payload.addr = current_addr;
        new_payload.size = beat_size_log2; // Keep original size

        // 2. Calculate distance to next 256-byte boundary
        // Logic: (current_addr | 255) + 1 gets the next multiple of 256
        uint64_t next_boundary = (current_addr | 0xFF) + 1; //(addr + 255) & ~255ULL;
        uint64_t bytes_to_boundary = next_boundary - current_addr;

        // 3. Determine how many bytes we can send in this chunk
        uint32_t bytes_for_this_chunk = std::min((uint32_t)bytes_to_boundary, (uint32_t)bytes_left);
        bytes_for_this_chunk -= (bytes_for_this_chunk % bytes_per_beat);

        // 4. Calculate 'len' (beats - 1) for this chunk
        // (AXI forbids bursts that don't align with their own beat size)
        uint16_t beats_this_chunk = bytes_for_this_chunk / bytes_per_beat;

        panic_if(bytes_for_this_chunk == 0,
            "chopInto256BRequests: start address 0x%lx leaves zero usable bytes "
            "before 256B boundary for %d-byte beats",
            current_addr, bytes_per_beat);

        new_payload.len = beats_this_chunk - 1;

        // 5. Push and Advance
        new_payloads.push_back(new_payload);

        bytes_left -= (beats_this_chunk * bytes_per_beat);
        current_addr += (beats_this_chunk * bytes_per_beat);
    }

    return new_payloads;
}

bool
mmNocMasterUnit::flitisizeWriteRequest(MsgPtr msg_ptr, aximmRWAddr axi_payload, NetworkInterface::OutputPort *oPort, gem5::ruby::NodeID destID, int vc) {

    std::vector<aximmRWAddr> NPP_write_payloads;

    bool SSIDMet = writeTracker.checkSSID(axi_payload.id, destID);

    // only want to do the following once per write request,
    // check if we've seen this same request before but was delayed due to SSID check
    if (!writeRequestSSIDDelayed) {
        // first chop the entire write into 256B aligned writes
        NPP_write_payloads = chopInto256BRequests(axi_payload);

        // put each NPP into write buffer to await write data
        Tick awArrivalTick = curTick();
        for (int i=0; i<NPP_write_payloads.size(); i++){
            writeBuffer.add(NPP_write_payloads[i], vc, oPort, SSIDMet, awArrivalTick);
        }

        numWriteBufferEntriesCurrRequest = NPP_write_payloads.size();
    }

    // stop now if SSID check not met
    if (!SSIDMet) {
        writeRequestSSIDDelayed = true;
        return false;
    }

    writeTracker.addAxiWriteRequest(axi_payload.id, destID, numWriteBufferEntriesCurrRequest, vc);

    // was delayed by SSID check, mark buffer entry with SSID met now that met
    if (writeRequestSSIDDelayed) {
        writeBuffer.setSSIDMet(numWriteBufferEntriesCurrRequest);
        writeRequestSSIDDelayed = false;
    }

    return true;
}

void
mmNocMasterUnit::bufferHeadReadyHandler(aximmRWAddr nppRequest, std::array<aximmRWData, 4> nppData)
{
    if (currDrainEntry.valid) {
        return;
    }

    aximmWriteBufferEntry wbEntry;

    wbEntry = writeBuffer.readHead();
    writeBuffer.removeHead();

    if (wbEntry.isDecErr) {
        DPRINTF(NocTiming,
                "AXIMM NMU: Drained Write Data for DECERR (Addr: %lu). Discarding.\n",
                wbEntry.nppRequest.addr);
        return; // Just exit. Data is drained/removed. No flits sent.
    }

    // flit per 16B of write data, +1 for any <16B left over if not divisible by 16, +1 for head flit corresponding to write req
    uint16_t total_data_bytes = wbEntry.nppRequest.getTotalByteSize();
    int num_data_flits = (total_data_bytes + 15) / 16;
    int total_flits = 1 + num_data_flits; // +1 for Head Flit

    // --- NMU Prep Delay Calculation ---
    Tick period = clockPeriod();
    constexpr int FIXED_OVERHEAD = 8;

    // Hot start: pipeline was busy with previous NPP, no startup overhead
    Tick hotReady = lastNppReadyTick + num_data_flits * period;
    if (num_data_flits < 16)
        hotReady += period;  // +1 back-to-back transition for non-full NPP

    // Cold start: pipeline was idle, use per-entry beat tracking + startup overhead
    Tick coldReady = wbEntry.pipelineEndTick + FIXED_OVERHEAD * period;

    if (lastNppReadyTick > curTick()) {
        coldReady += period;
    }
    if (num_data_flits >= 16)
        coldReady -= period;  // full NPP -1 optimization

    // Whichever is later wins
    Tick readyTick = std::max(hotReady, coldReady);

    DPRINTF(NocTiming, "AXIMM NMU: NPP Delay Calc (Addr: %lu, df: %d)\n",
            wbEntry.nppRequest.addr, num_data_flits);
    DPRINTF(NocTiming, "     hotReady: %lu, coldReady: %lu, readyTick: %lu, curTick: %lu, total_flits: %d, total_data_bytes: %d\n",
            hotReady, coldReady, readyTick, curTick(), total_flits, total_data_bytes);
    DPRINTF(NocTiming, "     lastNppReadyTick: %lu, pipelineEndTick: %lu, creationTick: %lu\n",
            lastNppReadyTick, wbEntry.pipelineEndTick, wbEntry.creationTick);

    lastNppReadyTick = readyTick;

    // --- End Delay Calculation ---

    int packet_id = m_net_ptr->getNextPacketID();

    NocRouteInfo route;
    route.src_ni = m_id;
    route.src_router = wbEntry.oPort->routerID();
    route.dest_ni = writeTracker.getDestID(nppRequest.id);
    route.dest_router = m_net_ptr->get_router_id(route.dest_ni, AW_VNET);
    route.hops_traversed = -1;

    MessagePayload writeReqPayload = wbEntry.nppRequest;
    MessagePayload writeDataPayload = aximmRWData();

    // create a new NocMemoryMsg
    MsgPtr HeadMsg = std::shared_ptr<NocMemoryMsg>(new NocMemoryMsg(clockEdge(), nullptr, AxiMsgSizeType::AW, writeReqPayload));
    auto BodyMsgMem = std::make_shared<NocMemoryMsg>(clockEdge(), nullptr, AxiMsgSizeType::W, writeDataPayload, wbEntry.nppData);
    HeadMsg->setVnet(AW_VNET);
    BodyMsgMem->setVnet(W_VNET);

     //save vnet for receiving interface
    // BodyMsgMem->setBeatSize(wbEntry.nppRequest.size);
    BodyMsgMem->setBeatSize(6); // 64-byte beats
    // BodyMsgMem->setBurstLen(wbEntry.nppRequest.len);
    BodyMsgMem->setBurstLen(4); // 16 beats
    BodyMsgMem->setNumFlits(num_data_flits);
    MsgPtr BodyMsg = BodyMsgMem;

    if (wbEntry.probeDebugId >= 0) {
        const int32_t dbg = wbEntry.probeDebugId;
        const std::vector<int32_t> net_dbg{{dbg}};
        if (auto head_mm = std::dynamic_pointer_cast<NocMemoryMsg>(HeadMsg)) {
            head_mm->setDebugId(dbg);
            head_mm->setNetworkProbeDebugIds(net_dbg);
        }
        BodyMsgMem->setDebugId(dbg);
        BodyMsgMem->setNetworkProbeDebugIds(net_dbg);
    }

    DPRINTF(NocPacketFlow, "AXIMM NMU: Sending Write Packet (PktID: %d)\n", packet_id);
    DPRINTF(NocPacketFlow,"     Total Data Bytes: %d\n", total_data_bytes);
    DPRINTF(NocPacketFlow,"     Total Flits: %d\n", num_data_flits);

    // Inspect the packed data/strobes in the buffer entry
    int num_npp_beats = (num_data_flits + 3) / 4;  // 4 flits per 64B NPP beat
    for (int i = 0; i < num_npp_beats; i++) {
        uint64_t strobe = wbEntry.nppData[i].wstrb;
        DPRINTF(NocPacketFlow,"     [Flit %d] Strobe: 0x%lx (Popcount: %d)\n",
               i+1, strobe, __builtin_popcountll(strobe));
    }

    currDrainEntry.valid = true;
    currDrainEntry.entry = wbEntry;
    currDrainEntry.readyTick = readyTick;
    currDrainEntry.flit_id_to_send = 0;
    currDrainEntry.packet_id = packet_id;
    currDrainEntry.route = route;
    currDrainEntry.total_flits = total_flits;
    currDrainEntry.headMsg = HeadMsg;
    currDrainEntry.bodyMsg = BodyMsg;

    schedule(dequeueIntermediateEvent, clockEdge(Cycles(1))); // TODO: did this add an extra cycle of delay?
}

void
mmNocMasterUnit::dequeueIntermediate(){

    if (!currDrainEntry.valid) {
        return;
    }

    if (currDrainEntry.flit_id_to_send >= currDrainEntry.total_flits) {
        return;
    }

    const Tick flit_ready_tick = currDrainEntry.readyTick +
        currDrainEntry.flit_id_to_send * clockPeriod();
    if (curTick() < flit_ready_tick) {
        schedule(dequeueIntermediateEvent, flit_ready_tick);
        return;
    }

    // Backpressure: NI output VC queue capped at kNiOutVcMaxFlits flits.
    if (niOutVcs[currDrainEntry.entry.vc].isFull()) {
        schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));
        return;
    }

    // Head flit carries AW (address); body flits carry W data — match AXIMM NI CDC VNs.
    const int flit_vnet = (currDrainEntry.flit_id_to_send == 0) ? AW_VNET : W_VNET;
    currDrainEntry.route.vnet = flit_vnet;
    currDrainEntry.route.dest_router =
        m_net_ptr->get_router_id(currDrainEntry.route.dest_ni, flit_vnet);

    gem5::ruby::garnet::flit<NocMessage, NocRouteInfo> *fl = new gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>(
        currDrainEntry.packet_id,
        currDrainEntry.flit_id_to_send, // id 0, each flit by itself
        currDrainEntry.entry.vc, // virtual channel
        flit_vnet,
        currDrainEntry.route,
        currDrainEntry.total_flits,
        currDrainEntry.flit_id_to_send==0 ? currDrainEntry.headMsg : currDrainEntry.bodyMsg,
        0, //change bWidth if need to serialize/deserialize
        currDrainEntry.entry.oPort->bitWidth(), flit_ready_tick);


    if (!injectFlit(fl, flit_vnet, currDrainEntry.flit_id_to_send==0 ? currDrainEntry.headMsg : currDrainEntry.bodyMsg, currDrainEntry.entry.vc)) {
        delete fl;
        schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));
        return;
    }

    if (currDrainEntry.flit_id_to_send == currDrainEntry.total_flits - 1) {
        currDrainEntry.valid = false;
        writeBuffer.notifyTransmitComplete();
    } else {
        currDrainEntry.flit_id_to_send++;
        schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));
    }
}

// find next available burst in RROB to read out
// don't actually mark it as read (only when know slave had valid high)
void
mmNocMasterUnit::rrobWriteCallback(AxiID axi_id){
    Tick curTime = clockEdge();
    std::vector<MsgPtr> read_resp_msgs = m_rrob->generateAxiReadPayloads(axi_id, curTime);

    // std::vector<std::tuple<aximmRWData, uint8_t, uint8_t>> npp_read_payloads = m_rrob->generateAxiReadPayloads(axi_id);
    for (auto& msg : read_resp_msgs) {
        auto castedMessage = std::dynamic_pointer_cast<NocMemoryMsg>(msg);
        if (!castedMessage)
            panic("rrobWriteCallback: msg is not NocMemoryMsg");
        int vnet = m_rrob->getVnet(axi_id, castedMessage->getAxiRROBTag());
        MessageBuffer *const obuf = outNode_ptr[vnet];
        panic_if(!obuf, "mmNocMasterUnit::rrobWriteCallback: outNode vnet %d null",
            vnet);
        DPRINTF(NocDebugVerbose,
            "[NMU outNode R] ni=%d vnet=%d msgbuf_size=%u need_slots=1 tick=%llu\n",
            m_id, vnet, obuf->getSize(curTime),
            (unsigned long long)curTime);

        if (outNode_ptr[vnet]->areNSlotsAvailable(1, curTime)) {

            // --- NMU Read Response Delay Formula ---
            Tick period = clockPeriod();
            // Idle Cool-Down Check: If gap is large, Pipeline State entirely Resets
            if (curTime > m_last_read_beat_tick + NMU_COOL_DOWN_CYCLES * period) {
                m_read_flits_processed = 0;
            }

            int beat_size = castedMessage->getBeatSize();
            int delay;
            int group = 0;

            if (m_read_response_delay_cycles >= 0) {
                delay = m_read_response_delay_cycles;
            } else {
                // Mathematical Pipeline delays (-1 for MTileController hop)
                if (beat_size < 16) {
                    // Keep sub-16B beats at a fixed delay to preserve FIFO ordering
                    // when multiple R beats are enqueued at the same clock edge.
                    delay = NMU_SMALL_READ_BEAT_DELAY_CYCLES;
                } else if (beat_size == 64) {
                    delay = 10 - 1;
                } else if (beat_size == 32) {
                    group = (m_read_flits_processed / 2) % 2;
                    delay = ((group == 0) ? 8 : 7) - 1;
                } else {
                    group = (m_read_flits_processed / 4) % 3;
                    delay = (7 - group) - 1;
                }
            }

            int num_flits = std::max(1, beat_size / 16);
            m_read_flits_processed += num_flits;
            m_last_read_beat_tick = curTime;

        // Space is available. Enqueue to protocol buffer.
            DPRINTF(NocTiming, "AXIMM NMU %d enqueing R-beat to TC, id = %d, beat size = %d, delay = %d, group = %d\n", m_id, axi_id, castedMessage->getBeatSize(), delay, group);
            // DPRINTF(NocTiming, "m_read_flits_processed = %d, num_flits = %d, m_last_read_beat_tick = %d\n", m_read_flits_processed, num_flits, m_last_read_beat_tick);
            outNode_ptr[vnet]->enqueue(msg, curTime,
                                       cyclesToTicks(Cycles(delay)), // Apply precision calculated delay
                                       m_net_ptr->getRandomization(),
                                       m_net_ptr->getWarmupEnabled());

        } else {
            DPRINTF(NocDebugVerbose,
                "[NMU outNode R FULL] ni=%d vnet=%d msgbuf_size=%u need_slots=1 "
                "tick=%llu\n",
                m_id, vnet, obuf->getSize(curTime),
                (unsigned long long)curTime);
            panic("mmNocMasterUnit::rrobWriteCallback: No space available in output buffer");
        }
    }

}

// tile controller calls this when slave has read message
// use it to free corresponding RROB entries or mark sections as free
void
mmNocMasterUnit::msgReadCallback(const NocMessage* msg){

    // if this message corresponded to size 64 read resp, mark 2 RROB entries as read
    // so half a beat each (function name bit misleading in this case)
    // printf("NocMasterUnit::msgReadCallback called\n");
    aximmRWData axi_payload;
    // getPayload() returns a value. The pointer obtained from this local
    // variant remains valid until the AXI payload is copied below.
    MessagePayload payload = msg->getPayload();
    if(aximmRWData* p = std::get_if<aximmRWData>(&payload)) {
        axi_payload = *p;
    } else {
        panic("mmNocMasterUnit::msgReadCallback: Unsupported payload type");
    }
    const NocMemoryMsg* castedMsg = dynamic_cast<const NocMemoryMsg*>(msg);
    m_rrob->markBeatRead(axi_payload.id, castedMsg->getAxiRROBTag(), castedMsg->getRROBBeatID());
}

bool
mmNocMasterUnit::flitisizeWriteData(aximmRWData axi_payload, int32_t probe_debug_id){

    writeBuffer.write(axi_payload.data, axi_payload.wstrb, curTick(), clockPeriod(),
                      probe_debug_id);

    return true;
}



bool
mmNocMasterUnit::getAxiRAddrReady(bool upstreamValid, aximmMasterState upstreamState){

    // calculate current size of protocol in buffer for AR
    // this plus number of outstanding read requests internally (in rrob)
    // plus 1 if accepting a request current cycle
    // must be <64 to accept a new Axi Read

    int num_buffered_read_requests = 0;
    bool accepting_AR_curr_cycle = (upstreamValid && internal_ar_ready);
    uint8_t num_AR_accepting_curr_cycle = accepting_AR_curr_cycle;

    MessageBuffer *b = inNode_ptr[AR_VNET];
    if (b != nullptr) {
        num_buffered_read_requests += b->getMsgCount();
    }

    bool new_ready = (num_AR_accepting_curr_cycle + num_buffered_read_requests + m_rrob->getNumAxiReads()) < 64;

    internal_ar_ready = new_ready;
    return new_ready;

}

bool
mmNocMasterUnit::getAxiWAddrReady(bool upstreamValid, aximmMasterState upstreamState){

    // calculate current size of protocol in buffer for AW
    // this plus number of outstanding write requests internally (in write tracker)
    // plus 1 if accepting a request current cycle
    // must be <64 to accept a new Axi Write

    int num_buffered_write_requests = 0;
    bool accepting_AW_curr_cycle = (upstreamValid && internal_aw_ready);
    uint8_t num_AW_accepting_curr_cycle = accepting_AW_curr_cycle;

    MessageBuffer *b = inNode_ptr[AW_VNET];
    if (b != nullptr) {
        num_buffered_write_requests += b->getMsgCount();
    }

    bool new_ready = (num_AW_accepting_curr_cycle + num_buffered_write_requests + writeTracker.getNumEntries()) < 64;
    internal_aw_ready = new_ready;
    return new_ready;
}

bool
mmNocMasterUnit::getAxiWReady(bool upstreamValid, aximmMasterState upstreamState)
{
    (void)upstreamValid;
    (void)upstreamState;
    //TODO have this function look at size of beat to actually know if room in write buffer

    // also look at size of data beat may currently be accepting?

    return (writeBuffer.getSize() < 512);
}

bool
mmNocMasterUnit::depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit)
{

    aximmRWData axi_data_payload;
    MessagePayload payload = flit->get_msg_ptr()->getPayload();

    if (std::get_if<aximmRWData>(&payload)) {
        return processReadResponseFlit(flit);
    } else if (aximmWResp* p = std::get_if<aximmWResp>(&payload)){
        return processWriteResponseFlit(*p);
    } else {
        panic("mmNocMasterUnit::depacketizeFlit: Unsupported payload type");
    }
    // temporary, !! change to another location later, counting everything as reads for now


    return true;

}

bool
mmNocMasterUnit::processReadResponseFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit){
    DPRINTF(NocTiming, "NMU %d received a read flit, depackatizing\n", m_id);
    std::array<uint8_t, 16> flit_data;

    // At the top of the function
    DPRINTF(NocPacketFlow,"[TRACE-5] AXIMM NMU Recv: FlitID=%d, RROB Tag=%d, Section=%d\n",
        flit->get_id(), flit->get_rrob_tag(), flit->get_rrob_flit_idx());

    flit_data = flit->get_msg_ptr()->getFlitData(flit->get_id());
    m_rrob->writeFlit(flit->get_rrob_tag(),
                        &flit_data,
                        flit->get_rrob_flit_idx());

    return true;
}

bool
mmNocMasterUnit::processWriteResponseFlit(aximmWResp payload){
    DPRINTF(NocTiming, "AXIMM NMU %d received a write response flit, depacketizing\n", m_id);

    writeTracker.markRespReceived(payload.id, payload.resp == AximmResp::SLVERR);

    return true;
}

void
mmNocMasterUnit::writeRespReadyHandler(uint8_t axi_id){
    Tick curTime = clockEdge();
    WriteTrackerEntry wtEntry = writeTracker.readAndRemoveEntry(axi_id);

    aximmWResp payload;
    payload.id = axi_id;
    // payload.user = //TODO
    payload.resp = (wtEntry.receivedSLVERR) ? AximmResp::SLVERR : AximmResp::OKAY;

    MsgPtr msg = std::shared_ptr<NocMemoryMsg>(new NocMemoryMsg(clockEdge(), nullptr, AxiMsgSizeType::B, payload));

    int vnet = B_VNET;
    MessageBuffer *const bbuf = outNode_ptr[vnet];
    panic_if(!bbuf, "mmNocMasterUnit::writeRespReadyHandler: outNode B null");
    DPRINTF(NocDebugVerbose,
        "[NMU outNode B] ni=%d vnet=%d msgbuf_size=%u need_slots=1 tick=%llu\n",
        m_id, vnet, bbuf->getSize(curTime),
        (unsigned long long)curTime);

    if (outNode_ptr[vnet]->areNSlotsAvailable(1, curTime)) {
    // Space is available. Enqueue to protocol buffer.
        outNode_ptr[vnet]->enqueue(msg, curTime,
                                   cyclesToTicks(Cycles(3)),
                                   m_net_ptr->getRandomization(),
                                   m_net_ptr->getWarmupEnabled());
    } else {
        DPRINTF(NocDebugVerbose,
            "[NMU outNode B FULL] ni=%d vnet=%d msgbuf_size=%u need_slots=1 "
            "tick=%llu\n",
            m_id, vnet, bbuf->getSize(curTime),
            (unsigned long long)curTime);
        panic("mmNocMasterUnit::writeRespReadyHandler: No space available in output buffer");
    }

}

bool
mmNocMasterUnit::handleWriteDecErr(aximmRWAddr axi_payload) {
    Tick curTime = clockEdge();

    MessageBuffer *const bbuf = outNode_ptr[B_VNET];
    panic_if(!bbuf, "mmNocMasterUnit::handleWriteDecErr: outNode B null");
    DPRINTF(NocDebugVerbose,
        "[NMU outNode B decerr] ni=%d vnet=%d msgbuf_size=%u need_slots=1 "
        "tick=%llu\n",
        m_id, B_VNET, bbuf->getSize(curTime),
        (unsigned long long)curTime);

    if (!bbuf->areNSlotsAvailable(1, curTime)) {
        DPRINTF(NocDebugVerbose,
            "[NMU outNode B decerr FULL] ni=%d vnet=%d msgbuf_size=%u "
            "need_slots=1 tick=%llu\n",
            m_id, B_VNET, bbuf->getSize(curTime),
            (unsigned long long)curTime);
        return false;
    }

    aximmWResp err_resp;
    err_resp.id = axi_payload.id;
    err_resp.resp = AximmResp::DECERR;
    err_resp.valid = true;

    MsgPtr msg = std::shared_ptr<NocMemoryMsg>(new NocMemoryMsg(
        curTime, nullptr, AxiMsgSizeType::B, err_resp));

    bbuf->enqueue(msg, curTime, cyclesToTicks(Cycles(1)),
                                 m_net_ptr->getRandomization(),
                                 m_net_ptr->getWarmupEnabled());

    writeBuffer.add(axi_payload, 0, nullptr, true, /*creationTick=*/0, /*isDecErr=*/true);

    return true;
}

bool
mmNocMasterUnit::handleReadDecErr(aximmRWAddr axi_payload) {
    Tick curTime = clockEdge();

    int total_beats = axi_payload.len + 1;

    MessageBuffer *const rbuf = outNode_ptr[R_VNET];
    panic_if(!rbuf, "mmNocMasterUnit::handleReadDecErr: outNode R null");
    DPRINTF(NocDebugVerbose,
        "[NMU outNode R decerr] ni=%d vnet=%d msgbuf_size=%u need_slots=%d "
        "tick=%llu\n",
        m_id, R_VNET, rbuf->getSize(curTime), total_beats,
        (unsigned long long)curTime);

    // Check if we have space in the output buffer for all responses
    if (!rbuf->areNSlotsAvailable(1, curTime)) {
        DPRINTF(NocDebugVerbose,
            "[NMU outNode R decerr FULL] ni=%d vnet=%d msgbuf_size=%u "
            "need_slots=%d tick=%llu\n",
            m_id, R_VNET, rbuf->getSize(curTime), total_beats,
            (unsigned long long)curTime);
        return false; // Retry later
    }

    // Create Error Payload
    aximmRWData err_data;
    err_data.id = axi_payload.id;
    err_data.resp = AximmResp::DECERR;
    err_data.valid = true;

    // Inject Loop
    for (int i = 0; i < total_beats; i++) {
        err_data.last = (i == (total_beats - 1));

        MsgPtr msg = std::shared_ptr<NocMemoryMsg>(new NocMemoryMsg(
            curTime, nullptr, AxiMsgSizeType::R, err_data));

        rbuf->enqueue(msg, curTime, cyclesToTicks(Cycles(1)),
                                     m_net_ptr->getRandomization(),
                                     m_net_ptr->getWarmupEnabled());
    }

    return true;
}

void
mmNocMasterUnit::print(std::ostream& out) const
{
    out << "[AXIMM NocMasterUnit " << m_id << "]";
}

void
mmNocMasterUnit::serialize(CheckpointOut &cp) const
{
    NocMasterUnit::serialize(cp);

    {
        Serializable::ScopedCheckpointSection sec(cp, "mm_nmu_state");
        ::gem5::paramOut(cp, "writeRequestSSIDDelayed", writeRequestSSIDDelayed);
        ::gem5::paramOut(cp, "numWriteBufferEntriesCurrRequest",
                         (uint64_t)numWriteBufferEntriesCurrRequest);
        ::gem5::paramOut(cp, "lastNppReadyTick", (uint64_t)lastNppReadyTick);
        ::gem5::paramOut(cp, "m_read_flits_processed", m_read_flits_processed);
        ::gem5::paramOut(cp, "m_last_read_beat_tick", (uint64_t)m_last_read_beat_tick);

        {
            Serializable::ScopedCheckpointSection state_sec(cp, "writeBuffer");
            writeBuffer.serialize(cp);
        }
        {
            Serializable::ScopedCheckpointSection state_sec(cp, "writeTracker");
            writeTracker.serialize(cp);
        }
    }
}

void
mmNocMasterUnit::unserialize(CheckpointIn &cp)
{
    NocMasterUnit::unserialize(cp);

    const std::string obj = name();
    const bool has_state_section =
        cp.entryExists(obj + ".mm_nmu_state", "writeRequestSSIDDelayed");

    auto unserialize_state = [&](bool legacy_layout) {
        uint64_t tmp = 0;
        if (legacy_layout) {
            std::vector<std::string> sections = {obj};
            if (!inPorts.empty()) {
                sections.push_back(
                    csprintf("%s.ni_inp_%u", obj.c_str(), (unsigned)inPorts.size() - 1));
            }
            paramInAnySection(cp, sections, "writeRequestSSIDDelayed",
                              writeRequestSSIDDelayed, obj);
            paramInAnySection(cp, sections, "numWriteBufferEntriesCurrRequest",
                              tmp, obj);
            numWriteBufferEntriesCurrRequest = (uint8_t)tmp;
            paramInAnySection(cp, sections, "lastNppReadyTick", tmp, obj);
            lastNppReadyTick = (Tick)tmp;
            paramInAnySection(cp, sections, "m_read_flits_processed",
                              m_read_flits_processed, obj);
            paramInAnySection(cp, sections, "m_last_read_beat_tick", tmp, obj);
            m_last_read_beat_tick = (Tick)tmp;
        } else {
            ::gem5::paramIn(cp, "writeRequestSSIDDelayed", writeRequestSSIDDelayed);
            ::gem5::paramIn(cp, "numWriteBufferEntriesCurrRequest", tmp);
            numWriteBufferEntriesCurrRequest = (uint8_t)tmp;
            ::gem5::paramIn(cp, "lastNppReadyTick", tmp);
            lastNppReadyTick = (Tick)tmp;
            ::gem5::paramIn(cp, "m_read_flits_processed", m_read_flits_processed);
            ::gem5::paramIn(cp, "m_last_read_beat_tick", tmp);
            m_last_read_beat_tick = (Tick)tmp;
        }

        {
            Serializable::ScopedCheckpointSection sec(cp, "writeBuffer");
            writeBuffer.unserialize(cp, outPorts);
            writeBuffer.setHeadReadyHandler(
                [this](aximmRWAddr nppRequest, std::array<aximmRWData, 4> nppData) {
                    this->bufferHeadReadyHandler(nppRequest, nppData);
                });
        }
        {
            Serializable::ScopedCheckpointSection sec(cp, "writeTracker");
            writeTracker.unserialize(cp);
            writeTracker.setWriteRespReadyHandler(
                [this](uint8_t axi_id) { this->writeRespReadyHandler(axi_id); });
        }
    };

    if (has_state_section) {
        Serializable::ScopedCheckpointSection sec(cp, "mm_nmu_state");
        unserialize_state(false);
    } else {
        unserialize_state(true);
    }

    m_rrob->setWakeupHandler(
        [this](AxiID axi_id) { this->rrobWriteCallback(axi_id); });
}

}
}
}
