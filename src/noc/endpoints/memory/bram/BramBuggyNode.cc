#include "noc/endpoints/memory/bram/BramBuggyNode.hh"

#include "base/logging.hh"
#include "sim/core.hh"

namespace gem5
{
namespace noc
{

BramBuggyNode::BramBuggyNode(const Params& p)
    : NocNode(p),
      m_bram(p.bram),
      m_awPct(p.awready_percentage),
      m_wPct(p.wready_percentage),
      m_arPct(p.arready_percentage),
      m_mutateRespAxiIdPct(p.mutate_response_axi_id_percentage),
      m_mutateAxiIdVal(p.mutate_axi_id_val),
      m_rng(std::random_device{}()),
      m_dist100(0, 99)
{
    if (!m_bram) {
        panic("BramBuggyNode: bram parameter must point to a BramEndpoint instance");
    }
    maxPorts = 1;

    // Percentage 0 means never expose ready on that channel; avoid a first-cycle
    // window where in-class defaults were true before tick().
    if (m_arPct == 0) {
        m_exposeAr = false;
        m_nextExposeAr = false;
    }
    if (m_awPct == 0) {
        m_exposeAw = false;
        m_nextExposeAw = false;
    }
    if (m_wPct == 0) {
        m_exposeW = false;
        m_nextExposeW = false;
    }

    panic_if(m_mutateRespAxiIdPct > 100,
        "BramBuggyNode: mutate_response_axi_id_percentage must be in [0, 100]");
}

void
BramBuggyNode::functionalWrite(Addr addr, const uint8_t* data, size_t size)
{
    m_bram->functionalWrite(addr, data, size);
}

void
BramBuggyNode::functionalRead(Addr addr, uint8_t* data, size_t size)
{
    m_bram->functionalRead(addr, data, size);
}

bool
BramBuggyNode::addressInRange(Addr addr) const
{
    return m_bram->addressInRange(addr);
}

bool
BramBuggyNode::done()
{
    return m_bram->done();
}

bool
BramBuggyNode::shouldMutateResponseId()
{
    return m_dist100(m_rng) < static_cast<int>(m_mutateRespAxiIdPct);
}

void
BramBuggyNode::update(int portID, State* inputNocInterfaceState)
{
    if (portID != 0) {
        panic("BramBuggyNode::update invalid portID %d", portID);
    }
    auto* masterIn = dynamic_cast<aximmMasterState*>(inputNocInterfaceState);
    if (!masterIn) {
        panic("BramBuggyNode::update expected aximmMasterState");
    }

    m_mutedMaster = *masterIn;
    const bool rAccepted = m_exposedSlave.r.valid && masterIn->rReady;
    const bool bAccepted = m_exposedSlave.b.valid && masterIn->bReady;

    if (!m_exposeAr) {
        m_mutedMaster.ar.valid = false;
    }
    if (!m_exposeAw) {
        m_mutedMaster.aw.valid = false;
    }
    if (!m_exposeW) {
        m_mutedMaster.w.valid = false;
    }

    m_bram->update(0, &m_mutedMaster);

    if (rAccepted) {
        m_rMutationDecisionValid = false;
        m_rMutationActive = false;
    }
    if (bAccepted) {
        m_bMutationDecisionValid = false;
        m_bMutationActive = false;
    }

    m_nextExposeAr = m_dist100(m_rng) < static_cast<int>(m_arPct);
    m_nextExposeAw = m_dist100(m_rng) < static_cast<int>(m_awPct);
    m_nextExposeW = m_dist100(m_rng) < static_cast<int>(m_wPct);
}

State*
BramBuggyNode::getCurrentState(int portID)
{
    if (portID != 0) {
        panic("BramBuggyNode::getCurrentState invalid portID %d", portID);
    }

    auto* inner = dynamic_cast<aximmSlaveState*>(m_bram->getCurrentState(0));
    if (!inner) {
        panic("BramBuggyNode: inner BramEndpoint returned non aximmSlaveState");
    }

    m_exposedSlave = *inner;
    m_exposedSlave.arReady = inner->arReady && m_exposeAr;
    m_exposedSlave.awReady = inner->awReady && m_exposeAw;
    m_exposedSlave.wReady = inner->wReady && m_exposeW;

    if (m_exposedSlave.r.valid) {
        if (!m_rMutationDecisionValid) {
            m_rMutationActive = shouldMutateResponseId();
            m_rMutationDecisionValid = true;
        }
        if (m_rMutationActive) {
            m_exposedSlave.r.id = m_mutateAxiIdVal;
        }
    } else {
        m_rMutationDecisionValid = false;
        m_rMutationActive = false;
    }

    if (m_exposedSlave.b.valid) {
        if (!m_bMutationDecisionValid) {
            m_bMutationActive = shouldMutateResponseId();
            m_bMutationDecisionValid = true;
        }
        if (m_bMutationActive) {
            m_exposedSlave.b.id = m_mutateAxiIdVal;
        }
    } else {
        m_bMutationDecisionValid = false;
        m_bMutationActive = false;
    }

    return &m_exposedSlave;
}

int
BramBuggyNode::assignPort(const std::string& endpointName)
{
    if (endpointName == portEndpointNames[0] && !m_portAssigned) {
        m_bram->assignPort(endpointName);
        m_portAssigned = true;
        return 0;
    }
    panic("BramBuggyNode::assignPort invalid endpointName: %s",
          endpointName.c_str());
}

bool
BramBuggyNode::tick(int clockDomain)
{
    if (clockDomain != clockDomains[0]) {
        return false;
    }

    m_bram->tick(clockDomain);

    m_exposeAr = m_nextExposeAr;
    m_exposeAw = m_nextExposeAw;
    m_exposeW = m_nextExposeW;

    return true;
}

} // namespace noc
} // namespace gem5
