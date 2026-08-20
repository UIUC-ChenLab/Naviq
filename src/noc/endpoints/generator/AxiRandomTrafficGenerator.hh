#ifndef __NOC_AXI_RANDOM_TRAFFIC_GENERATOR_HH__
#define __NOC_AXI_RANDOM_TRAFFIC_GENERATOR_HH__

#include "noc/endpoints/generator/AXIMMTrafficGenerator.hh"
#include "params/AxiRandomTrafficGenerator.hh"

namespace gem5 {
namespace noc {

class AxiRandomTrafficGenerator : public AXIMMTrafficGenerator
{
  public:
    typedef AxiRandomTrafficGeneratorParams Params;
    AxiRandomTrafficGenerator(const Params& p);
    ~AxiRandomTrafficGenerator() override = default;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_AXI_RANDOM_TRAFFIC_GENERATOR_HH__


