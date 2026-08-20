#include <gtest/gtest.h>

#include <array>
#include <cstdint>
#include <vector>

#include "noc/core/network/nsu_types/MmWriteDataDepacketizer.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{
namespace
{

std::array<uint8_t, 16>
flitBytes(uint8_t base)
{
    std::array<uint8_t, 16> data{};
    for (size_t i = 0; i < data.size(); ++i) {
        data[i] = static_cast<uint8_t>(base + i);
    }
    return data;
}

TEST(MmWriteDataDepacketizerTest, AssemblesWideBeatAcrossFourFlits)
{
    MmWriteDataAssemblyState state;
    std::vector<aximmRWData> emitted;

    for (uint8_t flit = 0; flit < 4; ++flit) {
        MmWriteDataDepacketizedFlit result = depacketizeMmWriteDataFlit(
            64, 2, 0, state, flit, 4, flitBytes(flit * 16), 0xffff);
        if (flit < 3) {
            EXPECT_TRUE(result.payloads.empty()) << "flit " << int(flit);
            EXPECT_TRUE(result.debugRanges.empty()) << "flit " << int(flit);
        } else {
            emitted = result.payloads;
            ASSERT_EQ(result.debugRanges.size(), 1);
            EXPECT_EQ(result.debugRanges[0].startByte, 0);
            EXPECT_EQ(result.debugRanges[0].validBytes, 64);
        }
    }

    ASSERT_EQ(emitted.size(), 1);
    const aximmRWData& beat = emitted[0];
    EXPECT_EQ(beat.cmd, AximmCommand::WRITE);
    EXPECT_EQ(beat.id, 2);
    EXPECT_TRUE(beat.last);
    EXPECT_EQ(beat.wstrb, 0xffffffffffffffffULL);
    for (size_t i = 0; i < 64; ++i) {
        EXPECT_EQ(beat.data[i], static_cast<uint8_t>(i)) << i;
    }
}

TEST(MmWriteDataDepacketizerTest, EmitsPartialTailAfterFullWideBeat)
{
    MmWriteDataAssemblyState state;

    for (uint8_t flit = 0; flit < 3; ++flit) {
        MmWriteDataDepacketizedFlit result = depacketizeMmWriteDataFlit(
            64, 1, 0, state, flit, 5, flitBytes(flit * 16), 0xffff);
        EXPECT_TRUE(result.payloads.empty()) << "flit " << int(flit);
    }

    MmWriteDataDepacketizedFlit firstBeat = depacketizeMmWriteDataFlit(
        64, 1, 0, state, 3, 5, flitBytes(48), 0xffff);
    ASSERT_EQ(firstBeat.payloads.size(), 1);
    EXPECT_FALSE(firstBeat.payloads[0].last);
    EXPECT_EQ(firstBeat.payloads[0].wstrb, 0xffffffffffffffffULL);
    ASSERT_EQ(firstBeat.debugRanges.size(), 1);
    EXPECT_EQ(firstBeat.debugRanges[0].startByte, 0);
    EXPECT_EQ(firstBeat.debugRanges[0].validBytes, 64);

    std::array<uint8_t, 16> tail = flitBytes(64);
    MmWriteDataDepacketizedFlit secondBeat = depacketizeMmWriteDataFlit(
        64, 1, 0, state, 4, 5, tail, 0x0001);
    ASSERT_EQ(secondBeat.payloads.size(), 1);
    EXPECT_TRUE(secondBeat.payloads[0].last);
    EXPECT_EQ(secondBeat.payloads[0].wstrb, 0x1ULL);
    EXPECT_EQ(secondBeat.payloads[0].data[0], 64);
    ASSERT_EQ(secondBeat.debugRanges.size(), 1);
    EXPECT_EQ(secondBeat.debugRanges[0].startByte, 64);
    EXPECT_EQ(secondBeat.debugRanges[0].validBytes, 1);
}

TEST(MmWriteDataDepacketizerTest, PreservesUnalignedWideWriteOffset)
{
    MmWriteDataAssemblyState state;
    MmWriteDataDepacketizedFlit result = depacketizeMmWriteDataFlit(
        64, 3, 3, state, 0, 1, flitBytes(0x80), 0x00ff);

    ASSERT_EQ(result.payloads.size(), 1);
    const aximmRWData& beat = result.payloads[0];
    EXPECT_TRUE(beat.last);
    EXPECT_EQ(beat.wstrb, 0x7f8ULL);
    for (size_t i = 0; i < 3; ++i) {
        EXPECT_EQ(beat.data[i], 0);
    }
    for (size_t i = 0; i < 8; ++i) {
        EXPECT_EQ(beat.data[i + 3], static_cast<uint8_t>(0x80 + i));
    }
}

TEST(MmWriteDataDepacketizerTest, SplitsNarrowSlaveBeatsWithPartialStrobes)
{
    MmWriteDataAssemblyState state;
    MmWriteDataDepacketizedFlit result = depacketizeMmWriteDataFlit(
        8, 4, 0, state, 0, 1, flitBytes(0x20), 0x0f0f);

    ASSERT_EQ(result.payloads.size(), 2);
    ASSERT_EQ(result.debugRanges.size(), 2);

    EXPECT_FALSE(result.payloads[0].last);
    EXPECT_EQ(result.payloads[0].wstrb, 0x0fULL);
    EXPECT_EQ(result.debugRanges[0].startByte, 0);
    EXPECT_EQ(result.debugRanges[0].validBytes, 4);
    for (size_t i = 0; i < 8; ++i) {
        EXPECT_EQ(result.payloads[0].data[i], static_cast<uint8_t>(0x20 + i));
    }

    EXPECT_TRUE(result.payloads[1].last);
    EXPECT_EQ(result.payloads[1].wstrb, 0x0fULL);
    EXPECT_EQ(result.debugRanges[1].startByte, 8);
    EXPECT_EQ(result.debugRanges[1].validBytes, 4);
    for (size_t i = 0; i < 8; ++i) {
        EXPECT_EQ(result.payloads[1].data[i], static_cast<uint8_t>(0x28 + i));
    }
}

TEST(MmWriteDataDepacketizerTest, EmitsShortSingleFlitBurstOnEqualWidthSlave)
{
    MmWriteDataAssemblyState state;
    MmWriteDataDepacketizedFlit result = depacketizeMmWriteDataFlit(
        16, 6, 0, state, 0, 1, flitBytes(0x40), 0x0003);

    ASSERT_EQ(result.payloads.size(), 1);
    ASSERT_EQ(result.debugRanges.size(), 1);
    EXPECT_TRUE(result.payloads[0].last);
    EXPECT_EQ(result.payloads[0].wstrb, 0x3ULL);
    EXPECT_EQ(result.payloads[0].data[0], 0x40);
    EXPECT_EQ(result.payloads[0].data[1], 0x41);
    EXPECT_EQ(result.debugRanges[0].startByte, 0);
    EXPECT_EQ(result.debugRanges[0].validBytes, 2);
}

} // anonymous namespace
} // namespace garnet
} // namespace noc
} // namespace gem5
