#include <gtest/gtest.h>

#include <array>
#include <deque>

#include "noc/core/network/NppReceive.hh"

namespace gem5::noc::garnet
{
namespace
{

using Queue = std::deque<NppReceiveFlit>;
using Status = NppReceiveStatus;

Queue
packet(int count, int packetId = 10, int source = 2, int vc = 1)
{
    Queue flits;
    for (int index = 0; index < count; ++index) {
        flits.push_back({packetId, source, vc, index, count,
                         index == 0, index == count - 1});
    }
    return flits;
}

NppReceiveCheck
check(const Queue &queue, int window = 5)
{
    return checkNppReceivePrefix(queue, 4, window,
        [](const NppReceiveFlit &flit) { return flit; });
}

TEST(NppReceive, EmptyQueueCannotLockSharedDrain)
{
    EXPECT_EQ(check({}).status, Status::Incomplete);
}

TEST(NppReceive, NativePacketSizesBecomeEligibleOnlyAfterTail)
{
    for (int count = 1; count <= 4; ++count) {
        SCOPED_TRACE(count);
        Queue receiving;
        for (const auto &flit : packet(count)) {
            EXPECT_EQ(check(receiving).status, Status::Incomplete);
            receiving.push_back(flit);
        }
        EXPECT_EQ(check(receiving).status, Status::Complete);
        // Eligibility inspection must not consume storage or return credits.
        EXPECT_EQ(receiving.size(), size_t(count));
        EXPECT_EQ(receiving.front().index, 0);
    }
}

TEST(NppReceive, IncompleteVcDoesNotHideCompleteOtherVc)
{
    std::array<Queue, 2> vcs{packet(4), packet(4, 20, 3, 5)};
    vcs[0].resize(2);
    int selected = -1;
    for (size_t vc = 0; vc < vcs.size(); ++vc) {
        if (check(vcs[vc]).status == Status::Complete) {
            selected = int(vc);
            break;
        }
    }
    ASSERT_EQ(selected, 1);
    EXPECT_EQ(vcs[0].size(), size_t(2));
    EXPECT_EQ(vcs[0].front().packetId, 10);
    // Completing the other VC never changes this VC's owner or flit order.
    const auto continuation = packet(4);
    vcs[0].push_back(continuation[2]);
    vcs[0].push_back(continuation[3]);
    EXPECT_EQ(check(vcs[0]).status, Status::Complete);
}

TEST(NppReceive, FollowingPacketMayAlreadyBeQueued)
{
    auto queue = packet(4);
    const auto next = packet(4, 20, 3);
    queue.insert(queue.end(), next.begin(), next.begin() + 1);
    EXPECT_EQ(check(queue).status, Status::Complete);
    for (int count = 0; count < 4; ++count) {
        queue.pop_front();
    }
    EXPECT_EQ(check(queue).status, Status::Incomplete);
}

TEST(NppReceive, SingleFlitPacketsCanHaveDifferentSuccessiveOwners)
{
    auto queue = packet(1);
    queue.push_back(packet(1, 20, 3).front());
    EXPECT_EQ(check(queue).status, Status::Complete);
    queue.pop_front();
    EXPECT_EQ(check(queue).status, Status::Complete);
}

TEST(NppReceive, RejectsPacketChangeBeforeTail)
{
    auto queue = packet(4);
    queue[2].packetId = 20;
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsSourceChangeBeforeTail)
{
    auto queue = packet(4);
    queue[2].source = 3;
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsVcChangeBeforeTail)
{
    auto queue = packet(4);
    queue[2].vc = 5;
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsDuplicateFlitIndex)
{
    auto queue = packet(4);
    queue[2].index = 1;
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsMissingFlit)
{
    auto queue = packet(4);
    queue.erase(queue.begin() + 1);
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsLengthChangeWithinPacket)
{
    auto queue = packet(4);
    queue[2].count = 3;
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsZeroLengthAndOversizedNativePackets)
{
    auto zero = packet(1);
    zero.front().count = 0;
    EXPECT_EQ(check(zero).status, Status::Invalid);
    EXPECT_EQ(check(packet(5)).status, Status::Invalid);
}

TEST(NppReceive, RejectsHeadWithoutIndexZero)
{
    auto queue = packet(4);
    queue.front().index = 1;
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsMissingHead)
{
    auto queue = packet(4);
    queue.front().head = false;
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsAnotherHeadBeforeTail)
{
    auto queue = packet(4);
    queue[2].head = true;
    EXPECT_EQ(check(queue).status, Status::Invalid);
}

TEST(NppReceive, RejectsEarlyOrMissingTail)
{
    auto early = packet(4);
    early[1].tail = true;
    EXPECT_EQ(check(early).status, Status::Invalid);
    auto missing = packet(4);
    missing.back().tail = false;
    EXPECT_EQ(check(missing).status, Status::Invalid);
}

TEST(NppReceive, RejectsInsufficientCreditWindowWithoutWaitingForever)
{
    for (int window = 0; window < 4; ++window) {
        auto head = packet(4);
        head.resize(1);
        EXPECT_EQ(check(head, window).status, Status::InsufficientWindow);
    }
    EXPECT_EQ(check(packet(4), 4).status, Status::Complete);
}

TEST(NppReceive, RejectsInsufficientAssemblerStorageIndependentlyOfCredits)
{
    const auto queue = packet(4);
    const auto result = checkNppReceivePrefix(queue, 4, std::min(3, 5),
        [](const NppReceiveFlit &flit) { return flit; });
    EXPECT_EQ(result.status, Status::InsufficientWindow);
}

} // namespace
} // namespace gem5::noc::garnet
