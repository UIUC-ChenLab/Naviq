#ifndef __AXIS_FIFO_NODE_HH
#define __AXIS_FIFO_NODE_HH

#include "noc/endpoints/NocNode.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "params/AxisFifoNode.hh"

#include <cstdint>
#include <deque>
#include <random>

namespace gem5
{
namespace noc
{

class AxisFifoNode : public NocNode
{
  public:
    typedef AxisFifoNodeParams Params;
    AxisFifoNode(const Params &p);

    // one-cycle simulation advancement
    bool tick(int clockDomain) override;
    bool done() {
        return numPacketsReceived >= m_expectedPackets &&
            m_fifo.empty() &&
            !m_currentMasterState.data.tvalid;
    }

    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string &endpointName) override;

  private:
    struct FifoEntry {
        axisData data;
        uint64_t ready_cycle = 0;
        FifoEntry(const axisData& d, uint64_t ready) : data(d), ready_cycle(ready) {}
    };

    // configuration
    // uint8_t m_readyPercent;
    uint32_t m_expectedPackets;
    uint32_t m_fifoDepth;
    uint32_t m_delayTicks;
    bool m_printData;
    uint32_t m_dataWidthBits;
    uint32_t m_idWidth;
    uint32_t m_destWidth;

    // state
    axisSlaveState m_currentSlaveState;
    axisSlaveState m_nextSlaveState;
    axisMasterState m_currentMasterState;
    axisMasterState m_nextMasterState;

    axisSlaveState m_slaveIn;
    axisMasterState m_masterIn;
    
    // internals
    // bool transfer;
    // bool counting;
    // int countdown;
    int numPacketsReceived;
    std::deque<FifoEntry> m_fifo;
    int portAssigned;
    
    // rng
    std::mt19937 m_rng;
    std::uniform_int_distribution<int> m_dist100;

    void printBeat(const axisData& beat) const;
};

} // namespace noc
} // namespace gem5

#endif