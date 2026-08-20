#include "noc/core/network/NocMasterUnit.hh"
#include "debug/NocTiming.hh"
#include <bit> // For std::countl_zero

namespace gem5 {
namespace noc {
namespace garnet {


NocMasterUnit::NocMasterUnit(const Params &p) : NetworkInterface(p)
{
}

NocMasterUnit::~NocMasterUnit() = default;

// void
// NocMasterUnit::init()
// {
//     // Initialization code
// }

void
NocMasterUnit::addNode(std::vector<MessageBuffer *>& in,
                          std::vector<MessageBuffer *>& out)
{
    inNode_ptr = in;
    outNode_ptr = out;

    for (auto& it : in) {
        if (it != nullptr) {
            it->setConsumer(this, this);
        }
    }
}

uint8_t
NocMasterUnit::getLargestPossibleBeatSize(uint8_t num_bytes){

    if (num_bytes%64 == 0)
        return 6;
    else if (num_bytes%32 == 0)
        return 5;
    else if (num_bytes%16 == 0)
        return 4;
    else if (num_bytes%8 == 0)
        return 3;
    else if (num_bytes%4 == 0)
        return 2;
    else if (num_bytes%2 == 0)
        return 1;
    else
        panic("NocMasterUnit::getLargestPossibleBeatSize can't find beat size ");
}



uint64_t
NocMasterUnit::get256ByteAlignedAddr(uint64_t addr) {
    // Align the address to the next 256-byte boundary
    return (addr + 255) & ~255ULL;
}


void
NocMasterUnit::print(std::ostream& out) const
{
    out << "[NocMasterUnit " << m_id << "]";
}

}
}
}
