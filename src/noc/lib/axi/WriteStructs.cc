#include "noc/lib/axi/WriteStructs.hh"
#include "base/cprintf.hh"
#include <algorithm>

namespace gem5
{
namespace noc
{
namespace garnet
{

namespace {
static void
serialize_axisData(CheckpointOut &cp, const axisData &d)
{
    ::gem5::paramOut(cp, "DATA_WIDTH", d.DATA_WIDTH);
    ::gem5::paramOut(cp, "DST_ID_WIDTH", d.DST_ID_WIDTH);
    ::gem5::paramOut(cp, "ID_WIDTH", d.ID_WIDTH);
    ::gem5::arrayParamOut(cp, "tdata", d.tdata);
    ::gem5::paramOut(cp, "tid", d.tid);
    ::gem5::paramOut(cp, "tdest", d.tdest);
    ::gem5::paramOut(cp, "tkeep", d.tkeep);
    ::gem5::paramOut(cp, "tuser", (uint64_t)d.tuser);
    ::gem5::paramOut(cp, "tlast", d.tlast);
    ::gem5::paramOut(cp, "tvalid", d.tvalid);
}

static axisData
unserialize_axisData(CheckpointIn &cp)
{
    uint32_t data_width = 512, id_width = 6, dest_width = 4;
    ::gem5::paramIn(cp, "DATA_WIDTH", data_width);
    ::gem5::paramIn(cp, "ID_WIDTH", id_width);
    ::gem5::paramIn(cp, "DST_ID_WIDTH", dest_width);
    axisData d(data_width, id_width, dest_width);
    ::gem5::arrayParamIn(cp, "tdata", d.tdata);
    ::gem5::paramIn(cp, "tid", d.tid);
    ::gem5::paramIn(cp, "tdest", d.tdest);
    ::gem5::paramIn(cp, "tkeep", d.tkeep);
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "tuser", tmp); d.tuser = (uint8_t)tmp;
    ::gem5::paramIn(cp, "tlast", d.tlast);
    ::gem5::paramIn(cp, "tvalid", d.tvalid);
    return d;
}
} // namespace

void
WriteTracker::addAxiWriteRequest(uint8_t axi_id, uint16_t destID, uint16_t numNPPWrites, int vc) {

    // // generate a unique tag for this axi write request
    // static WriteTag nextTag = 0;

    // nextTag++;

    writeTrackerMap[axi_id].push_back(WriteTrackerEntry(destID, numNPPWrites, vc));
    numAxiWrites++;
    // tag is equal to the id of the entry we just added
    // this will be needed later to track NPP writes for this axi request
    // return nextTag;
}

bool
WriteTracker::checkSSID(uint8_t axi_id, uint16_t destID) {

    // Check if the AXI ID is in the map and matches the SSID
    auto it = writeTrackerMap.find(axi_id);

    if (it != writeTrackerMap.end()) {
        return it->second.front().destID == destID;
    } else {
        return true; // AXI ID not found, no outstanding requests for this id, SSID check met
    }
}

void
WriteTracker::markRespReceived(uint8_t axi_id, bool SLVERR){
    auto it = writeTrackerMap.find(axi_id);

    if (it == writeTrackerMap.end()){
        panic("WriteTracker::markRespReceived no entry in WriteTracker exists for axi_id %d \n", axi_id);
    } else {
        (it->second).front().numOutstandingResponses--;
        if (SLVERR)
            (it->second).front().receivedSLVERR = true;
        if ((it->second).front().numOutstandingResponses == 0){
            if (writeRespReadyHandler)
                writeRespReadyHandler(axi_id);
            else
                panic("No writeRrespReadyHanlder callback \n");
        }
    }
}

WriteTrackerEntry
WriteTracker::readAndRemoveEntry(uint8_t axi_id){

    auto it = writeTrackerMap.find(axi_id);

    if (it == writeTrackerMap.end()){
        panic("WriteTracker::readAndRemoveEntry no entry in WriteTracker exists for axi_id i%d \n", axi_id);
    } else {
        WriteTrackerEntry wtEntry = (it->second).front();
        (it->second).pop_front();
        if ((it->second).size() == 0)
            writeTrackerMap.erase(axi_id);

        numAxiWrites--;
        return wtEntry;
    }
}

void
aximmWriteBuffer::add(aximmRWAddr nppRequest, int vc, NetworkInterface::OutputPort* oPort, bool SSIDMet, Tick creationTick, bool isDecErr) {

    writeBuffer.push_back(aximmWriteBufferEntry(nppRequest, vc, oPort, SSIDMet, creationTick, isDecErr));

}

void
aximmWriteBuffer::write(std::array<uint8_t, 64> data, uint64_t wstrb, Tick now, Tick period,
                        int32_t probeDebugId)
{

    uint8_t totalBytesWritten = 0;
    auto src = data.begin();

    for (auto it = writeBuffer.begin(); it != writeBuffer.end(); it++){

        uint8_t bytesWritten =
            writeSingleEntry(src, data.begin(), it, wstrb, now, period, probeDebugId);

        src += bytesWritten;
        totalBytesWritten += bytesWritten;

        // axiBeatSize tells us how many beats of data are valid
        // if this many bytes have been written, we've written the entire beat to the buffer,
        // can return
        if (totalBytesWritten == it->axiBeatSize)
            break;
    }

    bufferSize+=totalBytesWritten;
    checkHeadReady();

}

void
aximmWriteBuffer::setSSIDMet(uint8_t numEntries){
    uint8_t numMarked = 0;

    // because ordering of AW corresponding W, AW corresponding W, etc,
    // if SSID check is finally met for an AW, it must correspond to the first entry we
    // find that is waiting for SSID check to be met
    // set first numEntries with !SSIDMet to have SSIDMet
    for (auto it = writeBuffer.begin(); it!= writeBuffer.end(); it++){

        if (!it->SSIDMet) {
            it->SSIDMet = true;
            checkHeadReady(); // maybe head was waiting for SSID check, need to check if now ready
            numMarked++;
            if (numMarked == numEntries)
                return;
        }

    }

    // nothing waiting for SSID to be met
    panic("WriteBuffer::setSSIDMet no data wating for SSID check to be met");
}

uint8_t
aximmWriteBuffer::writeSingleEntry(DataIt src, DataIt srcBegin, WBIt dest,
                                   uint64_t srcWstrb, Tick now, Tick period,
                                   int32_t probeDebugId){

    uint8_t beatSize = dest->axiBeatSize;
    uint8_t bytesWritten = 0;
    uint8_t bytesToWrite;

    // remaining valid bytes in data to write to buffer
    uint8_t dataValidBytes = beatSize - (src - srcBegin);

    if (dest->numEmptyBytes >= dataValidBytes){
        bytesToWrite = dataValidBytes;
    } else {
        bytesToWrite = dest->numEmptyBytes;
    }

    // Track flit boundaries before writing to count new flits produced
    uint16_t totalBytesBefore = dest->nppRequest.getTotalByteSize() - dest->numEmptyBytes;
    int flitsBefore = totalBytesBefore / 16;

    int srcOffsetStart = (src - srcBegin);

    while (bytesToWrite > 0) {
        //bytes left to write in current NPP beat in buffer
        uint8_t* destBase = &(dest->nppData[dest->beatIdx].data[0]);
        // Get reference to the destination strobe so we can OR bits into it
        uint64_t& destStrobe = dest->nppData[dest->beatIdx].wstrb;
        // auto bytesLeftInBeat = dest->nppRequest.getBeatByteSize() - dest->beatOffset;
        // constexpr uint8_t NPP_BEAT_SIZE = 64;
        auto bytesLeftInBeat = NPP_BEAT_SIZE - dest->beatOffset;
        auto bytesToWriteThisRound = std::min<uint8_t>(bytesLeftInBeat, bytesToWrite);

        std::copy(src, src + bytesToWriteThisRound, destBase + dest->beatOffset);

        // Shifting uint64_t by 64 is undefined; a full 64-byte slice needs a full mask.
        const uint64_t mask = (bytesToWriteThisRound >= 64)
            ? ~0ULL
            : ((1ULL << bytesToWriteThisRound) - 1ULL);
        int currentSrcBit = srcOffsetStart + bytesWritten;
        uint64_t relevantBits = (srcWstrb >> currentSrcBit) & mask;
        uint64_t shiftedToDest = relevantBits << dest->beatOffset;

        destStrobe |= shiftedToDest;

        src += bytesToWriteThisRound;
        dest->beatOffset += bytesToWriteThisRound;
        dest->numEmptyBytes -= bytesToWriteThisRound;
        bytesWritten += bytesToWriteThisRound;
        bytesToWrite -= bytesToWriteThisRound;
        bytesLeftInBeat -= bytesToWriteThisRound;

        // have written to all bytes of this NPP beat
        if (bytesLeftInBeat == 0){
            dest->beatIdx++;
            dest->beatOffset = 0;
        }
    }

    // Update pipeline tracking: count how many new flits were produced by this write
    uint16_t totalBytesAfter = dest->nppRequest.getTotalByteSize() - dest->numEmptyBytes;
    int flitsAfter = totalBytesAfter / 16;
    int newFlits = flitsAfter - flitsBefore;

    // Flush any remaining partial flit at the very end of the transaction
    if (dest->numEmptyBytes == 0 && (totalBytesAfter % 16) != 0) {
        newFlits++;
    }

    if (newFlits > 0) {
        if (dest->pipelineEndTick <= now) {
            // Pipeline was idle, start fresh
            dest->pipelineEndTick = now + newFlits * period;
        } else {
            // Pipeline still busy from previous beat, queue behind it
            dest->pipelineEndTick += newFlits * period;
        }
    }

    dest->lastBeatTick = now;

    if (probeDebugId >= 0) {
        dest->probeDebugId = probeDebugId;
    }

    return bytesWritten;
}

void
aximmWriteBuffer::checkHeadReady(){

    if (writeBuffer.size()> 0 && writeBuffer[0].numEmptyBytes == 0 && writeBuffer[0].SSIDMet){
        if (headReadyHandler)
            headReadyHandler(writeBuffer[0].nppRequest, writeBuffer[0].nppData);
        else
            panic("no headReadyHandler setup in WriteBuffer for when head NPP write request ready");
    }
}



void
axisWriteBuffer::add(const axisData& beat, NetworkInterface::OutputPort *oPort, int vc,
                     int32_t debugId) {

    // first check if this is a valid add to the write buffer
    // if we're currently transmitting a packet, tid and tdest must not be different
    if(transmitting) {
        bool tidChanged = currTid != beat.tid;
        bool tdestChanged = currTdest != beat.tdest;

        if(tidChanged || tdestChanged) panic("AXIS Write Buffer: tid or tdest changed before tlast asserted in previous transmission.");
    } else {
        currTid = beat.tid;
        currTdest = beat.tdest;
        transmitting = true;
    }

    if (beat.tlast) {
        transmitting = false;
    }

    // if everything is fine
    // construct new write buffer entry
    axisWriteBufferEntry entry(beat, oPort, vc, debugId);

    // add to write buffer
    writeBuffer.push_back(entry);
    bufferSize += entry.numTotalBytes;

    // update dequeue logic:

    if(beat.tlast) {
        tlastPositions.push_back(bufferSize);
    }

    // if there is a tlast position that is less than the NPP size, set the next dequeue position to that
    // otherwise, if the buffer size is greater than or equal to the NPP size, set the next dequeue position to the NPP size
    // otherwise, set the next dequeue position to -1
    if(!tlastPositions.empty() && tlastPositions.front() <= NPP_SIZE) {
        nextDequeuePos = tlastPositions.front();
    } else if(bufferSize >= NPP_SIZE) {
        nextDequeuePos = NPP_SIZE;
    } else {
        nextDequeuePos = -1;
    }

    checkDequeueReady();
}

bool
axisWriteBuffer::checkDequeueReady() {

    // upon enqueue, we will know if there can be a dequeue same cycle
    if(nextDequeuePos != -1) {

        if (headReadyHandler) {
            headReadyHandler();
            return true;
        }
        else
            panic("no headReadyHandler setup in WriteBuffer for when head NPP write request ready");

    }
    return false;
}

std::unique_ptr<axisPayload>
axisWriteBuffer::popNextPacket(int* vc, NetworkInterface::OutputPort** oPort,
                               int32_t* debugId) {
    // create new axis payload object to return
    auto ret = std::make_unique<axisPayload>();

    const bool endsAtTlast =
        (!tlastPositions.empty() && nextDequeuePos == tlastPositions.front());
    if (endsAtTlast) {
        tlastPositions.pop_front();
    }

    // since buffer is popping nextDequeuePos bytes, we need to subtract that from all tlast positions
    for(int& pos : tlastPositions) {
        pos -= nextDequeuePos;
    }

    // Determine how many bytes we are allowed to dequeue this cycle.
    const int bytesTarget = nextDequeuePos;

    int bytesPacked = 0;
    bool outParamsSet = false;

    while (bytesPacked < bytesTarget && !writeBuffer.empty()) {
        auto& entry = writeBuffer.front();

        // Set vc/oPort from the first contributing entry for this NPP
        if (!outParamsSet) {
            if (vc)    *vc = entry.vc;
            if (oPort) *oPort = entry.oPort;
            if (debugId) *debugId = entry.debugId;
            outParamsSet = true;
        }

        const int spaceRemaining = bytesTarget - bytesPacked;   // remaining space in this NPP
        const int bytesRemaining = entry.numBytesRemaining;     // bytes left in this beat

        if (bytesRemaining <= spaceRemaining) {
            // Whole beat fits
            ret->add(entry.nppData, entry.debugId);
            bytesPacked += bytesRemaining;
            bufferSize  -= bytesRemaining;
            writeBuffer.pop_front();
        } else {
            // Only partial beat fits: split tkeep between current NPP and remaining
            axisData partial(entry.nppData);

            uint64_t x = entry.nppData.tkeep;
            int n = spaceRemaining;
            uint64_t tkeepLower = 0; // the tkeep, but only with the bottom spaceRemaining ones kept
            uint64_t tkeepHigher = x; // the tkeep, but with the bottom spaceRemaining zeroed out
            int count = 0;

            for (int c = 0; c < 64; c++) {
                if (x & (1ULL << c)) {
                    count++;
                    if (count <= n) {
                        tkeepLower |= (1ULL << c); // keep this bit in tkeepLower
                    } else {
                        tkeepHigher &= ~(1ULL << c); // clear this bit in tkeepHigher
                    }
                }
            }

            partial.tkeep = tkeepLower;
            entry.nppData.tkeep = tkeepHigher;
            entry.numBytesRemaining -= spaceRemaining;

            ret->add(partial, entry.debugId);
            bytesPacked += spaceRemaining;
            bufferSize  -= spaceRemaining;
            // Do not pop_front(); the entry still has remaining bytes
        }
    }

    // Set 'last' if this dequeue ends exactly at a TLAST boundary,
    // even when the boundary aligns with a full NPP.
    if (endsAtTlast)
        ret->last = 1;

    // Recompute nextDequeuePos based on remaining buffer
    if(!tlastPositions.empty() && tlastPositions.front() <= NPP_SIZE) {
        nextDequeuePos = tlastPositions.front();
    } else if(bufferSize >= NPP_SIZE) {
        nextDequeuePos = NPP_SIZE;
    } else {
        nextDequeuePos = -1;
    }

    return ret;
}

void
axisWriteBuffer::serialize(CheckpointOut &cp) const
{
    ::gem5::paramOut(cp, "maxBeatSize", maxBeatSize);
    ::gem5::paramOut(cp, "bufferSize", bufferSize);
    ::gem5::paramOut(cp, "currTid", currTid);
    ::gem5::paramOut(cp, "currTdest", currTdest);
    ::gem5::paramOut(cp, "transmitting", transmitting);
    ::gem5::paramOut(cp, "nextDequeuePos", nextDequeuePos);

    ::gem5::paramOut(cp, "tlastPositionsSize", (uint64_t)tlastPositions.size());
    ::gem5::paramOut(cp, "writeBufferSize", (uint64_t)writeBuffer.size());

    size_t idx = 0;
    for (const auto &p : tlastPositions) {
        ::gem5::paramOut(cp, csprintf("tlastPos%d", (int)idx), p);
        idx++;
    }

    for (size_t i = 0; i < writeBuffer.size(); i++) {
        const auto &e = writeBuffer[i];
        Serializable::ScopedCheckpointSection sec(cp, csprintf("e%d", (int)i));
        ::gem5::paramOut(cp, "numTotalBytes", (uint64_t)e.numTotalBytes);
        ::gem5::paramOut(cp, "numBytesRemaining", (uint64_t)e.numBytesRemaining);
        ::gem5::paramOut(cp, "debugId", (int64_t)e.debugId);
        ::gem5::paramOut(cp, "vc", e.vc);
        int router_id = -1;
        if (e.oPort)
            router_id = e.oPort->routerID();
        ::gem5::paramOut(cp, "oPortRouterId", router_id);
        Serializable::ScopedCheckpointSection sec2(cp, "nppData");
        serialize_axisData(cp, e.nppData);
    }
}

void
axisWriteBuffer::unserialize(CheckpointIn &cp,
                             const std::vector<NetworkInterface::OutputPort*> &outPorts)
{
    ::gem5::paramIn(cp, "maxBeatSize", maxBeatSize);
    ::gem5::paramIn(cp, "bufferSize", bufferSize);
    ::gem5::paramIn(cp, "currTid", currTid);
    ::gem5::paramIn(cp, "currTdest", currTdest);
    ::gem5::paramIn(cp, "transmitting", transmitting);
    ::gem5::paramIn(cp, "nextDequeuePos", nextDequeuePos);

    tlastPositions.clear();
    uint64_t tls = 0;
    ::gem5::paramIn(cp, "tlastPositionsSize", tls);
    for (size_t i = 0; i < tls; i++) {
        int pos = 0;
        ::gem5::paramIn(cp, csprintf("tlastPos%d", (int)i), pos);
        tlastPositions.push_back(pos);
    }

    writeBuffer.clear();
    uint64_t wbs = 0;
    ::gem5::paramIn(cp, "writeBufferSize", wbs);
    for (size_t i = 0; i < wbs; i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("e%d", (int)i));
        axisWriteBufferEntry e;
        uint64_t tmp = 0;
        ::gem5::paramIn(cp, "numTotalBytes", tmp); e.numTotalBytes = (uint8_t)tmp;
        ::gem5::paramIn(cp, "numBytesRemaining", tmp); e.numBytesRemaining = (uint16_t)tmp;
        int64_t dbg = -1;
        ::gem5::paramIn(cp, "debugId", dbg);
        e.debugId = (int32_t)dbg;
        ::gem5::paramIn(cp, "vc", e.vc);
        int router_id = -1;
        ::gem5::paramIn(cp, "oPortRouterId", router_id);
        e.oPort = nullptr;
        if (router_id >= 0) {
            for (auto *op : outPorts) {
                if (op && op->routerID() == router_id) { e.oPort = op; break; }
            }
        }
        {
            Serializable::ScopedCheckpointSection sec2(cp, "nppData");
            e.nppData = unserialize_axisData(cp);
        }
        writeBuffer.push_back(e);
    }
}

namespace {

template <typename T, std::size_t N>
void
serializeStdArrayWB(CheckpointOut &cp, const char *name,
                  const std::array<T, N> &arr)
{
    ::gem5::arrayParamOut(cp, name, arr.data(), N);
}

template <typename T, std::size_t N>
void
unserializeStdArrayWB(CheckpointIn &cp, const char *name, std::array<T, N> &arr)
{
    ::gem5::arrayParamIn(cp, name, arr.data(), N);
}

static void
serialize_aximmRWAddrWB(CheckpointOut &cp, const aximmRWAddr &a)
{
    ::gem5::paramOut(cp, "cmd", (int)a.cmd);
    ::gem5::paramOut(cp, "id", a.id);
    ::gem5::paramOut(cp, "addr", a.addr);
    ::gem5::paramOut(cp, "len", (uint64_t)a.len);
    ::gem5::paramOut(cp, "size", (uint64_t)a.size);
    ::gem5::paramOut(cp, "burst", (int)a.burst);
    ::gem5::paramOut(cp, "lock", a.lock);
    ::gem5::paramOut(cp, "cache", (uint64_t)a.cache);
    ::gem5::paramOut(cp, "prot", (uint64_t)a.prot);
    ::gem5::paramOut(cp, "qos", (uint64_t)a.qos);
    ::gem5::paramOut(cp, "region", (uint64_t)a.region);
    ::gem5::paramOut(cp, "user", (uint64_t)a.user);
    ::gem5::paramOut(cp, "valid", a.valid);
}

static aximmRWAddr
unserialize_aximmRWAddrWB(CheckpointIn &cp)
{
    aximmRWAddr a;
    int cmd = (int)AximmCommand::NONE;
    int burst = (int)BurstType::INCR;
    ::gem5::paramIn(cp, "cmd", cmd);
    ::gem5::paramIn(cp, "burst", burst);
    a.cmd = (AximmCommand)cmd;
    a.burst = (BurstType)burst;
    ::gem5::paramIn(cp, "id", a.id);
    ::gem5::paramIn(cp, "addr", a.addr);
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "len", tmp); a.len = (uint8_t)tmp;
    ::gem5::paramIn(cp, "size", tmp); a.size = (uint8_t)tmp;
    ::gem5::paramIn(cp, "lock", a.lock);
    ::gem5::paramIn(cp, "cache", tmp); a.cache = (uint8_t)tmp;
    ::gem5::paramIn(cp, "prot", tmp); a.prot = (uint8_t)tmp;
    ::gem5::paramIn(cp, "qos", tmp); a.qos = (uint8_t)tmp;
    ::gem5::paramIn(cp, "region", tmp); a.region = (uint8_t)tmp;
    ::gem5::paramIn(cp, "user", tmp); a.user = (uint8_t)tmp;
    ::gem5::paramIn(cp, "valid", a.valid);
    return a;
}

static void
serialize_aximmRWDataWB(CheckpointOut &cp, const aximmRWData &d)
{
    ::gem5::paramOut(cp, "cmd", (int)d.cmd);
    ::gem5::paramOut(cp, "id", d.id);
    ::gem5::paramOut(cp, "resp", (int)d.resp);
    ::gem5::paramOut(cp, "last", d.last);
    ::gem5::paramOut(cp, "user", (uint64_t)d.user);
    ::gem5::paramOut(cp, "valid", d.valid);
    ::gem5::paramOut(cp, "ready", d.ready);
    serializeStdArrayWB(cp, "data", d.data);
    ::gem5::paramOut(cp, "wstrb", d.wstrb);
}

static aximmRWData
unserialize_aximmRWDataWB(CheckpointIn &cp)
{
    aximmRWData d;
    int cmd = 0, resp = 0;
    ::gem5::paramIn(cp, "cmd", cmd);
    ::gem5::paramIn(cp, "resp", resp);
    d.cmd = (AximmCommand)cmd;
    d.resp = (AximmResp)resp;
    ::gem5::paramIn(cp, "id", d.id);
    ::gem5::paramIn(cp, "last", d.last);
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "user", tmp); d.user = (uint8_t)tmp;
    ::gem5::paramIn(cp, "valid", d.valid);
    ::gem5::paramIn(cp, "ready", d.ready);
    unserializeStdArrayWB(cp, "data", d.data);
    ::gem5::paramIn(cp, "wstrb", d.wstrb);
    return d;
}

} // namespace

