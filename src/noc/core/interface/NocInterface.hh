#ifndef __NOCINTERFACE_HH__
#define __NOCINTERFACE_HH__

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/common/MachineID.hh"

#include "noc/lib/interface/InterfaceTypes.hh"
#include "noc/lib/debug/ProbeTypes.hh"
#include "noc/core/network/NocMessageBuffer.hh"
#include "noc/core/network/NocNetwork.hh"

#include "params/NocInterface.hh"

#include "sim/clocked_object.hh"
#include "sim/system.hh"
#include "sim/serialize.hh"

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>

namespace gem5 {
namespace noc {

class NocProbe;

class ProtocolHandler;
class NocNetwork;
class MessageBuffer;

class NocInterface : public ClockedObject, public gem5::ruby::Consumer
{
    public:
        typedef NocInterfaceParams Params;
        NocInterface(const Params &p);
        const std::string& getProtocol() const { return protocol; }
        const std::string& getRole() const { return role; }
        const std::string& getEndpointName() const { return endpointName; }

        //original functions
        void init();
        void initNocNetworkPtr(NocNetwork* netwk_ptr) { m_netwk_ptr = netwk_ptr; }
        NocNetwork* getNocNetworkPtr() { return m_netwk_ptr; }
        gem5::ruby::NodeID getVersion() const { return m_machineID.getNum(); }
        gem5::ruby::MachineType getType() const { return m_machineID.getType(); }
        gem5::ruby::MachineID getMachineID() const { return m_machineID; }
        gem5::RequestorID getRequestorId() const { return m_id; }
        const gem5::AddrRangeList &getAddrRanges() const { return addrRanges; }

        void initNetQueues();

        void tick();
        void update(State* inputNodeState) { nodeSideUpdate(inputNodeState); } // TODO: temp
        void nocSideUpdate();
        void nodeSideUpdate(State* inputNodeState);

        State* getCurrentState() { return currentState.get(); }
        std::string getRole() { return role; }
        std::string getProtocol() { return protocol; }

        void wakeup() override;
        void print(std::ostream & out) const;

        void serialize(CheckpointOut &cp) const override;
        void unserialize(CheckpointIn &cp) override;

        /** Optional NoC debug probe; may be shared by more than one interface. */
        NocProbe* getNocProbe() const { return m_nocProbe; }

    private:
        // input params for settings
        std::string protocol; // "AXIMM" / "AXIS"
        std::string role; // "Master" / "Slave"
        std::string endpointName; // NMU/NSU endpoint name
        std::vector<MessageBuffer*> buffers;

        // handlers for different setings
        std::unique_ptr<ProtocolHandler> protocolHandler;
        std::vector<ChannelDesc> channels;

        // AXI configuration
        std::vector<uint32_t> protocol_parameters;


        // helpers
        void recordTrafficMonitorForOutgoing(const MessageParams& params);
        void enqueueMessageToBuffer(MessageParams params, MessageBuffer* queue);

        // The address range to which the controller responds on the CPU side.
        const gem5::AddrRangeList addrRanges;

        NocNetDest downstreamDestinations;
        NocNetDest upstreamDestinations;

        std::unordered_map< gem5::ruby::MachineType,
                            gem5::AddrRangeMap
                                <gem5::ruby::MachineID, 3>> downstreamAddrMap;

        std::unique_ptr<State> currentState, nextState, nodeState;

        garnet::NetworkInterface* m_consumerNI;
        int m_record_mode;

    protected:

        // RequestorID used by some components of gem5.
        const gem5::ruby::NodeID m_version;
        const gem5::RequestorID m_id;

        bool m_is_blocking;

        gem5::ruby::MachineID m_machineID;

        NocSystem* m_noc_system = nullptr;
        NocNetwork* m_netwk_ptr;
        bool m_waiting_mem_retry;
        bool m_mem_ctrl_waiting_retry;

        NocProbe* m_nocProbe = nullptr;
        void nocProbeEvent(const char* hookId);
        void nocProbeEvent(const char* hookId, State* st);
        void nocProbeEvent(const char* hookId, const MsgPtr& msg);

        bool nocProbeSnoopMode() const;
        bool nocProbeComparatorMode() const;
        void nocProbeComparatorEvent(const char* hookId);
        void nocProbeComparatorEvent(const char* hookId, State* st);
        void nocProbeComparatorEvent(const char* hookId, const MsgPtr& msg);
        void nocProbeNodeSnooperEvent(State* inputNodeState);
        void nocProbeNocSnooperEvent();

        NocInterfaceAxisBeatData m_axisProbeNode{};
        NocInterfaceAxisBeatData m_axisProbeNoc{};
        NocInterfaceAximmBeatData m_aximmProbeNode{};
        NocInterfaceAximmBeatData m_aximmProbeNoc{};

        struct ProtocolChecker
        {
            bool hasPrev = false;
            bool prevValid = false;
            bool prevReady = false;
            std::optional<bool> prevLast;
            std::optional<uint64_t> prevDest;
            std::vector<uint8_t> prevPayload;

            bool inPacket = false;
            uint64_t packetDest = 0;

            void protocolCheck(Tick now, const std::string& ifName,
                                gem5::ruby::NodeID ifVersion,
                                const std::string& channel,
                                const StreamObservation& cur);
        };

        std::unordered_map<std::string, ProtocolChecker> m_streamCheckers;

        // bool serviceMemoryQueue() { return false; }
};

}} // end namespace
#endif
