#include "noc/endpoints/fifo/AxisFifoNode.hh"

#include "base/logging.hh"
#include "base/types.hh"
#include "debug/NocTiming.hh"
#include "debug/NocControl.hh"
#include "sim/core.hh"

#include <cstdio>
#include <iomanip>
#include <iostream>

namespace gem5
{
namespace noc
{

AxisFifoNode::AxisFifoNode(const Params &p)
    : NocNode(p),
    //   m_readyPercent(p.ready_percent),
      m_expectedPackets(p.expected_packets),
      m_fifoDepth(p.fifo_depth),
      m_delayTicks(p.delay*1000),
      m_printData(p.print_data),
      m_dataWidthBits(p.data_width),
      m_idWidth(p.id_width),
      m_destWidth(p.dest_width),
      m_currentSlaveState(),
      m_nextSlaveState(),
      m_currentMasterState(m_dataWidthBits, m_idWidth, m_destWidth),
      m_nextMasterState(m_dataWidthBits, m_idWidth, m_destWidth),
      m_slaveIn(),
      m_masterIn(m_dataWidthBits, m_idWidth, m_destWidth),
      m_rng(std::random_device{}()),
      m_dist100(0, 99)
{
    // counting = false;
    // countdown = m_countdown; // ticks since the last tlast until it asserts it's done
    // transfer = false;
    maxPorts = 2;
    numPacketsReceived = 0;
    portAssigned = 0;
    m_currentSlaveState.tready = true;
    m_currentMasterState.data.tvalid = false;
    m_nextSlaveState = m_currentSlaveState;
    m_nextMasterState = m_currentMasterState;
}

void
AxisFifoNode::update(int portID, State* inputNocInterfaceState)
{
    if (portID == 0) {
        auto* axisMaster = dynamic_cast<axisMasterState*>(inputNocInterfaceState);
        if (!axisMaster)
            panic("AxisFifoNode::update expected axisMasterState on port 0");

        // start from current state for next-state computation
        m_nextSlaveState = m_currentSlaveState;

        m_masterIn = *axisMaster;

        // compute next-cycle tready based on fifo occupancy
        m_nextSlaveState.tready = (m_fifoDepth == 0) ? false : (m_fifo.size() < m_fifoDepth);
        // bool willDeq = m_currentMasterState.data.tvalid && m_slaveIn.tready;
        // size_t avail = m_fifo.size();
        // if (willDeq && avail > 0)
        //     --avail;
        // m_nextSlaveState.tready = (m_fifoDepth == 0) ? false : (avail < m_fifoDepth);
        return;
    }

    if (portID == 1) {
        auto* axisSlave = dynamic_cast<axisSlaveState*>(inputNocInterfaceState);
        if (!axisSlave)
            panic("AxisFifoNode::update expected axisSlaveState on port 1");

        // start from current state for next-state computation
        m_nextMasterState = m_currentMasterState;

        m_slaveIn = *axisSlave;

        // master side handshake accept
        if (m_currentMasterState.data.tvalid && m_slaveIn.tready) {
            // bool willDeq = m_currentMasterState.data.tvalid && m_slaveIn.tready;
            // if (willDeq) {
            m_nextMasterState.data.tvalid = false;
        }

        // if idle, drive next ready beat (do not pop here)
        // // if idle, drive next ready beat (skip the one that will dequeue)
        // size_t front_index = willDeq ? 1 : 0;
        if (!m_nextMasterState.data.tvalid &&
            !m_fifo.empty() &&
            m_fifo.front().ready_cycle <= curTick()) {
            m_nextMasterState.data = m_fifo.front().data;
            // m_fifo.size() > front_index &&
            // m_fifo[front_index].ready_cycle <= curTick()) {
            // m_nextMasterState.data = m_fifo[front_index].data;
            m_nextMasterState.data.tvalid = true;
        }
        return;
    }

    panic("AxisFifoNode::update invalid portID %d", portID);
}

State*
AxisFifoNode::getCurrentState(int portID)
{
    if (portID == 0)
        return &m_currentSlaveState;
    if (portID == 1)
        return &m_currentMasterState;
    panic("AxisFifoNode::getCurrentState invalid portID %d", portID);
}

int
AxisFifoNode::assignPort(const std::string &endpointName)
{
    if (endpointName == portEndpointNames[0] && portAssigned < 2) {
        portAssigned += 1;
        return 0;
    }
    if (endpointName == portEndpointNames[1] && portAssigned < 2) {
        portAssigned += 1;
        return 1;
    }
    panic("AxisFifoNode::assignPort invalid endpointName: %s",
          endpointName.c_str());
}

bool
AxisFifoNode::tick(int clockDomain)
{
    if (clockDomain != clockDomains[0])
        return false;
    // DPRINTF(NocControl,
    //     "[AxisFifoNode] tick @ %llu tready=%d tvalid=%d tlast=%d bytes=%u fifo=%zu out_valid=%d\n",
    //     (unsigned long long)curTick(),
    //     (int)m_currentSlaveState.tready,
    //     (int)m_masterIn.data.tvalid,
    //     (int)m_masterIn.data.tlast,
    //     (unsigned)m_masterIn.data.getTotalByteSize(),
    //     m_fifo.size(),
    //     (int)m_masterOut.data.tvalid);

    // update current state
    m_currentMasterState = m_nextMasterState;
    m_currentSlaveState = m_nextSlaveState;

    // slave side handshake accept and push to fifo
    if (m_currentSlaveState.tready && m_masterIn.data.tvalid) {
        if (m_printData) {
            printBeat(m_masterIn.data);
        }
        if (m_masterIn.data.tlast) numPacketsReceived++;
        if (m_fifoDepth == 0 || m_fifo.size() >= m_fifoDepth) {
            panic("AxisFifoNode: FIFO is unexpectedly full");
        }
        axisData beat = m_masterIn.data;
        beat.tvalid = true;
        m_fifo.emplace_back(beat, curTick() + m_delayTicks);
    }

    // master side handshake accept and pop from fifo
    if (m_currentMasterState.data.tvalid && m_slaveIn.tready) {
        if (!m_fifo.empty()) {
            m_fifo.pop_front();
        } else {
            panic("AxisFifoNode: FIFO is unexpectedly empty");
        }
    }

    // // update current state
    // m_currentMasterState = m_nextMasterState;
    // m_currentSlaveState = m_nextSlaveState;

    return true;
}


void
AxisFifoNode::printBeat(const axisData& beat) const
{
    const auto bytes = beat.getTotalByteSize();
    std::cout << "[AxisFifoNode] accept: "
              << "tid=" << beat.tid
              << " tdest=" << beat.tdest
              << " bytes=" << bytes
              << " last=" << (beat.tlast ? 1 : 0)
              << " data[0..15]=";
    // Print first up-to 16 bytes according to tkeep
    uint64_t mask = (m_dataWidthBits >= 64) ? 0xFFFFFFFFFFFFFFFFULL
                                            : ((1ULL << (m_dataWidthBits / 8)) - 1);
    uint64_t effective_tkeep = beat.tkeep & mask;
    size_t limit = std::min<size_t>(beat.tdata.size(), 16);
    for (size_t i = 0; i < limit; ++i) {
        bool byte_valid = (effective_tkeep & (1ULL << i)) != 0;
        if (byte_valid)
            std::cout << " " << std::hex << std::setw(2) << std::setfill('0')
                      << (unsigned)beat.tdata[i] << std::dec;
        else
            std::cout << " --";
    }
    std::cout << "\n";
}

} // namespace noc
} // namespace gem5
