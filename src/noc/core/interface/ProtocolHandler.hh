#ifndef __PROTOCOL_HANDLER_HH
#define __PROTOCOL_HANDLER_HH

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/lib/interface/InterfaceTypes.hh"
#include "noc/lib/debug/ProbeTypes.hh"

#include "noc/core/network/NocSystem.hh"
#include "noc/core/network/NocMessageBuffer.hh"
#include "sim/serialize.hh"
#include <memory>
#include <optional>
#include <vector>

namespace gem5 {
namespace noc {

/**
 * Protocol adapter between endpoint state and NoC messages.
 *
 * Implementations own protocol-specific ready/valid, ordering, and CDC state.
 * NocInterface calls the paired CDC methods instead of moving State objects
 * directly, which keeps clock-domain crossing and ownership explicit.
 */
class ProtocolHandler {
    public:
        virtual ~ProtocolHandler() = default;
        
        // factory function
        static std::unique_ptr<ProtocolHandler> create(const std::string &proto,
                                                    const std::string &role,
                                                    Tick clock_period,
                                                    const std::vector<uint32_t>& protocol_parameters = {});

        virtual void init() = 0;
        virtual void setNMU(garnet::NetworkInterface*) = 0;
        virtual void setNSU(garnet::NetworkInterface*) = 0;
        virtual std::vector<ChannelDesc> getChannelMap() = 0;
        virtual bool isTransactionReady(std::string, State*, State*) = 0;

        virtual bool cdcEnqueueReady(std::string) = 0;
        virtual bool cdcDequeueReady(std::string) = 0;
        /// Whether NMU/NSU can accept another beat from CDC toward the NoC this cycle.
        virtual bool cdcDequeueNiReady(
            std::string channel, State* interfaceState) {
            return true;
        }
        virtual bool channelBufferReady(MessageBuffer*) = 0;
        /// Pop one beat from CDC and return ownership (toward Ruby / NoC buffers).
        virtual std::unique_ptr<State> cdcDequeueToNoC(std::string, Tick) = 0;
        /// If this ingress path attaches ResponseInfo to the CDC entry, fill *storage
        /// and return storage; otherwise return nullptr (caller passes nullptr to cdcEnqueue).
        virtual ResponseInfo* optionalResponseInfoForCdcEnqueue(
            std::string, State*, MessageBuffer*, ResponseInfo* storage) = 0;
        virtual bool currChannelValid(std::string, State*) = 0;
        /// Apply one CDC dequeue into nextState for this channel (node-side path).
        virtual void updateChannelNextState(std::string channel, State* nextState, Tick tick) = 0;
        virtual void setChannelNextValidFalse(
            std::string, std::unique_ptr<State>& nextState, State* currentState) = 0;
        /** Copy only `channel`'s slice from current → next (preserves other channels). */
        virtual void copyChannelFromCurrentState(
            std::string channel, State* nextState, const State* currentState) = 0;
        virtual bool isRequestQueue(std::string) = 0;
        virtual void cdcEnqueue(std::string, std::unique_ptr<State>, ResponseInfo*) = 0;
        /// Merge one CDC beat into the node-side interface state (`nextState`).
        virtual void cdcDequeueToNode(State*, std::string, Tick) = 0;
        virtual std::optional<ResponseInfo> peekResponseInfoFromCdcQueue(std::string) = 0;
        virtual State* getStateFromChannelQueue(State*, std::string, MessageBuffer*) = 0;
        virtual ResponseInfo getResponseInfoFromChannelQueue(State*, std::string, MessageBuffer*) = 0;

        virtual MessageParams createMessage(std::string, State*, Tick, NocSystem*) = 0;

        // Optional: if a channel maps onto a stream-style ready/valid interface,
        // expose the signals/payload in a protocol-agnostic shape so NocInterface
        // can enforce generic stream contracts (stable payload on stall, etc.).
        virtual std::optional<StreamObservation>
        observeStream(std::string /*channel*/, State* /*sendingState*/, State* /*receivingState*/)
        {
            return std::nullopt;
        }

        /// Fill only `data` / `beatBytes` for NocTrafficMonitor when the node enqueues
        /// to the CDC on an output channel (dir==0). Must not mutate handler timing state.
        virtual void fillTrafficMonitorParamsOnNodeCdcEnqueue(
            std::string channel, State* nodeState, MessageParams& out) {}

        /// Optional: copy NI-side handshake / CDC acceptance onto node `State` for probes
        /// (e.g. before `noc_if.state.to_cdc`). Default does nothing.
        virtual void snapshotNodeStateForToCdcProbe(
            std::string /*channel*/, State* /*nodeState*/, State* /*interfaceState*/)
        {}

        virtual std::unique_ptr<State> createNodeInterfaceState() = 0;
        virtual std::unique_ptr<State> createNodeState() = 0;

        virtual void updateBookkeeping(std::string, MessageBuffer*) = 0;
        virtual void tickBookkeeping(std::string, bool, int) = 0;
        virtual void updateChannelNextReady(State*, std::string, State*, State*) = 0;

        virtual void serializeInterfaceState(CheckpointOut &cp, const State *s) const = 0;
        virtual std::unique_ptr<State> unserializeInterfaceState(CheckpointIn &cp) = 0;

        /** Tile + NI beat snapshot at end of nodeSideUpdate (snooper: noc_if.state.node_side). */
        virtual void fillNocIfProbeFromNode(
            State* towardNi, State* towardTile, ProbeData* out) = 0;

        /**
         * CDC peek at end of nocSideUpdate (snooper: noc_if.state.noc_side). If nothing
         * dequeues this cycle, valid=false and beat fields are inactive/zero.
         */
        virtual void fillNocIfProbeFromCdcPeek(
            Tick t, State* interfaceState, ProbeData* out, bool& valid) = 0;
};

}}
#endif
