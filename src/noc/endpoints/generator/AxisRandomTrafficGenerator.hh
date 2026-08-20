#ifndef __NOC_AXIS_RANDOM_TRAFFIC_GENERATOR_HH__
#define __NOC_AXIS_RANDOM_TRAFFIC_GENERATOR_HH__

#include "noc/endpoints/generator/AXISTrafficGenerator.hh"
#include "params/AxisRandomTrafficGenerator.hh"

namespace gem5 {
namespace noc {

class AxisRandomTrafficGenerator : public AXISTrafficGenerator
{
  public:
    typedef AxisRandomTrafficGeneratorParams Params;
    AxisRandomTrafficGenerator(const Params& p);
    ~AxisRandomTrafficGenerator() override = default;

    bool tick(int clockDomain) override;

  protected:
    void serializeNocNodeState(CheckpointOut &cp) const override;
    void unserializeNocNodeState(CheckpointIn &cp) override;

  private:
    uint64_t ticksExecuted = 0;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_AXIS_RANDOM_TRAFFIC_GENERATOR_HH__


