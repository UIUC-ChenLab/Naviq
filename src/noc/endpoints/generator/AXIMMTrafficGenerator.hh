#ifndef __NOC_AXIMM_INTERNAL_TRAFFIC_GENERATOR_HH__
#define __NOC_AXIMM_INTERNAL_TRAFFIC_GENERATOR_HH__

#include "noc/endpoints/generator/TrafficGenerator.hh"
#include "params/AXIMMTrafficGenerator.hh"

namespace gem5 {
namespace noc {

// Internal SimObject base for AXI-MM generators (distinct from external AxiTrafficGenerator).
class AXIMMTrafficGenerator : public TrafficGenerator
{
  public:
    typedef AXIMMTrafficGeneratorParams Params;
    AXIMMTrafficGenerator(const Params& p);
    ~AXIMMTrafficGenerator() override = default;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_AXIMM_INTERNAL_TRAFFIC_GENERATOR_HH__