void
WriteTracker::serialize(CheckpointOut &cp) const
{
    ::gem5::paramOut(cp, "numAxiWrites", (uint64_t)numAxiWrites);
    std::vector<uint8_t> keys;
    keys.reserve(writeTrackerMap.size());
    for (const auto &p : writeTrackerMap)
        keys.push_back(p.first);
    std::sort(keys.begin(), keys.end());
    ::gem5::paramOut(cp, "numKeys", (uint64_t)keys.size());
    for (size_t ki = 0; ki < keys.size(); ki++) {
        uint8_t axi_id = keys[ki];
        Serializable::ScopedCheckpointSection sec(cp, csprintf("wtKey%u", (unsigned)ki));
        ::gem5::paramOut(cp, "axiId", (uint64_t)axi_id);
        const auto &dq = writeTrackerMap.at(axi_id);
        ::gem5::paramOut(cp, "dequeSize", (uint64_t)dq.size());
        for (size_t i = 0; i < dq.size(); i++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("wtE%u", (unsigned)i));
            const auto &e = dq[i];
            ::gem5::paramOut(cp, "destID", e.destID);
            ::gem5::paramOut(cp, "numOutstandingResponses",
                             e.numOutstandingResponses);
            ::gem5::paramOut(cp, "receivedSLVERR", e.receivedSLVERR);
            ::gem5::paramOut(cp, "vc", e.vc);
        }
    }
}

