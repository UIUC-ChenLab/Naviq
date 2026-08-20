#include "noc/endpoints/misc/SynchronizerNode.hh"

#include "sim/core.hh"

namespace gem5
{
namespace noc
{

SynchronizerNode::SynchronizerNode(const Params& p)
    : NocNode(p),
      m_axisSink(p.axis_sink),
      m_bram(p.bram)
{
    if (!m_axisSink) {
        panic("SynchronizerNode: axis_sink must point to an AxisSinkNode");
    }
    if (!m_bram) {
        panic("SynchronizerNode: bram must point to a BramBuggyNode");
    }
    if (clockDomains.size() != 2) {
        panic("SynchronizerNode: expected two clock domains (one per port), got %zu",
              clockDomains.size());
    }
    if (portEndpointNames.size() != 2) {
        panic("SynchronizerNode: expected two port endpoint names, got %zu",
              portEndpointNames.size());
    }
    maxPorts = 2;
}

void
SynchronizerNode::functionalWrite(Addr addr, const uint8_t* data, size_t size)
{
    m_bram->functionalWrite(addr, data, size);
}

void
SynchronizerNode::functionalRead(Addr addr, uint8_t* data, size_t size)
{
    m_bram->functionalRead(addr, data, size);
}

bool
SynchronizerNode::addressInRange(Addr addr) const
{
    return m_bram->addressInRange(addr);
}

bool
SynchronizerNode::done()
{
    return m_axisSink->done() && m_bram->done();
}

void
SynchronizerNode::update(int portID, State* inputNocInterfaceState)
{
    if (portID == 0) {
        m_axisSink->update(0, inputNocInterfaceState);
    } else if (portID == 1) {
        m_bram->update(0, inputNocInterfaceState);
    } else {
        panic("SynchronizerNode::update invalid portID %d", portID);
    }
}

State*
SynchronizerNode::getCurrentState(int portID)
{
    if (portID == 0) {
        return m_axisSink->getCurrentState(0);
    }
    if (portID == 1) {
        return m_bram->getCurrentState(0);
    }
    panic("SynchronizerNode::getCurrentState invalid portID %d", portID);
}

int
SynchronizerNode::assignPort(const std::string& endpointName)
{
    if (endpointName == portEndpointNames[0] && !m_axisPortAssigned) {
        m_axisSink->assignPort(endpointName);
        m_axisPortAssigned = true;
        return 0;
    }
    if (endpointName == portEndpointNames[1] && !m_bramPortAssigned) {
        m_bram->assignPort(endpointName);
        m_bramPortAssigned = true;
        return 1;
    }
    panic("SynchronizerNode::assignPort invalid endpointName: %s",
          endpointName.c_str());
}

bool
SynchronizerNode::tick(int clockDomain)
{
    const bool same_cd = (clockDomains[0] == clockDomains[1]);

    // Same MHz on both ports: Control runs update(0), tick, update(1), tick in one
    // simulator cycle. Advancing both inners on the first tick() runs the BRAM
    // model before update(1), corrupting AXIMM state vs. the NI.
    if (same_cd && clockDomain == clockDomains[0]) {
        if (m_sameCdBundleTick != curTick()) {
            m_sameCdBundleTick = curTick();
            m_sameCdPhase = 0;
        }
        if (m_sameCdPhase == 0) {
            if (m_lastAxisInnerTick != curTick()) {
                m_axisSink->tick(clockDomain);
                m_lastAxisInnerTick = curTick();
            }
            m_sameCdPhase = 1;
            return true;
        }
        if (m_sameCdPhase == 1) {
            if (m_lastBramInnerTick != curTick()) {
                m_bram->tick(clockDomain);
                m_lastBramInnerTick = curTick();
            }
            m_sameCdPhase = 2;
            return true;
        }
        return false;
    }

    bool progressed = false;
    if (clockDomain == clockDomains[0]) {
        if (m_lastAxisInnerTick != curTick()) {
            m_axisSink->tick(clockDomain);
            m_lastAxisInnerTick = curTick();
            progressed = true;
        }
    }
    if (clockDomain == clockDomains[1]) {
        if (m_lastBramInnerTick != curTick()) {
            m_bram->tick(clockDomain);
            m_lastBramInnerTick = curTick();
            progressed = true;
        }
    }
    return progressed;
}

} // namespace noc
} // namespace gem5
