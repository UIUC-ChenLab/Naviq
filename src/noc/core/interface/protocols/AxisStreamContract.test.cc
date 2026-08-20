#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "noc/core/interface/protocols/AxisStreamContract.hh"

namespace gem5
{
namespace noc
{
namespace
{

axisData
makeBeat()
{
    std::vector<uint8_t> data(64, 0);
    for (size_t i = 0; i < data.size(); ++i) {
        data[i] = static_cast<uint8_t>(0x20 + i);
    }

    axisData beat(data, 512, 6, 4, 3, 5, false, true);
    beat.tkeep = 0x000000ffffffffffULL;
    beat.tuser = 0x1234;
    return beat;
}

TEST(AxisStreamContractTest, FingerprintIgnoresHandshakeSignals)
{
    axisData baseline = makeBeat();
    axisData changed = baseline;
    changed.tvalid = !changed.tvalid;

    EXPECT_EQ(axisStablePayloadFingerprint(baseline),
              axisStablePayloadFingerprint(changed));
}

TEST(AxisStreamContractTest, FingerprintCoversPayloadAndSidebandSignals)
{
    const axisData baseline = makeBeat();
    const std::vector<uint8_t> baselineFp =
        axisStablePayloadFingerprint(baseline);

    std::vector<std::pair<std::string, axisData>> cases;

    axisData dataChanged = baseline;
    dataChanged.tdata[17] ^= 0xff;
    cases.emplace_back("tdata", dataChanged);

    axisData keepChanged = baseline;
    keepChanged.tkeep ^= (1ULL << 9);
    cases.emplace_back("tkeep", keepChanged);

    axisData tidChanged = baseline;
    tidChanged.tid += 1;
    cases.emplace_back("tid", tidChanged);

    axisData destChanged = baseline;
    destChanged.tdest += 1;
    cases.emplace_back("tdest", destChanged);

    axisData userChanged = baseline;
    userChanged.tuser += 1;
    cases.emplace_back("tuser", userChanged);

    axisData lastChanged = baseline;
    lastChanged.tlast = !lastChanged.tlast;
    cases.emplace_back("tlast", lastChanged);

    for (const auto& testCase : cases) {
        EXPECT_NE(baselineFp, axisStablePayloadFingerprint(testCase.second))
            << testCase.first;
    }
}

TEST(AxisStreamContractTest, StalledStableBeatKeepsSameFingerprint)
{
    axisData previous = makeBeat();
    axisData current = previous;
    previous.tvalid = true;
    current.tvalid = true;

    EXPECT_EQ(axisStablePayloadFingerprint(previous),
              axisStablePayloadFingerprint(current));
}

} // anonymous namespace
} // namespace noc
} // namespace gem5
