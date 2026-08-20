#ifndef __NOC_MM_WRITE_DATA_DEPACKETIZER_HH
#define __NOC_MM_WRITE_DATA_DEPACKETIZER_HH

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

struct MmWriteDataAssemblyState
{
    // Partial AXI-MM W beat reconstructed across 16-byte NoC flits. Strobes
    // are accumulated with bytes so sparse writes retain byte accuracy.
    std::array<uint8_t, 64> aggregateData{};
    uint64_t aggregateStrobe = 0;

    MmWriteDataAssemblyState()
    {
        aggregateData.fill(0);
    }
};

struct MmWriteDataDebugRange
{
    int startByte = 0;
    int validBytes = 0;
};

struct MmWriteDataDepacketizedFlit
{
    std::vector<aximmRWData> payloads;
    std::vector<MmWriteDataDebugRange> debugRanges;
};

MmWriteDataDepacketizedFlit depacketizeMmWriteDataFlit(
    uint32_t slaveDataWidthBytes,
    uint32_t axiId,
    uint64_t writeAddress,
    MmWriteDataAssemblyState& assembly,
    uint8_t flitId,
    uint8_t numFlits,
    const std::array<uint8_t, 16>& flitData,
    uint64_t flitStrobe);

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif
