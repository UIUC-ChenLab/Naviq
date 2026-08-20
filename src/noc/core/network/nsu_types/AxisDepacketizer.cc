#include "noc/core/network/nsu_types/AxisDepacketizer.hh"

#include <algorithm>
#include <stdexcept>
#include <unordered_set>

namespace gem5
{
namespace noc
{
namespace garnet
{

namespace
{

std::vector<int32_t>
debugIdsForNppByteRange(const axisPayload& ap, int startByte, int nbytes,
                        int32_t fallback)
{
    std::vector<int32_t> out;
    if (nbytes <= 0) {
        if (fallback >= 0) {
            out.push_back(fallback);
        }
        return out;
    }
    if (ap.beats.size() != ap.debugIds.size() || ap.beats.empty()) {
        if (fallback >= 0) {
            out.push_back(fallback);
        }
        return out;
    }

    const int endByte = startByte + nbytes;
    int cum = 0;
    std::unordered_set<int32_t> seen;
    for (size_t i = 0; i < ap.beats.size(); ++i) {
        const int bsz = ap.beats[i].getTotalByteSize();
        if (bsz <= 0) {
            continue;
        }
        const int beatStart = cum;
        const int beatEnd = cum + bsz;
        const bool overlaps = startByte < beatEnd && endByte > beatStart;
        if (overlaps) {
            const int32_t id = ap.debugIds[i];
            if (seen.insert(id).second) {
                out.push_back(id);
            }
        }
        cum += bsz;
        if (cum >= endByte) {
            break;
        }
    }
    if (out.empty() && fallback >= 0) {
        out.push_back(fallback);
    }
    return out;
}

uint64_t
tkeepForValidBytes(int validBytes)
{
    if (validBytes >= 64) {
        return 0xFFFFFFFFFFFFFFFFULL;
    }
    if (validBytes <= 0) {
        return 0;
    }
    return (1ULL << validBytes) - 1;
}

const axisData*
findSourceBeatForByteRange(const axisPayload& source, int startByte, int nbytes)
{
    if (nbytes <= 0) {
        return nullptr;
    }
    const int endByte = startByte + nbytes;
    int cum = 0;
    for (const axisData& sourceBeat : source.beats) {
        const int bsz = sourceBeat.getTotalByteSize();
        if (bsz <= 0) {
            continue;
        }
        const int beatStart = cum;
        const int beatEnd = cum + bsz;
        if (startByte < beatEnd && endByte > beatStart) {
            return &sourceBeat;
        }
        cum += bsz;
        if (cum >= endByte) {
            break;
        }
    }
    return nullptr;
}

void
applySidebandForByteRange(const axisPayload& source, axisData& beat,
                          int startByte, int nbytes)
{
    const axisData* original =
        findSourceBeatForByteRange(source, startByte, nbytes);
    if (!original) {
        return;
    }
    beat.tid = original->tid;
    beat.tdest = original->tdest;
    beat.tuser = original->tuser;
}

} // namespace

AxisDepacketizedFlit
depacketizeAxisPayloadFlit(const axisPayload& payload, uint32_t sDataWidth,
                           std::array<uint8_t, 64>& aggregateData,
                           uint8_t flitId, uint8_t numFlits, bool streamLast,
                           const std::array<uint8_t, 16>& flitData,
                           int32_t fallbackDebugId)
{
    if ((sDataWidth % 8) != 0) {
        throw std::invalid_argument("AXIS NSU data width must be byte aligned");
    }
    const uint32_t widthBytes = sDataWidth / 8;
    if (widthBytes == 0 || widthBytes > 64) {
        throw std::invalid_argument("AXIS NSU data width must be 1..64 bytes");
    }

    const bool isTailFlit = (numFlits > 0) && ((numFlits - 1) == flitId);
    const int totalValid = payload.totalBytes;
    const int bytesBefore = static_cast<int>(flitId) * 16;
    const int flitValid =
        std::min(16, std::max(0, totalValid - bytesBefore));

    AxisDepacketizedFlit result;

    if (widthBytes < 16) {
        const uint8_t beatsPerFlit = 16 / widthBytes;
        int lastValidSubBeat = -1;
        for (uint8_t i = 0; i < beatsPerFlit; i++) {
            if (std::max(0, flitValid - static_cast<int>(i * widthBytes)) > 0) {
                lastValidSubBeat = i;
            }
        }

        for (uint8_t i = 0; i < beatsPerFlit; i++) {
            const int base = i * widthBytes;
            const int remaining = std::max(0, flitValid - base);
            const int copy = std::min<int>(widthBytes, remaining);
            if (copy <= 0) {
                continue;
            }

            std::fill(aggregateData.begin(), aggregateData.begin() + widthBytes, 0);
            if (copy > 0) {
                std::copy(flitData.begin() + base,
                          flitData.begin() + base + copy,
                          aggregateData.begin());
            }

            std::vector<uint8_t> beat(aggregateData.begin(),
                                      aggregateData.begin() + widthBytes);
            result.payloads.emplace_back(
                beat, sDataWidth, 6, 4, 0, 0,
                static_cast<bool>(
                    isTailFlit && streamLast && i == lastValidSubBeat),
                true);
            result.payloads.back().tkeep = tkeepForValidBytes(copy);
            applySidebandForByteRange(payload, result.payloads.back(),
                                      bytesBefore + base, copy);
            result.debugIds.push_back(debugIdsForNppByteRange(
                payload, bytesBefore + base, copy, fallbackDebugId));
        }
    } else if (widthBytes == 16) {
        std::fill(aggregateData.begin(), aggregateData.begin() + widthBytes, 0);
        if (flitValid > 0) {
            std::copy(flitData.begin(), flitData.begin() + flitValid,
                      aggregateData.begin());
        }

        std::vector<uint8_t> beat(aggregateData.begin(),
                                  aggregateData.begin() + widthBytes);
        result.payloads.emplace_back(
            beat, sDataWidth, 6, 4, 0, 0,
            static_cast<bool>(isTailFlit && streamLast), true);
        result.payloads.back().tkeep = tkeepForValidBytes(flitValid);
        applySidebandForByteRange(payload, result.payloads.back(),
                                  bytesBefore, flitValid);
        result.debugIds.push_back(debugIdsForNppByteRange(
            payload, bytesBefore, flitValid, fallbackDebugId));
    } else {
        const uint8_t flitsPerBeat = widthBytes / 16;
        if (flitsPerBeat == 0 || widthBytes % 16 != 0) {
            throw std::invalid_argument(
                "AXIS NSU data width above 16 bytes must be a multiple of 16");
        }

        if (flitValid > 0) {
            std::copy(
                flitData.begin(), flitData.begin() + flitValid,
                aggregateData.begin() + ((flitId % flitsPerBeat) * 16));
        }
        if (((flitId + 1) % flitsPerBeat) == 0 || isTailFlit) {
            std::vector<uint8_t> beat(aggregateData.begin(),
                                      aggregateData.begin() + widthBytes);
            result.payloads.emplace_back(
                beat, sDataWidth, 6, 4, 0, 0,
                static_cast<bool>(isTailFlit && streamLast), true);

            const int beatIndex =
                static_cast<int>(flitId) / static_cast<int>(flitsPerBeat);
            const int beatStart = beatIndex * static_cast<int>(widthBytes);
            const int beatEnd = beatStart + static_cast<int>(widthBytes);
            const int bytesUpToPrev = std::min(totalValid, beatStart);
            const int bytesUpToThisBeat = std::min(totalValid, beatEnd);
            const int validInBeat = std::min<int>(
                widthBytes, std::max(0, bytesUpToThisBeat - bytesUpToPrev));

            result.payloads.back().tkeep = tkeepForValidBytes(validInBeat);
            applySidebandForByteRange(payload, result.payloads.back(),
                                      beatStart, validInBeat);
            result.debugIds.push_back(debugIdsForNppByteRange(
                payload, beatStart, validInBeat, fallbackDebugId));
        }
    }

    return result;
}

} // namespace garnet
} // namespace noc
} // namespace gem5
