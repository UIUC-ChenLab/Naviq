#ifndef __NOC_TEST_BRAM_BUGGY_NODE_HH__
#define __NOC_TEST_BRAM_BUGGY_NODE_HH__

#include "noc/endpoints/memory/bram/BramEndpoint.hh"
#include "noc/endpoints/NocNode.hh"
#include "params/BramBuggyNode.hh"

#include "noc/lib/axi/AXITypes.hh"

#include <cstdint>
#include <random>

namespace gem5
{
namespace noc
{

/**
 * Wraps a BramEndpoint without modifying it: exposes masked AW/W/AR readies to the
 * NoC (AxisSinkNode-style percentages) and feeds the inner BRAM with muted address/
 * write valids whenever a channel is artificially not-ready, so the inner model
 * does not accept handshakes that the master does not observe.
 *
 * Expose/mute timing follows Control's order (getCurrentState before update): flags
 * committed in tick() apply starting the following cycle.
 */
class BramBuggyNode : public NocNode, public FunctionalMemoryEndpoint
{
  public:
    typedef BramBuggyNodeParams Params;
    BramBuggyNode(const Params& p);

    bool tick(int clockDomain) override;
    bool done() override;
    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string& endpointName) override;

    void functionalWrite(Addr addr, const uint8_t* data, size_t size) override;
    void functionalRead(Addr addr, uint8_t* data, size_t size) override;
    bool addressInRange(Addr addr) const override;

  private:
    bool shouldMutateResponseId();

    BramEndpoint* m_bram;
    uint8_t m_awPct;
    uint8_t m_wPct;
    uint8_t m_arPct;
    uint8_t m_mutateRespAxiIdPct;
    uint32_t m_mutateAxiIdVal;

    std::mt19937 m_rng;
    std::uniform_int_distribution<int> m_dist100;

    /** Master view toward BRAM after muting stalled channels. */
    aximmMasterState m_mutedMaster{};
    /** Slave view toward NoC after masking readies. */
    aximmSlaveState m_exposedSlave{};

    /** Committed this tick(); used by getCurrentState() / mute in update(). */
    bool m_exposeAr = true;
    bool m_exposeAw = true;
    bool m_exposeW = true;
    /** Set in update(); committed in tick(). */
    bool m_nextExposeAr = true;
    bool m_nextExposeAw = true;
    bool m_nextExposeW = true;

    bool m_rMutationDecisionValid = false;
    bool m_rMutationActive = false;
    bool m_bMutationDecisionValid = false;
    bool m_bMutationActive = false;

    bool m_portAssigned = false;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_TEST_BRAM_BUGGY_NODE_HH__
