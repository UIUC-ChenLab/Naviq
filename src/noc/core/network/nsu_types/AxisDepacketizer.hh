#ifndef __NOC_CORE_NETWORK_NSU_TYPES_AXIS_DEPACKETIZER_HH__
#define __NOC_CORE_NETWORK_NSU_TYPES_AXIS_DEPACKETIZER_HH__

#include <array>
#include <cstdint>
#include <vector>

#include "noc/lib/axi/AXITypes.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{

struct AxisDepacketizedFlit
{
    std::vector<axisData> payloads;
    std::vector<std::vector<int32_t>> debugIds;
};

AxisDepacketizedFlit depacketizeAxisPayloadFlit(
    const axisPayload& payload,
    uint32_t sDataWidth,
    std::array<uint8_t, 64>& aggregateData,
    uint8_t flitId,
    uint8_t numFlits,
    bool streamLast,
    const std::array<uint8_t, 16>& flitData,
    int32_t fallbackDebugId);

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif // __NOC_CORE_NETWORK_NSU_TYPES_AXIS_DEPACKETIZER_HH__
