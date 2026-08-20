#include <gtest/gtest.h>

#include <array>
#include <vector>

#include "noc/core/network/rrob.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{
namespace
{

std::array<uint8_t, 16>
makeFlit(uint8_t base)
{
    std::array<uint8_t, 16> data;
    for (size_t i = 0; i < data.size(); ++i)
        data[i] = base + i;
    return data;
}

TEST(AxiListManagerTest, EnforcesCapacity)
{
    AxiListManager manager(2);

    EXPECT_EQ(manager.addEntry(1, 16, true, 1, 0), 1);
    EXPECT_EQ(manager.addEntry(2, 16, true, 1, 0), 2);
    EXPECT_EQ(manager.addEntry(3, 16, true, 1, 0), 255);
    EXPECT_EQ(manager.getNumEntries(), 2);
}

TEST(AxiListManagerTest, TracksAxiIdAndVnetByTag)
{
    AxiListManager manager(4);

    const auto tag1 = manager.addEntry(5, 16, true, 1, 3);
    const auto tag2 = manager.addEntry(9, 32, false, 0, 7);

    EXPECT_EQ(manager.getAxiID(tag1), 5);
    EXPECT_EQ(manager.getAxiID(tag2), 9);
    EXPECT_EQ(manager.getVnet(5, tag1), 3);
    EXPECT_EQ(manager.getVnet(9, tag2), 7);
}

TEST(AxiListManagerTest, WriteHalfEntryCopiesDataAndMarksBeatsValid)
{
    AxiListManager manager(4);

    const auto tag = manager.addEntry(5, 16, true, 1, 0);

    auto flit0 = makeFlit(0);
    auto flit1 = makeFlit(16);
    manager.writeFlitEntry(tag, &flit0, 0);
    manager.writeFlitEntry(tag, &flit1, 1);

    auto it = manager.getIterator(tag);
    const RROBEntry &entry = *it;

    EXPECT_EQ(entry.filled_flits, 2);
    EXPECT_TRUE(entry.flit_written[0]);
    EXPECT_TRUE(entry.flit_written[1]);
    for (size_t i = 0; i < 16; ++i)
        EXPECT_EQ(entry.data[i], flit0[i]);
    for (size_t i = 0; i < 16; ++i)
        EXPECT_EQ(entry.data[16 + i], flit1[i]);
    ASSERT_EQ(entry.beat_statuses.size(), 2);
    EXPECT_TRUE(entry.beat_statuses[0].valid);
    EXPECT_TRUE(entry.beat_statuses[1].valid);
}

TEST(AxiListManagerTest, OutOfOrderFlitArrivalStillStoresOrderedEntryBytes)
{
    AxiListManager manager(4);
    const auto tag = manager.addEntry(5, 16, true, 1, 2);

    auto flit0 = makeFlit(0);
    auto flit1 = makeFlit(16);
    manager.writeFlitEntry(tag, &flit1, 1);
    {
        const RROBEntry& entry = *manager.getIterator(tag);
        EXPECT_EQ(entry.filled_flits, 1);
        EXPECT_FALSE(entry.flit_written[0]);
        EXPECT_TRUE(entry.flit_written[1]);
        EXPECT_FALSE(entry.beat_statuses[0].valid);
        EXPECT_TRUE(entry.beat_statuses[1].valid);
    }

    manager.writeFlitEntry(tag, &flit0, 0);
    const RROBEntry& entry = *manager.getIterator(tag);
    EXPECT_EQ(entry.filled_flits, 2);
    EXPECT_TRUE(entry.flit_written[0]);
    EXPECT_TRUE(entry.flit_written[1]);
    for (size_t i = 0; i < 32; ++i) {
        EXPECT_EQ(entry.data[i], static_cast<uint8_t>(i));
    }
    EXPECT_TRUE(entry.beat_statuses[0].valid);
    EXPECT_TRUE(entry.beat_statuses[1].valid);
}

TEST(AxiListManagerTest, MergesTwoEntriesForSixtyFourByteBeat)
{
    AxiListManager manager(4);
    const auto firstTag = manager.addEntry(3, 64, false, 0, 7, true);
    const auto secondTag = manager.addEntry(3, 64, true, 0, 7, false);

    auto f0 = makeFlit(0);
    auto f1 = makeFlit(16);
    auto f2 = makeFlit(32);
    auto f3 = makeFlit(48);
    manager.writeFlitEntry(firstTag, &f0, 0);
    manager.writeFlitEntry(firstTag, &f1, 1);
    manager.writeFlitEntry(secondTag, &f2, 0);
    manager.writeFlitEntry(secondTag, &f3, 1);

    AxiListManager::AxiList& list = manager.getList(3);
    ASSERT_EQ(list.size(), 2);
    auto it = list.begin();
    EXPECT_EQ(it->tag, firstTag);
    EXPECT_TRUE(it->need_next_entry);
    EXPECT_TRUE(it->beat_statuses[0].valid);
    for (size_t i = 0; i < 32; ++i) {
        EXPECT_EQ(it->data[i], static_cast<uint8_t>(i));
    }
    ++it;
    EXPECT_EQ(it->tag, secondTag);
    EXPECT_FALSE(it->need_next_entry);
    EXPECT_TRUE(it->contains_last);
    EXPECT_TRUE(it->beat_statuses[0].valid);
    for (size_t i = 0; i < 32; ++i) {
        EXPECT_EQ(it->data[i], static_cast<uint8_t>(i + 32));
    }
}

TEST(AxiListManagerTest, ReadyScanHonorsPerAxiOrderingAndRoundRobin)
{
    AxiListManager manager(6);
    const auto blockedHead = manager.addEntry(4, 16, true, 1, 0);
    const auto readyBehindBlockedHead = manager.addEntry(4, 16, true, 1, 0);
    const auto readyOtherAxi = manager.addEntry(9, 16, true, 1, 0);

    auto f0 = makeFlit(0);
    auto f1 = makeFlit(16);
    manager.writeFlitEntry(readyBehindBlockedHead, &f0, 0);
    manager.writeFlitEntry(readyBehindBlockedHead, &f1, 1);
    manager.writeFlitEntry(readyOtherAxi, &f0, 0);
    manager.writeFlitEntry(readyOtherAxi, &f1, 1);

    EXPECT_EQ(manager.getNextReadyAxiID(), -1)
        << "ready entry behind incomplete same-ID head must not pass it";
    EXPECT_EQ(manager.getNextReadyAxiID(), 9);

    manager.writeFlitEntry(blockedHead, &f0, 0);
    manager.writeFlitEntry(blockedHead, &f1, 1);
    EXPECT_EQ(manager.getNextReadyAxiID(), 4);
}

} // anonymous namespace
} // namespace garnet
} // namespace noc
} // namespace gem5
