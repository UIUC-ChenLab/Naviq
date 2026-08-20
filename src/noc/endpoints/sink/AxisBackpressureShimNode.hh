#ifndef __AXIS_BACKPRESSURE_SHIM_NODE_HH__
#define __AXIS_BACKPRESSURE_SHIM_NODE_HH__

#include <cstdint>
#include <deque>
#include <fstream>
#include <string>

#include "base/types.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/endpoints/NocNode.hh"
#include "params/AxisBackpressureShimNode.hh"

namespace gem5
{
namespace noc
{

class AxisBackpressureShimNode : public NocNode
{
  public:
    typedef AxisBackpressureShimNodeParams Params;
    explicit AxisBackpressureShimNode(const Params &p);
    ~AxisBackpressureShimNode() override;

    bool tick(int clockDomain) override;
    bool done() override;
    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string &endpointName) override;

  private:
    struct ReadyValidCounters
    {
        uint64_t readyValid = 0;
        uint64_t validOnly = 0;
        uint64_t readyOnly = 0;
        uint64_t idle = 0;
    };

    struct StabilityTracker
    {
        bool stalled = false;
        axisData beat;

        StabilityTracker(uint32_t dataWidth, uint32_t idWidth,
                         uint32_t destWidth)
            : beat(dataWidth, idWidth, destWidth)
        {
        }
    };

    static void recordReadyValid(ReadyValidCounters& counters,
                                 bool valid, bool ready);
    static double validOnlyPct(const ReadyValidCounters& counters);
    static void writeJsonString(std::ofstream& out, const std::string& text);

    bool patternReady() const;
    bool validGatedBackpressure() const;
    bool inputPatternReady() const;
    void advanceInputPattern(bool inputValid);
    bool axisEqual(const axisData& lhs, const axisData& rhs,
                   std::string& signal) const;
    void checkStability(StabilityTracker& tracker, bool valid, bool ready,
                        const axisData& beat, const std::string& side);
    void recordInputBeat(const axisData& beat);
    void recordOutputBeat(const axisData& beat);
    void emitMetricsFragment() const;

    uint32_t m_expectedPackets;
    uint32_t m_dataWidthBits;
    uint32_t m_idWidth;
    uint32_t m_destWidth;
    uint32_t m_fifoDepth;
    bool m_backpressureEnabled;
    std::string m_backpressureConfigName;
    uint32_t m_backpressurePeriod;
    uint32_t m_backpressureAllow;
    std::string m_backpressureScope;
    std::string m_metricsOutputPath;
    mutable bool m_metricsEmitted = false;

    axisSlaveState m_currentSlaveState;
    axisMasterState m_currentMasterState;
    axisMasterState m_masterIn;
    axisSlaveState m_slaveIn;

    std::deque<axisData> m_fifo;
    uint32_t m_fifoMaxOccupancy = 0;
    uint64_t m_activeCycles = 0;
    uint32_t m_validGatedPhase = 0;
    uint32_t m_outputPacketsSeen = 0;

    ReadyValidCounters m_dmaToShimCounters;
    ReadyValidCounters m_shimToCheckerCounters;
    uint64_t m_dmaToShimAcceptedBeats = 0;
    uint64_t m_shimToCheckerAcceptedBeats = 0;

    uint64_t m_inputBytes = 0;
    uint64_t m_outputBytes = 0;
    uint64_t m_inputPackets = 0;
    uint64_t m_outputPackets = 0;
    uint64_t m_inputTlastCount = 0;
    uint64_t m_outputTlastCount = 0;
    Tick m_inputFirstTick = 0;
    Tick m_inputLastTick = 0;
    Tick m_outputFirstTick = 0;
    Tick m_outputLastTick = 0;
    bool m_sawInput = false;
    bool m_sawOutput = false;

    bool m_axisStabilityViolation = false;
    Tick m_axisStabilityViolationTick = 0;
    std::string m_axisStabilityViolationSignal;
    std::string m_axisStabilityViolationSide;
    StabilityTracker m_inputStability;
    StabilityTracker m_outputStability;

    bool m_ingressPortAssigned = false;
    bool m_egressPortAssigned = false;
};

} // namespace noc
} // namespace gem5

#endif
