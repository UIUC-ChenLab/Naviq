#ifndef NocSlaveUnit_HH
#define NocSlaveUnit_HH

#include <list>
#include <vector>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "params/NocSlaveUnit.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{

class NocSlaveUnit : public NetworkInterface
{
    public:
        // typedef NSUParams Params;
        NocSlaveUnit(const Params &p);
        ~NocSlaveUnit() = default;

        virtual bool depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit) override = 0;

        void addNode(std::vector<MessageBuffer *>& in, std::vector<MessageBuffer *>& out);
        void print(std::ostream & out) const override;

    protected:
        virtual bool depacketizeWriteDataFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit) = 0;

    private:

};

} // namespace gem5
}
}

#endif // NSU_HH
