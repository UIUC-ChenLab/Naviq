#ifndef __NOC_EXTERNAL_DDR_DMA_DDR_PACKET_DMA_NODE_HH__
#define __NOC_EXTERNAL_DDR_DMA_DDR_PACKET_DMA_NODE_HH__

#include "noc/lib/axi/AXITypes.hh"
#include "noc/endpoints/NocNode.hh"
#include "params/DdrPacketDmaNode.hh"

#include <array>
#include <cstdint>
#include <deque>
#include <random>
#include <string>
#include <vector>

namespace gem5
{
namespace noc
{

class DdrPacketDmaNode : public NocNode
{
  public:
    typedef DdrPacketDmaNodeParams Params;
    explicit DdrPacketDmaNode(const Params& p);

    bool tick(int clockDomain) override;
    bool done() override;
    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string& endpointName) override;

  private:
    static constexpr uint32_t DescriptorBytes = 32;
    static constexpr uint32_t BeatBytes = 64;
    static constexpr uint32_t DescriptorStride = BeatBytes;
    static constexpr uint16_t DescFlagValid = 1u << 0;
    static constexpr uint16_t DescFlagInterrupt = 1u << 1;
    static constexpr uint16_t DescFlagEndOfChain = 1u << 2;
    static constexpr uint16_t DescFlagDrop = 1u << 3;

    static constexpr uint32_t ControlStart = 1u << 0;
    static constexpr uint32_t ControlClearStatus = 1u << 1;
    static constexpr uint32_t StatusBusy = 1u << 0;
    static constexpr uint32_t StatusDone = 1u << 1;
    static constexpr uint32_t StatusError = 1u << 2;
    static constexpr uint32_t StatusEocSeen = 1u << 3;

    struct Descriptor
    {
        uint64_t packetAddr = 0;
        uint32_t packetLen = 0;
        uint16_t tdest = 0;
        uint16_t tid = 0;
        uint16_t tuser = 0;
        uint16_t flags = 0;
    };

    enum class AxiKind
    {
        None,
        Write,
        ReadDescriptor,
        ReadPacket,
    };

    struct AxiOp
    {
        AxiKind kind = AxiKind::None;
        uint64_t addr = 0;
        std::vector<uint8_t> bytes;
        uint32_t validBytes = 0;
        uint32_t bytesTransferred = 0;
        uint32_t packetIndex = 0;
        uint32_t descriptorCount = 0;
        Tick issueTick = 0;
    };

    struct PacketState
    {
        std::vector<uint8_t> descReadBuffer;
        std::vector<uint8_t> packetReadBuffer;
        Descriptor desc;
        bool descriptorIssued = false;
        bool descriptorDone = false;
        uint32_t packetReadIssuedBytes = 0;
    };

    aximmMasterState m_aximmOut;
    aximmSlaveState m_aximmIn;
    axisMasterState m_axisOut;
    axisSlaveState m_axisIn;
    aximmSlaveState m_ctrlOut;
    aximmMasterState m_ctrlIn;

    std::vector<uint8_t> m_portAssigned;
    std::vector<Descriptor> m_expectedDescriptors;
    std::vector<std::vector<uint8_t>> m_expectedPackets;
    std::deque<AxiOp> m_preloadWrites;
    std::vector<PacketState> m_packetStates;
    std::vector<axisData> m_axisBeats;
    FunctionalMemoryEndpoint* m_preloadMemory = nullptr;

