#ifndef __AXIMM_HANDLER_HH
#define __AXIMM_HANDLER_HH

#include "base/logging.hh"
#include "base/types.hh"
#include "debug/NocTiming.hh"

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/lib/interface/InterfaceTypes.hh"
#include "noc/core/interface/ProtocolHandler.hh"
#include "noc/core/network/nmu_types/mmNocMasterUnit.hh"
#include "noc/core/network/nsu_types/mmNocSlaveUnit.hh"
#include "noc/core/network/NocSlaveUnit.hh"
#include "noc/core/network/NocMessageBuffer.hh"

namespace gem5 {
namespace noc {

/**
 * AXI-MM protocol adapter at an endpoint/NoC boundary.
 *
 * It translates channel-specific AXI state (AR, AW, W, R, and B) to generic
 * CDC queue entries and NoC messages.  The paired NMU or NSU owns routing and
 * packetization; this handler owns ready/valid visibility and state transfer
 * across the endpoint and NoC clock domains.
 */
class AXIMMHandler : public ProtocolHandler {
    private:
        std::vector<ChannelDesc> channelMap;
        std::string role;

        void initChannelMap();

        MessageParams generateReadAddrToNoC(aximmRWAddr, Tick, NocSystem*);
        MessageParams generateWriteAddrToNoC(aximmRWAddr, Tick, NocSystem*);
        MessageParams generateWriteDataToNoC(aximmRWData, Tick, NocSystem*);
        MessageParams generateReadRespToNoC(aximmRWData, Tick, NocSystem*);
        MessageParams generateWriteRespToNoC(aximmWResp, Tick, NocSystem*);

        void checkTickAssertions(std::string);

        // Source-endpoint state (AR/AW/W toward an NMU, R/B returning).
        uint8_t write_delay;
        garnet::mmNocMasterUnit* nmu;
        garnet::mmNocSlaveUnit* nsu;

        // Destination-endpoint state (requests entering an NSU, R/B leaving).
        static constexpr size_t NUM_SUPPORTED_AXI_IDS = 4;
        // std::deque<MsgPtr> readBuffers[NUM_SUPPORTED_AXI_IDS];
        uint8_t readBeatSize[NUM_SUPPORTED_AXI_IDS] = {0};
        uint16_t nsu_read_base_delay;

    public:
        AXIMMHandler(const std::string& type);
        ~AXIMMHandler() override = default;

        void init();
        void setNMU(garnet::NetworkInterface*);
        void setNSU(garnet::NetworkInterface*);

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
        void fillTrafficMonitorParamsOnNodeCdcEnqueue(
            std::string channel, State* nodeState, MessageParams& out) override;
        void snapshotNodeStateForToCdcProbe(
            std::string channel, State* nodeState,
            State* interfaceState) override;
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
