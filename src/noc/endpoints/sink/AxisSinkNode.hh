#ifndef __AXIS_SINK_NODE_HH
#define __AXIS_SINK_NODE_HH

#include "noc/endpoints/NocNode.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "params/AxisSinkNode.hh"

#include <deque>
#include <random>

namespace gem5
{
namespace noc
{

class AxisSinkNode : public NocNode
{
  public:
    typedef AxisSinkNodeParams Params;
    AxisSinkNode(const Params &p);

    // one-cycle simulation advancement
    bool tick(int clockDomain) override;
    bool done() { return numPacketsReceived >= m_expectedPackets; }

    // provide latest master state (TVALID and payload)
    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string &endpointName) override;

  private:
    // configuration
    uint8_t m_readyPercent;
    /** TLASTs received before stochastic ready_percent applies (see ctor). */
    uint32_t m_readyPercentStartAfterPackets;
    uint32_t m_expectedPackets;
    bool m_printData;
    uint32_t m_dataWidthBits;
    uint32_t m_idWidth;
    uint32_t m_destWidth;

    // state
    axisSlaveState m_currentState;
    axisSlaveState m_nextState;
    axisMasterState m_masterIn;
    // bool transfer;
    // bool counting;
    // int countdown;
    int numPacketsReceived;
    bool portAssigned;
    
    // rng
    std::mt19937 m_rng;
    std::uniform_int_distribution<int> m_dist100;

    void printBeat(const axisData& beat) const;
};

} // namespace noc
} // namespace gem5

#endif