    AxiOp m_activeOp;
    AxiOp m_pendingReadOp;
    std::deque<AxiOp> m_inflightReads;
    bool m_hasActiveOp = false;
    bool m_hasPendingReadOp = false;
    bool m_awAccepted = false;
    bool m_wAccepted = false;
    uint32_t m_packetIndex = 0;
    uint32_t m_nextDescriptorIndex = 0;
    size_t m_axisBeatIndex = 0;
    uint64_t m_beatsEmitted = 0;
    uint64_t m_bytesEmitted = 0;
    uint64_t m_descriptorsRead = 0;
    uint64_t m_packetsCompleted = 0;
    uint64_t m_descriptorErrors = 0;
    uint64_t m_totalDdrBytesRead = 0;
    uint64_t m_readsIssued = 0;
    uint64_t m_maxInflightReadsObserved = 0;
    uint64_t m_descriptorReadsCompleted = 0;
    uint64_t m_packetReadsCompleted = 0;
    uint64_t m_descriptorReadTransactionsIssued = 0;
    uint64_t m_packetReadTransactionsIssued = 0;
    uint64_t m_descriptorReadTransactionsCompleted = 0;
    uint64_t m_packetReadTransactionsCompleted = 0;
    uint64_t m_descriptorReadRequestBytesIssued = 0;
    uint64_t m_packetReadRequestBytesIssued = 0;
    uint64_t m_arValidCycles = 0;
    uint64_t m_arReadyValidCycles = 0;
    uint64_t m_arValidNotReadyCycles = 0;
    uint64_t m_rValidCycles = 0;
    uint64_t m_rReadyValidCycles = 0;
    uint64_t m_rValidNotReadyCycles = 0;
    uint64_t m_rIdleInflightCycles = 0;
    uint64_t m_axisValidCycles = 0;
    uint64_t m_axisReadyValidCycles = 0;
    uint64_t m_axisValidNotReadyCycles = 0;
    uint64_t m_inflightSampleCycles = 0;
    uint64_t m_inflightReadOccupancySum = 0;
    uint64_t m_pendingReadValidCycles = 0;
    uint64_t m_readIssueStallInflightFullCycles = 0;
    uint64_t m_axisWaitPacketCycles = 0;
    Tick m_firstAxisTick = 0;
    Tick m_lastAxisTick = 0;
    Tick m_dmaLaunchTick = 0;
    Tick m_firstDdrReadRequestTick = 0;
    Tick m_lastDdrReadCompletionTick = 0;
    Tick m_dmaDoneTick = 0;
    bool m_sawAxisBeat = false;
    bool m_reportedSummary = false;
    bool m_sawDmaLaunch = false;
    bool m_sawFirstDdrReadRequest = false;
    bool m_eocSeen = false;
    uint32_t m_startDelayRemaining = 0;
    uint32_t m_postPreloadReadDelayRemaining = 0;
    uint32_t m_packetGapRemaining = 0;
    bool m_postPreloadReadDelayArmed = true;
    bool m_started = false;
    bool m_doneStatus = false;
    bool m_errorStatus = false;
    bool m_functionalPacketsPreloaded = false;
    uint32_t m_errorCode = 0;

    aximmRWAddr m_ctrlAw;
    aximmRWData m_ctrlW;
    bool m_ctrlHaveAw = false;
    bool m_ctrlHaveW = false;

    uint64_t m_descriptorBase;
    const uint64_t m_packetBase;
    const uint64_t m_controlBase;
    const uint32_t m_packetStride;
    uint32_t m_packetCount;
    uint32_t m_maxReadBurstBeats;
    uint32_t m_maxOutstandingReads;
    const uint32_t m_descriptorPrefetchDepth;
    const uint32_t m_packetPrefetchDepth;
    const uint32_t m_startDelayCycles;
    const uint32_t m_postPreloadReadDelayCycles;
    const uint32_t m_packetGapCycles;
    const uint16_t m_descriptorFlags;
    const uint32_t m_dataWidth;
    const uint32_t m_tidWidth;
    const uint32_t m_tdestWidth;
    const uint32_t m_tuserWidth;
    const uint32_t m_axiId;
    const uint32_t m_tid;
    const uint32_t m_tdest;
    const uint32_t m_tuser;
    const bool m_preloadDdr;
    const bool m_preloadDescriptors;
    const bool m_preloadPackets;
    const bool m_functionalPreloadPackets;
    const bool m_waitForControlStart;
    const bool m_printSummary;
    const bool m_stopOnEoc;
    const std::string m_metricsOutputPath;
    std::vector<uint64_t> m_readLatencyTicks;

    void buildExpectedPackets(const Params& p);
    void buildPreloadWrites();
    void performFunctionalPacketPreload();
    void functionalPreloadWrite(uint64_t addr, const std::vector<uint8_t>& bytes);
    std::vector<uint8_t> serializeDescriptor(const Descriptor& desc) const;
    Descriptor parseDescriptor(const std::vector<uint8_t>& bytes) const;
    void enqueueWrite(uint64_t addr, const std::vector<uint8_t>& bytes);

    void consumeHandshakes();
    void driveNextOutputs();
    void consumeControlPort();
    void driveControlPort();
    void writeControlReg(uint64_t addr, uint32_t data, uint64_t wstrb);
    uint32_t readControlReg(uint64_t addr) const;
    uint64_t controlOffset(uint64_t addr) const;
    void clearStatus();
    void startDma();
    bool dmaTransferFinished() const;
    bool readCreditAvailable() const;
    bool hasSchedulableReadCandidate() const;
    bool buildNextReadOp(AxiOp& op);
    bool startNextAxiOp();
    void driveWriteOp(const AxiOp& op);
    void driveReadOp(const AxiOp& op);
    void completeReadOp(const AxiOp& op);
    void clearAxiRequestOutputs();
    void preparePacketAxisBeats();
    bool packetComplete() const;
    void printSummary();
    void emitMetricsFragment() const;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_EXTERNAL_DDR_DMA_DDR_PACKET_DMA_NODE_HH__
