#ifndef mmNocSlaveUnit_HH
#define mmNocSlaveUnit_HH

#include <list>
#include <vector>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/core/network/NocSlaveUnit.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "noc/core/network/NocNetworkInterface.hh"
#include "noc/core/network/nsu_types/MmWriteDataDepacketizer.hh"
#include "params/mmNocSlaveUnit.hh"
#include "sim/eventq.hh"
#include "sim/serialize.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{

/**
 * AXI-MM destination endpoint for the NoC.
 *
 * The NSU turns routed request flits back into endpoint AXI-MM transactions
 * and packetizes R/B responses for the return path.  AXI write data may cross
 * 16-byte NoC-flit boundaries, so assembly is keyed by NoC packet ID.  Read
 * requests are tracked per AXI ID so responses preserve per-ID ordering even
 * when different IDs interleave in the network.
 */
class mmNocSlaveUnit : public NocSlaveUnit
{
    public:
        typedef mmNocSlaveUnitParams Params;
        mmNocSlaveUnit(const Params &p);
        ~mmNocSlaveUnit() = default;

        static constexpr size_t NUM_SUPPORTED_AXI_IDS = 4;

        uint32_t S_DATA_WIDTH; // data width, in bytes, of connected slave tile


        
        bool flitisizeMessage(MsgPtr msg_ptr, int vnet) override;

