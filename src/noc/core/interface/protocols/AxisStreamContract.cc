#include "noc/core/interface/protocols/AxisStreamContract.hh"

namespace gem5
{
namespace noc
{
namespace
{

void
appendU64(std::vector<uint8_t>& out, uint64_t value)
{
    for (int i = 0; i < 8; ++i) {
        out.push_back(static_cast<uint8_t>((value >> (i * 8)) & 0xff));
    }
}

void
appendU32(std::vector<uint8_t>& out, uint32_t value)
{
    for (int i = 0; i < 4; ++i) {
        out.push_back(static_cast<uint8_t>((value >> (i * 8)) & 0xff));
    }
}

void
appendU8(std::vector<uint8_t>& out, uint8_t value)
{
    out.push_back(value);
}

} // anonymous namespace

std::vector<uint8_t>
axisStablePayloadFingerprint(const axisData& data)
{
    std::vector<uint8_t> payload;
    payload.reserve(data.tdata.size() + 25);
    payload.insert(payload.end(), data.tdata.begin(), data.tdata.end());
    appendU64(payload, data.tkeep);
    appendU32(payload, data.tid);
    appendU32(payload, data.tdest);
    appendU32(payload, data.tuser);
    appendU8(payload, static_cast<uint8_t>(data.tlast ? 1 : 0));
    return payload;
}

} // namespace noc
} // namespace gem5
