#ifndef __WRITE_STRUCTS_HH
#define __WRITE_STRUCTS_HH

#include "noc/lib/axi/AXITypes.hh"
#include "base/logging.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "sim/serialize.hh"


#include <deque>
#include <vector>
#include <unordered_map>
#include <array>

namespace gem5{
namespace noc{
namespace garnet{

    // use to tag each outstanding write request for a given axi id
using WriteTag = uint8_t;

struct WriteTrackerEntry{

    uint16_t destID;
    uint16_t numOutstandingResponses;
    bool receivedSLVERR; // if any of the NPP writes get a SLVERR rsp, send back error for entire AXI
                            // request corresponding to this entry
    int vc; //vc write request corresponds to and vc to send resp to

    WriteTrackerEntry(uint16_t destID, uint16_t numNPPWrites, int vc) :
        destID(destID), numOutstandingResponses(numNPPWrites), receivedSLVERR(false),
        vc(vc)
    {

    }

    WriteTrackerEntry() : destID(0) {panic("default constructor for WriteTrackerEntry called");}

};

/**
 * Tracks one ordered response stream per AXI ID after a request is split into
 * NoC packet payloads. The released contract accepts AW before its W beats;
 * arbitrary W-before-AW association is intentionally not provided here.
 */
class WriteTracker{

    public:
        void addAxiWriteRequest(uint8_t axi_id, uint16_t destID, uint16_t numNPPWrites, int vc);
        bool checkSSID(uint8_t axi_id, uint16_t destID);
        void markRespReceived(uint8_t axi_id, bool SLVERR);
        WriteTrackerEntry readAndRemoveEntry(uint8_t axi_id);

        uint8_t getNumEntries(){return numAxiWrites;}
        uint16_t getDestID(uint8_t axi_id){

            auto it = writeTrackerMap.find(axi_id);
            if (it == writeTrackerMap.end())
                panic("WriteTracker::getDestID no entry in WriteTracker exists for axi_id %d \n", axi_id);
            else
                return ((it->second).front()).destID;
        }

        void setWriteRespReadyHandler(std::function<void(uint8_t)> cb){
            writeRespReadyHandler = std::move(cb);
        }

        WriteTracker(): writeTrackerMap(), writeRespReadyHandler(nullptr), numAxiWrites(0){;}

        void serialize(CheckpointOut &cp) const;
        void unserialize(CheckpointIn &cp);

    private:
        // each AXI ID has 1 writeTrackerEntry, can only be writing to 1 destination at a time
        std::unordered_map<uint8_t, std::deque<WriteTrackerEntry>> writeTrackerMap;

        // callback to NMU when an axi_id has received all NPP write responses for head entry corresponding to an AXI Write
        std::function<void(uint8_t)> writeRespReadyHandler;
        uint8_t numAxiWrites; // number of AXI write requests currently being stored in tracker

};

struct aximmWriteBufferEntry{

    // WriteTag wtTag;
    uint8_t axiBeatSize;
    aximmRWAddr nppRequest;
    uint16_t numEmptyBytes; //# of bytes that remain left to be written to by W channel
    std::array<aximmRWData, 4> nppData; //up to 4 beats
    uint8_t beatIdx; // current nppData beat to write to
    uint8_t beatOffset; // current byte within beat to write to
    bool SSIDMet; // tag whether this data is waiting for SSID check of corresponding req to be met
    int vc;
    NetworkInterface::OutputPort* oPort;
    bool isDecErr; // tag whether this write has a decode error and should be dropped
    Tick creationTick; // when AW request arrived (for NMU prep time calculation)
    Tick pipelineEndTick; // tracks when internal flit packing will finish for data received so far
    Tick lastBeatTick; // tracks when the last beat arrived

    /** Last probe-assigned id from NocProbe on AW/W path (AXIS-style correlation). */
    int32_t probeDebugId = -1;

    aximmWriteBufferEntry(aximmRWAddr nppRequest, int vc, NetworkInterface::OutputPort* oPort, bool SSIDMet, Tick creationTick = 0, bool isDecErr = false):
        axiBeatSize(nppRequest.getBeatByteSize()), nppRequest(nppRequest),
        numEmptyBytes(nppRequest.getTotalByteSize()),
        beatIdx(0), beatOffset(0), SSIDMet(SSIDMet), vc(vc), oPort(oPort), isDecErr(isDecErr),
        creationTick(creationTick), pipelineEndTick(0), lastBeatTick(0)
        {
            // Initialize AXI ID and valid flag in all data beats
            // so NSU can properly track write data and read strobe values
            for (auto& beat : nppData) {
                beat.id = nppRequest.id;
                beat.valid = true;  // Must set valid for getFlitStrobe() to work
                beat.wstrb = 0;
                beat.data.fill(0);
            }
        }

    aximmWriteBufferEntry() = default;
};

/**
 * Bounded staging buffer for AXI-MM W data after AW has created the matching
 * NPP entries.  The capacity models 512 bytes of local storage; entries are
 * made visible to the NMU only when the head NPP is complete.
 */
class aximmWriteBuffer{

    constexpr static size_t MAX_SIZE = 512; // in bytes

