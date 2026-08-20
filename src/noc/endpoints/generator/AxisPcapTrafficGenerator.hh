#ifndef __NOC_AXIS_PCAP_TRAFFIC_GENERATOR_HH__
#define __NOC_AXIS_PCAP_TRAFFIC_GENERATOR_HH__

#include "noc/endpoints/generator/AXISTrafficGenerator.hh"
#include "params/AxisPcapTrafficGenerator.hh"

namespace gem5 {
namespace noc {

class AxisPcapTrafficGenerator : public AXISTrafficGenerator
{
  public:
    typedef AxisPcapTrafficGeneratorParams Params;
    AxisPcapTrafficGenerator(const Params& p);
    ~AxisPcapTrafficGenerator() override = default;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_AXIS_PCAP_TRAFFIC_GENERATOR_HH__


