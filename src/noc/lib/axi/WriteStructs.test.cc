#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>

#include "noc/lib/axi/WriteStructs.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{
namespace
{

uint64_t
maskForBytes(size_t bytes)
{
    if (bytes >= 64) {
        return 0xffffffffffffffffULL;
    }
    if (bytes == 0) {
        return 0;
    }
    return (1ULL << bytes) - 1;
}

std::vector<uint8_t>
makeBytes(size_t bytes)
{
    std::vector<uint8_t> out(bytes);
    for (size_t i = 0; i < bytes; ++i) {
        out[i] = static_cast<uint8_t>((0x17 + i) & 0xff);
    }
    return out;
}

std::vector<uint8_t>
validAxisBytes(const axisPayload& payload)
{
    std::vector<uint8_t> out;
    for (const axisData& beat : payload.beats) {
        for (size_t i = 0; i < beat.tdata.size(); ++i) {
            if (beat.tkeep & (1ULL << i)) {
                out.push_back(beat.tdata[i]);
            }
        }
    }
    return out;
}

std::vector<axisPayload>
buildAndDrainAxisPacket(size_t packetBytes)
{
    axisWriteBuffer buffer;
    buffer.setHeadReadyHandler([]() {});
    const std::vector<uint8_t> bytes = makeBytes(packetBytes);

    size_t offset = 0;
    while (offset < packetBytes) {
        const size_t beatBytes = std::min<size_t>(64, packetBytes - offset);
        std::vector<uint8_t> data(64, 0);
        std::copy(bytes.begin() + offset, bytes.begin() + offset + beatBytes,
                  data.begin());
        axisData beat(data, 512, 6, 4, 7, 3,
                      offset + beatBytes == packetBytes, true);
        beat.tkeep = maskForBytes(beatBytes);
        buffer.add(beat, nullptr, 5, static_cast<int32_t>(1000 + offset));
        offset += beatBytes;
    }

    std::vector<axisPayload> packets;
    int vc = -1;
    NetworkInterface::OutputPort* oport = nullptr;
    int32_t debugId = -1;
    while (buffer.getSize() > 0) {
        std::unique_ptr<axisPayload> payload =
            buffer.popNextPacket(&vc, &oport, &debugId);
        packets.push_back(*payload);
    }
    return packets;
}

aximmRWAddr
makeWriteRequestForTotalBytes(size_t totalBytes)
{
    aximmRWAddr request;
    request.cmd = AximmCommand::WRITE;
    request.id = 7;
    request.addr = 0x1000;
    request.valid = true;
    request.size = 6;
    request.len = (totalBytes + 63) / 64 - 1;

    if (totalBytes == 1 || totalBytes == 65) {
        request.size = 0;
        request.len = totalBytes - 1;
    } else if (totalBytes == 16) {
        request.size = 4;
        request.len = 0;
    }

    return request;
}

std::array<aximmRWData, 4>
writeAximmBytes(size_t totalBytes)
{
    aximmWriteBuffer buffer;
    bool ready = false;
    std::array<aximmRWData, 4> readyPayload;
    buffer.setHeadReadyHandler(
        [&](aximmRWAddr, std::array<aximmRWData, 4> payload) {
            ready = true;
            readyPayload = payload;
        });

    const aximmRWAddr request = makeWriteRequestForTotalBytes(totalBytes);
    buffer.add(request, 1, nullptr, true);

    const size_t beatBytes = request.getBeatByteSize();
    size_t offset = 0;
    while (offset < totalBytes) {
        std::array<uint8_t, 64> data{};
        data.fill(0);
        const size_t bytesThisBeat = std::min(beatBytes, totalBytes - offset);
        for (size_t i = 0; i < bytesThisBeat; ++i) {
            data[i] = static_cast<uint8_t>((offset + i) & 0xff);
        }
        buffer.write(data, maskForBytes(bytesThisBeat), 10 + offset, 2, 99);
        offset += bytesThisBeat;
    }

    EXPECT_TRUE(ready) << "totalBytes=" << totalBytes;
    EXPECT_EQ(buffer.getSize(), totalBytes);
    return readyPayload;
}

std::vector<uint8_t>
validAximmBytes(const std::array<aximmRWData, 4>& payload)
{
    std::vector<uint8_t> out;
    for (const aximmRWData& beat : payload) {
        for (size_t i = 0; i < beat.data.size(); ++i) {
            if (beat.wstrb & (1ULL << i)) {
                out.push_back(beat.data[i]);
            }
        }
    }
    return out;
}

TEST(WriteTrackerTest, BlocksSameAxiIdUntilHeadResponseCompletes)
{
    WriteTracker tracker;
    uint8_t ready_id = 255;
    tracker.setWriteRespReadyHandler(
        [&](uint8_t axi_id) { ready_id = axi_id; });

    tracker.addAxiWriteRequest(3, 10, 2, 4);
    tracker.addAxiWriteRequest(3, 11, 1, 5);

    EXPECT_EQ(tracker.getNumEntries(), 2);
    EXPECT_FALSE(tracker.checkSSID(3, 11));
    EXPECT_TRUE(tracker.checkSSID(3, 10));

    tracker.markRespReceived(3, false);
    EXPECT_EQ(ready_id, 255);

    tracker.markRespReceived(3, true);
    EXPECT_EQ(ready_id, 3);

    const WriteTrackerEntry first = tracker.readAndRemoveEntry(3);
    EXPECT_EQ(first.destID, 10);
    EXPECT_EQ(first.vc, 4);
    EXPECT_TRUE(first.receivedSLVERR);

    EXPECT_TRUE(tracker.checkSSID(3, 11));
    const WriteTrackerEntry second = tracker.readAndRemoveEntry(3);
    EXPECT_EQ(second.destID, 11);
    EXPECT_EQ(second.vc, 5);
    EXPECT_EQ(tracker.getNumEntries(), 0);
}

TEST(WriteTrackerTest, TracksMultipleAxiIdsIndependently)
{
    WriteTracker tracker;
    std::vector<uint8_t> readyIds;
    tracker.setWriteRespReadyHandler(
        [&](uint8_t axiId) { readyIds.push_back(axiId); });

    tracker.addAxiWriteRequest(1, 10, 1, 4);
    tracker.addAxiWriteRequest(2, 20, 2, 5);
    tracker.addAxiWriteRequest(1, 11, 1, 6);

    EXPECT_TRUE(tracker.checkSSID(1, 10));
    EXPECT_FALSE(tracker.checkSSID(1, 11));
    EXPECT_TRUE(tracker.checkSSID(2, 20));

    tracker.markRespReceived(2, false);
    EXPECT_TRUE(readyIds.empty());
    tracker.markRespReceived(2, true);
    ASSERT_EQ(readyIds.size(), 1);
    EXPECT_EQ(readyIds[0], 2);
    WriteTrackerEntry entry2 = tracker.readAndRemoveEntry(2);
    EXPECT_EQ(entry2.destID, 20);
    EXPECT_EQ(entry2.vc, 5);
    EXPECT_TRUE(entry2.receivedSLVERR);

    tracker.markRespReceived(1, false);
    ASSERT_EQ(readyIds.size(), 2);
    EXPECT_EQ(readyIds[1], 1);
    WriteTrackerEntry entry1 = tracker.readAndRemoveEntry(1);
    EXPECT_EQ(entry1.destID, 10);
    EXPECT_EQ(entry1.vc, 4);
    EXPECT_TRUE(tracker.checkSSID(1, 11));
    EXPECT_EQ(tracker.getNumEntries(), 1);
}

TEST(AximmWriteBufferTest, AwBeforeWContractPacketizesAndSignalsReady)
{
    aximmRWAddr request;
    request.cmd = AximmCommand::WRITE;
    request.id = 7;
    request.addr = 0x1000;
    request.len = 0;
    request.size = 4;
    request.valid = true;

    aximmWriteBuffer buffer;
    bool ready = false;
    aximmRWAddr ready_request;
    aximmPayload ready_payload;
    buffer.setHeadReadyHandler(
        [&](aximmRWAddr req, std::array<aximmRWData, 4> payload) {
            ready = true;
            ready_request = req;
            ready_payload = payload;
        });

    buffer.add(request, 2, nullptr, true);
    // Public AXI-MM contract: an accepted AW creates the write-buffer entry
    // before its W beat arrives. W-before-AW remains intentionally unsupported.
    EXPECT_FALSE(ready);

    std::array<uint8_t, 64> data;
    for (size_t i = 0; i < data.size(); ++i)
        data[i] = static_cast<uint8_t>(i);

    buffer.write(data, 0x00ff, 10, 2, 99);

    ASSERT_TRUE(ready);
    EXPECT_EQ(ready_request.id, 7);
    EXPECT_EQ(ready_request.getTotalByteSize(), 16);
    EXPECT_EQ(ready_payload[0].id, 7);
    EXPECT_TRUE(ready_payload[0].valid);
    EXPECT_EQ(ready_payload[0].wstrb, 0x00ff);
    for (size_t i = 0; i < 16; ++i)
        EXPECT_EQ(ready_payload[0].data[i], static_cast<uint8_t>(i));
    EXPECT_EQ(buffer.getSize(), 16);
}

class AximmWriteBufferSizeTest : public testing::TestWithParam<size_t>
{
};

TEST_P(AximmWriteBufferSizeTest, PacketizesBoundaryWriteSizes)
{
    const size_t totalBytes = GetParam();
    const std::array<aximmRWData, 4> payload = writeAximmBytes(totalBytes);
    const std::vector<uint8_t> bytes = validAximmBytes(payload);

    ASSERT_EQ(bytes.size(), totalBytes);
    for (size_t i = 0; i < totalBytes; ++i) {
        EXPECT_EQ(bytes[i], static_cast<uint8_t>(i & 0xff))
            << "totalBytes=" << totalBytes << " byte=" << i;
    }
}

INSTANTIATE_TEST_SUITE_P(
    BoundaryWrites,
    AximmWriteBufferSizeTest,
    testing::Values<size_t>(1, 16, 65));

TEST(AximmWriteBufferTest, PacketizesWideWritesWithFullStrobes)
{
    for (size_t totalBytes : {64, 128, 256}) {
        const std::array<aximmRWData, 4> payload = writeAximmBytes(totalBytes);
        EXPECT_EQ(validAximmBytes(payload).size(), totalBytes)
            << "totalBytes=" << totalBytes;
    }
}

TEST(AxisWriteBufferTest, EmitsShortPacketAtTlast)
{
    axisWriteBuffer buffer;
    bool ready = false;
    buffer.setHeadReadyHandler([&]() { ready = true; });

    axisData beat(512, 6, 4);
    beat.tvalid = true;
    beat.tlast = true;
    beat.tid = 3;
    beat.tdest = 2;
    beat.tkeep = (1ULL << 15) - 1;
    for (size_t i = 0; i < beat.tdata.size(); ++i)
        beat.tdata[i] = static_cast<uint8_t>(0xa0 + i);

    buffer.add(beat, nullptr, 6, 42);

    ASSERT_TRUE(ready);
    EXPECT_EQ(buffer.getSize(), 15);

    int vc = -1;
    NetworkInterface::OutputPort *oport = nullptr;
    int32_t debug_id = -1;
    std::unique_ptr<axisPayload> payload =
        buffer.popNextPacket(&vc, &oport, &debug_id);

    ASSERT_NE(payload, nullptr);
    EXPECT_EQ(vc, 6);
    EXPECT_EQ(oport, nullptr);
    EXPECT_EQ(debug_id, 42);
    EXPECT_EQ(payload->numBeats, 1);
    EXPECT_EQ(payload->totalBytes, 15);
    EXPECT_EQ(payload->last, 1);
    ASSERT_EQ(payload->debugIds.size(), 1);
    EXPECT_EQ(payload->debugIds[0], 42);
    EXPECT_EQ(buffer.getSize(), 0);
}

TEST(AxisWriteBufferTest, SplitsFullNppBeforeTlast)
{
    axisWriteBuffer buffer;
    int ready_count = 0;
    buffer.setHeadReadyHandler([&]() { ++ready_count; });

    for (int i = 0; i < 5; ++i) {
        axisData beat(512, 6, 4);
        beat.tvalid = true;
        beat.tlast = (i == 4);
        beat.tid = 1;
        beat.tdest = 0;
        beat.tkeep = 0xffffffffffffffffULL;
        buffer.add(beat, nullptr, 3, 100 + i);
    }

    ASSERT_GE(ready_count, 1);
    EXPECT_EQ(buffer.getSize(), 320);

    int vc = -1;
    NetworkInterface::OutputPort *oport = nullptr;
    int32_t debug_id = -1;
    std::unique_ptr<axisPayload> first =
        buffer.popNextPacket(&vc, &oport, &debug_id);
    ASSERT_NE(first, nullptr);
    EXPECT_EQ(first->totalBytes, 256);
    EXPECT_EQ(first->last, 0);
    EXPECT_EQ(vc, 3);
    EXPECT_EQ(debug_id, 100);
    EXPECT_EQ(buffer.getSize(), 64);

    std::unique_ptr<axisPayload> second =
        buffer.popNextPacket(&vc, &oport, &debug_id);
    ASSERT_NE(second, nullptr);
    EXPECT_EQ(second->totalBytes, 64);
    EXPECT_EQ(second->last, 1);
    EXPECT_EQ(buffer.getSize(), 0);
}

class AxisWriteBufferSizeTest : public testing::TestWithParam<size_t>
{
};

TEST_P(AxisWriteBufferSizeTest, PacketizesBoundaryPacketSizes)
{
    const size_t packetBytes = GetParam();
    const std::vector<uint8_t> expected = makeBytes(packetBytes);
    const std::vector<axisPayload> packets = buildAndDrainAxisPacket(packetBytes);

    ASSERT_FALSE(packets.empty());

    std::vector<uint8_t> actual;
    for (size_t i = 0; i < packets.size(); ++i) {
        const std::vector<uint8_t> packetBytes = validAxisBytes(packets[i]);
        actual.insert(actual.end(), packetBytes.begin(), packetBytes.end());
        if (i + 1 < packets.size()) {
            EXPECT_EQ(packets[i].totalBytes, 256);
            EXPECT_EQ(packets[i].last, 0);
        }
    }

    EXPECT_EQ(actual, expected);
    EXPECT_EQ(packets.back().last, 1);
    EXPECT_LE(packets.back().totalBytes, 256);
}

INSTANTIATE_TEST_SUITE_P(
    BoundaryPackets,
    AxisWriteBufferSizeTest,
    testing::Values<size_t>(1, 15, 16, 17, 63, 64, 65, 255, 256, 257));

TEST(AxisWriteBufferTest, PacketizesMtuSizedPacketAsMultipleNpps)
{
    const std::vector<axisPayload> packets = buildAndDrainAxisPacket(1500);
    ASSERT_GT(packets.size(), 1);
    for (size_t i = 0; i < packets.size(); ++i) {
        EXPECT_LE(packets[i].totalBytes, 256) << "packet " << i;
        EXPECT_EQ(packets[i].last, i + 1 == packets.size());
    }
}

#if GTEST_HAS_DEATH_TEST
TEST(AxisWriteBufferTest, RejectsTidChangeBeforeTlast)
{
    axisWriteBuffer buffer;
    buffer.setHeadReadyHandler([]() {});

    axisData first(512, 6, 4);
    first.tvalid = true;
    first.tlast = false;
    first.tid = 1;
    first.tdest = 2;
    first.tkeep = 0xff;
    buffer.add(first, nullptr, 3, 1);

    axisData changed = first;
    changed.tid = 9;
    EXPECT_ANY_THROW(buffer.add(changed, nullptr, 3, 2));
}

TEST(AxisWriteBufferTest, RejectsTdestChangeBeforeTlast)
{
    axisWriteBuffer buffer;
    buffer.setHeadReadyHandler([]() {});

    axisData first(512, 6, 4);
    first.tvalid = true;
    first.tlast = false;
    first.tid = 1;
    first.tdest = 2;
    first.tkeep = 0xff;
    buffer.add(first, nullptr, 3, 1);

    axisData changed = first;
    changed.tdest = 9;
    EXPECT_ANY_THROW(buffer.add(changed, nullptr, 3, 2));
}
#endif

} // anonymous namespace
} // namespace garnet
} // namespace noc
} // namespace gem5
