#ifndef sNocSlaveUnit_HH
#define sNocSlaveUnit_HH

#include <list>
#include <array>
#include <deque>
#include <fstream>
#include <map>
#include <tuple>
#include <unordered_map>
#include <vector>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/core/network/NocSlaveUnit.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "params/sNocSlaveUnit.hh"
#include "sim/serialize.hh"
#include "sim/eventq.hh"

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
 * endpoint-facing AXIS state. Hardware mode delivers independently arbitrated
 * 64-byte NoC chunks without waiting for TLAST. Receiving logic must use the
 * visible AXIS identifiers to reassemble interleaved frames. Whole-frame
 * reconstruction is an explicit synthetic compatibility option only.
 */
class sNocSlaveUnit : public NocSlaveUnit
{
    public:
        using Params = sNocSlaveUnitParams;
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

        using FrameKey = std::tuple<uint32_t, uint32_t, uint32_t>;
        struct Frame {
            std::deque<MsgPtr> beats;
            uint64_t storedBytes = 0;
        };
        // One reserved partial-frame slot per legal (source, TDEST, TID).
        // Storage is allocated lazily, but completed frames have a separate
        // bounded FIFO: they cannot consume a continuation's reservation.
        std::map<FrameKey, Frame> partialFrames;
        std::deque<Frame> completeFrames;
        const bool axisReassembleFrames;
        const uint32_t axisTidWidth;
        const uint64_t axisMaxFrameBytes;
        const uint32_t axisCompleteFrames;
        void drainFrame();
        MemberEventWrapper<&sNocSlaveUnit::drainFrame> drainFrameEvent;
        bool bufferFrameMsgs(std::vector<MsgPtr> messages);
        void serializeFrame(CheckpointOut &cp, const Frame &frame) const;
        Frame unserializeFrame(CheckpointIn &cp);
        std::ofstream beatCapture;
        uint64_t capturedBeats = 0;
        void captureBeat(const MsgPtr &message);

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
