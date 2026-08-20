#include "noc/endpoints/memory/bram/BramEndpoint.hh"


#include "noc/core/network/NocMemoryMsg.hh"
#include "mem/ruby/protocol/MessageSizeType.hh"
#include "base/logging.hh"
#include "debug/NocTiming.hh"
#include "debug/NocControl.hh"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <cmath>
#include <algorithm>
#include <memory>

namespace gem5{

namespace noc{

namespace
{

constexpr const char *kBramReadTraceFilename = "bram_read_trace.csv";

std::ofstream *
bramReadTraceFile()
{
    static std::unique_ptr<std::ofstream> traceFile = []() {
        const char *enabled = std::getenv("NOC_BRAM_READ_TRACE");
        if (!enabled || enabled[0] == '\0' || enabled[0] == '0') {
            return std::unique_ptr<std::ofstream>();
        }

        std::filesystem::path path;
        if (const char *explicitPath = std::getenv("NOC_BRAM_READ_TRACE_PATH")) {
            if (explicitPath[0] != '\0') {
                path = explicitPath;
            }
        }
        if (path.empty()) {
            const char *dir = std::getenv("NOC_CSV_OUTPUT_DIR");
            path = dir && dir[0] != '\0' ? dir : "src/noc/out/csv";
            path /= kBramReadTraceFilename;
        }

        const auto parent = path.parent_path();
        if (!parent.empty()) {
            std::filesystem::create_directories(parent);
        }
        auto file = std::make_unique<std::ofstream>(
            path, std::ios::out | std::ios::trunc);
        if (file->good()) {
            *file << "tick,cycle,event,endpoint,src_ni,axi_id,addr,bytes,"
                     "beat_idx,last,read_req_q,read_req_delay_q,"
                     "original_read_bytes,debug_id,final_read_chunk\n";
        }
        return file;
    }();

    if (!traceFile || !traceFile->good()) {
        return nullptr;
    }
    return traceFile.get();
}

void
traceBramReadEvent(
    const BramEndpoint *endpoint,
    const char *event,
    Tick clockPeriod,
    const aximmRWAddr &addr,
    uint8_t beatIdx,
    bool last,
    size_t readReqQ,
    size_t readReqDelayQ)
{
    std::ofstream *file = bramReadTraceFile();
    if (!file) {
        return;
    }

    const Tick tick = curTick();
    const uint64_t cycle = clockPeriod ? tick / clockPeriod : 0;
    *file << tick << ',' << cycle << ',' << (event ? event : "") << ','
          << endpoint->name() << ',' << addr.sourceNiDebug << ',' << addr.id
          << ",0x" << std::hex << addr.addr << std::dec << ','
          << addr.getTotalByteSize() << ',' << static_cast<unsigned>(beatIdx)
          << ',' << (last ? 1 : 0) << ',' << readReqQ << ','
          << readReqDelayQ << ',' << addr.originalReadBytesDebug << ','
          << addr.debugId << ',' << (addr.finalReadChunkDebug ? 1 : 0)
          << '\n';
}

} // namespace


BramEndpoint::BramEndpoint(const Params &p) :
    NocNode(p),
    system(p.noc_system),
    tile_controller(p.tile_controller),
    baseAddr(p.base_addr),
    memorySize(p.memory_size),
    readLatency(p.read_latency),
    writeLatency(p.write_latency),
    currWriteBeatIdx(0),
    writeInProgress(false)
{
    maxPorts = 1;

    // Initialize BRAM storage
    memoryStorage.resize(memorySize, 0);
    DPRINTF(NocControl, "[TileNSU] Initialized BRAM storage: base=0x%lx size=%zu bytes\n",
            baseAddr, memorySize);

    currentState.r.valid = false;
    currentState.b.valid = false;
    currentState.awReady = false;
    currentState.arReady = false;
    currentState.wReady = false;
    portAssigned = false;
}

// Empty implementation - required for vtable. Overridden by tileNSU_HBM.
void BramEndpoint::updateReadyFlag(bool recvFlag) {
    // Base class does nothing
}

// ====== BRAM Helper Methods ======

bool BramEndpoint::isValidAddress(Addr addr, uint16_t size) const {
    return (addr >= baseAddr) && (addr + size <= baseAddr + memorySize);
}

void BramEndpoint::functionalWrite(Addr addr, const uint8_t* data, size_t size) {
    if (!isValidAddress(addr, size)) {
        panic("BramEndpoint::functionalWrite: Address out of range! Addr=0x%lx Size=%lu (Base=0x%lx Size=%lu)", 
               addr, size, baseAddr, memorySize);
    }
    
    Addr localAddr = toLocalAddr(addr);
    for (size_t i = 0; i < size; i++) {
        memoryStorage[localAddr + i] = data[i];
    }
    DPRINTF(NocControl, "[TileNSU] functionalWrite: Addr=0x%lx (local=0x%lx) Size=%lu\n", 
            addr, localAddr, size);
}

void BramEndpoint::functionalRead(Addr addr, uint8_t* data, size_t size) {
    if (!isValidAddress(addr, size)) {
         panic("BramEndpoint::functionalRead: Address out of range! Addr=0x%lx Size=%lu (Base=0x%lx Size=%lu)", 
                addr, size, baseAddr, memorySize);
    }
    
    Addr localAddr = toLocalAddr(addr);
    for (size_t i = 0; i < size; i++) {
        data[i] = memoryStorage[localAddr + i];
    }
}

bool BramEndpoint::addressInRange(Addr addr) const {
    return isValidAddress(addr, 1);
}

void BramEndpoint::writeToStorage(Addr localAddr, const std::array<uint8_t, 64>& data,
                              uint64_t wstrb, uint8_t beatSize) {
    for (int i = 0; i < beatSize && i < 64; i++) {
        // Check WSTRB bit for this byte
        if ((wstrb >> i) & 1) {
            if (localAddr + i < memorySize) {
                memoryStorage[localAddr + i] = data[i];
                DPRINTF(NocTiming, "[TileNSU] Write byte[%d]=0x%02x to localAddr=0x%lx\n",
                        i, data[i], localAddr + i);
            }
        }
    }
}

void BramEndpoint::readFromStorage(Addr localAddr, std::array<uint8_t, 64>& data,
                               uint8_t beatSize) const {
    for (int i = 0; i < beatSize && i < 64; i++) {
        if (localAddr + i < memorySize) {
            data[i] = memoryStorage[localAddr + i];
        } else {
            data[i] = 0;  // Out of bounds reads return 0
        }
    }
}

// ====== Main Tick Function ======

bool BramEndpoint::tick(int clockDomain){
    DPRINTF(NocControl, "[TileNSU] tick @ %llu "
                "arReady=%d awReady=%d wReady=%d "
                "readReqQ=%zu readReqDelayQ=%zu writeReqQ=%zu "
                "readRespQ=%zu writeRespQ=%zu\n",
                (unsigned long long)curTick(),
                (int)currentState.arReady, (int)currentState.awReady, (int)currentState.wReady,
                readRequests.size(), readRequestsdelay.size(), writeRequests.size(),
                readResponses.size(), writeResponses.size());

    // Handle read requests - buffer them
    if (currentState.arReady && tileControllerState.ar.valid){
        DPRINTF(NocTiming,"[TileNSU] Received read request: addr=0x%lx size=%d len=%d\n",
                tileControllerState.ar.addr, tileControllerState.ar.size, tileControllerState.ar.len);
        traceBramReadEvent(this, "accept_ar", tile_controller->clockPeriod(),
            tileControllerState.ar, 0, false, readRequests.size(),
            readRequestsdelay.size());
        readRequestsdelay.push_back(ReadRequestEntry{
            tileControllerState.ar, 0, curTick() + tile_controller->clockPeriod()});
    }

    // Handle write address - start tracking multi-beat write
    if (currentState.awReady && tileControllerState.aw.valid){
        DPRINTF(NocTiming,"[TileNSU] Received write address: addr=0x%lx size=%d len=%d\n",
                tileControllerState.aw.addr, tileControllerState.aw.size, tileControllerState.aw.len);
        writeRequests.push_back(tileControllerState.aw);
        currWriteRequest = tileControllerState.aw;
        currWriteBeatIdx = 0;
        writeInProgress = true;
    }

    // Handle write data - store with WSTRB
    if (currentState.wReady && tileControllerState.w.valid) {
        handleWriteData(tileControllerState.w);
    }

    if (!delayedWriteResponses.empty()){
        if (curTick() >= delayedWriteResponses.front().second){
            writeResponses.push_back(delayedWriteResponses.front().first);
            delayedWriteResponses.pop_front();
        }
    }

    // Generate write response when last beat received
    if (currentState.wReady && tileControllerState.w.valid && tileControllerState.w.last){
        generateNextWriteResp();
        writeInProgress = false;
    }

    // Generate read response beats
    generateNextReadRespBeat();

    currentState = nextState;
    DPRINTF(NocControl, "[TileNSU] end-of-tick @ %llu\n", (unsigned long long)curTick());
    return true;
}

// ====== Handle Write Data with WSTRB ======

void BramEndpoint::handleWriteData(const aximmRWData& writeData) {
    if (!writeInProgress) {
        DPRINTF(NocTiming, "[TileNSU] WARNING: Received write data without active write request\n");
        return;
    }

    // Calculate address for this beat based on burst type
    uint8_t beatSize = 1 << currWriteRequest.size;
    Addr beatAddr;

    switch (currWriteRequest.burst) {
        case BurstType::INCR:
            beatAddr = currWriteRequest.addr + (currWriteBeatIdx * beatSize);
            break;
        case BurstType::FIXED:
            beatAddr = currWriteRequest.addr;  // Same address for all beats
            break;
        case BurstType::WRAP:
            // Wrap burst - address wraps at boundary
            {
                Addr wrapBoundary = (currWriteRequest.len + 1) * beatSize;
                Addr offset = (currWriteBeatIdx * beatSize) % wrapBoundary;
                Addr alignedAddr = currWriteRequest.addr & ~(wrapBoundary - 1);
                beatAddr = alignedAddr + offset;
            }
            break;
        default:
            beatAddr = currWriteRequest.addr + (currWriteBeatIdx * beatSize);
    }

    DPRINTF(NocTiming, "[TileNSU] Write data beat %d: addr=0x%lx size=%d wstrb=0x%lx\n",
            currWriteBeatIdx, beatAddr, beatSize, writeData.wstrb);

    // Check address validity
    if (!isValidAddress(beatAddr, beatSize)) {
        DPRINTF(NocTiming, "[TileNSU] Write to invalid address 0x%lx (base=0x%lx size=%zu)\n",
                beatAddr, baseAddr, memorySize);
        // Continue - response will indicate error
    } else {
        // Write to storage with WSTRB masking
        Addr localAddr = toLocalAddr(beatAddr);
        writeToStorage(localAddr, writeData.data, writeData.wstrb, beatSize);
    }

    currWriteBeatIdx++;
}

void BramEndpoint::update(int portID, State* inputNocInterfaceState)
{
    if (portID != 0)
        panic("BramEndpoint::update invalid portID %d", portID);
    auto* masterState = dynamic_cast<aximmMasterState*>(inputNocInterfaceState);
    if (!masterState) {
        panic("BramEndpoint::update expected aximmMasterState");
    }
    updateTileNSU(*masterState);
}

State*
BramEndpoint::getCurrentState(int portID)
{
    if (portID != 0)
        panic("BramEndpoint::getCurrentState invalid portID %d", portID);
    return &currentState;
}

int
BramEndpoint::assignPort(const std::string &endpointName)
{
    if (endpointName == portEndpointNames[0] && !portAssigned) {
        portAssigned = true;
        return 0;
    }
    panic("BramEndpoint::assignPort invalid endpointName: %s",
          endpointName.c_str());
}

void BramEndpoint::updateTileNSU(aximmMasterState tileControllerState){
    // if master accepting read response this cycle, dequeue it
    if (tileControllerState.rReady && currentState.r.valid){
        // dequeue the read response
        readResponses.pop_front();
        nextState.r = this->getNextAxiResponse();
    } else if(!currentState.r.valid){
        // no valid request this cycle, get one if ready for next cycle
        nextState.r = this->getNextAxiResponse();
    } else {
        // master (tileController) wasn't ready, but current state was valid, maintain state
        nextState.r = currentState.r;
    }

    // if master accepting write response this cycle, dequeue it
    if (tileControllerState.bReady && currentState.b.valid){
        // dequeue the write response that was read
        writeResponses.pop_front();
        nextState.b = this->getNextWriteResponse();
    } else if (!currentState.b.valid){
        // no valid response this cycle, get one if ready for next cycle
        nextState.b = this->getNextWriteResponse();
    } else {
        // master (tileController) wasn't ready, but current state was valid, maintain state
        nextState.b = currentState.b;
    }

    nextState.arReady = true;
    nextState.awReady = true;
    nextState.wReady = true;

    this->tileControllerState = tileControllerState;
}

aximmRWData BramEndpoint::getNextAxiResponse(){

    aximmRWData resp;

    if (!readResponses.empty()){
        // peek at the top of the response buffer for the next message
        resp = readResponses.front();
        DPRINTF(NocTiming,"TileNSU generated read response, set response as next state, last = %d\n", resp.last);
    } else {
        resp.valid = false;
    }

    return resp;
}

aximmWResp BramEndpoint::getNextWriteResponse(){

    aximmWResp resp;

    if (!writeResponses.empty()){
        // peek at the top of the response buffer for the next resp
        resp = writeResponses.front();
    } else {
        resp.valid = false;
    }

    return resp;
}

void BramEndpoint::generateNextReadRespBeat(){

    if (!readRequests.empty()){
        // get the next read request
        auto& readReq = readRequests.front();

        // generate next read response beat for this request
        uint8_t beatIdx = readReq.beatIdx;
        bool last = beatIdx == readReq.addr.len;
        traceBramReadEvent(this, "emit_r_beat", tile_controller->clockPeriod(),
            readReq.addr, beatIdx, last, readRequests.size(),
            readRequestsdelay.size());
        generateBeatPayload(readReq.addr, last, beatIdx);

        if (last){
            // if all beats have been sent, remove from queue
            readRequests.pop_front();
        } else {
            // otherwise increment the beat number
            readRequests.front().beatIdx++;
        }
    }
    if (!readRequestsdelay.empty()){
        auto readReq = readRequestsdelay.front();
        traceBramReadEvent(this, "promote_ar", tile_controller->clockPeriod(),
            readReq.addr, readReq.beatIdx, false, readRequests.size(),
            readRequestsdelay.size());
        readRequests.push_back(readReq);
        readRequestsdelay.pop_front();
    }
}

void BramEndpoint::generateNextWriteResp(){

    aximmRWAddr req;
    if (!writeRequests.empty()){
        req = writeRequests.front();
        writeRequests.pop_front();
    } else if (writeInProgress) {
        req = currWriteRequest;
    } else {
        DPRINTF(NocTiming,
                "[TileNSU] WARNING: generating write response without queued AW; "
                "using W channel id=%u\n",
                tileControllerState.w.id);
        req.id = tileControllerState.w.id;
        req.addr = baseAddr;
        req.len = 0;
        req.size = 6;
        req.valid = true;
    }

    // Fetch the simulation clock period dynamically using the attached NocInterface
    Tick period = tile_controller->clockPeriod();
    Tick delta_ticks = curTick() - m_last_w_last_tick;
    uint64_t delta_cycles = delta_ticks / period;
    
    bool apply_penalty = (m_last_w_last_tick != 0) && (delta_cycles < 3);

    aximmWResp resp;
    resp.id = req.id;
    resp.valid = true;

    // Check if entire write was to valid addresses
    uint16_t totalBytes = req.getTotalByteSize();
    if (isValidAddress(req.addr, totalBytes)) {
        resp.resp = AximmResp::OKAY;
    } else {
        resp.resp = AximmResp::DECERR;
        DPRINTF(NocTiming, "[TileNSU] Write response DECERR for addr=0x%lx size=%d\n",
                req.addr, totalBytes);
    }

    if (apply_penalty) {
        delayedWriteResponses.push_back(std::make_pair(resp, curTick() + period));
    } else {
        writeResponses.push_back(resp);
    }

    m_last_w_last_tick = curTick();
}

aximmRWAddr BramEndpoint::getRequestPayload(const NocMemoryMsg* msg_ptr){

    aximmRWAddr axi_payload;
    MessagePayload payload = msg_ptr->getPayload();

    if(aximmRWAddr* p = std::get_if<aximmRWAddr>(&payload)) {
        axi_payload = *p;
    } else {
        panic("BramEndpoint::getRequestPayload: Unsupported payload type");
    }

    return axi_payload;
}

void BramEndpoint::generateBeatPayload(aximmRWAddr readCmd, bool last, uint8_t beatIdx){
    aximmRWData payload;

    payload.cmd = AximmCommand::READ;
    payload.id = readCmd.id;
    payload.last = last;
    payload.valid = true;

    // Validate size field - should be log2(bytes per beat), typically 0-6 for 1-64 bytes
    // Max allowed is 6 (64 bytes = 512 bits, matching payload.data size)
    if (readCmd.size > 6) {
        DPRINTF(NocTiming, "WARNING: BramEndpoint::generateBeatPayload received invalid size=%d (expected 0-6). Clamping to 6.\n", readCmd.size);
        readCmd.size = 6;  // Clamp to max valid value
    }

    // Calculate beat size
    uint8_t beatSize = 1 << readCmd.size;
    beatSize = std::min(beatSize, (uint8_t)64);  // Clamp to max

    // Calculate address for this beat
    Addr beatAddr;
    switch (readCmd.burst) {
        case BurstType::INCR:
            beatAddr = readCmd.addr + (beatIdx * beatSize);
            break;
        case BurstType::FIXED:
            beatAddr = readCmd.addr;
            break;
        case BurstType::WRAP:
            {
                Addr wrapBoundary = (readCmd.len + 1) * beatSize;
                Addr offset = (beatIdx * beatSize) % wrapBoundary;
                Addr alignedAddr = readCmd.addr & ~(wrapBoundary - 1);
                beatAddr = alignedAddr + offset;
            }
            break;
        default:
            beatAddr = readCmd.addr + (beatIdx * beatSize);
    }

    // Check address validity and set response
    if (!isValidAddress(beatAddr, beatSize)) {
        DPRINTF(NocTiming, "[TileNSU] Read from invalid address 0x%lx\n", beatAddr);
        payload.resp = AximmResp::DECERR;
        payload.data.fill(0);  // Return zeros for invalid address
    } else {
        payload.resp = AximmResp::OKAY;
        // Read actual data from storage
        Addr localAddr = toLocalAddr(beatAddr);
        readFromStorage(localAddr, payload.data, beatSize);
        DPRINTF(NocTiming, "[TileNSU] Read beat %d from addr=0x%lx (local=0x%lx) size=%d\n",
                beatIdx, beatAddr, localAddr, beatSize);
    }

    readResponses.push_back(payload);
}


}
}
