#ifndef __HBMArbiter_HH__
#define __HBMArbiter_HH__

#include "base/types.hh"
#include <vector>
#include <cstdint>
#include <unordered_map>

namespace gem5 {
namespace noc {

class tileNSU_HBM;

class HBMArbiter
{
    public:
        HBMArbiter(uint32_t issueIntervalCycles, uint64_t sharedBwMBps,
                   uint64_t nmuBwMBps);

        void addEndpoint(tileNSU_HBM *endpoint);
        bool grantFor(const tileNSU_HBM *endpoint, Tick now) const;
        void noteIssued(const tileNSU_HBM *endpoint, Tick now, Tick clockPeriod,
                        size_t requestBytes);
        uint32_t getIssueIntervalCycles() const { return issueIntervalCycles; }
        uint64_t getSharedBwMBps() const { return sharedBwMBps; }
        uint64_t getNmuBwMBps() const { return nmuBwMBps; }

    private:
        tileNSU_HBM *selectWinner(Tick now) const;

        std::vector<tileNSU_HBM*> endpoints;
        std::unordered_map<const tileNSU_HBM*, Tick> endpointNextGrantTick;
        size_t rrNextIndex = 0;
        Tick nextGrantTick = 0;
        uint32_t issueIntervalCycles = 1;
        uint64_t sharedBwMBps = 0;
        uint64_t nmuBwMBps = 0;
};

}} // end namespace
#endif
