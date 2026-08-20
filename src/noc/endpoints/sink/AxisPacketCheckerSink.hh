#ifndef __NOC_AXIS_PACKET_CHECKER_SINK_HH__
#define __NOC_AXIS_PACKET_CHECKER_SINK_HH__

#include "noc/lib/axi/AXITypes.hh"
#include "noc/endpoints/NocNode.hh"
#include "params/AxisPacketCheckerSink.hh"

#include <random>
#include <string>
#include <vector>

namespace gem5
{
namespace noc
{

class AxisPacketCheckerSink : public NocNode
{
  public:
    enum class CheckMode
    {
        Exact,
        Ipv4,
        NatOutbound,
    };

    typedef AxisPacketCheckerSinkParams Params;
    AxisPacketCheckerSink(const Params& p);
    ~AxisPacketCheckerSink();

    bool tick(int clockDomain) override;
    bool done() override;
    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string &endpointName) override;

  private:
    axisSlaveState m_currentState;
    axisSlaveState m_nextState;
    axisMasterState m_masterIn;
    std::vector<axisData> m_expectedStream;
    std::vector<uint8_t> m_packetBytes;
    std::mt19937 m_rng;
    std::uniform_int_distribution<int> m_dist100;
    CheckMode m_checkMode;
    uint32_t m_dataWidthBits;
    uint32_t m_expectedPackets;
    uint32_t m_packetsReceived = 0;
    uint64_t m_beatsReceived = 0;
    uint64_t m_bytesReceived = 0;
    Tick m_firstBeatTick = 0;
    Tick m_lastBeatTick = 0;
    bool m_sawBeat = false;
    size_t m_expectedBeat = 0;
    uint8_t m_readyPercent;
    bool m_validateIpv4Checksum;
    bool m_validateL4Checksum;
    bool m_printSummary;
    std::string m_metricsOutputPath;
    uint32_t m_validationSkipBytes;
    bool m_checkTdest;
    uint32_t m_expectedTdest;
    bool m_reportedSummary = false;
    uint32_t m_natPublicIp;
    uint16_t m_natBasePort;
    uint16_t m_natPortCount;
    bool m_portAssigned = false;

    void acceptBeat(const axisData& beat);
    void checkExactBeat(const axisData& beat);
    void checkPacket();
    void checkNatOutboundPacket();
    void printSummary();
    void emitMetricsFragment() const;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_AXIS_PACKET_CHECKER_SINK_HH__