void
WriteTracker::unserialize(CheckpointIn &cp)
{
    writeTrackerMap.clear();
    uint64_t num_ax_discard = 0;
    ::gem5::paramIn(cp, "numAxiWrites", num_ax_discard);

    uint64_t nk = 0;
    ::gem5::paramIn(cp, "numKeys", nk);
    for (size_t ki = 0; ki < nk; ki++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("wtKey%u", (unsigned)ki));
        uint64_t axi_id_u = 0;
        ::gem5::paramIn(cp, "axiId", axi_id_u);
        uint8_t axi_id = (uint8_t)axi_id_u;
        uint64_t dqs = 0;
        ::gem5::paramIn(cp, "dequeSize", dqs);
        std::deque<WriteTrackerEntry> dq;
        for (size_t i = 0; i < dqs; i++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("wtE%u", (unsigned)i));
            uint16_t destID = 0;
            uint16_t numOut = 0;
            bool slv = false;
            int vc = 0;
            ::gem5::paramIn(cp, "destID", destID);
            ::gem5::paramIn(cp, "numOutstandingResponses", numOut);
            ::gem5::paramIn(cp, "receivedSLVERR", slv);
            ::gem5::paramIn(cp, "vc", vc);
            WriteTrackerEntry e(destID, numOut, vc);
            e.receivedSLVERR = slv;
            dq.push_back(e);
        }
        writeTrackerMap[axi_id] = std::move(dq);
    }

    size_t sum = 0;
    for (const auto &p : writeTrackerMap)
        sum += p.second.size();
    fatal_if(sum > 255, "WriteTracker::unserialize: too many outstanding writes");
    numAxiWrites = (uint8_t)sum;
}

