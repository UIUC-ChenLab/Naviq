#ifndef __RESPONSE_INFO_HH__
#define __RESPONSE_INFO_HH__

#include <vector>
#include "base/types.hh"

namespace gem5
{
namespace noc
{

struct ResponseInfo {
    bool responseEnd = false;
    bool dataValid = false;
    enum class Type { NONE, READ, WRITE } type = Type::NONE;
    uint32_t id = 0;
    Cycles delay;
    uint32_t src = 0;
    // AXIS stuff
    std::vector<uint8_t> dataBytes;
    bool tlast = false;
    int tdest = 0;
};

} // namespace noc
} // namespace gem5

#endif
