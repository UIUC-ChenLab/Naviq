#ifndef __CPU_NOC_BRIDGE_HH
#define __CPU_NOC_BRIDGE_HH

#include "noc/endpoints/NocNode.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "params/CpuNocBridge.hh"
#include "mem/port.hh"
#include <string>

namespace gem5
{
namespace noc
{

// Forward declaration
namespace garnet {
class NocGarnetNetwork;
}

class CpuNocBridge : public NocNode
{
  public:
    typedef CpuNocBridgeParams Params;
    CpuNocBridge(const Params &p);
    
    void init() override;

    /** gem5 port interface */
    Port& getPort(const std::string &if_name, PortID idx) override;

    /** NocNode interface - called by Control.cc */
    bool tick(int clockDomain) override;
    bool done() override;
    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string &endpointName) override;

  private:
    // CPU-side ResponsePort - receives requests from CPU, sends responses back.
    class CpuSidePort : public ResponsePort
    {
      private:
        CpuNocBridge* owner;
        bool needRetry;
        
      public:
        CpuSidePort(const std::string& name, CpuNocBridge* owner);
        
        // Receive a timing request from the CPU
        bool recvTimingReq(PacketPtr pkt) override;
        
        // CPU is retrying a response we couldn't accept
        void recvRespRetry() override;
        
        // Return the address ranges we handle
        AddrRangeList getAddrRanges() const override;
        
        // Functional and atomic access (for initialization)
        Tick recvAtomic(PacketPtr pkt) override;
        void recvFunctional(PacketPtr pkt) override;
        
        // Send a retry to the CPU
        void sendRetryReq();
        
        // Try to send a response
        bool trySendResponse(PacketPtr pkt);
    };
    
    CpuSidePort cpuSidePort;

    /** Track outstanding requests by AXI ID */
    struct OutstandingRequest {
        PacketPtr pkt;           // Original gem5 packet
        uint32_t axi_id;         // Assigned AXI ID
        uint64_t dest_id;        // Destination ID (for ID tracking)
        uint16_t beats_expected; // For multi-beat reads
        uint16_t beats_received; // Beats received so far
        Addr axi_addr;           // Address used on the AXI transaction
        uint32_t axi_beat_bytes; // Bytes per AXI beat for this request
        std::vector<uint8_t> data; // Accumulated read data
        bool is_read;
        bool is_mmio = false;
        Addr original_addr = 0;
        unsigned original_size = 0;
        unsigned axi_bytes = 0;
        Tick start_tick = 0;
    };
    
    std::map<uint32_t, std::deque<OutstandingRequest>> outstanding;  // AXI ID → queue (FIFO)
    std::deque<uint32_t> freeAxiIds;  // Pool of available AXI IDs
    
    /** Destination-based AXI ID tracking */
    // Maps destination ID → assigned AXI ID (only valid while transactions outstanding)
    std::map<uint64_t, uint32_t> destToAxiId;
    // Tracks count of outstanding transactions per destination
    std::map<uint64_t, uint32_t> destOutstandingCount;
    
    /** Pending requests from CPU that haven't been converted to AXI yet */
    std::deque<PacketPtr> pendingRequests;
    
    /** Pending responses to send back to CPU */
    std::deque<PacketPtr> pendingResponses;
    bool blockedOnResponse;  
    
    /** AXI state machines */
    aximmMasterState currentState;
    aximmMasterState nextState;
    aximmSlaveState nocInterfaceState;
    
    /** Queues for AXI transactions (like tile.cc) */
    std::deque<aximmRWAddr> readRequests;   // AR channel
    std::deque<aximmRWAddr> writeRequests;  // AW channel
    std::deque<aximmRWData> writeData;      // W channel
    
    /** Configuration */
    garnet::NocGarnetNetwork* nocNetwork;  // For address→dest mapping
    Tick simCycles;
    int maxOutstanding;
    std::vector<AddrRange> addrRanges;
    std::vector<AddrRange> mmioRanges;
    Addr scratchReadBurstBase;
    unsigned scratchReadBurstSize;
    unsigned scratchReadBurstBytes;
    FunctionalMemoryEndpoint* functionalMemory;
    FunctionalMemoryEndpoint* secondaryFunctionalMemory;
    std::vector<AddrRange> secondaryFunctionalRanges;
    bool runConsistencyCheck;
    std::string metricsOutputPath;
    
    void startup() override;

    
    /** Helper methods */
    uint64_t getDestIdForAddr(Addr addr) const;
    uint32_t getAxiIdForDest(uint64_t dest_id);
    void releaseAxiIdForDest(uint64_t dest_id, uint32_t axi_id);
    bool canAcceptRequest(Addr addr) const;
    bool isMmioRequest(Addr addr, unsigned size) const;
    bool isScratchBurstRead(Addr addr, unsigned size) const;
    unsigned mmioAxiSize(unsigned bytes) const;
    FunctionalMemoryEndpoint* functionalMemoryForAddr(Addr addr) const;
    void functionalWrite(Addr addr, const uint8_t* data, size_t size);
    void functionalRead(Addr addr, uint8_t* data, size_t size);
    
    void processNewRequests();     // Convert pending Packets → AXI
    void processReadResponse();    // Handle read data from NoC
    void processWriteResponse();   // Handle write response from NoC
    void trySendPendingResponses(); // Send responses to CPU
    
    aximmRWAddr createAxiReadAddr(PacketPtr pkt, uint32_t axi_id);
    aximmRWAddr createAxiWriteAddr(PacketPtr pkt, uint32_t axi_id);
    void createAxiWriteData(PacketPtr pkt, uint32_t axi_id);
    
    /** Statistics */
    uint64_t requestsReceived;
    uint64_t responsesCompleted;
    struct TransactionRecord {
        Addr addr = 0;
        unsigned size = 0;
        unsigned axi_bytes = 0;
        bool is_read = false;
        Tick start_tick = 0;
        Tick end_tick = 0;
    };
    std::vector<TransactionRecord> mmioTransactions;
    std::vector<TransactionRecord> memoryTransactions;

    bool portAssigned{false};

    void emitMetricsFragment() const;
};

} // namespace noc
} // namespace gem5

#endif
