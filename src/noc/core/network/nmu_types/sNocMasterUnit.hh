#ifndef __S_NMU_HH
#define __S_NMU_HH

#include <unordered_map>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/flit.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "noc/monitors/NocTrafficMonitor.hh"
#include "noc/lib/axi/WriteStructs.hh"
#include "noc/core/network/rrob.hh"
#include "params/sNocMasterUnit.hh"
#include "noc/core/network/NocMasterUnit.hh"
#include "noc/core/network/NocStreamMsg.hh"
#include "debug/NocTiming.hh"
#include "sim/eventq.hh"
#include "sim/serialize.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{

struct NPPInfo {
    bool valid = false;
    int flit_num = 0;
    int packet_id = 0;
    int vc = 0;
    NocRouteInfo route{};
    int num_flits = 0;
    MsgPtr message;
    NetworkInterface::OutputPort *oPort = nullptr;
    int last_flit_size_bytes = 0;
};

/**
 * AXIS source endpoint for the NoC.
 *
 * Accepted stream beats are buffered until packet boundaries (TLAST, TID, or
 * TDEST) permit an NPP to be emitted.  The buffer never produces a payload
 * larger than 256 bytes, even for a single large AXIS packet.
 */
class sNocMasterUnit : public NocMasterUnit
{
    public:
        typedef sNocMasterUnitParams Params;
        sNocMasterUnit(const Params &p);
        ~sNocMasterUnit() = default;

        bool flitisizeMessage(MsgPtr msg_ptr, int vnet) override;
        bool depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit) override { return false; }
        void enqueueBytes(int num_bytes) { inQueueBytes += num_bytes; }

        bool getAxiWReady(bool upstreamValid, axisMasterState upstreamState) override;

        void print(std::ostream & out) const override;

        void serialize(CheckpointOut &cp) const override;
        void unserialize(CheckpointIn &cp) override;

    private:
        void bufferHeadReadyHandler();

        axisWriteBuffer writeBuffer;

        void dequeueIntermediate();
        gem5::MemberEventWrapper<&sNocMasterUnit::dequeueIntermediate> dequeueIntermediateEvent;
        NPPInfo currNPPInfo;

        int inQueueBytes = 0;
};

} // namespace gem5
}
}

#endif // NMU_HH
