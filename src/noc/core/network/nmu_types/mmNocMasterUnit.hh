#ifndef __MM_NMU_HH
#define __MM_NMU_HH

#include <unordered_map>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/flit.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "noc/monitors/NocTrafficMonitor.hh"
#include "noc/lib/axi/WriteStructs.hh"
#include "noc/core/network/rrob.hh"
#include "params/mmNocMasterUnit.hh"
#include "noc/core/network/NocMasterUnit.hh"
#include "sim/eventq.hh"
#include "sim/serialize.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{



/**
 * AXI-MM source endpoint for the NoC.
 *
 * The NMU accepts AXI-MM AR/AW/W traffic from an endpoint through its
 * protocol handler, maps each request to a route and virtual channel, and
 * packetizes it into NoC payloads.  An AXI request may be split into several
 * 256-byte-or-smaller NPPs; WriteTracker combines their B responses back into
 * one AXI response, while the RROB preserves AXI-ID ordering for reads.
 *
 * The released interface supports AW-before-W association.  Do not add
 * W-before-AW behavior here without a pending-W ownership model and its
 * corresponding regressions.
 */
class mmNocMasterUnit : public NocMasterUnit
{
    public:
        typedef mmNocMasterUnitParams Params;
        mmNocMasterUnit(const Params &p);
        ~mmNocMasterUnit() = default;

        /// Convert an AXI-MM request accepted from the endpoint into NoC flits.
        bool flitisizeMessage(MsgPtr msg_ptr, int vnet) override;
        /// Reconstruct and retire a read or write response received from the NoC.
        bool depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit);
        void print(std::ostream & out) const override;

        /// Ready calculations include local ordering and write-buffer capacity.
        bool getAxiRAddrReady(bool upstreamValid, aximmMasterState upstreamState);
        bool getAxiWAddrReady(bool upstreamValid, aximmMasterState upstreamState);
        bool getAxiWReady(bool upstreamValid, aximmMasterState upstreamState);


        void rrobWriteCallback(AxiID axi_id);
        void msgReadCallback(const NocMessage* msg);

        void serialize(CheckpointOut &cp) const override;
        void unserialize(CheckpointIn &cp) override;

    private:
        ReadReorderBuffer* m_rrob;

        bool flitisizeWriteRequest(MsgPtr msg_ptr, aximmRWAddr axi_payload, NetworkInterface::OutputPort *oPort, gem5::ruby::NodeID destID, int vc);
        bool flitisizeReadRequest(MsgPtr msg_ptr, int vnet, aximmRWAddr axi_payload, NetworkInterface::OutputPort *oPort, gem5::ruby::NodeID destID, int vc);
        bool flitisizeWriteData(aximmRWData axi_payload, int32_t probe_debug_id = -1);
        /// Split an AXI-MM address request while preserving the 256-byte NPP bound.
        std::vector<aximmRWAddr> chopInto256BRequests(aximmRWAddr og_payload);
        void bufferHeadReadyHandler(aximmRWAddr nppRequest, std::array<aximmRWData, 4> nppData);
        bool processReadResponseFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit);
        bool processWriteResponseFlit(aximmWResp payload);
        void writeRespReadyHandler(uint8_t axi_id);

        bool handleReadDecErr(aximmRWAddr axi_payload);
        bool handleWriteDecErr(aximmRWAddr axi_payload);

        bool internal_ar_ready;
        bool internal_aw_ready;

        // Tracks outstanding writes per AXI ID and aggregates NPP responses
        // into the single B response visible to the endpoint.
        WriteTracker writeTracker;

        // Owns W bytes after their AW-created NPP entries exist. A head entry
        // is emitted only after its complete NPP payload is available.
        aximmWriteBuffer writeBuffer;

        NocTrafficMonitor trafficMonitor;

        // SSID serializes same-ID writes to one destination until the prior
        // response is complete.
        bool writeRequestSSIDDelayed;
        uint8_t numWriteBufferEntriesCurrRequest;

        Tick lastNppReadyTick; // computed ready time of the most recently processed NPP (for pipeline constraint)

        // Read-response pacing models endpoint-side service time after RROB
        // release; it does not relax RROB's per-ID ordering guarantee.
        uint64_t m_read_flits_processed = 0;
        Tick m_last_read_beat_tick = 0;
        int32_t m_read_response_delay_cycles = -1;
        static constexpr Tick NMU_COOL_DOWN_CYCLES = 4;
        static constexpr int NMU_SMALL_READ_BEAT_DELAY_CYCLES = 6;
        bool m_packetize_read_req_chunks = true;

        struct DrainEntry {
            bool valid = false;
            aximmWriteBufferEntry entry;
            Tick readyTick;
            int flit_id_to_send = 0;
            int packet_id;
            NocRouteInfo route;
            int total_flits;
            MsgPtr headMsg;
            MsgPtr bodyMsg;
        };

        void dequeueIntermediate();
        gem5::MemberEventWrapper<&mmNocMasterUnit::dequeueIntermediate> dequeueIntermediateEvent;
        DrainEntry currDrainEntry;

};

} // namespace gem5
}
}

#endif // NMU_HH
