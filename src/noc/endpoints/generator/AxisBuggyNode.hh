#ifndef __NOC_TEST_AXIS_BUGGY_NODE_HH__
#define __NOC_TEST_AXIS_BUGGY_NODE_HH__

#include "noc/lib/axi/AXITypes.hh"
#include "noc/endpoints/NocNode.hh"
#include "params/AxisBuggyGenerator.hh"

#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxisTrafficGenerator/strategies/AxisRandomStrategy.h"

#include <cstdint>
#include <functional>
#include <memory>
#include <random>
#include <string>
#include <vector>

class AxisInterface;
class AxisTrafficGenerator;

namespace gem5 {
namespace noc {

/**
 * SimObject wrapper around the underlying external `AxisTrafficGenerator`
 * configured with `AxisRandomStrategy`.
 *
 * Key property: the *internal* traffic generator object is not a SimObject and
 * is not tracked by gem5; this node simply exposes the same NoC-facing AXIS
 * state interface (`axisSlaveState` in, `axisMasterState` out) as
 * `AxisRandomTrafficGenerator`.
 *
 * A hook point is provided to allow bug injection by mutating outgoing beats
 * before they are observed by the rest of the NoC.
 */
class AxisBuggyGenerator : public NocNode
{
  public:
    typedef AxisBuggyGeneratorParams Params;
    AxisBuggyGenerator(const Params& p);
    ~AxisBuggyGenerator() override;

    bool tick(int clockDomain) override;
    bool done() override;

    void update(int portID, State* inputNocInterfaceState) override;
    State* getCurrentState(int portID) override;
    int assignPort(const std::string& endpointName) override;

    using OutMutator = std::function<void(axisMasterState&)>;
    void setOutMutator(OutMutator mutator) { m_outMutator = std::move(mutator); }

  protected:
    /** Bug-injection hook: called on the outbound AXIS master state each cycle. */
    virtual void mutateOutgoing(axisMasterState& state);

  private:
    struct MasterPort;

    static DistributionType parseDistribution(const std::string& s);
    void copyAxisValuesFromChannel(MasterPort& master, axisMasterState& state);
    void refreshCurrentState(MasterPort& master);
    void applyValidPercentToOutgoing(MasterPort& master, axisMasterState& state);
    void mutateOutgoing(MasterPort& master, axisMasterState& state);
    void mutatePayload(MasterPort& master, axisMasterState& state);

    std::vector<std::unique_ptr<MasterPort>> m_masters;
    int m_lastUpdatedPort = -1;
    OutMutator m_outMutator{};
};

} // namespace noc
} // namespace gem5

#endif // __NOC_TEST_AXIS_BUGGY_NODE_HH__
