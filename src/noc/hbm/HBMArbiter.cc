#include "noc/endpoints/memory/hbm/tileNSU_HBM.hh"
#include "noc/hbm/HBMArbiter.hh"
#include "base/logging.hh"
#include "sim/core.hh"
#include <algorithm>
#include <cmath>

namespace gem5 {
namespace noc {

namespace {
Tick
bwSpacingTicks(uint64_t bwMBps, size_t requestBytes)
{
    if (bwMBps == 0) {
        return 0;
    }

    const long double ticksPerSecond = gem5::sim_clock::Frequency;
    const long double bytesPerSecond =
        static_cast<long double>(bwMBps) * 1000.0L * 1000.0L;
    return static_cast<Tick>(std::ceil(
        (static_cast<long double>(std::max<size_t>(requestBytes, 1)) *
         ticksPerSecond) /
        bytesPerSecond));
}
} // anonymous namespace

HBMArbiter::HBMArbiter(uint32_t intervalCycles, uint64_t sharedBwMBps_,
                       uint64_t nmuBwMBps_)
    : issueIntervalCycles(intervalCycles),
      sharedBwMBps(sharedBwMBps_),
      nmuBwMBps(nmuBwMBps_)
{
}

void
HBMArbiter::addEndpoint(tileNSU_HBM *endpoint)
{
    if (!endpoint) {
        return;
    }
    for (auto *existing : endpoints) {
        if (existing == endpoint) {
            return;
        }
    }
    endpoints.push_back(endpoint);
    endpointNextGrantTick.emplace(endpoint, 0);
}

tileNSU_HBM *
HBMArbiter::selectWinner(Tick now) const
{
    if (now < nextGrantTick || endpoints.empty()) {
        return nullptr;
    }

    const size_t numEndpoints = endpoints.size();
    for (size_t checkOffset = 0; checkOffset < numEndpoints; ++checkOffset) {
        const size_t idx = (rrNextIndex + checkOffset) % numEndpoints;
        tileNSU_HBM *ep = endpoints[idx];
        const auto nextIt = endpointNextGrantTick.find(ep);
        const Tick endpointReadyTick =
            nextIt == endpointNextGrantTick.end() ? 0 : nextIt->second;
        if (ep && now >= endpointReadyTick && ep->arbiterWantsIssue(now)) {
            return ep;
        }
    }
    return nullptr;
}

bool
HBMArbiter::grantFor(const tileNSU_HBM *endpoint, Tick now) const
{
    return selectWinner(now) == endpoint;
}

void
HBMArbiter::noteIssued(const tileNSU_HBM *endpoint, Tick now, Tick clockPeriod,
                       size_t requestBytes)
{
    if (!endpoint || endpoints.empty()) {
        return;
    }

    constexpr uint64_t hbmBurstBytes = 32;
    Tick minBurstTicks = 0;
    if (issueIntervalCycles > 0) {
        minBurstTicks = std::max<Tick>(
            clockPeriod,
            static_cast<Tick>(((std::max<size_t>(requestBytes, 1) + hbmBurstBytes - 1) /
                               hbmBurstBytes) * issueIntervalCycles *
                              clockPeriod));
    }
    const Tick sharedSpacingTicks =
        std::max(minBurstTicks, bwSpacingTicks(sharedBwMBps, requestBytes));
    const Tick endpointSpacingTicks = bwSpacingTicks(nmuBwMBps, requestBytes);

    for (size_t i = 0; i < endpoints.size(); ++i) {
        if (endpoints[i] == endpoint) {
            rrNextIndex = (i + 1) % endpoints.size();
            nextGrantTick = now + sharedSpacingTicks;
            endpointNextGrantTick[endpoint] = now + endpointSpacingTicks;
            return;
        }
    }
}

}} // namespace gem5::noc
