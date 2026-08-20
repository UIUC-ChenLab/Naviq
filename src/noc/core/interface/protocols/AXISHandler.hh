#ifndef __AXIS_HANDLER_HH
#define __AXIS_HANDLER_HH

#include "base/logging.hh"
#include "base/types.hh"
#include "debug/NocTiming.hh"

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/core/interface/CDCQueue.hh"
#include "noc/lib/interface/InterfaceTypes.hh"
#include "noc/core/interface/ProtocolHandler.hh"
#include "noc/core/network/nmu_types/sNocMasterUnit.hh"
#include "noc/core/network/nsu_types/sNocSlaveUnit.hh"
#include "noc/core/network/NocMessageBuffer.hh"
#include <vector>

namespace gem5 {
namespace noc {

/**
 * AXIS protocol adapter at an endpoint/NoC boundary.
 *
 * The handler maps AXIS TVALID/TREADY handshakes and sideband fields into CDC
 * entries.  The stream NMU packetizes accepted beats and the stream NSU
 * reconstructs them.  TKEEP identifies valid bytes, while TID, TDEST, and
 * TLAST define the packet identity that must survive packetization.
 */
class AXISHandler : public ProtocolHandler {
    private:
        std::vector<ChannelDesc> channelMap;
        std::string role;

        // AXIS configuration
        uint32_t axisDataWidth = 512;
        uint32_t axisIdWidth = 6;
        uint32_t axisDestWidth = 4;

        void initChannelMap();

        MessageParams generateWriteDataToNoC(axisData, Tick, NocSystem*);


        // Source-endpoint state (AXIS beats sent toward an NMU).
        uint64_t write_delay;
        garnet::NocMasterUnit* nmu;

        // Destination-endpoint state (received AXIS beats toward the tile).
        static constexpr size_t NUM_SUPPORTED_AXI_IDS = 4;
        std::deque<MsgPtr> readBuffers[NUM_SUPPORTED_AXI_IDS];
        uint16_t m_delay;

        // keeping track variables
        Tick clock_period;
        Tick last_enqueue_tick;

    public:
        AXISHandler(const std::string& type, const std::vector<uint32_t>& protocol_parameters, Tick clockPeriod);
        ~AXISHandler() override = default;
        void init();
        void setNMU(garnet::NetworkInterface*);
        void setNSU(garnet::NetworkInterface*) override;

        std::unique_ptr<State> createNodeInterfaceState();
        std::unique_ptr<State> createNodeState();

        std::vector<ChannelDesc> getChannelMap();
        bool isRequestQueue(std::string);
        bool isTransactionReady(std::string, State*, State*) override;
        bool cdcEnqueueReady(std::string) override;
        bool cdcDequeueReady(std::string) override;
        bool cdcDequeueNiReady(
            std::string channel, State* interfaceState) override;
        bool channelBufferReady(MessageBuffer*) override;
        std::unique_ptr<State> cdcDequeueToNoC(std::string, Tick) override;
        ResponseInfo* optionalResponseInfoForCdcEnqueue(
            std::string, State*, MessageBuffer*, ResponseInfo* storage) override;
        bool currChannelValid(std::string, State*) override;
        void updateChannelNextState(std::string, State*, Tick) override;
        void setChannelNextValidFalse(
            std::string, std::unique_ptr<State>&, State*) override;
        void copyChannelFromCurrentState(
            std::string channel, State* nextState,
            const State* currentState) override;
        void cdcEnqueue(std::string, std::unique_ptr<State>, ResponseInfo*) override;
        void cdcDequeueToNode(State*, std::string, Tick) override;
        std::optional<ResponseInfo> peekResponseInfoFromCdcQueue(std::string) override;
        State* getStateFromChannelQueue(State*, std::string, MessageBuffer*) override;
        ResponseInfo getResponseInfoFromChannelQueue(State*, std::string, MessageBuffer*) override;

        MessageParams createMessage(std::string, State*, Tick, NocSystem*);
        std::optional<StreamObservation>
        observeStream(std::string channel, State* sendingState, State* receivingState) override;
        void fillTrafficMonitorParamsOnNodeCdcEnqueue(
            std::string channel, State* nodeState, MessageParams& out) override;
        void snapshotNodeStateForToCdcProbe(
            std::string channel, State* nodeState, State* interfaceState) override;
        void updateBookkeeping(std::string, MessageBuffer*);
        void tickBookkeeping(std::string, bool, int);
        void updateChannelNextReady(State*, std::string, State*, State*);

        void serializeInterfaceState(CheckpointOut &cp, const State *s) const override;
        std::unique_ptr<State> unserializeInterfaceState(CheckpointIn &cp) override;

        void fillNocIfProbeFromNode(
            State* towardNi, State* towardTile, ProbeData* out) override;
        void fillNocIfProbeFromCdcPeek(
            Tick t, State* interfaceState, ProbeData* out,
            bool& valid) override;

};

}}

#endif
