#ifndef __NOC_AXIS_INTERNAL_TRAFFIC_GENERATOR_HH__
#define __NOC_AXIS_INTERNAL_TRAFFIC_GENERATOR_HH__

#include "noc/endpoints/generator/TrafficGenerator.hh"
#include "params/AXISTrafficGenerator.hh"

namespace gem5 {
namespace noc {

// Internal SimObject base for AXIS generators (distinct from external AxisTrafficGenerator).
class AXISTrafficGenerator : public TrafficGenerator
{
  public:
    typedef AXISTrafficGeneratorParams Params;
    AXISTrafficGenerator(const Params& p);
    ~AXISTrafficGenerator() override = default;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_AXIS_INTERNAL_TRAFFIC_GENERATOR_HH__