#include "noc/endpoints/cpu/CpuNocBridge.hh"
#include "noc/core/network/NocGarnetNetwork.hh"
#include "base/logging.hh"
#include "debug/NocPacketFlow.hh"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

namespace gem5 {
namespace noc {
CpuNocBridge::CpuNocBridge(const Params &p)
    : NocNode(p),
      cpuSidePort(name() + ".cpu_side", this),
      blockedOnResponse(false),
      nocNetwork(p.noc_network),
      simCycles(p.sim_cycles),
      maxOutstanding(p.max_outstanding),
      addrRanges(p.addr_ranges.begin(), p.addr_ranges.end()),
      mmioRanges(p.mmio_ranges.begin(), p.mmio_ranges.end()),
      metricsOutputPath(p.metrics_output_path),
      scratchReadBurstBase(p.scratch_read_burst_base),
      scratchReadBurstSize(p.scratch_read_burst_size),
      scratchReadBurstBytes(std::max(64u, static_cast<unsigned>(p.scratch_read_burst_bytes))),
      functionalMemory(nullptr),
      secondaryFunctionalMemory(nullptr),
      secondaryFunctionalRanges(
          p.secondary_functional_ranges.begin(),
          p.secondary_functional_ranges.end()),
      runConsistencyCheck(p.run_consistency_check),
      requestsReceived(0),
      responsesCompleted(0)
{
    maxPorts = 1;

    // Resolve functional memory endpoint
    if (p.functional_memory) {
        functionalMemory = dynamic_cast<FunctionalMemoryEndpoint*>(p.functional_memory);
        if (!functionalMemory) {
            fatal("CpuNocBridge: functional_memory parameter must implement FunctionalMemoryEndpoint");
        }
    } else {
        warn("CpuNocBridge: No functional_memory provided. Functional access (binary loading) will fail.");
    }
    if (p.secondary_functional_memory) {
        secondaryFunctionalMemory =
            dynamic_cast<FunctionalMemoryEndpoint*>(p.secondary_functional_memory);
        if (!secondaryFunctionalMemory) {
            fatal("CpuNocBridge: secondary_functional_memory parameter must implement FunctionalMemoryEndpoint");
        }
    }
    
    // Initialize AXI ID pool
    for (int i = 0; i < maxOutstanding; i++) {
        freeAxiIds.push_back(i);
    }
    
    // Initialize AXI state
    currentState.ar.valid = false;
    currentState.aw.valid = false;
    currentState.w.valid = false;
    currentState.rReady = true;
    currentState.bReady = true;
    
    nextState = currentState;
}

FunctionalMemoryEndpoint*
CpuNocBridge::functionalMemoryForAddr(Addr addr) const
{
    if (secondaryFunctionalMemory) {
        for (const auto &range : secondaryFunctionalRanges) {
            if (range.contains(addr)) {
                return secondaryFunctionalMemory;
            }
        }
    }
    return functionalMemory;
}

void
CpuNocBridge::functionalWrite(Addr addr, const uint8_t* data, size_t size)
{
    FunctionalMemoryEndpoint* memory = functionalMemoryForAddr(addr);
    if (!memory) {
        panic("CpuNocBridge: functional write to %#x but no backing store configured", addr);
    }
    memory->functionalWrite(addr, data, size);
}

void
CpuNocBridge::functionalRead(Addr addr, uint8_t* data, size_t size)
{
    FunctionalMemoryEndpoint* memory = functionalMemoryForAddr(addr);
    if (!memory) {
        panic("CpuNocBridge: functional read from %#x but no backing store configured", addr);
    }
    memory->functionalRead(addr, data, size);
}

void
CpuNocBridge::init()
{
    NocNode::init();
    
    // Notify connected ports (e.g. XBar) about our address ranges
    if (cpuSidePort.isConnected()) {
        cpuSidePort.sendRangeChange();
    }
}

void CpuNocBridge::startup()
{
    NocNode::startup();
    
    if (runConsistencyCheck) {
        if (!functionalMemory) {
            warn("CpuNocBridge: run_consistency_check enabled but no functional_memory! Skipping.");
            return;
        }
        
        inform("CpuNocBridge: Running functional consistency check...");
        
        if (addrRanges.empty()) {
            warn("CpuNocBridge: No address ranges! Skipping check.");
            return;
        }
        
        Addr testAddr = addrRanges[0].start() + 0x100;
        uint8_t writeData[8] = {0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE};
        uint8_t readData[8] = {0};
        
        // 1. Functional Write via recvFunctional (simulating CPU load)
        RequestPtr reqW = std::make_shared<Request>(testAddr, 8, 0, 0);
        PacketPtr writePkt = new Packet(reqW, MemCmd::WriteReq);
        writePkt->dataStatic(writeData);
        
        // Call our own port implementation
        cpuSidePort.recvFunctional(writePkt);
        
        delete writePkt;
        
        // 2. Functional Read via recvFunctional (simulating CPU verify)
        RequestPtr reqR = std::make_shared<Request>(testAddr, 8, 0, 0);
        PacketPtr readPkt = new Packet(reqR, MemCmd::ReadReq);
        readPkt->dataStatic(readData);
        
        cpuSidePort.recvFunctional(readPkt);
        
        delete readPkt;
        
        // 3. Verify
        bool match = true;
        for(int i=0; i<8; i++) {
            if (writeData[i] != readData[i]) match = false;
        }
        
        if (match) {
            inform("CpuNocBridge: Functional consistency check PASSED! (Addr: 0x%lx Data: 0xDEADBEEFCAFEBABE)", testAddr);
        } else {
            fatal("CpuNocBridge: Functional consistency check FAILED! Read: 0x%02x%02x... Expected: 0x%02x%02x...",
                   readData[0], readData[1], writeData[0], writeData[1]);
        }
    }
}

Port&
CpuNocBridge::getPort(const std::string &if_name, PortID idx)
{
    if (if_name == "cpu_side") {
        return cpuSidePort;
    }
    return NocNode::getPort(if_name, idx);
}

//-----------------------------------------------------------------------------
// NocNode Interface (called by Control.cc)
//-----------------------------------------------------------------------------
bool
CpuNocBridge::tick(int clockDomain)
{
    // 1. Check for read responses from NoC
    if (currentState.rReady && nocInterfaceState.r.valid) {
        processReadResponse();
    }
    
    // 2. Check for write responses from NoC
    if (currentState.bReady && nocInterfaceState.b.valid) {
        processWriteResponse();
    }
    
    // 3. Try to convert pending CPU requests to AXI
    processNewRequests();
    
    // 4. Try to send pending responses to CPU
    trySendPendingResponses();
    
    currentState = nextState;
    return true;
}

bool
CpuNocBridge::done()
{
    // Never done - CPU controls when simulation ends
    return false;
}

void
CpuNocBridge::update(int portID, State* inputNocInterfaceState)
{
    if (portID != 0)
        panic("CpuNocBridge::update invalid portID %d", portID);
    
    auto* slaveState = dynamic_cast<aximmSlaveState*>(inputNocInterfaceState);
    if (!slaveState)
        panic("CpuNocBridge::update expected aximmSlaveState");
    
    // Update our view of NocInterface state
    nocInterfaceState = *slaveState;
    
    // Same pattern as tile.cc - update AXI channel states
    auto updateChannel = [](auto& queue, auto& cur, auto& next, bool ready) {
        using T = std::decay_t<decltype(cur)>;
        
        if (ready && cur.valid) {
            queue.pop_front();
            if (!queue.empty()) {
                next = queue.front();
            } else {
                next = T{};
                next.valid = false;
            }
        } else if (!cur.valid) {
            if (!queue.empty()) {
                next = queue.front();
            } else {
                next = T{};
                next.valid = false;
            }
        } else {
            next = cur;
        }
    };
    
    updateChannel(readRequests, currentState.ar, nextState.ar, slaveState->arReady);
    updateChannel(writeRequests, currentState.aw, nextState.aw, slaveState->awReady);
    updateChannel(writeData, currentState.w, nextState.w, slaveState->wReady);
    
    nextState.rReady = true;
    nextState.bReady = true;
}
State*
CpuNocBridge::getCurrentState(int portID)
{
    if (portID != 0)
        panic("CpuNocBridge::getCurrentState invalid portID %d", portID);
    return &currentState;
}
int
CpuNocBridge::assignPort(const std::string &endpointName)
{
    if (endpointName == portEndpointNames[0] && !portAssigned) {
        portAssigned = true;
        return 0;
    }
    panic("CpuNocBridge::assignPort invalid endpointName: %s",
          endpointName.c_str());
}
//-----------------------------------------------------------------------------
// CPU Side Port Implementation
//-----------------------------------------------------------------------------
CpuNocBridge::CpuSidePort::CpuSidePort(const std::string& name, CpuNocBridge* owner)
    : ResponsePort(name), owner(owner), needRetry(false)
{}
bool
CpuNocBridge::CpuSidePort::recvTimingReq(PacketPtr pkt)
{
    DPRINTF(NocPacketFlow, "CpuNocBridge: Received %s request for addr %#x, size %d cmd=%s\n",
            pkt->isRead() ? "read" : "write", pkt->getAddr(), pkt->getSize(), pkt->cmdString());
    
    // Filter out CleanEvict (no data, not needed for memory)
    if (pkt->cmd == MemCmd::CleanEvict) {
        DPRINTF(NocPacketFlow, "CpuNocBridge: Dropping CleanEvict for addr %#x (no data)\n", pkt->getAddr());
        // CleanEvict does not require a response. We just consume it.
        // But we must delete the packet as we are the sink.
        delete pkt;
        return true;
    }
    
    if (!owner->canAcceptRequest(pkt->getAddr())) {
        DPRINTF(NocPacketFlow, "CpuNocBridge: Cannot accept, returning false\n");
        needRetry = true;
        return false;
    }
    
    owner->pendingRequests.push_back(pkt);
    owner->requestsReceived++;
    return true;
}
void
CpuNocBridge::CpuSidePort::recvRespRetry()
{
    DPRINTF(NocPacketFlow, "CpuNocBridge: Got response retry\n");
    owner->blockedOnResponse = false;
    owner->trySendPendingResponses();
}
AddrRangeList
CpuNocBridge::CpuSidePort::getAddrRanges() const
{
    return AddrRangeList(owner->addrRanges.begin(), owner->addrRanges.end());
}
Tick
CpuNocBridge::CpuSidePort::recvAtomic(PacketPtr pkt)
{
    // Enable support for AtomicSimpleCPU by forwarding to functional memory.
    // This effectively bypasses the detailed NoC timing model, which is useful for
    // fast-forwarding/booting.
    if (owner->functionalMemory) {
        // Handle store conditional (SC) — always succeeds in single-core
        if (pkt->isLLSC() && pkt->isWrite()) {
            // Store conditional: write data and report success
            owner->functionalWrite(pkt->getAddr(), pkt->getPtr<uint8_t>(), pkt->getSize());
            // SC success is indicated by extraData = 0
            pkt->req->setExtraData(0);
        }
        // Handle load-linked (LR) — just a normal read
        else if (pkt->isLLSC() && pkt->isRead()) {
            owner->functionalRead(pkt->getAddr(), pkt->getPtr<uint8_t>(), pkt->getSize());
        }
        // Handle swap (AMOSWAP) — read old value, write new value
        else if (pkt->cmd == MemCmd::SwapReq) {
            // Read old value into packet data, then write new value
            uint8_t* pkt_data = pkt->getPtr<uint8_t>();
            std::vector<uint8_t> old_data(pkt->getSize());
            owner->functionalRead(pkt->getAddr(), old_data.data(), pkt->getSize());
            owner->functionalWrite(pkt->getAddr(), pkt_data, pkt->getSize());
            // Copy old value back into packet for the CPU
            memcpy(pkt_data, old_data.data(), pkt->getSize());
        }
        // Handle regular writes
        else if (pkt->isWrite()) {
            owner->functionalWrite(pkt->getAddr(), pkt->getPtr<uint8_t>(), pkt->getSize());
        }
        // Handle regular reads
        else if (pkt->isRead()) {
            owner->functionalRead(pkt->getAddr(), pkt->getPtr<uint8_t>(), pkt->getSize());
        }
        
        if (pkt->needsResponse()) {
            pkt->makeResponse();
        }
        // Return a small fixed latency (e.g. 1 cycle) to allow simulation to progress
        return 1000; 
    } else {
        panic("CpuNocBridge: recvAtomic called but no functional_memory configured.");
    }
}
void
CpuNocBridge::CpuSidePort::recvFunctional(PacketPtr pkt)
{
    if (owner->functionalMemory) {
        if (pkt->isWrite()) {
            owner->functionalWrite(pkt->getAddr(), pkt->getPtr<uint8_t>(), pkt->getSize());
        } else if (pkt->isRead()) {
            owner->functionalRead(pkt->getAddr(), pkt->getPtr<uint8_t>(), pkt->getSize());
        }
        pkt->makeResponse();
    } else {
        panic("CpuNocBridge: recvFunctional called but no functional_memory configured. Cannot load binary.");
    }
}
void
CpuNocBridge::CpuSidePort::sendRetryReq()
{
    if (needRetry) {
        needRetry = false;
        ResponsePort::sendRetryReq();  // Call parent's method to tell CPU to retry
    }
}
bool
CpuNocBridge::CpuSidePort::trySendResponse(PacketPtr pkt)
{
    return sendTimingResp(pkt);
}
//-----------------------------------------------------------------------------
// Request/Response Processing
//-----------------------------------------------------------------------------

/**
 * Get destination ID from address.
 * Uses the NoC address map to determine which NSU this address routes to.
 */
uint64_t
CpuNocBridge::getDestIdForAddr(Addr addr) const
{
    return nocNetwork->getDestFromAddress(addr);
}

/**
 * Get (or allocate) an AXI ID for a destination.
 * Same destination reuses the same ID. New destination needs a new ID.
 */
uint32_t
CpuNocBridge::getAxiIdForDest(uint64_t dest_id)
{
    // Check if we already have an ID for this destination
    auto it = destToAxiId.find(dest_id);
    if (it != destToAxiId.end()) {
        // Reuse existing ID, increment outstanding count
        destOutstandingCount[dest_id]++;
        DPRINTF(NocPacketFlow, "CpuNocBridge: Reusing AXI ID %d for dest %llu (outstanding=%d)\n",
                it->second, dest_id, destOutstandingCount[dest_id]);
        return it->second;
    }
    
    // Need to allocate a new ID for this destination
    assert(!freeAxiIds.empty());
    uint32_t id = freeAxiIds.front();
    freeAxiIds.pop_front();
    
    destToAxiId[dest_id] = id;
    destOutstandingCount[dest_id] = 1;
    
    DPRINTF(NocPacketFlow, "CpuNocBridge: Allocated new AXI ID %d for dest %llu\n",
            id, dest_id);
    return id;
}

/**
 * Release an AXI ID when a transaction completes.
 * Only actually frees the ID when no more transactions to that destination.
 */
void
CpuNocBridge::releaseAxiIdForDest(uint64_t dest_id, uint32_t axi_id)
{
    auto it = destOutstandingCount.find(dest_id);
    assert(it != destOutstandingCount.end());
    
    it->second--;
    DPRINTF(NocPacketFlow, "CpuNocBridge: Released transaction for dest %llu (remaining=%d)\n",
            dest_id, it->second);
    
    if (it->second == 0) {
        destOutstandingCount.erase(it);

        if (maxOutstanding == 1) {
            destToAxiId.erase(dest_id);
            freeAxiIds.push_back(axi_id);
            DPRINTF(NocPacketFlow,
                    "CpuNocBridge: Freed AXI ID %d from dest %llu\n",
                    axi_id, dest_id);
        } else {
            // Keep the destination-to-AXI-ID binding stable. The NoC-side read
            // reorder buffer tracks streams per AXI ID, and reassigning a fresh
            // ID for every serial CPU fetch can leave later responses stuck
            // behind stale per-ID bookkeeping.
            DPRINTF(NocPacketFlow,
                    "CpuNocBridge: Keeping AXI ID %d bound to dest %llu\n",
                    axi_id, dest_id);
        }
        
        // If CPU was blocked, tell it to retry
        cpuSidePort.sendRetryReq();
    }
}

bool
CpuNocBridge::canAcceptRequest(Addr addr) const
{
    // Check if we're under the pending limit
    if (pendingRequests.size() >= 16) return false;
    
    uint64_t dest_id = getDestIdForAddr(addr);
    
    // Unmapped addresses are handled via functional memory (no NoC ID needed)
    if (dest_id == (uint64_t)-1 || dest_id == (uint64_t)0xFFFFFFFF) return true;
    
    // If we already have an ID for this dest, we can accept (up to OT limit per dest)
    if (destToAxiId.find(dest_id) != destToAxiId.end()) {
        return true;
    }
    
    // Need a new ID, check if any are free
    return !freeAxiIds.empty();
}

bool
CpuNocBridge::isMmioRequest(Addr addr, unsigned size) const
{
    if (size == 0) {
        return false;
    }

    const Addr last = addr + size - 1;
    for (const auto& range : mmioRanges) {
        if (range.contains(addr) && range.contains(last)) {
            return true;
        }
    }
    return false;
}

bool
CpuNocBridge::isScratchBurstRead(Addr addr, unsigned size) const
{
    if (scratchReadBurstSize == 0 || size == 0) {
        return false;
    }
    const Addr last = addr + size - 1;
    const Addr burstLast = scratchReadBurstBase + scratchReadBurstSize - 1;
    return addr <= burstLast && last >= scratchReadBurstBase;
}

unsigned
CpuNocBridge::mmioAxiSize(unsigned bytes) const
{
    panic_if(bytes == 0 || bytes > 64,
             "CpuNocBridge: unsupported MMIO access size %u", bytes);
    panic_if((bytes & (bytes - 1)) != 0,
             "CpuNocBridge: MMIO access size %u is not a power of two", bytes);

    unsigned size = 0;
    while ((1U << size) < bytes) {
        ++size;
    }
    return size;
}

void
CpuNocBridge::processNewRequests()
{
    while (!pendingRequests.empty()) {
        PacketPtr pkt = pendingRequests.front();
        uint64_t dest_id = getDestIdForAddr(pkt->getAddr());
        
        // Handle unmapped addresses via functional memory (bypass NoC).
        // This occurs for kernel virtual addresses (e.g. 0xffffffe000c04000)
        // that flow through the L2 cache default port but are outside the
        // NoC address map.
        if (dest_id == (uint64_t)-1 || dest_id == (uint64_t)0xFFFFFFFF) {
            pendingRequests.pop_front();
            DPRINTF(NocPacketFlow, "CpuNocBridge: Addr %#x unmapped in NoC, "
                    "handling via functional memory\n", pkt->getAddr());
            if (functionalMemory) {
                if (pkt->isRead()) {
                    functionalRead(pkt->getAddr(), pkt->getPtr<uint8_t>(), pkt->getSize());
                } else if (pkt->isWrite()) {
                    functionalWrite(pkt->getAddr(), pkt->getPtr<uint8_t>(), pkt->getSize());
                }
            } else {
                warn("CpuNocBridge: Unmapped addr %#x and no functional memory!",
                     pkt->getAddr());
            }
            if (pkt->needsResponse()) {
                pkt->makeResponse();
                pendingResponses.push_back(pkt);
            } else {
                delete pkt;
            }
            continue;
        }
        
        // Check if we can accept this request
        bool have_id = destToAxiId.find(dest_id) != destToAxiId.end();
        if (!have_id && freeAxiIds.empty()) {
            // Need new ID but none available, stop processing
            break;
        }
        
        pendingRequests.pop_front();
        
        uint32_t axi_id = getAxiIdForDest(dest_id);
        
        int total_size = pkt->getSize();
        aximmRWAddr addr = pkt->isRead()
            ? createAxiReadAddr(pkt, axi_id)
            : createAxiWriteAddr(pkt, axi_id);
        int beat_bytes = 1 << addr.size;
        int num_beats = addr.len + 1;
        
        // Create outstanding entry
        OutstandingRequest req;
        req.pkt = pkt;
        req.axi_id = axi_id;
        req.dest_id = dest_id;
        req.is_read = pkt->isRead();
        req.is_mmio = isMmioRequest(pkt->getAddr(), pkt->getSize());
        req.original_addr = pkt->getAddr();
        req.original_size = pkt->getSize();
        req.axi_bytes = num_beats * beat_bytes;
        req.start_tick = curTick();
        req.beats_expected = num_beats;
        req.beats_received = 0;
        req.axi_addr = addr.addr;
        req.axi_beat_bytes = beat_bytes;
        if (pkt->isRead()) {
            req.data.resize(total_size);
        }
        
        // Push to the queue for this AXI ID (FIFO - same ID, same dest, in-order responses)
        outstanding[axi_id].push_back(req);
        
        if (pkt->isRead()) {
            readRequests.push_back(addr);
            DPRINTF(NocPacketFlow, "CpuNocBridge: Queued AR id=%d dest=%llu addr=%#x size=%d len=%d\n",
                    axi_id, dest_id, addr.addr, addr.size, addr.len);
        } else {
            writeRequests.push_back(addr);
            createAxiWriteData(pkt, axi_id);
            DPRINTF(NocPacketFlow, "CpuNocBridge: Queued AW+W id=%d dest=%llu addr=%#x size=%d len=%d\n",
                    axi_id, dest_id, addr.addr, addr.size, addr.len);
        }
    }
}
aximmRWAddr
CpuNocBridge::createAxiReadAddr(PacketPtr pkt, uint32_t axi_id)
{
    aximmRWAddr addr;
    if (isMmioRequest(pkt->getAddr(), pkt->getSize())) {
        addr.addr = pkt->getAddr();
        addr.cmd = AximmCommand::READ;
        addr.id = axi_id;
        addr.valid = true;
        addr.size = mmioAxiSize(pkt->getSize());
        addr.len = 0;
        return addr;
    }

    constexpr int BeatBytes = 64;
    Addr pkt_start = pkt->getAddr();
    Addr pkt_end = pkt_start + pkt->getSize();
    Addr aligned_start = pkt_start & ~(Addr)(BeatBytes - 1);
    Addr aligned_end = (pkt_end + BeatBytes - 1) & ~(Addr)(BeatBytes - 1);
    if (isScratchBurstRead(pkt_start, pkt->getSize())) {
        const Addr burst_limit = scratchReadBurstBase + scratchReadBurstSize;
        const unsigned burst_bytes =
            ((scratchReadBurstBytes + BeatBytes - 1) / BeatBytes) * BeatBytes;
        const Addr burst_end = std::min(burst_limit, aligned_start + (Addr)burst_bytes);
        aligned_end = std::max(aligned_end, burst_end);
    }

    addr.addr = aligned_start;
    addr.cmd = AximmCommand::READ;
    addr.id = axi_id;
    addr.valid = true;
    addr.size = 6;
    addr.len = (aligned_end - aligned_start) / BeatBytes - 1;
    
    return addr;
}
aximmRWAddr
CpuNocBridge::createAxiWriteAddr(PacketPtr pkt, uint32_t axi_id)
{
    aximmRWAddr addr;
    if (isMmioRequest(pkt->getAddr(), pkt->getSize())) {
        addr.addr = pkt->getAddr();
        addr.cmd = AximmCommand::WRITE;
        addr.id = axi_id;
        addr.valid = true;
        addr.size = mmioAxiSize(pkt->getSize());
        addr.len = 0;
        return addr;
    }

    constexpr int BeatBytes = 64;
    Addr pkt_start = pkt->getAddr();
    Addr pkt_end = pkt_start + pkt->getSize();
    Addr aligned_start = pkt_start & ~(Addr)(BeatBytes - 1);
    Addr aligned_end = (pkt_end + BeatBytes - 1) & ~(Addr)(BeatBytes - 1);

    addr.addr = aligned_start;
    addr.cmd = AximmCommand::WRITE;
    addr.id = axi_id;
    addr.valid = true;
    addr.size = 6;
    addr.len = (aligned_end - aligned_start) / BeatBytes - 1;
    
    return addr;
}
void
CpuNocBridge::createAxiWriteData(PacketPtr pkt, uint32_t axi_id)
{
    if (pkt->getSize() == 0) {
        return;
    }
    if (!pkt->hasData()) {
        panic("CpuNocBridge: Write packet has size %d but no data! cmd=%s addr=%#x", 
              pkt->getSize(), pkt->cmdString(), pkt->getAddr());
    }

    if (isMmioRequest(pkt->getAddr(), pkt->getSize())) {
        aximmRWData data;
        data.cmd = AximmCommand::WRITE;
        data.id = axi_id;
        data.valid = true;
        data.last = true;
        data.data.fill(0);

        const uint8_t* src = pkt->getConstPtr<uint8_t>();
        std::memcpy(data.data.data(), src, pkt->getSize());
        data.wstrb = (pkt->getSize() == 64)
            ? 0xFFFFFFFFFFFFFFFFULL
            : ((1ULL << pkt->getSize()) - 1ULL);

        writeData.push_back(data);
        return;
    }

    constexpr int BeatBytes = 64;
    const uint8_t* src = pkt->getConstPtr<uint8_t>();
    Addr pkt_start = pkt->getAddr();
    Addr pkt_end = pkt_start + pkt->getSize();
    Addr aligned_start = pkt_start & ~(Addr)(BeatBytes - 1);
    Addr aligned_end = (pkt_end + BeatBytes - 1) & ~(Addr)(BeatBytes - 1);
    int num_beats = (aligned_end - aligned_start) / BeatBytes;
    std::vector<uint8_t> merged(num_beats * BeatBytes, 0);

    // tileNSU_HBM does not preserve WSTRB on the final gem5 memory write.
    // Preserve byte-store semantics by sending full 64B lines with unchanged
    // bytes prefilled from the functional backing memory.
    if (functionalMemory) {
        functionalRead(aligned_start, merged.data(), merged.size());
    }
    std::memcpy(merged.data() + (pkt_start - aligned_start), src, pkt->getSize());
    
    for (int b = 0; b < num_beats; b++) {
        aximmRWData data;
        data.cmd = AximmCommand::WRITE;
        data.id = axi_id;
        data.valid = true;
        data.last = (b == num_beats - 1);
        
        int offset = b * BeatBytes;
        std::memcpy(data.data.data(), merged.data() + offset, BeatBytes);
        data.wstrb = 0xFFFFFFFFFFFFFFFFULL;
        
        writeData.push_back(data);
    }
}
void
CpuNocBridge::processReadResponse()
{
    const aximmRWData& r = nocInterfaceState.r;
    
    auto it = outstanding.find(r.id);
    if (it == outstanding.end() || it->second.empty()) {
        panic("CpuNocBridge: Received read response for unknown AXI ID %d", r.id);
    }
    
    // Find the oldest READ request for this ID (responses are in order per type)
    auto& queue = it->second;
    auto req_it = queue.end();
    for (auto i = queue.begin(); i != queue.end(); ++i) {
        if (i->is_read) {
            req_it = i;
            break;
        }
    }
    
    if (req_it == queue.end()) {
        panic("CpuNocBridge: Got R response but no read requests outstanding (ID=%d)", r.id);
    }
    
    OutstandingRequest& req = *req_it;
    
    Addr pkt_start = req.pkt->getAddr();
    Addr pkt_end = pkt_start + req.pkt->getSize();
    Addr beat_start = req.axi_addr + req.beats_received * req.axi_beat_bytes;
    Addr beat_end = beat_start + req.axi_beat_bytes;
    Addr copy_start = std::max(pkt_start, beat_start);
    Addr copy_end = std::min(pkt_end, beat_end);

    if (copy_start < copy_end) {
        int src_offset = copy_start - beat_start;
        int dst_offset = copy_start - pkt_start;
        int bytes_to_copy = copy_end - copy_start;

        if (src_offset + bytes_to_copy > (int)r.data.size() ||
            dst_offset + bytes_to_copy > (int)req.data.size()) {
             panic("CpuNocBridge: Read data copy out of bounds! pkt_addr=0x%lx "
                   "beat_addr=0x%lx src_offset=%d dst_offset=%d copy=%d "
                   "r_size=%lu req_size=%lu",
                   pkt_start, beat_start, src_offset, dst_offset, bytes_to_copy,
                   r.data.size(), req.data.size());
        }

        std::memcpy(req.data.data() + dst_offset,
                    r.data.data() + src_offset,
                    bytes_to_copy);
    }
    
    req.beats_received++;
    
    DPRINTF(NocPacketFlow, "CpuNocBridge: Got R beat for id=%d, beat %d/%d, last=%d\n",
            r.id, req.beats_received, req.beats_expected, r.last);
    
    if (r.last) {
        // All beats received, create response packet
        PacketPtr pkt = req.pkt;
        if (!pkt) {
            panic("CpuNocBridge: Null packet pointer in outstanding request (ID=%d)", r.id);
        }
        uint64_t dest_id = req.dest_id;
        pkt->makeResponse();
        if (pkt->getSize() > 0 && pkt->getSize() <= req.data.size()) {
            std::memcpy(pkt->getPtr<uint8_t>(), req.data.data(), pkt->getSize());
        }
        
        pendingResponses.push_back(pkt);
        if (req.is_mmio) {
            mmioTransactions.push_back(
                TransactionRecord{
                    req.original_addr,
                    req.original_size,
                    req.axi_bytes,
                    true,
                    req.start_tick,
                    curTick()});
        } else {
            memoryTransactions.push_back(
                TransactionRecord{
                    req.original_addr,
                    req.original_size,
                    req.axi_bytes,
                    true,
                    req.start_tick,
                    curTick()});
        }
        if (req.is_mmio) {
            emitMetricsFragment();
        }
        
        // Remove from queue and release ID tracking
        queue.erase(req_it);
        if (queue.empty()) {
            outstanding.erase(it);
        }
        releaseAxiIdForDest(dest_id, r.id);
        responsesCompleted++;
    }
}
void
CpuNocBridge::processWriteResponse()
{
    const aximmWResp& b = nocInterfaceState.b;
    
    auto it = outstanding.find(b.id);
    if (it == outstanding.end() || it->second.empty()) {
        panic("CpuNocBridge: Received write response for unknown AXI ID %d", b.id);
    }
    
    // Find the oldest WRITE request for this ID (responses are in order per type)
    auto& queue = it->second;
    auto req_it = queue.end();
    for (auto i = queue.begin(); i != queue.end(); ++i) {
        if (!i->is_read) {
            req_it = i;
            break;
        }
    }
    
    if (req_it == queue.end()) {
        panic("CpuNocBridge: Got B response but no write requests outstanding (ID=%d)", b.id);
    }
    
    OutstandingRequest& req = *req_it;
    uint64_t dest_id = req.dest_id;
    
    DPRINTF(NocPacketFlow, "CpuNocBridge: Got B response for id=%d\\n", b.id);
    
    // Create response packet
    PacketPtr pkt = req.pkt;
    
    if (pkt->needsResponse()) {
        pkt->makeResponse();
        pendingResponses.push_back(pkt);
    } else {
        DPRINTF(NocPacketFlow, "CpuNocBridge: Write complete (no response needed? %d) for id=%d pkt_cmd=%s\n", 
                pkt->needsResponse(), b.id, pkt->cmdString());
        delete pkt;
    }
    
    // Remove from queue and release ID tracking
    queue.erase(req_it);
    if (queue.empty()) {
        outstanding.erase(it);
    }
    if (req.is_mmio) {
        mmioTransactions.push_back(
            TransactionRecord{
                req.original_addr,
                req.original_size,
                req.axi_bytes,
                false,
                req.start_tick,
                curTick()});
    } else {
        memoryTransactions.push_back(
            TransactionRecord{
                req.original_addr,
                req.original_size,
                req.axi_bytes,
                false,
                req.start_tick,
                curTick()});
    }
    if (req.is_mmio) {
        emitMetricsFragment();
    }
    releaseAxiIdForDest(dest_id, b.id);
    responsesCompleted++;
}
void
CpuNocBridge::trySendPendingResponses()
{
    while (!pendingResponses.empty() && !blockedOnResponse) {
        PacketPtr pkt = pendingResponses.front();
        
        if (cpuSidePort.trySendResponse(pkt)) {
            pendingResponses.pop_front();
            DPRINTF(NocPacketFlow, "CpuNocBridge: Sent response to CPU for addr %#x\n",
                    pkt->getAddr());
        } else {
            blockedOnResponse = true;
            DPRINTF(NocPacketFlow, "CpuNocBridge: Blocked sending response, will retry\n");
        }
    }
}

void
CpuNocBridge::emitMetricsFragment() const
{
    if (metricsOutputPath.empty()) {
        return;
    }
    std::ofstream out(metricsOutputPath, std::ios::trunc);
    if (!out.is_open()) {
        warn("CpuNocBridge could not open metrics fragment %s",
             metricsOutputPath.c_str());
        return;
    }
    uint64_t readCount = 0;
    uint64_t writeCount = 0;
    uint64_t memoryReadCount = 0;
    uint64_t memoryWriteCount = 0;
    out << "{\n";
    out << "  \"type\": \"cpu_noc_bridge\",\n";
    out << "  \"mmio_transactions\": [\n";
    for (size_t i = 0; i < mmioTransactions.size(); ++i) {
        const auto& txn = mmioTransactions[i];
        if (txn.is_read) {
            ++readCount;
        } else {
            ++writeCount;
        }
        out << "    {\"addr\": " << txn.addr
            << ", \"size\": " << txn.size
            << ", \"axi_bytes\": " << txn.axi_bytes
            << ", \"is_read\": " << (txn.is_read ? "true" : "false")
            << ", \"start_tick\": " << txn.start_tick
            << ", \"end_tick\": " << txn.end_tick
            << ", \"latency_ticks\": " << (txn.end_tick - txn.start_tick) << "}";
        if (i + 1 != mmioTransactions.size()) {
            out << ",";
        }
        out << "\n";
    }
    out << "  ],\n";
    out << "  \"memory_transactions\": [\n";
    for (size_t i = 0; i < memoryTransactions.size(); ++i) {
        const auto& txn = memoryTransactions[i];
        if (txn.is_read) {
            ++memoryReadCount;
        } else {
            ++memoryWriteCount;
        }
        out << "    {\"addr\": " << txn.addr
            << ", \"size\": " << txn.size
            << ", \"axi_bytes\": " << txn.axi_bytes
            << ", \"is_read\": " << (txn.is_read ? "true" : "false")
            << ", \"start_tick\": " << txn.start_tick
            << ", \"end_tick\": " << txn.end_tick
            << ", \"latency_ticks\": " << (txn.end_tick - txn.start_tick) << "}";
        if (i + 1 != memoryTransactions.size()) {
            out << ",";
        }
        out << "\n";
    }
    out << "  ],\n";
    out << "  \"total_mmio_count\": " << mmioTransactions.size() << ",\n";
    out << "  \"total_mmio_reads\": " << readCount << ",\n";
    out << "  \"total_mmio_writes\": " << writeCount << ",\n";
    out << "  \"total_memory_count\": " << memoryTransactions.size() << ",\n";
    out << "  \"total_memory_reads\": " << memoryReadCount << ",\n";
    out << "  \"total_memory_writes\": " << memoryWriteCount << "\n";
    out << "}\n";
}
} // namespace noc
} // namespace gem5
