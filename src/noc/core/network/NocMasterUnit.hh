#ifndef __NMU_HH
#define __NMU_HH

#include <unordered_map>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/flit.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "noc/monitors/NocTrafficMonitor.hh"
#include "noc/lib/axi/WriteStructs.hh"
#include "noc/core/network/rrob.hh"
#include "params/NocMasterUnit.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{



class NocMasterUnit : public NetworkInterface
{
    public:
        typedef NocMasterUnitParams Params;
        NocMasterUnit(const Params &p);
        virtual ~NocMasterUnit();

        // void init() override;
        virtual bool flitisizeMessage(MsgPtr msg_ptr, int vnet) override = 0; // implemented in children

        // bool depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit); // only mm nmu ever needs to depacketize a flit

        void addNode(std::vector<MessageBuffer *>& in, std::vector<MessageBuffer *>& out);
        void print(std::ostream & out) const override;
        
        virtual bool getAxiWReady(bool upstreamValid, axisMasterState upstreamState) { return false; }

    private:
    protected:
        uint64_t get256ByteAlignedAddr(uint64_t addr);
        void writeRespReadyHandler(uint8_t axi_id);
        uint8_t getLargestPossibleBeatSize(uint8_t num_bytes);
};

} // namespace gem5
}
}

#endif // NMU_HH
