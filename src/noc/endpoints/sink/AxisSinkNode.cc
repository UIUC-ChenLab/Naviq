#include "noc/endpoints/sink/AxisSinkNode.hh"

#include "base/logging.hh"
#include "base/types.hh"
#include "debug/NocTiming.hh"
#include "debug/NocControl.hh"
#include "sim/core.hh"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <iomanip>
#include <iostream>

namespace gem5
{
namespace noc
{

AxisSinkNode::AxisSinkNode(const Params &p)
    : NocNode(p),
      m_readyPercent(p.ready_percent),
      m_readyPercentStartAfterPackets(
          static_cast<uint32_t>(std::floor(
              static_cast<double>(p.expected_packets) *
              std::clamp(p.ready_percent_start_fraction, 0.0, 1.0)))),
      m_expectedPackets(p.expected_packets),
      m_printData(p.print_data),
      m_dataWidthBits(p.data_width),
      m_idWidth(p.id_width),
      m_destWidth(p.dest_width),
      m_currentState(),
      m_nextState(),
      m_masterIn(m_dataWidthBits, m_idWidth, m_destWidth),
      m_rng(std::random_device{}()),
      m_dist100(0, 99)
{
    // counting = false;
    // countdown = m_countdown; // ticks since the last tlast until it asserts it's done
    // transfer = false;
    maxPorts = 1;
    numPacketsReceived = 0;
    m_currentState.tready = true;
    m_nextState = m_currentState;
    portAssigned = false;
}

void
AxisSinkNode::update(int portID, State* inputNocInterfaceState)
{
    if (portID != 0)
        panic("AxisSinkNode::update invalid portID %d", portID);
    auto* axisMaster = dynamic_cast<axisMasterState*>(inputNocInterfaceState);
    if (!axisMaster)
        panic("AxisSinkNode::update expected axisMasterState");
    m_masterIn = *axisMaster;

    // Until enough TLASTs are received, keep sink permissive; then apply %
    if (numPacketsReceived <
        static_cast<int>(m_readyPercentStartAfterPackets)) {
        m_nextState.tready = true;
    } else {
        int roll = m_dist100(m_rng);
        m_nextState.tready = (roll < static_cast<int>(m_readyPercent));
    }
}

State*
AxisSinkNode::getCurrentState(int portID)
{
    if (portID != 0)
        panic("AxisSinkNode::getCurrentState invalid portID %d", portID);
    return &m_currentState;
}

int
AxisSinkNode::assignPort(const std::string &endpointName)
{
    if (endpointName == portEndpointNames[0] && !portAssigned) {
        portAssigned = true;
        return 0;
    }
    panic("AxisSinkNode::assignPort invalid endpointName: %s",
          endpointName.c_str());
}

bool
AxisSinkNode::tick(int clockDomain)
{
    if (clockDomain != clockDomains[0])
        return false;
    
    DPRINTF(NocControl, "[AxisSinkNode] tick @ %llu tready=%d tvalid=%d tlast=%d bytes=%u\n",
        (unsigned long long)curTick(),
        (int)m_currentState.tready,
        (int)m_masterIn.data.tvalid,
        (int)m_masterIn.data.tlast,
        (unsigned)m_masterIn.data.getTotalByteSize());

    // handshake accept
    if (m_currentState.tready && m_masterIn.data.tvalid) {
        if (m_printData) {
            printBeat(m_masterIn.data);
        }
        if (m_masterIn.data.tlast) numPacketsReceived++;
        // transfer = true; // flag active transfer on any accepted beat

        // countdown = m_countdown;
        // if (m_masterIn.data.tlast) {
        //     counting = true;
        //     countdown = m_countdown;
        // } else {
        //     counting = false; // no countdown until TLAST
        // }
    }
    // if (countdown > 0) countdown--;
    // if (counting) {
    //     if (--countdown <= 0) {
    //         transfer = false;
    //         counting = false;
    //         countdown = 0; // clamp
    //     }
    // }

    m_currentState = m_nextState;
    return true;
}


void
AxisSinkNode::printBeat(const axisData& beat) const
{
    const auto bytes = beat.getTotalByteSize();
    std::cout << "[AxisSinkNode] accept: "
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