    using WBIt = std::deque<aximmWriteBufferEntry>::iterator;
    using DataIt = std::array<uint8_t, 64>::iterator;

    public:
        aximmWriteBuffer() : writeBuffer(), bufferSize(0), headReadyHandler(nullptr){;}
        ~aximmWriteBuffer() = default;

        void add(aximmRWAddr nppRequest, int vc, NetworkInterface::OutputPort* oPort, bool SSIDMet, Tick creationTick = 0, bool isDecErr = false);
        void write(std::array<uint8_t, 64> data, uint64_t wstrb, Tick now, Tick period,
                   int32_t probeDebugId = -1);
        void setSSIDMet(uint8_t numEntries);
        uint16_t getSize(){return bufferSize;}

        aximmWriteBufferEntry readHead(){return writeBuffer.front();}
        void removeHead(){
            aximmWriteBufferEntry entry = writeBuffer.front();
            bufferSize -= entry.nppRequest.getTotalByteSize();
            writeBuffer.pop_front();
        }

        void setHeadReadyHandler(std::function<void(aximmRWAddr, std::array<aximmRWData, 4>)> cb){
            headReadyHandler = std::move(cb);
        }

        /** After removing the head entry (full write injected), may start the next NPP. */
        void notifyTransmitComplete() { checkHeadReady(); }

        void serialize(CheckpointOut &cp) const;
        void unserialize(CheckpointIn &cp,
                         const std::vector<NetworkInterface::OutputPort*> &outPorts);

    private:
        std::deque<aximmWriteBufferEntry> writeBuffer;
        uint16_t bufferSize;

        uint8_t writeSingleEntry(DataIt src, DataIt srcBegin, WBIt dest,
                                 uint64_t wstrb, Tick now, Tick period,
                                 int32_t probeDebugId);
        void checkHeadReady(); // after write to buffer, check if head NPP write request is ready to be sent out

        // callback to NMU when head of write buffer ready for transmission
        std::function<void(aximmRWAddr, std::array<aximmRWData, 4>)> headReadyHandler; 

};


struct axisWriteBufferEntry {
    // write buffer size 512 bytes, can be any size 
    // maximum npp data size 256 bytes + 1 flit of header (16 bytes)
    // npps are not efficient, if write buffer entry is smaller than npp

    // to finish packing, id changes, dest changes, or t last is asserted

    // 45 total 16 bytes in total pipeline

    uint8_t numTotalBytes; // active bytes that needs to be sent per this beat
    axisData nppData;
    uint16_t numBytesRemaining; // number of bytes still needed to be transferred

    // Optional debug correlation id (assigned by NocProbe at state->cdc boundary).
    // Propagated across packetization so receiver-side state hooks can observe it.
    int32_t debugId = -1;

    int vc; // should be set
    NetworkInterface::OutputPort* oPort;

    axisWriteBufferEntry(axisData nppData, NetworkInterface::OutputPort* oPort, int vc,
                         int32_t debugId = -1):
        numTotalBytes(nppData.getTotalByteSize()),
        nppData(nppData),
        numBytesRemaining(nppData.getTotalByteSize()),
        debugId(debugId),
        vc(vc), oPort(oPort)
        {;}

    axisWriteBufferEntry() = default;

};

class axisWriteBuffer{

    constexpr static size_t MAX_SIZE = 512; // in bytes
    constexpr static size_t NPP_SIZE = 256; // in bytes

    public:
        axisWriteBuffer() : writeBuffer(),
                            maxBeatSize(512),
                            bufferSize(0),
                            currTid(-1), currTdest(-1),
                            transmitting(0),
                            nextDequeuePos(-1),
                            headReadyHandler(nullptr) {;} 
        ~axisWriteBuffer() = default;

        void add(const axisData& beat, NetworkInterface::OutputPort *oPort, int vc,
                 int32_t debugId = -1);
        
        // Collect one NPP (never more than 256 bytes). Packetization must not
        // merge adjacent AXIS bytes into a payload larger than this invariant.
        // Packet identity (TID, TDEST, TLAST) is retained while a packet is open.
        std::unique_ptr<axisPayload> popNextPacket(int* vc, NetworkInterface::OutputPort** oPort,
                                                   int32_t* debugId = nullptr);

        uint16_t getSize(){return bufferSize;}
        void setHeadReadyHandler(std::function<void()> cb){
            headReadyHandler = std::move(cb);
        }
        bool checkDequeueReady();

        void serialize(CheckpointOut &cp) const;
        void unserialize(CheckpointIn &cp, const std::vector<NetworkInterface::OutputPort*> &outPorts);

    private:
        std::deque<axisWriteBufferEntry> writeBuffer;
        uint16_t maxBeatSize; // max number of bytes per beat (size of axis data bus)
        uint16_t bufferSize; // amnt of bytes currently in buffer

        // Packet identity of the oldest buffered stream bytes.
        int currTid, currTdest;
        bool transmitting;

        std::deque<int> tlastPositions;
        // Highest byte position known ready for the next NPP dequeue.
        int nextDequeuePos;

        // callback to NMU when head of write buffer ready for transmission 
        std::function<void()> headReadyHandler;

};
 

}
}
}


#endif
