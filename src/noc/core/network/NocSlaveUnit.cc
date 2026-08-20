#include "noc/core/network/NocSlaveUnit.hh"
#include "sim/eventq.hh"
#include "debug/NocTiming.hh"
#include <bit>


namespace gem5 {
namespace noc {
namespace garnet {


NocSlaveUnit::NocSlaveUnit(const Params &p) : NetworkInterface(p)
{ }

// void
// NSU::init()
// {
//     // Initialization code
// }

void
NocSlaveUnit::addNode(std::vector<MessageBuffer *>& in,
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

void
NocSlaveUnit::print(std::ostream& out) const
{
    out << "[NocSlaveUnit " << m_id << "]";
}

}
}
}
