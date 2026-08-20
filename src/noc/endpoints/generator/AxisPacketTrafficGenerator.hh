#ifndef __NOC_AXIS_PACKET_TRAFFIC_GENERATOR_HH__
#define __NOC_AXIS_PACKET_TRAFFIC_GENERATOR_HH__

#include "noc/endpoints/generator/AXISTrafficGenerator.hh"
#include "params/AxisPacketTrafficGenerator.hh"

namespace gem5
{
namespace noc
{

class AxisPacketTrafficGenerator : public AXISTrafficGenerator
{
  public:
    typedef AxisPacketTrafficGeneratorParams Params;
    AxisPacketTrafficGenerator(const Params& p);
    ~AxisPacketTrafficGenerator() override = default;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_AXIS_PACKET_TRAFFIC_GENERATOR_HH__