void
aximmWriteBuffer::serialize(CheckpointOut &cp) const
{
    ::gem5::paramOut(cp, "bufferSize", bufferSize);
    ::gem5::paramOut(cp, "writeBufferSize", (uint64_t)writeBuffer.size());
    for (size_t i = 0; i < writeBuffer.size(); i++) {
        const auto &ent = writeBuffer[i];
        Serializable::ScopedCheckpointSection sec(cp, csprintf("wbe%u", (unsigned)i));
        ::gem5::paramOut(cp, "axiBeatSize", (uint64_t)ent.axiBeatSize);
        {
            Serializable::ScopedCheckpointSection sec2(cp, "nppRequest");
            serialize_aximmRWAddrWB(cp, ent.nppRequest);
        }
        ::gem5::paramOut(cp, "numEmptyBytes", ent.numEmptyBytes);
        for (int b = 0; b < 4; b++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("nppData%d", b));
            serialize_aximmRWDataWB(cp, ent.nppData[b]);
        }
        ::gem5::paramOut(cp, "beatIdx", (uint64_t)ent.beatIdx);
        ::gem5::paramOut(cp, "beatOffset", (uint64_t)ent.beatOffset);
        ::gem5::paramOut(cp, "SSIDMet", ent.SSIDMet);
        ::gem5::paramOut(cp, "vc", ent.vc);
        int router_id = ent.oPort ? ent.oPort->routerID() : -1;
        ::gem5::paramOut(cp, "oPortRouterId", router_id);
        ::gem5::paramOut(cp, "isDecErr", ent.isDecErr);
        ::gem5::paramOut(cp, "creationTick", (uint64_t)ent.creationTick);
        ::gem5::paramOut(cp, "pipelineEndTick", (uint64_t)ent.pipelineEndTick);
        ::gem5::paramOut(cp, "lastBeatTick", (uint64_t)ent.lastBeatTick);
        ::gem5::paramOut(cp, "probeDebugId", ent.probeDebugId);
    }
}

