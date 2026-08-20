#include "noc/endpoints/generator/AXISTrafficGenerator.hh"

namespace gem5 {
namespace noc {

AXISTrafficGenerator::AXISTrafficGenerator(const Params& p)
    : TrafficGenerator(p)
{
    if (protocol != "AXIS") {
        panic("AXISTrafficGenerator requires protocol=AXIS");
    }
}

} // namespace noc
} // namespace gem5