        bool depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit) override;

        bool getAxiRReady(bool upstreamValid);
        bool getAxiBReady(bool upstreamValid, aximmSlaveState upstreamState);

        void print(std::ostream & out) const override;

        void serialize(CheckpointOut &cp) const override;
        void unserialize(CheckpointIn &cp) override;

    protected:
    private:

        // Flits from different packets can interleave at one NSU.  Never share
        // wide-beat assembly state between packet IDs.
        std::unordered_map<int, MmWriteDataAssemblyState> writeDataAssemblyByPacket;

        bool depacketizeReadRequestFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit);
        bool depacketizeWriteRequestFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit);
        bool depacketizeWriteDataFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit);
        bool enqueueReadRequestToTile(MsgPtr NPPMsg, MsgPtr tileMsg, Tick curTime);


        bool flitisizeWriteResponse(MsgPtr msg_ptr, aximmWResp axi_payload, OutputPort *oPort);
        bool flitisizeReadResponse(MsgPtr msg_ptr, OutputPort *oPort, int vnet);
        bool sendNWriteDataMsgs(std::vector<MsgPtr> Msgs);
        std::vector<MsgPtr> createNWriteDataMsgs(
                                    std::vector<aximmRWData> payloads,
                                    const std::vector<std::vector<int32_t>>& per_payload_debug_ids,
                                    int32_t fallback_debug_id);
        // One response assembly state per supported AXI ID.  A state is reset
        // only after its complete AXI read response has been emitted.
        struct ReadResponseState {
            bool active = false;
            
            // Accumulation buffer for incoming narrow beats → 64-byte NPP beats
            std::array<uint8_t, NPP_BEAT_SIZE> accumBuffer;
            uint64_t accumStrobe = 0;
            uint8_t accumOffset = 0;
            
            // NPP message being built
            std::shared_ptr<NocMemoryMsg> nppMsg;
            
            // Progress through the original AXI read request and emitted NPPs.
            int packet_id = 0;
            uint8_t num_flits = 0;
            uint16_t total_bytes_needed = 0;
            uint16_t bytes_received = 0;
            uint16_t bytes_sent = 0;
            
            // Original request info for proper data handling
            uint8_t original_beat_size = 0;
            uint32_t original_read_bytes = 0;
            bool auto_per_flit_gap = false;
            
            void reset() {
                active = false;
                accumBuffer.fill(0);
                accumStrobe = 0;
                accumOffset = 0;
                nppMsg = nullptr;
                original_read_bytes = 0;
                auto_per_flit_gap = false;
            }
        };
        
        ReadResponseState m_read_response_state[NUM_SUPPORTED_AXI_IDS];

        // BRAM timing penalty state, isolated by AXI ID.
        std::unordered_map<uint32_t, Tick> last_tail_flit_tick;
        std::unordered_map<uint32_t, bool> is_back_to_back;
        std::unordered_map<uint32_t, bool> bram_penalty_due;

        // Read-response pacing and B-response accounting.
        uint16_t m_read_flits_in_burst = 0;    // resets after cool-down
        uint16_t m_read_flits_total = 0;       // cumulative across NSU lifetime
        Tick     m_last_read_flit_inject_tick = 0;
        uint32_t m_read_response_gap_cycles = 1;
        uint32_t m_read_response_per_flit_gap_cycles = 0;
        uint64_t m_write_resp_total = 0;       // cumulative B responses emitted

        static constexpr uint16_t FLITS_PER_BURST = 4;
        static constexpr uint16_t STICKY_GAP_THRESHOLD = 16;
        static constexpr int      COOL_DOWN_CYCLES = 2;
        static constexpr uint16_t WRITE_RESP_STICKY_GAP_THRESHOLD = 16;
        class RequestTracker
        {
            public:
                static constexpr size_t MAX_SIZE = 32;
                RequestTracker() : m_size(0), m_num_ids(0) {}

                bool add(MsgPtr msg) {
                    // Each request flit is one NPP request and consumes one
                    // tracker entry.  Each AXI-ID queue is FIFO ordered.
                    if (getRemainingEntries()==0){
                        return false; // can't add entry, already at max size
                    }

                    MessagePayload payload = msg->getPayload();
                    aximmRWAddr* p = std::get_if<aximmRWAddr>(&payload);
                    if (p == nullptr) {
                        panic("NocSlaveUnit::RequestTracker::add: Unsupported payload type");
                    }
                    aximmRWAddr axi_payload = *p;

                    // Create a FIFO only for a newly observed AXI ID.
                    auto it = axiReads.find(axi_payload.id);
                    if (it == axiReads.end()) {
                        if(m_num_ids == 4)
                            return false; // can only have 4 ids in the read tracker
                        m_num_ids += 1;
                        axiReads[axi_payload.id] = std::list<MsgPtr>();
                    }
                    axiReads[axi_payload.id].push_back(msg);
                    m_size += 1;
                    return true;

                }

                // call these on last beat of read response burst, else just read
                MsgPtr readAndRemove(uint32_t r_id) {
                    // use r_id to find the corresponding read request in the map
                    auto it = axiReads.find(r_id);
                    if (it == axiReads.end()) {
                        panic("NocSlaveUnit::readTracker::readAndRemove: No read request found for id %d\n", r_id);
                    }

                    MsgPtr msg = it->second.front();
                    it->second.pop_front();
                    if (it->second.size() == 0) {
                        axiReads.erase(it);
                        m_num_ids--;
                    }
                    m_size -= 1;
                    return msg;
                }

                MsgPtr read(uint32_t r_id) {
                    // use r_id to find the corresponding read request in the map
                    auto it = axiReads.find(r_id);
                    if (it == axiReads.end()) {
                        panic("NocSlaveUnit::RequestTracker::read: No request found for id %d", r_id);
                    }

                    return it->second.front();
                }

                /** True if an outstanding request exists for this AXI ID. */
                bool has(uint32_t id) const {
                    auto it = axiReads.find(id);
                    return it != axiReads.end() && !it->second.empty();
                }

                bool isFull() const {
                    return m_size >= MAX_SIZE;
                }

                uint16_t getSize() const {
                    return m_size;
                }

                uint16_t getRemainingEntries() const {
                    return MAX_SIZE - m_size;
                }

                void serialize(CheckpointOut &cp) const;
                void unserialize(CheckpointIn &cp);

            private:
                uint16_t m_size;
                uint8_t m_num_ids;
                std::unordered_map<uint32_t, std::list<MsgPtr>> axiReads;
        };

        RequestTracker readTracker;
        RequestTracker writeTracker;

        bool internal_r_ready = true;

        struct DrainEntry {
            bool valid = false;
            uint32_t axi_id = 0;
            int drain_vnet = 0;
            NetworkInterface::OutputPort *oPort = nullptr;
            int vc = 0;
            bool slave_finished = false;
            MsgPtr original_req;
            Tick request_tick = 0;
        };

        void dequeueIntermediate();
        gem5::MemberEventWrapper<&mmNocSlaveUnit::dequeueIntermediate> dequeueIntermediateEvent;
        DrainEntry currDrainEntry;

};

} // namespace gem5
}
}

#endif // NSU_HH
