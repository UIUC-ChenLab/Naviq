#ifndef __BRAM_ENDPOINT_HH__
#define __BRAM_ENDPOINT_HH__

#include "noc/core/interface/NocInterface.hh"
#include "params/BramEndpoint.hh"
#include "noc/core/network/NocSystem.hh"
#include "noc/core/network/NocSlaveUnit.hh"
#include "noc/endpoints/NocNode.hh"

#include <deque>
#include <cstdint>
#include <vector>

namespace gem5
{
namespace noc{


class BramEndpoint : public NocNode, public FunctionalMemoryEndpoint
{
    public:
        typedef BramEndpointParams Params;
        BramEndpoint(const Params &p);

        // FunctionalMemoryEndpoint interface
        void functionalWrite(Addr addr, const uint8_t* data, size_t size) override;
        void functionalRead(Addr addr, uint8_t* data, size_t size) override;
        bool addressInRange(Addr addr) const override;

        //main simulation loop (1 cycle)
        bool tick(int clockDomain) override;
        bool done() { return true; }
        void update(int portID, State* inputNocInterfaceState) override;
        State* getCurrentState(int portID) override;
        int assignPort(const std::string &endpointName) override;

        virtual void updateTileNSU(aximmMasterState tileControllerState);

        // added for hbm to inherit from, maybe dont need?
        virtual void updateReadyFlag(bool recvFlag);

    protected:
        NocSystem* system;
        NocInterface* tile_controller;

        Tick simCycles;

        // ====== BRAM Storage ======
        std::vector<uint8_t> memoryStorage;  // Actual data storage
        Addr baseAddr;                        // Base address of this BRAM
        size_t memorySize;                    // Size in bytes
        Cycles readLatency;                   // Read latency
        Cycles writeLatency;                  // Write latency

        // Helper methods for BRAM operations
        bool isValidAddress(Addr addr, uint16_t size) const;
        Addr toLocalAddr(Addr addr) const { return addr - baseAddr; }
        void writeToStorage(Addr localAddr, const std::array<uint8_t, 64>& data, 
                           uint64_t wstrb, uint8_t beatSize);
        void readFromStorage(Addr localAddr, std::array<uint8_t, 64>& data, 
                            uint8_t beatSize) const;

    private:
        void generateBeatPayload(aximmRWAddr readCmd, bool last, uint8_t beatIdx);
        aximmRWAddr getRequestPayload(const NocMemoryMsg* msg_ptr);
        void generateNextReadRespBeat();
        aximmRWData getNextAxiResponse();

        aximmWResp getNextWriteResponse();
        void generateNextWriteResp();
        void handleWriteData(const aximmRWData& writeData);

        aximmSlaveState currentState;
        aximmSlaveState nextState;
        aximmMasterState tileControllerState;

        // store read requests and id of requests we need to serve
        // id meaning the beat id of the next response to be sent for the request
        struct ReadRequestEntry
        {
            aximmRWAddr addr;
            uint8_t beatIdx = 0;
            Tick readyTick = 0;
        };
        std::deque<ReadRequestEntry> readRequests;
        std::deque<ReadRequestEntry> readRequestsdelay;

        // store read responses that are ready to be sent to master
        std::deque<aximmRWData> readResponses;

        // store write requests to serve
        std::deque<aximmRWAddr> writeRequests;

        // store write responses that are ready to be sent to master
        std::deque<aximmWResp> writeResponses;
        Tick m_last_w_last_tick = 0;
        std::deque<std::pair<aximmWResp, Tick>> delayedWriteResponses;

        // Multi-beat write tracking
        aximmRWAddr currWriteRequest;  // Current write request being processed
        uint8_t currWriteBeatIdx;       // Current beat index for multi-beat writes
        bool writeInProgress;           // Whether a multi-beat write is in progress
        bool portAssigned;
};
}
}

#endif
