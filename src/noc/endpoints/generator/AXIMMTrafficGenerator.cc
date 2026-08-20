#include "noc/endpoints/generator/AXIMMTrafficGenerator.hh"

namespace gem5 {
namespace noc {

AXIMMTrafficGenerator::AXIMMTrafficGenerator(const Params& p)
    : TrafficGenerator(p)
{
    if (protocol != "AXIMM") {
        panic("AXIMMTrafficGenerator requires protocol=AXIMM");
    }
}

} // namespace noc
} // namespace gem5