void
aximmWriteBuffer::unserialize(
    CheckpointIn &cp, const std::vector<NetworkInterface::OutputPort*> &outPorts)
{
    writeBuffer.clear();
    ::gem5::paramIn(cp, "bufferSize", bufferSize);
    uint64_t wbs = 0;
    ::gem5::paramIn(cp, "writeBufferSize", wbs);
    for (size_t i = 0; i < wbs; i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("wbe%u", (unsigned)i));
        aximmWriteBufferEntry ent;
        uint64_t tmp = 0;
        ::gem5::paramIn(cp, "axiBeatSize", tmp); ent.axiBeatSize = (uint8_t)tmp;
        {
            Serializable::ScopedCheckpointSection sec2(cp, "nppRequest");
            ent.nppRequest = unserialize_aximmRWAddrWB(cp);
        }
        ::gem5::paramIn(cp, "numEmptyBytes", ent.numEmptyBytes);
        for (int b = 0; b < 4; b++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("nppData%d", b));
            ent.nppData[b] = unserialize_aximmRWDataWB(cp);
        }
        ::gem5::paramIn(cp, "beatIdx", tmp); ent.beatIdx = (uint8_t)tmp;
        ::gem5::paramIn(cp, "beatOffset", tmp); ent.beatOffset = (uint8_t)tmp;
        ::gem5::paramIn(cp, "SSIDMet", ent.SSIDMet);
        ::gem5::paramIn(cp, "vc", ent.vc);
        int router_id = -1;
        ::gem5::paramIn(cp, "oPortRouterId", router_id);
        ent.oPort = nullptr;
        if (router_id >= 0) {
            for (auto *op : outPorts) {
                if (op && op->routerID() == router_id) {
                    ent.oPort = op;
                    break;
                }
            }
        }
        ::gem5::paramIn(cp, "isDecErr", ent.isDecErr);
        uint64_t t = 0;
        ::gem5::paramIn(cp, "creationTick", t); ent.creationTick = (Tick)t;
        ::gem5::paramIn(cp, "pipelineEndTick", t); ent.pipelineEndTick = (Tick)t;
        ::gem5::paramIn(cp, "lastBeatTick", t); ent.lastBeatTick = (Tick)t;
        ::gem5::paramIn(cp, "probeDebugId", ent.probeDebugId);
        writeBuffer.push_back(ent);
    }
}

}
}
}
