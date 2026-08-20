#ifndef __TILENSU_HBM_HH__
#define __TILENSU_HBM_HH__

#include "noc/endpoints/memory/bram/BramEndpoint.hh"
#include "noc/core/interface/NocInterface.hh"
#include "noc/hbm/HBMArbiter.hh"
#include "params/tileNSU_HBM.hh"
#include "noc/core/network/NocSystem.hh"
#include "noc/core/network/NocSlaveUnit.hh"
#include "sim/sim_object.hh"

#include <unordered_map>
#include <map>
#include <deque>
#include <fstream>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace gem5
{
namespace noc{

class tileNSU_HBM : public BramEndpoint
{
    public:
        typedef tileNSU_HBMParams Params;
        tileNSU_HBM(const Params &p);
        ~tileNSU_HBM();

        RequestorID requestorId() const { return _requestorId; }
        Port& getPort(const std::string &if_name, PortID idx);

        // RequestPort noc_hbm_port;

        bool arbiter_ready_flag;   // a,rbiter says "you can send now"
        bool arbiter_valid_flag;   // tells arbiter "I have data"


        //main simulation loop (1 cycle)
        bool tick(int clockDomain) override;

        void updateTileNSU(aximmMasterState tileControllerState) override;
        State* getCurrentState(int portID) override;

        // FunctionalMemoryEndpoint interface overrides (forward to HBM/DDR)
        void functionalWrite(Addr addr, const uint8_t* data, size_t size) override;
        void functionalRead(Addr addr, uint8_t* data, size_t size) override;
        bool addressInRange(Addr addr) const override;

        
        //function that is triggered when recieve a new pkt from AXI
        void recvTimingResp(PacketPtr pkt);
        
        // function used by arbirter to set flag to true or false
        void updateReadyFlag(bool recvFlag);
        bool displayValidFlag();
        bool arbiterWantsIssue(Tick now) const;

    private:
        friend class NoC_SidePort;

        struct ControllerKey
        {
            uint32_t controllerId;
            uint32_t pseudoChannelId;

            bool operator==(const ControllerKey &other) const
            {
                return controllerId == other.controllerId &&
                       pseudoChannelId == other.pseudoChannelId;
            }
        };

        struct ControllerKeyHash
        {
            size_t operator()(const ControllerKey &key) const
            {
                return (static_cast<size_t>(key.controllerId) << 1) ^
                       static_cast<size_t>(key.pseudoChannelId);
            }
        };

        bool blockedOnRetry;
        bool needToRetry;
        PacketPtr retry_pkt;

        int axi_pack_read_id;
        int axi_pack_write_id;
        class NoC_SidePort : public RequestPort
        {
        private:
            /// The object that owns this object (tileNSU_HBM)
            tileNSU_HBM *owner;

            /// If we tried to send a packet and it was blocked, store it here
            PacketPtr blockedPacket;

        public:
            /**
             * Constructor. Just calls the superclass constructor.
             */
            NoC_SidePort(const std::string& name, tileNSU_HBM *owner) :
                RequestPort(name), owner(owner), blockedPacket(nullptr)
            { }

            /**
             * Send a packet across this port. This is called by the owner and
             * all of the flow control is hanled in this function.
             *
             * @param packet to send.
             */
            bool send_port_ptr();

        protected:
            /**
             * Receive a timing response from the response port.
             */
            bool recvTimingResp(PacketPtr pkt) override;

            /**
             * Called by the response port if sendTimingReq was called on this
             * request port (causing recvTimingReq to be called on the responder
             * port) and was unsuccesful.
             */
            void recvReqRetry() override;

            /**
             * Called to receive an address range change from the peer responder
             * port. The default implementation ignores the change and does
             * nothing. Override this function in a derived class if the owner
             * needs to be aware of the address ranges, e.g. in an
             * interconnect component like a bus.
             */
            void recvRangeChange() override;
        };

        NoC_SidePort noc_hbm_port;
        struct AxiSenderState : public Packet::SenderState
        {
            uint32_t axi_id;
            uint32_t HBM_id;
            uint8_t  size;    // AXI size (log2 bytes)
            uint8_t  len;     // AXI len (beats - 1)
            bool     is_read;
        };

        // PacketPtr HBM_pkt;
        RequestorID _requestorId;

        void generateBeatPayload(PacketPtr pkt, const AxiSenderState &s);
        aximmRWAddr getRequestPayload(const NocMemoryMsg* msg_ptr);

        void generateNextReadRespBeat();
        aximmRWData getNextAxiResponse();

        aximmWResp getNextWriteResponse();
        void generateNextWriteResp(const AxiSenderState &s);

        aximmSlaveState currentState;
        aximmSlaveState nextState;
        aximmMasterState tileControllerState;

        // void buffer_readRequestPacket(aximmRWAddr readCmdAXI);
        void buffer_writeRequestPacket(int HBM_id, aximmRWAddr writeCmdAXI, std::deque<aximmRWData> writeDataAXI);

        enum class MemCmdType {
            Read,
            Write
        };

        struct MemCmd {
            MemCmdType type;
            int HBM_id;
            aximmRWAddr addr;               // address, size, len, id
            std::vector<uint8_t> writeData; // only used for writes
            Tick eligibleTick = 0;
        };  

        struct ScheduledMemResp {
            Tick readyTick = 0;
            bool isRead = false;
            uint32_t axiId = 0;
            uint32_t hbmId = 0;
            uint8_t size = 0;
            uint8_t len = 0;
            std::vector<uint8_t> data;
        };

        struct BankState
        {
            bool rowValid = false;
            uint64_t openRow = 0;
            Tick readyTick = 0;
        };

        struct PseudoChannelState
        {
            std::vector<BankState> banks;
            Tick nextCmdTick = 0;
        };

        struct ControllerSchedulerState
        {
            uint32_t banksPerPseudoChannel = 16;
            uint32_t rowHitLatencyCycles = 4;
            uint32_t rowMissLatencyCycles = 18;
            uint32_t bankBusyCycles = 12;
            uint32_t cmdBusCycles = 2;
            bool closePage = false;
            std::vector<PseudoChannelState> pseudoChannels;
        };

        //store in order, our read/write packets 
        //actualy axi_mm data is stored in our readRequests/writeRequests queues
        //thus 
        std::deque<MemCmd> pendingCmds;

        //store write requests to serve && incoming write data
        std::unordered_map<uint32_t, std::pair<aximmRWAddr, std::deque<aximmRWData>>> writeRequests;
        std::deque<uint32_t> pendingWriteDataIds;

        // store read response_DATA that are ready to be sent to master
        // each unordered_map entry represents an AXIMM_ID, this allows us to access this in any order 
        // that we wish, this lets us model how we can respond to packets OOO if they are different ids
        // Within the unordered_map, there is a map of aximmRWData, maps are ordered so we will traverse 
        // this map in_order which models how for same ID transactions, it must complete in order
        std::unordered_map<int, std::map<int, std::deque<aximmRWData>>> readResponses;

        // store write response_PACKET that are ready to be sent to master
        // each unordered_map entry represents an AXIMM_ID, this allows us to access this in any order 
        // that we wish, this lets us model how we can respond to packets OOO if they are different ids
        // Within the unordered_map, there is a map of aximmRWData, maps are ordered so we will traverse 
        // this map in_order which models how for same ID transactions, it must complete in order
        std::unordered_map<int, std::map<int, aximmWResp>> writeResponses;

        // // store write responses that are ready to be sent to master
        // std::map<int, aximmWResp> writeResponses;

        //This map keeps track for each AXI_ID, what requests were made in order
        //this lets us respond to entry of unordered_map in whatever order we want (ie: differnt AXI ID, ooo handling)
        //however, within each map entry, we must handle the dequeu in order (ie: multiple requests wiht same ID must be handled in_order)
        //The dequeu stores a pair that holds the HBM_Id (so we know who we are responding to), and if its read(true) or a write(false)
        std::unordered_map<int, std::deque<int>> inOrderReadResp_Queue;

        //This map keeps track for each AXI_ID, what requests were made in order
        //this lets us respond to entry of unordered_map in whatever order we want (ie: differnt AXI ID, ooo handling)
        //however, within each map entry, we must handle the dequeu in order (ie: multiple requests wiht same ID must be handled in_order)
        //The dequeu stores a pair that holds the HBM_Id (so we know who we are responding to), and if its read(true) or a write(false)
        std::unordered_map<int, std::deque<int>> inOrderWriteResp_Queue;

        aximmRWAddr currWriteRequest; //store for printing purposes when receive write data to know what data is valid

        uint32_t hbmControllerId;
        uint32_t hbmPortId;
        uint32_t hbmPseudoChannelId;
        Addr hbmPseudoChannelBaseAddr;
        Addr hbmPseudoChannelSize;
        uint32_t readLatencyCycles;
        uint32_t writeLatencyCycles;
        uint32_t respLatencyCycles;
        uint32_t portQueueDepth;
        uint32_t maxOutstandingReads;
        uint32_t maxOutstandingWrites;
        uint32_t issueIntervalCycles;
        uint64_t sharedBwMBps;
        uint64_t nmuBwMBps;
        uint32_t banksPerPseudoChannel;
        uint32_t rowHitLatencyCycles;
        uint32_t rowMissLatencyCycles;
        uint32_t bankBusyCycles;
        uint32_t cmdBusCycles;
        bool closePagePolicy;
        size_t outstandingReadCmds;
        size_t outstandingWriteCmds;
        std::deque<ScheduledMemResp> scheduledResponses;
        std::shared_ptr<HBMArbiter> arbiter;
        std::shared_ptr<ControllerSchedulerState> schedulerState;
        int activeReadRespAxiId;
        int activeReadRespHbmId;
        int lastReadRespAxiId;
        int lastWriteRespAxiId;

        static std::unordered_map<ControllerKey, std::shared_ptr<HBMArbiter>, ControllerKeyHash> arbiterRegistry;
        static std::unordered_map<ControllerKey, std::shared_ptr<ControllerSchedulerState>, ControllerKeyHash> schedulerRegistry;

        Tick cyclesToTicks(uint32_t cycles) const;
        size_t bytesForAxiRequest(const aximmRWAddr &cmd) const;
        size_t hbmTransferUnits(const aximmRWAddr &cmd) const;
        bool canAcceptRead() const;
        bool canAcceptWriteAddr() const;
        bool canAcceptWriteData() const;
        bool frontCommandReady(Tick now) const;
        void registerWithArbiter();
        void registerScheduler();
        void serviceScheduledResponses(Tick now);
        void enqueueCompletedRead(const ScheduledMemResp &resp);
        void enqueueCompletedWrite(const ScheduledMemResp &resp);
        void clearActiveReadResponseIfDone();
        Addr relativePseudoChannelAddr(Addr addr) const;
        uint32_t decodeBankIndex(const aximmRWAddr &cmd) const;
        uint64_t decodeRowIndex(const aximmRWAddr &cmd) const;
        PseudoChannelState &schedulerPseudoChannelState();
        const PseudoChannelState &schedulerPseudoChannelState() const;
        Tick schedulerDelayFor(const MemCmd &cmd, Tick now) const;
        bool schedulerCanIssue(const MemCmd &cmd, Tick now) const;
        void noteSchedulerIssued(const MemCmd &cmd, Tick now);

        std::ofstream hbmTraceFile;
        bool hbmTraceCsvEnabled = false;
        bool hbmTraceCycleTouched = false;
        uint32_t hbmTraceTileIndexParam = 0;
        std::unordered_map<int, aximmRWAddr> hbmTraceAddrByHbmId;

        uint32_t
        hbmTraceTileId() const
        {
            return hbmTraceTileIndexParam == std::numeric_limits<uint32_t>::max()
                       ? static_cast<uint32_t>(_requestorId)
                       : hbmTraceTileIndexParam;
        }

        void
        hbmTraceInitFile(const std::string &path);

        void
        hbmTraceMark();

        void
        hbmTraceRow(Tick when,
                    const std::string &request_label,
                    const std::string &axi_type,
                    const std::string &event,
                    int data_bytes_neg1_if_empty,
                    Addr addr,
                    bool include_addr);

        void
        hbmTraceMaybeRefreshAtEndOfTick();

        bool hbmStatsCsvEnabled = false;
        uint32_t hbmStatsSampleGapCycles = 100;
        Tick hbmStatsNextSampleTick = 0;
        uint64_t hbmStatsCumulativeReadBytes = 0;
        uint64_t hbmStatsCumulativeWriteBytes = 0;
        uint64_t hbmStatsLastSampleReadBytes = 0;
        uint64_t hbmStatsLastSampleWriteBytes = 0;

        void
        hbmStatsInitFile(const std::string &path);

        void
        hbmStatsNoteIssue(const MemCmd &cmd);

        void
        hbmStatsMaybeSample(Tick now);

    protected:
        NocSystem* system;
        Tick simCycles;
    };
}
}

#endif
