#include "noc/core/network/nsu_types/MmWriteDataDepacketizer.hh"

#include <algorithm>

namespace gem5
{
namespace noc
{
namespace garnet
{
namespace
{

MmWriteDataDebugRange
makeDebugRange(int startByte, uint64_t strobe)
{
    MmWriteDataDebugRange range;
    range.startByte = startByte;
    range.validBytes = static_cast<int>(__builtin_popcountll(strobe));
    return range;
}

} // anonymous namespace

MmWriteDataDepacketizedFlit
depacketizeMmWriteDataFlit(
    uint32_t slaveDataWidthBytes,
    uint32_t axiId,
    uint64_t writeAddress,
    MmWriteDataAssemblyState& assembly,
    uint8_t flitId,
    uint8_t numFlits,
    const std::array<uint8_t, 16>& flitData,
    uint64_t flitStrobe)
{
    MmWriteDataDepacketizedFlit result;
    const int bytesBefore = static_cast<int>(flitId) * 16;
    const bool isTailFlit = ((numFlits - 1) == flitId);

    if (slaveDataWidthBytes < 16) {
        const uint8_t beatsPerFlit = 16 / slaveDataWidthBytes;
        for (uint8_t i = 0; i < beatsPerFlit; ++i) {
            const int beatStart =
                bytesBefore + static_cast<int>(i) * slaveDataWidthBytes;
            std::array<uint8_t, 64> payloadData{};
            payloadData.fill(0);
            std::copy(flitData.begin() + (slaveDataWidthBytes * i),
                      flitData.begin() + (slaveDataWidthBytes * i) +
                          slaveDataWidthBytes,
                      payloadData.begin());

            const uint64_t mask = (slaveDataWidthBytes >= 64)
                ? ~0ULL
                : ((1ULL << slaveDataWidthBytes) - 1);
            const uint64_t beatStrobe =
                (flitStrobe >> (slaveDataWidthBytes * i)) & mask;

            aximmRWData beat;
            beat.cmd = AximmCommand::WRITE;
            beat.id = axiId;
            beat.last = isTailFlit && (i == (beatsPerFlit - 1));
            beat.data = payloadData;
            beat.wstrb = beatStrobe;
            result.payloads.push_back(beat);
            result.debugRanges.push_back(makeDebugRange(beatStart, beatStrobe));
        }
        return result;
    }

    if (slaveDataWidthBytes == 16) {
        std::array<uint8_t, 64> payloadData{};
        payloadData.fill(0);
        std::copy(flitData.begin(), flitData.end(), payloadData.begin());
        result.payloads.push_back(aximmRWData(
            AximmCommand::WRITE, axiId, isTailFlit, &payloadData, flitStrobe));
        result.debugRanges.push_back(makeDebugRange(bytesBefore, flitStrobe));
        return result;
    }

    const uint8_t flitsPerBeat = slaveDataWidthBytes / 16;
    const uint8_t offsetIdx = flitId % flitsPerBeat;
    std::copy(flitData.begin(), flitData.end(),
              assembly.aggregateData.begin() + (offsetIdx * 16));
    assembly.aggregateStrobe |= (flitStrobe << (offsetIdx * 16));

    if (((flitId + 1) % flitsPerBeat) != 0 && !isTailFlit) {
        return result;
    }

    const int beatIndex =
        static_cast<int>(flitId) / static_cast<int>(flitsPerBeat);
    const int beatStart = beatIndex * static_cast<int>(slaveDataWidthBytes);
    const uint64_t alignShift = writeAddress % slaveDataWidthBytes;

    std::array<uint8_t, 64> alignedData{};
    alignedData.fill(0);
    const long bytesToCopy = 64 - static_cast<long>(alignShift);
    if (bytesToCopy > 0) {
        std::copy(assembly.aggregateData.begin(),
                  assembly.aggregateData.begin() + bytesToCopy,
                  alignedData.begin() + alignShift);
    }
    const uint64_t alignedStrobe = assembly.aggregateStrobe << alignShift;

    result.payloads.push_back(aximmRWData(
        AximmCommand::WRITE, axiId, isTailFlit, &alignedData, alignedStrobe));
    result.debugRanges.push_back(makeDebugRange(beatStart, alignedStrobe));

    assembly.aggregateData.fill(0);
    assembly.aggregateStrobe = 0;
    return result;
}

} // namespace garnet
} // namespace noc
} // namespace gem5
