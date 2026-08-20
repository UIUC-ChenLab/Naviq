#ifndef sNocSlaveUnit_HH
#define sNocSlaveUnit_HH

#include <list>
#include <array>
#include <unordered_map>
#include <vector>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/core/network/NocSlaveUnit.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "params/sNocSlaveUnit.hh"
#include "sim/serialize.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{

/**
 * AXIS destination endpoint for the NoC.
 *
 * It reconstructs stream beats from incoming NoC flits and writes them to the
 * endpoint-facing AXIS state.  Assembly is packet-scoped because traffic from
 * separate source NMUs can interleave at a shared NSU.
 */
class sNocSlaveUnit : public NocSlaveUnit
{
    public:
        sNocSlaveUnit(const Params &p);
        ~sNocSlaveUnit() = default;

        bool depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit) override;
        bool flitisizeMessage(MsgPtr, int) override { return false; }

        void print(std::ostream & out) const override;

        void serialize(CheckpointOut &cp) const override;
        void unserialize(CheckpointIn &cp) override;

    protected:
    private:
        bool depacketizeWriteDataFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit);

        uint32_t S_DATA_WIDTH; // data width, in bits, of connected slave tile
        // AXIS flits from separate source NMUs may interleave at this NSU.
        // Keep wide-beat reconstruction isolated by network packet instead of
        // sharing one flit index and aggregate buffer across all traffic.
        std::unordered_map<int, std::array<uint8_t, 64>>
            depacketizeWriteDataAggregateByPacket;

        bool sendNWriteDataMsgs(std::vector<MsgPtr> Msgs);
        std::vector<MsgPtr> createNWriteDataMsgs(
            std::vector<axisData> payloads,
            uint32_t src_nmu,
            const std::vector<std::vector<int32_t>>& per_payload_debug_ids,
            int32_t fallback_debug_id);


};

} // namespace gem5
}
}

#endif // sNSU_HH
