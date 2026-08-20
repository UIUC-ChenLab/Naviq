#ifndef __NOC_AXIS_STREAM_CONTRACT_HH
#define __NOC_AXIS_STREAM_CONTRACT_HH

#include <cstdint>
#include <vector>

#include "noc/core/axi/AXITypes.hh"

namespace gem5
{
namespace noc
{

std::vector<uint8_t> axisStablePayloadFingerprint(const axisData& data);

} // namespace noc
} // namespace gem5

#endif
