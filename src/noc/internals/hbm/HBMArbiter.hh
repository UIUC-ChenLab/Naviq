#ifndef __HBMArbiter_HH__
#define __HBMArbiter_HH__

#include "sim/clocked_object.hh"
#include <vector>

namespace gem5 {
namespace noc {

class tile_HBM_NSU;

class HBMArbiter : public ClockedObject
{
    public:
        typedef HBMArbiterParams Params;
        HBMArbiter(const Params &p);

        void tick();
        void addEndpoint(tile_HBM_NSU *endpoint);

    private:
        std::vector<tile_HBM_NSU*> endpoints;
        size_t rrNextIndex = 0;
};

}} // end namespace
#endif
