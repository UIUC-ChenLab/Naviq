#include "noc/test/tile_HBM_NSU.hh"
#include "noc/internals/hbm/HBMArbiter.hh"
#include "base/logging.hh"

namespace gem5 {
namespace noc {

HBMArbiter::HBMArbiter(const Params &p) { }

void
HBMArbiter::addEndpoint(tile_HBM_NSU *endpoint)
{
    if (endpoints.size() >= 4) {
        panic("HBMArbiter::addEndpoint: cannot register more than 4 endpoints (attempted %zu)", endpoints.size() + 1);
    }
    endpoints.push_back(endpoint);
}

void
HBMArbiter::tick() {
    const size_t numEndpoints = endpoints.size();
    if (numEndpoints == 0) {
        return;
    }

    // find next valid endpoint in round-robin order
    int grantIndex = -1;
    for (size_t checkOffset = 0; checkOffset < numEndpoints; ++checkOffset) {
        const size_t idx = (rrNextIndex + checkOffset) % numEndpoints;
        tile_HBM_NSU* ep = endpoints[idx];
        if (ep && ep->displayValidFlag()) {
            grantIndex = static_cast<int>(idx);
            break;
        }
    }

    // assert ready to exactly one endpoint (if valid), deassert others
    for (size_t i = 0; i < numEndpoints; ++i) {
        endpoints[i]->updateReadyFlag(static_cast<int>(i) == grantIndex);
    }

    // advance round robin num after a grant
    if (grantIndex >= 0) {
        rrNextIndex = (static_cast<size_t>(grantIndex) + 1) % numEndpoints;
    }
}

}} // namespace gem5::noc


