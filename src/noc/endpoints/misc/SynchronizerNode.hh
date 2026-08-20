#ifndef __NOC_TEST_SYNCHRONIZER_NODE_HH__
#define __NOC_TEST_SYNCHRONIZER_NODE_HH__

#include "base/types.hh"
#include "noc/endpoints/sink/AxisSinkNode.hh"
#include "noc/endpoints/memory/bram/BramBuggyNode.hh"
#include "noc/endpoints/NocNode.hh"
#include "params/SynchronizerNode.hh"

namespace gem5
{
namespace noc
{

/**
 * Two-port NocNode: port 0 delegates to an AxisSinkNode, port 1 to a BramBuggyNode.
 * Inner objects are child SimObjects; this wrapper forwards update/getCurrentState/
 * assignPort and coordinates tick() when Control invokes tick once per connection.
 * If both ports share the same clock MHz, Control calls tick twice per curTick
 * (port 0 then port 1); we must tick axis then bram on those successive calls so
 * bram is not advanced before update(1) runs in the same cycle.
 */
class SynchronizerNode : public NocNode, public FunctionalMemoryEndpoint
{
  public:
    typedef SynchronizerNodeParams Params;
    SynchronizerNode(const Params& p);

    bool tick(int clockDomain) override;
    bool done() override;
    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string& endpointName) override;

    void functionalWrite(Addr addr, const uint8_t* data, size_t size) override;
    void functionalRead(Addr addr, uint8_t* data, size_t size) override;
    bool addressInRange(Addr addr) const override;

  private:
    AxisSinkNode* m_axisSink;
    BramBuggyNode* m_bram;

    bool m_axisPortAssigned = false;
    bool m_bramPortAssigned = false;

    Tick m_lastAxisInnerTick = MaxTick;
    Tick m_lastBramInnerTick = MaxTick;

    /** When clockDomains[0]==clockDomains[1], order inner ticks across the two
     *  Control tick() calls in the same curTick(). */
    Tick m_sameCdBundleTick = MaxTick;
    uint8_t m_sameCdPhase = 0;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_TEST_SYNCHRONIZER_NODE_HH__
