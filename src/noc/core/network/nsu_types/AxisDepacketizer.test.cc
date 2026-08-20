#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>

#include "noc/core/network/nsu_types/AxisDepacketizer.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{
namespace
{

uint64_t
tkeepForBytes(size_t bytes)
{
    if (bytes >= 64) {
        return 0xFFFFFFFFFFFFFFFFULL;
    }
    if (bytes == 0) {
        return 0;
    }
    return (1ULL << bytes) - 1;
}

std::vector<uint8_t>
packetBytes(size_t size)
{
    std::vector<uint8_t> bytes(size);
    for (size_t i = 0; i < size; ++i) {
        bytes[i] = static_cast<uint8_t>((0x31 + i) & 0xff);
    }
    return bytes;
}

axisPayload
makePayloadChunk(const std::vector<uint8_t>& bytes, size_t offset, size_t count,
                 bool lastChunk)
{
    axisPayload payload;
    size_t consumed = 0;
    while (consumed < count) {
        const size_t beatBytes = std::min<size_t>(64, count - consumed);
        std::vector<uint8_t> data(64, 0);
        std::copy(bytes.begin() + offset + consumed,
                  bytes.begin() + offset + consumed + beatBytes,
                  data.begin());

        axisData beat(data, 512, 6, 4, 7, 3,
                      lastChunk && consumed + beatBytes == count, true);
        beat.tkeep = tkeepForBytes(beatBytes);
        beat.tuser = 0x40 + payload.numBeats;
        payload.add(beat, 1000 + payload.numBeats);
        consumed += beatBytes;
    }
    payload.last = lastChunk ? 1 : 0;
    return payload;
}

std::array<uint8_t, 16>
flitDataForPayload(const axisPayload& payload, uint8_t flitId)
{
    std::array<uint8_t, 16> flitData{};
    const int flitStart = flitId * 16;
    const int flitEnd = flitStart + 16;
    int validPos = 0;
    int outIdx = 0;

    for (const axisData& beat : payload.beats) {
        for (size_t lane = 0; lane < beat.tdata.size(); ++lane) {
            if ((beat.tkeep & (1ULL << lane)) == 0) {
                continue;
            }
            if (validPos >= flitStart && validPos < flitEnd) {
                flitData[outIdx++] = beat.tdata[lane];
            }
            ++validPos;
            if (validPos >= flitEnd && outIdx >= 16) {
                return flitData;
            }
        }
    }

    return flitData;
}

std::vector<axisData>
depacketizePacket(const std::vector<uint8_t>& bytes, uint32_t sDataWidth = 512)
{
    std::vector<axisData> out;
    size_t offset = 0;
    while (offset < bytes.size()) {
        const size_t chunkBytes = std::min<size_t>(axisPayload::NPP_MAX_SIZE,
                                                   bytes.size() - offset);
        const bool lastChunk = offset + chunkBytes == bytes.size();
        axisPayload payload =
            makePayloadChunk(bytes, offset, chunkBytes, lastChunk);
        const uint8_t numFlits = static_cast<uint8_t>((chunkBytes + 15) / 16);
        std::array<uint8_t, 64> aggregate{};

        for (uint8_t flitId = 0; flitId < numFlits; ++flitId) {
            AxisDepacketizedFlit result = depacketizeAxisPayloadFlit(
                payload, sDataWidth, aggregate, flitId, numFlits, payload.last,
                flitDataForPayload(payload, flitId), -1);
            out.insert(out.end(), result.payloads.begin(), result.payloads.end());
        }

        offset += chunkBytes;
    }
    return out;
}

std::vector<uint8_t>
validBytesFromBeats(const std::vector<axisData>& beats)
{
    std::vector<uint8_t> bytes;
    for (const axisData& beat : beats) {
        for (size_t lane = 0; lane < beat.tdata.size(); ++lane) {
            if (beat.tkeep & (1ULL << lane)) {
                bytes.push_back(beat.tdata[lane]);
            }
        }
    }
    return bytes;
}

class AxisDepacketizerBoundaryTest
    : public testing::TestWithParam<size_t>
{
};

TEST_P(AxisDepacketizerBoundaryTest, ReassemblesPacketBytesAndTlast)
{
    const std::vector<uint8_t> expected = packetBytes(GetParam());
    const std::vector<axisData> beats = depacketizePacket(expected);

    ASSERT_FALSE(beats.empty());
    EXPECT_EQ(validBytesFromBeats(beats), expected);
    for (size_t i = 0; i + 1 < beats.size(); ++i) {
        EXPECT_FALSE(beats[i].tlast) << "unexpected TLAST at beat " << i;
    }
    EXPECT_TRUE(beats.back().tlast);
    EXPECT_EQ(beats.back().getTotalByteSize(),
              ((GetParam() - 1) % 64) + 1);
}

INSTANTIATE_TEST_SUITE_P(
    BoundaryPacketSizes,
    AxisDepacketizerBoundaryTest,
    testing::Values<size_t>(1, 15, 16, 17, 63, 64, 65, 1500));

TEST(AxisDepacketizerTest, PreservesBeatSidebandOnMultiBeatBoundary)
{
    const std::vector<uint8_t> bytes = packetBytes(65);
    axisPayload payload = makePayloadChunk(bytes, 0, bytes.size(), true);
    ASSERT_EQ(payload.beats.size(), 2);

    std::array<uint8_t, 64> aggregate{};
    std::vector<axisData> out;
    std::vector<std::vector<int32_t>> debugIds;
    const uint8_t numFlits = static_cast<uint8_t>((bytes.size() + 15) / 16);
    for (uint8_t flitId = 0; flitId < numFlits; ++flitId) {
        AxisDepacketizedFlit result = depacketizeAxisPayloadFlit(
            payload, 512, aggregate, flitId, numFlits, true,
            flitDataForPayload(payload, flitId), 55);
        out.insert(out.end(), result.payloads.begin(), result.payloads.end());
        debugIds.insert(debugIds.end(), result.debugIds.begin(),
                        result.debugIds.end());
    }

    ASSERT_EQ(out.size(), 2);
    ASSERT_EQ(debugIds.size(), 2);
    for (size_t i = 0; i < out.size(); ++i) {
        EXPECT_EQ(out[i].tid, payload.beats[i].tid);
        EXPECT_EQ(out[i].tdest, payload.beats[i].tdest);
        EXPECT_EQ(out[i].tuser, payload.beats[i].tuser);
        EXPECT_EQ(out[i].tkeep, payload.beats[i].tkeep);
        ASSERT_EQ(debugIds[i].size(), 1);
        EXPECT_EQ(debugIds[i][0], payload.debugIds[i]);
    }
    EXPECT_FALSE(out[0].tlast);
    EXPECT_TRUE(out[1].tlast);
}

TEST(AxisDepacketizerTest, CoversEndpointWidthsBelowEqualAndAboveFlitWidth)
{
    const std::vector<uint8_t> expected = packetBytes(65);
    for (uint32_t sDataWidth : {64U, 128U, 512U}) {
        const std::vector<axisData> beats =
            depacketizePacket(expected, sDataWidth);
        const size_t widthBytes = sDataWidth / 8;
        const size_t expectedBeatCount =
            (expected.size() + widthBytes - 1) / widthBytes;

        ASSERT_EQ(beats.size(), expectedBeatCount)
            << "S_DATA_WIDTH=" << sDataWidth;
        EXPECT_EQ(validBytesFromBeats(beats), expected)
            << "S_DATA_WIDTH=" << sDataWidth;

        for (size_t i = 0; i < beats.size(); ++i) {
            const size_t remaining = expected.size() - (i * widthBytes);
            const size_t expectedValid = std::min(widthBytes, remaining);
            EXPECT_EQ(beats[i].DATA_WIDTH, sDataWidth);
            EXPECT_EQ(beats[i].getTotalByteSize(), expectedValid)
                << "S_DATA_WIDTH=" << sDataWidth << " beat=" << i;
            EXPECT_EQ(beats[i].tid, 7);
            EXPECT_EQ(beats[i].tdest, 3);
            EXPECT_EQ(beats[i].tuser, i * widthBytes < 64 ? 0x40U : 0x41U);
            EXPECT_EQ(beats[i].tlast, i + 1 == beats.size())
                << "S_DATA_WIDTH=" << sDataWidth << " beat=" << i;
        }
    }
}

} // anonymous namespace
} // namespace garnet
} // namespace noc
} // namespace gem5
