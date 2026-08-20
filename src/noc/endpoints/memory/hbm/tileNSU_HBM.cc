#include "noc/endpoints/memory/hbm/tileNSU_HBM.hh"

#include "noc/core/network/NocMemoryMsg.hh"
#include "mem/ruby/protocol/MessageSizeType.hh"
#include "base/logging.hh"
#include "debug/NocTiming.hh"
#include "debug/NocMemory.hh"
#include "debug/NocControl.hh"
#include "debug/NocHBM.hh"
#include "sim/core.hh"
#include "sim/cur_tick.hh"

#include <cstdio>
#include <sstream>
#include <cmath>
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <mutex>

namespace gem5{

namespace noc{

namespace {
inline std::string dumpAximmAddr(const aximmRWAddr &a)
{
    std::ostringstream oss;
    oss << "{cmd=" << (a.cmd == AximmCommand::READ ? "READ" : "WRITE")
        << " id=" << a.id
        << " addr=0x" << std::hex << a.addr << std::dec
        << " len=" << static_cast<unsigned>(a.len)
        << " size=" << static_cast<unsigned>(a.size)
        << " burst=" << static_cast<unsigned>(a.burst)
        << "}";
    return oss.str();
}
} // anonymous namespace

std::unordered_map<tileNSU_HBM::ControllerKey, std::shared_ptr<HBMArbiter>,
                   tileNSU_HBM::ControllerKeyHash>
    tileNSU_HBM::arbiterRegistry;
std::unordered_map<tileNSU_HBM::ControllerKey,
                   std::shared_ptr<tileNSU_HBM::ControllerSchedulerState>,
                   tileNSU_HBM::ControllerKeyHash>
    tileNSU_HBM::schedulerRegistry;


tileNSU_HBM::tileNSU_HBM(const Params &p) :
    BramEndpoint(p),
    noc_hbm_port(name() + ".noc_hbm_port", this),
    hbmControllerId(p.hbm_controller_id),
    hbmPortId(p.hbm_port_id),
    hbmPseudoChannelId(p.hbm_pseudo_channel_id),
    hbmPseudoChannelBaseAddr(p.hbm_pseudo_channel_base_addr),
    hbmPseudoChannelSize(p.hbm_pseudo_channel_size),
    readLatencyCycles(p.read_latency_cycles),
    writeLatencyCycles(p.write_latency_cycles),
    respLatencyCycles(p.resp_latency_cycles),
    portQueueDepth(p.port_queue_depth),
    maxOutstandingReads(p.max_outstanding_reads),
    maxOutstandingWrites(p.max_outstanding_writes),
    issueIntervalCycles(p.issue_interval_cycles),
    sharedBwMBps(p.shared_bw_MBps),
    nmuBwMBps(p.nmu_bw_MBps),
    banksPerPseudoChannel(p.banks_per_pseudo_channel),
    rowHitLatencyCycles(p.row_hit_latency_cycles),
    rowMissLatencyCycles(p.row_miss_latency_cycles),
    bankBusyCycles(p.bank_busy_cycles),
    cmdBusCycles(p.cmd_bus_cycles),
    closePagePolicy(std::string(p.page_policy) == "closed_page"),
    outstandingReadCmds(0),
    outstandingWriteCmds(0),
    activeReadRespAxiId(-1),
    activeReadRespHbmId(-1),
    lastReadRespAxiId(-1),
    lastWriteRespAxiId(-1),
    hbmTraceTileIndexParam(p.hbm_trace_tile_index),
    hbmStatsSampleGapCycles(p.hbm_stats_sample_gap_cycles),
    system(p.noc_system),
    simCycles(p.sim_cycles)
{
    _requestorId = p.requestorId;
    DPRINTF(NocMemory, "CONSTRUCTING HBM TILE\n");
    // Change arbiter_ready_flag to true by default.
    arbiter_ready_flag  = true;
    arbiter_valid_flag  = false;

    currentState.r.valid = false;
    currentState.b.valid = false;
    currentState.awReady = false;
    currentState.arReady = false;
    currentState.wReady = false;
    
    // FIX: Also initialize nextState to prevent spurious valid=true from default
    nextState.r.valid = false;
    nextState.b.valid = false;
    nextState.awReady = true;  // Ready to accept requests initially
    nextState.arReady = true;
    nextState.wReady = true;
    
    blockedOnRetry = false;
    needToRetry    = false;

    axi_pack_read_id       = 0;
    axi_pack_write_id      = 0;

    registerScheduler();
    registerWithArbiter();
    hbmTraceInitFile(std::string(p.hbm_trace_csv_path));
    hbmStatsInitFile(std::string(p.hbm_stats_csv_path));
}

tileNSU_HBM::~tileNSU_HBM()
{
    if (hbmTraceFile.is_open()) {
        hbmTraceFile.flush();
        hbmTraceFile.close();
    }
}

void
tileNSU_HBM::hbmTraceInitFile(const std::string &path)
{
    if (path.empty()) {
        hbmTraceCsvEnabled = false;
        return;
    }
    bool need_header = true;
    {
        std::ifstream in(path);
        if (in.good() && in.peek() != std::ifstream::traits_type::eof()) {
            need_header = false;
        }
    }
    hbmTraceFile.open(path, std::ios::out | std::ios::app);
    if (!hbmTraceFile.is_open()) {
        warn("tileNSU_HBM %s: could not open hbm_trace_csv_path '%s'",
             name(), path.c_str());
        hbmTraceCsvEnabled = false;
        return;
    }
    hbmTraceCsvEnabled = true;
    if (need_header) {
        hbmTraceFile << "ms,tile_hbm,request_num,axi_type,event,data_bytes,"
                        "address\n";
        hbmTraceFile.flush();
    }
}

void
tileNSU_HBM::hbmTraceMark()
{
    if (hbmTraceCsvEnabled) {
        hbmTraceCycleTouched = true;
    }
}

void
tileNSU_HBM::hbmTraceRow(Tick when,
                         const std::string &request_label,
                         const std::string &axi_type,
                         const std::string &event,
                         int data_bytes_neg1_if_empty,
                         Addr addr,
                         bool include_addr)
{
    if (!hbmTraceCsvEnabled || !hbmTraceFile.is_open()) {
        return;
    }
    hbmTraceMark();
    const double ms =
        (double)when * 1000.0 / (double)gem5::sim_clock::Frequency;
    hbmTraceFile << std::fixed << std::setprecision(6) << ms << ","
                   << hbmTraceTileId() << "," << request_label << ","
                   << axi_type << "," << event << ",";
    if (data_bytes_neg1_if_empty >= 0) {
        hbmTraceFile << data_bytes_neg1_if_empty;
    }
    hbmTraceFile << ",";
    if (include_addr) {
        hbmTraceFile << "0x" << std::hex << addr << std::dec;
    }
    hbmTraceFile << "\n";
    hbmTraceFile.flush();
}

namespace {

std::mutex &
hbmStatsCsvMutex()
{
    static std::mutex mtx;
    return mtx;
}

std::ofstream &
hbmStatsSharedCsv()
{
    static std::ofstream file;
    return file;
}

std::string &
hbmStatsSharedCsvPath()
{
    static std::string path;
    return path;
}

} // namespace

void
tileNSU_HBM::hbmStatsInitFile(const std::string &path)
{
    if (path.empty()) {
        hbmStatsCsvEnabled = false;
        return;
    }

    std::lock_guard<std::mutex> lock(hbmStatsCsvMutex());
    std::ofstream &shared = hbmStatsSharedCsv();
    if (!shared.is_open() || hbmStatsSharedCsvPath() != path) {
        if (shared.is_open()) {
            shared.close();
        }
        shared.open(path, std::ios::out | std::ios::trunc);
        hbmStatsSharedCsvPath() = path;
        if (!shared.is_open()) {
            warn("tileNSU_HBM %s: could not open hbm_stats_csv_path '%s'",
                 name(), path.c_str());
            hbmStatsCsvEnabled = false;
            return;
        }
        shared << "ms,controller_id,port_id,pseudo_channel_id,queue_depth,"
                  "outstanding_reads,outstanding_writes,read_bytes,"
                  "write_bytes\n";
        shared.flush();
    }
    hbmStatsCsvEnabled = true;
    hbmStatsNextSampleTick = 0;
}

void
tileNSU_HBM::hbmStatsNoteIssue(const MemCmd &cmd)
{
    if (!hbmStatsCsvEnabled) {
        return;
    }
    const size_t nbytes = bytesForAxiRequest(cmd.addr);
    if (cmd.type == MemCmdType::Read) {
        hbmStatsCumulativeReadBytes += nbytes;
    } else {
        hbmStatsCumulativeWriteBytes += nbytes;
    }
}

void
tileNSU_HBM::hbmStatsMaybeSample(Tick now)
{
    if (!hbmStatsCsvEnabled) {
        return;
    }
    const Tick gap_ticks = cyclesToTicks(hbmStatsSampleGapCycles);
    if (gap_ticks == 0 || now < hbmStatsNextSampleTick) {
        return;
    }
    hbmStatsNextSampleTick = now + gap_ticks;

    const uint64_t read_delta =
        hbmStatsCumulativeReadBytes - hbmStatsLastSampleReadBytes;
    const uint64_t write_delta =
        hbmStatsCumulativeWriteBytes - hbmStatsLastSampleWriteBytes;
    hbmStatsLastSampleReadBytes = hbmStatsCumulativeReadBytes;
    hbmStatsLastSampleWriteBytes = hbmStatsCumulativeWriteBytes;

    const size_t queue_depth =
        pendingCmds.size() + writeRequests.size();
    const double ms =
        (double)now * 1000.0 / (double)gem5::sim_clock::Frequency;

    std::lock_guard<std::mutex> lock(hbmStatsCsvMutex());
    std::ofstream &shared = hbmStatsSharedCsv();
    if (!shared.is_open()) {
        return;
    }
    shared << std::fixed << std::setprecision(6) << ms << ","
           << hbmControllerId << "," << hbmPortId << ","
           << hbmPseudoChannelId << "," << queue_depth << ","
           << outstandingReadCmds << "," << outstandingWriteCmds << ","
           << read_delta << "," << write_delta << "\n";
    shared.flush();
}

void
tileNSU_HBM::hbmTraceMaybeRefreshAtEndOfTick()
{
    if (!hbmTraceCsvEnabled || !hbmTraceFile.is_open()) {
        return;
    }
    if (hbmTraceCycleTouched) {
        return;
    }
    const double ms =
        (double)curTick() * 1000.0 / (double)gem5::sim_clock::Frequency;
    hbmTraceFile << std::fixed << std::setprecision(6) << ms << ","
                   << hbmTraceTileId() << ",refresh,,,,,\n";
    hbmTraceFile.flush();
}

State*
tileNSU_HBM::getCurrentState(int portID)
{
    if (portID != 0)
        panic("tileNSU_HBM::getCurrentState invalid portID %d", portID);
    return &currentState;
}

Port& tileNSU_HBM::getPort(const std::string &if_name, PortID idx) {
    if (if_name == "noc_hbm_port") {
        return noc_hbm_port;
    }

    //TODO: check if this is correct
    // return SimObject::getPort(if_name, idx);
    panic("Unknown port name: %s", if_name);
}

void tileNSU_HBM::updateReadyFlag(bool recvFlag){
    arbiter_ready_flag = recvFlag;
}

bool tileNSU_HBM::displayValidFlag(){
    return arbiter_valid_flag;
}

Tick
tileNSU_HBM::cyclesToTicks(uint32_t cycles) const
{
    const int clockDomainMhz = std::max(1, getPrimaryClockDomain());
    const Tick periodTicks = static_cast<Tick>(1000000 / clockDomainMhz);
    return cycles * periodTicks;
}

size_t
tileNSU_HBM::bytesForAxiRequest(const aximmRWAddr &cmd) const
{
    return static_cast<size_t>(cmd.len + 1) * static_cast<size_t>(1u << cmd.size);
}

size_t
tileNSU_HBM::hbmTransferUnits(const aximmRWAddr &cmd) const
{
    constexpr size_t hbmBurstBytes = 32;
    return std::max<size_t>(1, (bytesForAxiRequest(cmd) + hbmBurstBytes - 1) / hbmBurstBytes);
}

Addr
tileNSU_HBM::relativePseudoChannelAddr(Addr addr) const
{
    if (hbmPseudoChannelSize != 0 && addr >= hbmPseudoChannelBaseAddr) {
        const Addr relative = addr - hbmPseudoChannelBaseAddr;
        if (relative < hbmPseudoChannelSize) {
            return relative;
        }
    }
    return addr;
}

uint32_t
tileNSU_HBM::decodeBankIndex(const aximmRWAddr &cmd) const
{
    const uint32_t bankCount = std::max<uint32_t>(1, banksPerPseudoChannel);
    const Addr relative = relativePseudoChannelAddr(cmd.addr);
    const size_t burstUnits = hbmTransferUnits(cmd);
    return static_cast<uint32_t>((relative / 32 + burstUnits - 1) % bankCount);
}

uint64_t
tileNSU_HBM::decodeRowIndex(const aximmRWAddr &cmd) const
{
    const uint32_t bankCount = std::max<uint32_t>(1, banksPerPseudoChannel);
    const Addr relative = relativePseudoChannelAddr(cmd.addr);
    return static_cast<uint64_t>((relative / 32) / bankCount);
}

bool
tileNSU_HBM::canAcceptRead() const
{
    return pendingCmds.size() + writeRequests.size() < portQueueDepth &&
           outstandingReadCmds < maxOutstandingReads;
}

bool
tileNSU_HBM::canAcceptWriteAddr() const
{
    return pendingCmds.size() + writeRequests.size() < portQueueDepth &&
           outstandingWriteCmds < maxOutstandingWrites;
}

bool
tileNSU_HBM::canAcceptWriteData() const
{
    if (pendingWriteDataIds.empty()) {
        return false;
    }

    const uint32_t writeId = pendingWriteDataIds.front();
    const auto it = writeRequests.find(writeId);
    if (it == writeRequests.end()) {
        return false;
    }

    const aximmRWAddr &addr = it->second.first;
    const size_t expectedBeats = static_cast<size_t>(addr.len) + 1;
    return it->second.second.size() < expectedBeats;
}

bool
tileNSU_HBM::frontCommandReady(Tick now) const
{
    return !pendingCmds.empty() && pendingCmds.front().eligibleTick <= now;
}

bool
tileNSU_HBM::arbiterWantsIssue(Tick now) const
{
    return !pendingCmds.empty() &&
           frontCommandReady(now) &&
           !blockedOnRetry &&
           schedulerCanIssue(pendingCmds.front(), now);
}

void
tileNSU_HBM::registerScheduler()
{
    ControllerKey key{hbmControllerId, 0};
    auto &shared = schedulerRegistry[key];
    if (!shared) {
        shared = std::make_shared<ControllerSchedulerState>();
        shared->banksPerPseudoChannel = std::max<uint32_t>(1, banksPerPseudoChannel);
        shared->rowHitLatencyCycles = rowHitLatencyCycles;
        shared->rowMissLatencyCycles = rowMissLatencyCycles;
        shared->bankBusyCycles = bankBusyCycles;
        shared->cmdBusCycles = cmdBusCycles;
        shared->closePage = closePagePolicy;
    } else if (shared->banksPerPseudoChannel != std::max<uint32_t>(1, banksPerPseudoChannel) ||
               shared->rowHitLatencyCycles != rowHitLatencyCycles ||
               shared->rowMissLatencyCycles != rowMissLatencyCycles ||
               shared->bankBusyCycles != bankBusyCycles ||
               shared->cmdBusCycles != cmdBusCycles ||
               shared->closePage != closePagePolicy) {
        panic("HBM controller scheduler for controller %u was created with "
              "different scheduler knobs than endpoint %s.",
              hbmControllerId, name());
    }

    const size_t requiredPseudoChannels =
        static_cast<size_t>(hbmPseudoChannelId) + 1;
    if (shared->pseudoChannels.size() < requiredPseudoChannels) {
        shared->pseudoChannels.resize(requiredPseudoChannels);
    }
    auto &pcState = shared->pseudoChannels[hbmPseudoChannelId];
    if (pcState.banks.empty()) {
        pcState.banks.assign(shared->banksPerPseudoChannel, BankState{});
    } else if (pcState.banks.size() != shared->banksPerPseudoChannel) {
        panic("HBM controller scheduler for controller %u pc %u has inconsistent "
              "bank-state sizing in endpoint %s.",
              hbmControllerId, hbmPseudoChannelId, name());
    }
    schedulerState = shared;
}

void
tileNSU_HBM::registerWithArbiter()
{
    ControllerKey key{hbmControllerId, hbmPseudoChannelId};
    auto &shared = arbiterRegistry[key];
    if (!shared) {
        shared = std::make_shared<HBMArbiter>(
            issueIntervalCycles, sharedBwMBps, nmuBwMBps);
    } else if (shared->getIssueIntervalCycles() != issueIntervalCycles ||
               shared->getSharedBwMBps() != sharedBwMBps ||
               shared->getNmuBwMBps() != nmuBwMBps) {
        panic("HBM controller arbiter for controller %u pc %u was created "
              "with different timing knobs than endpoint %s.",
              hbmControllerId, hbmPseudoChannelId, name());
    }
    arbiter = shared;
    arbiter->addEndpoint(this);
}

tileNSU_HBM::PseudoChannelState &
tileNSU_HBM::schedulerPseudoChannelState()
{
    panic_if(!schedulerState,
             "HBM controller scheduler state was not registered for %s.",
             name());
    panic_if(hbmPseudoChannelId >= schedulerState->pseudoChannels.size(),
             "HBM controller %u is missing scheduler state for pseudo channel %u "
             "in endpoint %s.",
             hbmControllerId, hbmPseudoChannelId, name());
    return schedulerState->pseudoChannels[hbmPseudoChannelId];
}

const tileNSU_HBM::PseudoChannelState &
tileNSU_HBM::schedulerPseudoChannelState() const
{
    panic_if(!schedulerState,
             "HBM controller scheduler state was not registered for %s.",
             name());
    panic_if(hbmPseudoChannelId >= schedulerState->pseudoChannels.size(),
             "HBM controller %u is missing scheduler state for pseudo channel %u "
             "in endpoint %s.",
             hbmControllerId, hbmPseudoChannelId, name());
    return schedulerState->pseudoChannels[hbmPseudoChannelId];
}

Tick
tileNSU_HBM::schedulerDelayFor(const MemCmd &cmd, Tick now) const
{
    if (!schedulerState) {
        return cmd.eligibleTick;
    }

    const uint32_t bankIdx = decodeBankIndex(cmd.addr);
    const uint64_t rowIdx = decodeRowIndex(cmd.addr);
    const auto &pcState = schedulerPseudoChannelState();
    const auto &bank = pcState.banks[bankIdx];
    const bool rowHit = bank.rowValid && bank.openRow == rowIdx;
    const Tick policyDelay = cyclesToTicks(
        rowHit ? schedulerState->rowHitLatencyCycles
               : schedulerState->rowMissLatencyCycles);
    const Tick resourceReady = std::max(
        cmd.eligibleTick,
        std::max(bank.readyTick, pcState.nextCmdTick));
    return resourceReady + policyDelay;
}

bool
tileNSU_HBM::schedulerCanIssue(const MemCmd &cmd, Tick now) const
{
    return now >= schedulerDelayFor(cmd, now);
}

void
tileNSU_HBM::noteSchedulerIssued(const MemCmd &cmd, Tick now)
{
    if (!schedulerState) {
        return;
    }

    const uint32_t bankIdx = decodeBankIndex(cmd.addr);
    const uint64_t rowIdx = decodeRowIndex(cmd.addr);
    auto &pcState = schedulerPseudoChannelState();
    auto &bank = pcState.banks[bankIdx];
    bank.readyTick = now + cyclesToTicks(schedulerState->bankBusyCycles);
    pcState.nextCmdTick = now + cyclesToTicks(schedulerState->cmdBusCycles);

    if (schedulerState->closePage) {
        bank.rowValid = false;
    } else {
        bank.rowValid = true;
        bank.openRow = rowIdx;
    }
    hbmStatsNoteIssue(cmd);
}

void
tileNSU_HBM::enqueueCompletedRead(const ScheduledMemResp &resp)
{
    const uint8_t *src = resp.data.data();
    const int beat_bytes = 1 << resp.size;
    const int num_beats = resp.len + 1;

    for (int b = 0; b < num_beats; b++) {
        aximmRWData payload;
        payload.cmd = AximmCommand::READ;
        payload.id = resp.axiId;
        payload.valid = true;
        payload.last = (b == num_beats - 1);
        memcpy(payload.data.data(), src + b * beat_bytes, beat_bytes);
        readResponses[resp.axiId][resp.hbmId].push_back(payload);
    }
}

void
tileNSU_HBM::enqueueCompletedWrite(const ScheduledMemResp &resp)
{
    aximmWResp payload;
    payload.id = resp.axiId;
    payload.valid = true;
    payload.resp = AximmResp::OKAY;
    writeResponses[resp.axiId][resp.hbmId] = payload;
}

void
tileNSU_HBM::serviceScheduledResponses(Tick now)
{
    while (!scheduledResponses.empty() && scheduledResponses.front().readyTick <= now) {
        const auto resp = scheduledResponses.front();
        scheduledResponses.pop_front();
        if (resp.isRead) {
            enqueueCompletedRead(resp);
        } else {
            enqueueCompletedWrite(resp);
        }
    }
}

void
tileNSU_HBM::clearActiveReadResponseIfDone()
{
    if (activeReadRespAxiId < 0 || activeReadRespHbmId < 0) {
        return;
    }

    auto axiIt = readResponses.find(activeReadRespAxiId);
    if (axiIt == readResponses.end()) {
        activeReadRespAxiId = -1;
        activeReadRespHbmId = -1;
        return;
    }

    auto hbmIt = axiIt->second.find(activeReadRespHbmId);
    if (hbmIt == axiIt->second.end() || hbmIt->second.empty()) {
        activeReadRespAxiId = -1;
        activeReadRespHbmId = -1;
    }
}

void tileNSU_HBM::functionalWrite(Addr addr, const uint8_t* data, size_t size) {
    if (noc_hbm_port.isConnected()) {
        RequestPtr req = std::make_shared<Request>(addr, size, 0, _requestorId);
        PacketPtr pkt = new Packet(req, gem5::MemCmd::WriteReq);
        pkt->dataStatic(const_cast<uint8_t*>(data));
        
        // Create functional command
        noc_hbm_port.sendFunctional(pkt);
        
        delete pkt;
    } else {
        // Fallback to internal storage (BRAM)
        BramEndpoint::functionalWrite(addr, data, size);
    }
}

void tileNSU_HBM::functionalRead(Addr addr, uint8_t* data, size_t size) {
    if (noc_hbm_port.isConnected()) {
        RequestPtr req = std::make_shared<Request>(addr, size, 0, _requestorId);
        PacketPtr pkt = new Packet(req, gem5::MemCmd::ReadReq);
        pkt->dataStatic(data);
        
        noc_hbm_port.sendFunctional(pkt);
        
        delete pkt;
    } else {
         // Fallback to internal storage (BRAM)
         BramEndpoint::functionalRead(addr, data, size);
    }
}

bool tileNSU_HBM::addressInRange(Addr addr) const {
    return BramEndpoint::addressInRange(addr);
}

bool tileNSU_HBM::tick(int clockDomain){
    if (currentState.arReady && tileControllerState.ar.valid){
        DPRINTF(NocTiming,"TileNSU received Axi request\n");

        const int hbm_rid = axi_pack_read_id;
        hbmTraceAddrByHbmId[hbm_rid] = tileControllerState.ar;
        hbmTraceRow(curTick(), std::to_string(hbm_rid), "AR", "arrival_to_hbm",
                    -1, tileControllerState.ar.addr, true);

        DPRINTF(NocMemory, "RECIEVED AXI READ REQ(tileNSU_HBM) id: %d\n", tileControllerState.ar.id);
        DPRINTF(NocMemory, "RECIEVED AXI READ REQ(tileNSU_HBM) HBM_id: %x\n", axi_pack_read_id);
        DPRINTF(NocMemory, "RECIEVED AXI READ REQ(tileNSU_HBM) addr: %#lx\n", tileControllerState.ar.addr);
        DPRINTF(NocHBM,
                "[AXI_ARRIVE_TILE][tileNSU_HBM] tick=%llu name=%s HBM_id=0x%x "
                "AR %s\n",
                (unsigned long long)curTick(),
                name(),
                hbm_rid,
                dumpAximmAddr(tileControllerState.ar).c_str());

        MemCmd cmd;
        cmd.type = MemCmdType::Read;
        cmd.HBM_id = hbm_rid;
        cmd.addr = tileControllerState.ar;
        cmd.eligibleTick = curTick() + cyclesToTicks(readLatencyCycles);
        pendingCmds.push_back(cmd);
        DPRINTF(NocControl, "tileNSU_HBM::tick Pushed cmd. pendingCmds.size() = %zu\n", pendingCmds.size());

        //store our transactions in order
        inOrderReadResp_Queue[tileControllerState.ar.id].push_back(axi_pack_read_id);
        axi_pack_read_id++;
        outstandingReadCmds++;
    }

    //TODO: fix this such that this such that "buffer_writeRequestPacket" also triggers if both AW/W have finished
    //need to add checks in both to see which finished first to trigger the function
    //first check if this is needed for the NoC tho

    if (currentState.awReady && tileControllerState.aw.valid){
        //store any incoming write requests within a dictionary to buffer it for later
        const int hbm_wid = axi_pack_write_id;
        hbmTraceAddrByHbmId[hbm_wid] = tileControllerState.aw;
        hbmTraceRow(curTick(), std::to_string(hbm_wid), "AW", "arrival_to_hbm",
                    -1, tileControllerState.aw.addr, true);

        DPRINTF(NocMemory, "RECIEVED AXI WRITE REQ(tileNSU_HBM) id: %d\n", tileControllerState.aw.id);
        DPRINTF(NocMemory, "RECIEVED AXI WRITE REQ(tileNSU_HBM) HBM_id: %x\n", axi_pack_write_id);
        DPRINTF(NocMemory, "RECIEVED AXI WRITE REQ(tileNSU_HBM) addr: %#lx\n", tileControllerState.aw.addr);
        DPRINTF(NocHBM,
                "[AXI_ARRIVE_TILE][tileNSU_HBM] tick=%llu name=%s HBM_id=0x%x "
                "AW %s\n",
                (unsigned long long)curTick(),
                name(),
                hbm_wid,
                dumpAximmAddr(tileControllerState.aw).c_str());

        writeRequests[hbm_wid].first = tileControllerState.aw;
        pendingWriteDataIds.push_back(hbm_wid);

        //store our transactions in order
        inOrderWriteResp_Queue[tileControllerState.aw.id].push_back(hbm_wid);
        axi_pack_write_id++;
        outstandingWriteCmds++;
    }

    if (currentState.wReady && tileControllerState.w.valid) {
        const uint32_t writeDataId = pendingWriteDataIds.front();
        const int beat_bytes =
            static_cast<int>(writeRequests[writeDataId].first.getBeatByteSize());
        const std::string w_axi =
            tileControllerState.w.last ? "W_TLAST" : "W";
        hbmTraceRow(curTick(), std::to_string(writeDataId), w_axi,
                    "arrival_to_hbm", beat_bytes, 0, false);

        DPRINTF(NocMemory, "RECIEVED AXI WRITE DATA(tileNSU_HBM) id: %x\n", writeDataId);

        //since we can get write data ooo, we need to store each data packet into its corresponding dictionary
        writeRequests[writeDataId].second.push_back(tileControllerState.w);
    }

    if (currentState.wReady && tileControllerState.w.valid && tileControllerState.w.last){
        const uint32_t writeDataId = pendingWriteDataIds.front();
        DPRINTF(NocMemory, "RECIEVED AXI WRITE DATA LAST(tileNSU_HBM) id: %x\n", writeDataId);
        DPRINTF(NocHBM,
                "[AXI_WLAST_ARRIVE_TILE][tileNSU_HBM] tick=%llu name=%s "
                "HBM_id=0x%x W id=%u last=1\n",
                (unsigned long long)curTick(),
                name(),
                writeDataId,
                tileControllerState.w.id);

        buffer_writeRequestPacket(
            writeDataId,
            writeRequests[writeDataId].first,
            writeRequests[writeDataId].second
        );
        pendingWriteDataIds.pop_front();
    }

    currentState = nextState;
    hbmTraceMaybeRefreshAtEndOfTick();
    hbmStatsMaybeSample(curTick());
    return true;
}

void tileNSU_HBM::updateTileNSU(aximmMasterState tileControllerState){
    const Tick now = curTick();
    hbmTraceCycleTouched = false;

    serviceScheduledResponses(now);
    arbiter_valid_flag = !pendingCmds.empty() && frontCommandReady(now);
    arbiter_ready_flag = arbiter && arbiter->grantFor(this, now);

    if (arbiter_ready_flag && arbiter_valid_flag) {
        MemCmd issuingCmd = pendingCmds.front();
        bool issued = false;

        hbmTraceRow(now, std::to_string(issuingCmd.HBM_id),
                    issuingCmd.type == MemCmdType::Read ? "AR" : "AW",
                    "arbiter_granted", -1, 0, false);

        DPRINTF(NocHBM,
                "[ARB_SCHEDULE][tileNSU_HBM] tick=%llu name=%s type=%s "
                "HBM_id=0x%x %s\n",
                (unsigned long long)now,
                name(),
                issuingCmd.type == MemCmdType::Read ? "READ" : "WRITE",
                issuingCmd.HBM_id,
                dumpAximmAddr(issuingCmd.addr).c_str());

        if (!needToRetry) {
            issued = noc_hbm_port.send_port_ptr();
        } else {
            if (noc_hbm_port.sendTimingReq(retry_pkt)) {
                pendingCmds.pop_front();
                auto *state = static_cast<AxiSenderState*>(retry_pkt->senderState);
                DPRINTF(NocMemory, "SENT REQUEST TO HBM id: %x is read: %d\n", state->HBM_id, state->is_read);
                const int total_bytes =
                    (state->len + 1) * (1 << state->size);
                hbmTraceRow(now, std::to_string(state->HBM_id),
                            state->is_read ? "AR" : "AW", "hbm_request",
                            total_bytes, 0, false);
                needToRetry = false;
                retry_pkt = nullptr;
                blockedOnRetry = false;
                issued = true;
            } else {
                blockedOnRetry = true;
            }
        }

        if (issued) {
            noteSchedulerIssued(issuingCmd, now);
            arbiter->noteIssued(this, now, cyclesToTicks(1),
                                bytesForAxiRequest(issuingCmd.addr));
        }
    }

    // if master accepting read response this cycle, dequeue it
    if (tileControllerState.rReady && currentState.r.valid){

        int axi_HBM_id = inOrderReadResp_Queue[currentState.r.id].front();

        DPRINTF(NocMemory, "SENT READ_RESP: %d HBM_ID: %x\n", currentState.r.id, axi_HBM_id);

        int r_bytes = 0;
        auto r_cmd_it = hbmTraceAddrByHbmId.find(axi_HBM_id);
        if (r_cmd_it != hbmTraceAddrByHbmId.end()) {
            r_bytes = static_cast<int>(r_cmd_it->second.getBeatByteSize());
        }
        const std::string r_axi =
            currentState.r.last ? "R_TLAST" : "R";
        hbmTraceRow(now, std::to_string(axi_HBM_id), r_axi, "r_sent",
                    r_bytes, 0, false);

        readResponses[currentState.r.id][axi_HBM_id].pop_front();

        //remove our transactions from relevant structures
        if(readResponses[currentState.r.id][axi_HBM_id].empty()){
            readResponses[currentState.r.id].erase(axi_HBM_id);
            inOrderReadResp_Queue[currentState.r.id].pop_front();
            if (outstandingReadCmds > 0) {
                outstandingReadCmds--;
            }
            hbmTraceAddrByHbmId.erase(axi_HBM_id);
        }
        clearActiveReadResponseIfDone();

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

        int axi_HBM_id = inOrderWriteResp_Queue[currentState.b.id].front();

        // dequeue the write response that was read
        DPRINTF(NocMemory, "SENT WRITE_RESP: %d HBM_ID: %x\n", currentState.b.id, axi_HBM_id);
        DPRINTF(NocHBM,
                "[AXI_B_CONSUMED][tileNSU_HBM] tick=%llu name=%s axi_id=%u "
                "HBM_id=0x%x resp=%u\n",
                (unsigned long long)curTick(),
                name(),
                currentState.b.id,
                axi_HBM_id,
                static_cast<unsigned>(currentState.b.resp));

        hbmTraceRow(now, std::to_string(axi_HBM_id), "B", "b_sent", -1, 0,
                    false);
        hbmTraceAddrByHbmId.erase(axi_HBM_id);

        //remove our transactions from relevant structures
        writeResponses[currentState.b.id].erase(axi_HBM_id);
        inOrderWriteResp_Queue[currentState.b.id].pop_front();
        if (outstandingWriteCmds > 0) {
            outstandingWriteCmds--;
        }

        nextState.b = this->getNextWriteResponse();
        
    } else if (!currentState.b.valid){
        // no valid response this cycle, get one if ready for next cycle
        nextState.b = this->getNextWriteResponse();
    } else {
        // master (tileController) wasn't ready, but current state was valid, maintain state
        nextState.b = currentState.b;
    }

    nextState.arReady = canAcceptRead();
    nextState.awReady = canAcceptWriteAddr();
    nextState.wReady  = canAcceptWriteData();

    this->tileControllerState = tileControllerState;
}

bool tileNSU_HBM::NoC_SidePort::send_port_ptr(){
    auto readReq = owner->pendingCmds.front();
    auto readCmd = readReq.addr;

    int total_data_req_len = ((readCmd.len+1) * (1 << readCmd.size));

    // 

    //attach metadata regarding AXI to this port packet
    auto *state = new AxiSenderState();
    state->axi_id  = readCmd.id;
    state->HBM_id  = readReq.HBM_id;
    state->size    = readCmd.size;
    state->len     = readCmd.len;

    RequestPtr req = std::make_shared<Request>(
        readCmd.addr,
        total_data_req_len,
        0, // flags
        owner->requestorId()   // provided by your SimObject
    );

    DPRINTF(NocMemory, "TRYING REQUEST TO HBM requestorId: %d\n", owner->requestorId());
    PacketPtr pkt;
    
    if(readReq.type == MemCmdType::Read){
        pkt = Packet::createRead(req);
        pkt->allocate();
        state->is_read = true;
    } else {
        pkt = Packet::createWrite(req);
        pkt->allocate();
        std::memcpy(pkt->getPtr<uint8_t>(), readReq.writeData.data(), total_data_req_len);
        state->is_read = false;
    }

    pkt->senderState = state;

    //succesfully sent so just remove it from the front
    DPRINTF(NocMemory, "TRYING REQUEST TO HBM id: %x is read: %d addr: %#lx\n", 
            state->HBM_id, state->is_read, readCmd.addr);

    if(sendTimingReq(pkt)) {
        owner->pendingCmds.pop_front();
        DPRINTF(NocMemory, "SENT REQUEST TO HBM id: %x is read: %d\n", state->HBM_id, state->is_read);
        owner->hbmTraceRow(curTick(), std::to_string(state->HBM_id),
                          state->is_read ? "AR" : "AW", "hbm_request",
                          static_cast<int>(
                              owner->bytesForAxiRequest(readCmd)),
                          0, false);
        return true;
    } else {
        //we failed so unallocate pkt
        owner->blockedOnRetry = true;
        owner->needToRetry = true;
        owner->retry_pkt = pkt;
        DPRINTF(NocMemory, "BLOCKED ON RETRY: id: %x (sendTimingReq failed)\n", state->HBM_id);
        // delete state;
        // delete pkt;
        // pkt = nullptr;
        return false;
    }

}

aximmRWData tileNSU_HBM::getNextAxiResponse(){

    aximmRWData resp;
    clearActiveReadResponseIfDone();

    if (activeReadRespAxiId >= 0 && activeReadRespHbmId >= 0) {
        auto axiIt = readResponses.find(activeReadRespAxiId);
        if (axiIt != readResponses.end()) {
            auto hbmIt = axiIt->second.find(activeReadRespHbmId);
            if (hbmIt != axiIt->second.end() && !hbmIt->second.empty() &&
                !inOrderReadResp_Queue[activeReadRespAxiId].empty() &&
                inOrderReadResp_Queue[activeReadRespAxiId].front() == activeReadRespHbmId) {
                return hbmIt->second.front();
            }
        }
    }

    std::vector<int> readyAxiIds;
    readyAxiIds.reserve(readResponses.size());
    for (auto &[axi_id, resp_map] : readResponses) {
        if (resp_map.empty() || inOrderReadResp_Queue[axi_id].empty()) {
            continue;
        }
        const int expectedHbmId = inOrderReadResp_Queue[axi_id].front();
        auto hbmIt = resp_map.find(expectedHbmId);
        if (hbmIt != resp_map.end() && !hbmIt->second.empty()) {
            readyAxiIds.push_back(axi_id);
        }
    }

    if (!readyAxiIds.empty()) {
        std::sort(readyAxiIds.begin(), readyAxiIds.end());
        int selectedAxiId = readyAxiIds.front();
        for (int axiId : readyAxiIds) {
            if (axiId > lastReadRespAxiId) {
                selectedAxiId = axiId;
                break;
            }
        }
        const int selectedHbmId = inOrderReadResp_Queue[selectedAxiId].front();
        activeReadRespAxiId = selectedAxiId;
        activeReadRespHbmId = selectedHbmId;
        lastReadRespAxiId = selectedAxiId;
        return readResponses[selectedAxiId][selectedHbmId].front();
    }

    resp.valid = false;
    return resp;
}

aximmWResp tileNSU_HBM::getNextWriteResponse(){

    aximmWResp resp;
    std::vector<int> readyAxiIds;
    readyAxiIds.reserve(writeResponses.size());
    for (auto &[axi_id, resp_map] : writeResponses) {
        if (resp_map.empty() || inOrderWriteResp_Queue[axi_id].empty()) {
            continue;
        }
        const int expectedHbmId = inOrderWriteResp_Queue[axi_id].front();
        auto hbmIt = resp_map.find(expectedHbmId);
        if (hbmIt != resp_map.end()) {
            readyAxiIds.push_back(axi_id);
        }
    }

    if (!readyAxiIds.empty()) {
        std::sort(readyAxiIds.begin(), readyAxiIds.end());
        int selectedAxiId = readyAxiIds.front();
        for (int axiId : readyAxiIds) {
            if (axiId > lastWriteRespAxiId) {
                selectedAxiId = axiId;
                break;
            }
        }
        const int selectedHbmId = inOrderWriteResp_Queue[selectedAxiId].front();
        lastWriteRespAxiId = selectedAxiId;
        return writeResponses[selectedAxiId][selectedHbmId];
    }

    resp.valid = false;
    return resp;
}


void tileNSU_HBM::buffer_writeRequestPacket(int HBM_id, aximmRWAddr writeCmdAXI, std::deque<aximmRWData> writeDataAXI){
    
    MemCmd cmd;
    cmd.HBM_id = HBM_id;    

    //for each beat that is recieved, store its data in contigous orderz
    for(const auto &beat : writeDataAXI){
        for(int j = 0; j < (1 << writeCmdAXI.size); j++){ 
            //only append size number of bytes to our data, as we are not guaranteed to take up the whol size
            cmd.writeData.push_back(beat.data[j]);
        }  
    }

    //free up the dictionary as it is no longer needed
    writeDataAXI.clear();
    writeRequests.erase(HBM_id);
    
    cmd.type = MemCmdType::Write;
    cmd.addr = writeCmdAXI;
    cmd.eligibleTick = curTick() + cyclesToTicks(writeLatencyCycles);
    pendingCmds.push_back(cmd);
}

void tileNSU_HBM::generateNextWriteResp(const AxiSenderState &s){

    aximmWResp resp;
    resp.id    = s.axi_id;
    resp.valid = true;
    resp.resp  = AximmResp::OKAY;

    (writeResponses[s.axi_id])[s.HBM_id] = (resp);

    DPRINTF(NocMemory, "ADDED TO WRITE_RESP: %x\n", s.HBM_id);
}

aximmRWAddr tileNSU_HBM::getRequestPayload(const NocMemoryMsg* msg_ptr){

    aximmRWAddr axi_payload;
    MessagePayload payload = msg_ptr->getPayload();

    if(aximmRWAddr* p = std::get_if<aximmRWAddr>(&payload)) {
        axi_payload = *p;
    } else {
        panic("tileNSU_HBM::getRequestPayload: Unsupported payload type");
    }

    return axi_payload;
}

void tileNSU_HBM::generateNextReadRespBeat(){
    //do nothing!
}

//TODO: check AXI data length for bursts
void tileNSU_HBM::generateBeatPayload(PacketPtr pkt, const AxiSenderState &s){
        
    int beat_bytes = 1 << s.size;
    int num_beats  = s.len + 1;

    const uint8_t *src = pkt->getConstPtr<uint8_t>();

    for (int b = 0; b < num_beats; b++) {
        aximmRWData payload;

        payload.cmd  = AximmCommand::READ;
        payload.id   = s.axi_id;
        payload.valid = true;
        payload.last  = (b == num_beats - 1);

        assert(beat_bytes <= payload.data.size());
        // copy beat data - always at offset 0 within the beat
        memcpy(payload.data.data(), (src + b * beat_bytes), beat_bytes);

        (readResponses[s.axi_id])[s.HBM_id].push_back(payload);
        DPRINTF(NocMemory, "ADDED TO READ_RESP: %x is last: %d\n", s.HBM_id, payload.last);
    }
}

bool tileNSU_HBM::NoC_SidePort::recvTimingResp(PacketPtr pkt){
    auto *state = static_cast<AxiSenderState*>(pkt->senderState);

    assert(state);

    DPRINTF(NocMemory, "RECIEVED RESPONSE FROM HBM id: %x is read: %d\n", state->HBM_id, state->is_read);
    if (!state->is_read) {
        DPRINTF(NocHBM,
                "[HBM_WRITE_RESP_ARRIVE][tileNSU_HBM] tick=%llu name=%s "
                "axi_id=%u HBM_id=0x%x is_read=0\n",
                (unsigned long long)curTick(),
                owner->name(),
                state->axi_id,
                state->HBM_id);
    }
    // std::cout << "\n" << std::endl;

    tileNSU_HBM::ScheduledMemResp scheduled;
    scheduled.readyTick = curTick() + owner->cyclesToTicks(owner->respLatencyCycles);
    scheduled.isRead = state->is_read;
    scheduled.axiId = state->axi_id;
    scheduled.hbmId = state->HBM_id;
    scheduled.size = state->size;
    scheduled.len = state->len;

    if (state->is_read) {
        const int totalBytes = (state->len + 1) * (1 << state->size);
        scheduled.data.resize(totalBytes);
        memcpy(scheduled.data.data(), pkt->getConstPtr<uint8_t>(), totalBytes);
    }
    owner->scheduledResponses.push_back(std::move(scheduled));

    delete state;
    delete pkt;
    return true;
}

void tileNSU_HBM::NoC_SidePort::recvReqRetry() {
    DPRINTF(NocMemory, "RECV REQ RETRY: unblocking\n");
    owner->blockedOnRetry = false;
}

void tileNSU_HBM::NoC_SidePort::recvRangeChange() {
    // Nothing to do
}


}
}
