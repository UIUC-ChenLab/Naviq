#ifndef __NOC_TRAFFIC_MONITOR_HH__
#define __NOC_TRAFFIC_MONITOR_HH__

#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <map>
#include <string> // Include string for potential future use or warnings
#include <iostream> // Include for ostream in printStats signature (optional)
#include <fstream>
#include <array>
#include <deque>
#include <unordered_map>

#include "base/types.hh" // For Tick, Addr, etc.
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "sim/core.hh"   // For MaxTick
#include "noc/lib/axi/AXITypes.hh"
#include "sim/serialize.hh"

namespace std {
    template <>
    struct hash<std::pair<gem5::ruby::NodeID, uint32_t>> {
        std::size_t operator()(const std::pair<gem5::ruby::NodeID, uint32_t>& k) const {
            // Combine the hashes of the individual members.
            // Hashing NodeID might require casting if it's not a basic type
            // with a standard hash. Assuming it's int-like or has std::hash.
            size_t h1 = std::hash<gem5::ruby::NodeID>{}(k.first);
            size_t h2 = std::hash<uint32_t>{}(k.second); // Assuming AxiID is hashable (like uint8_t)

            // Combine the hashes - a simple XOR shift combination is common
            // return h1 ^ (h2 << 1);
            // Or use a slightly more robust combination (like boost::hash_combine)
             size_t seed = 0;
             // Combine h1
             seed ^= h1 + 0x9e3779b9 + (seed << 6) + (seed >> 2);
             // Combine h2
             seed ^= h2 + 0x9e3779b9 + (seed << 6) + (seed >> 2);
             return seed;
        }
    };
} // namespace std

namespace gem5
{
namespace noc
{
namespace garnet
{

// Forward declaration to avoid heavy includes in header
class NocGarnetNetwork;


// Structure to hold info about in-flight transactions
struct TransactionInfo {
    Tick startTime = 0;
    uint64_t dataSize = 0; // Bytes expected/transferred
    // Optional metadata for AXIMM
    gem5::ruby::NodeID receiverID = -1; // destination NI receiving the transaction
};
struct PerNodeStats {
    Tick minLatency = MaxTick;
    Tick maxLatency = 0;
    Tick totalLatency = 0;
    uint64_t completedCount = 0;
    uint64_t totalBytes = 0;
    Tick currentStartTime= MaxTick;
    Tick currentEndTime= 0;
    Tick totalTime = 0;
    std::vector<Tick> latencies;

    // axis specific stats
    bool isAxis = false;
    Tick firstSenderTransactionTime = MaxTick;
    Tick lastSenderTransactionTime = 0;
    uint64_t senderBytesTransferred = 0;
    Tick firstReceiverTransactionTime = MaxTick;
    Tick lastReceiverTransactionTime = 0;
    uint64_t receiverBytesTransferred = 0;
    int receiverBandwidth = 0;
    int senderBandwidth = 0;

    // Default constructor
    PerNodeStats() = default;

    // Method to update stats for a completed transaction
    void recordCompletion(Tick latency, uint64_t dataSize, Tick startTime, Tick endTime, int num_outstanding, Tick period_ticks, bool increment=true, bool detailed_metrics=true);
    void recordAxisSenderBandwidth(Tick time, uint64_t dataSize, Tick period_ticks);
    void recordAxisReceiverBandwidth(Tick time, uint64_t dataSize, Tick period_ticks);

    // Default destructor
    ~PerNodeStats() = default;
};

class NocTrafficMonitor {
public:
    // Constructor
    NocTrafficMonitor();

    void init(Tick period_ticks, int num_nmu);

    // register noc interface with traffic monitor
    void registerNode(int nmu_index, std::string protocol, std::string role, int record_mode);

    // Provide network context so the monitor can derive receiver from address
    void setNetworkContext(NocGarnetNetwork* net) { m_net = net; }

    void setDetailedMetrics(bool b) { m_detailed_metrics = b; }

    // Protocol-agnostic data logging/checking: pass raw valid bytes for the beat
    void logWriteData(std::string protocol, gem5::ruby::NodeID initiatorID, const std::vector<uint8_t>& beatBytes);
    void checkWriteData(std::string protocol, gem5::ruby::NodeID initiatorID, const std::vector<uint8_t>& incomingBytes);

    // Called when AR or AW is sent from NMU/Initiator
    // Now derives id/cmd/size from payload
    void recordRequestStart(std::string protocol,
                            gem5::ruby::NodeID initiatorID,
                            Tick time,
                            const std::variant<aximmRWAddr, axisData>& payload_in);
    // Backward-compatible overload
    void recordRequestStart(gem5::ruby::NodeID initiatorID, uint32_t id, Tick time, uint64_t size_bytes, AximmCommand axiType);

    // Called when the LAST beat of Read Data (R) arrives at NMU (via RROB)
    void recordReadResponseEnd(gem5::ruby::NodeID initiatorID, uint32_t id, Tick time);

    // Called when Write Response (B) arrives at NMU
    void recordWriteResponseEnd(std::string protocol, uint32_t src_nmu, bool axisTlast, int axisTdest, uint64_t num_bytes, gem5::ruby::NodeID initiatorID, uint32_t id, Tick time);
    // Backward-compatible overload
    void recordWriteResponseEnd(gem5::ruby::NodeID initiatorID, uint32_t id, Tick time);

    // Called at simulation end to calculate and print stats
    // Takes final simulation time and the AXI clock period (in picoseconds)
    // for converting ticks to cycles.
    void printStats(Tick final_time);

    // Called at end of simulation to output csv files for graphing
    void outputCSV();

    // Per-cycle ready/valid CSV logging (mode == 2 only)
    void recordReadyValidSignals(Tick tick, std::string protocol,
                                 gem5::ruby::NodeID node_id,
                                 std::string role,
                                 std::string channel_name,
                                 State* currentState,
                                 State* nodeState);

    // --- Checkpoint helpers (per initiating NMU) ---
    // These are intentionally narrow: they let the NI save/restore monitor
    // bookkeeping that affects correctness checks (e.g. AXIS data matching).
    bool exportAxisWriteDataBuffer(gem5::ruby::NodeID initiatorID,
                                  std::vector<uint8_t>& out) const;
    void importAxisWriteDataBuffer(gem5::ruby::NodeID initiatorID,
                                  const std::vector<uint8_t>& in);

    bool exportAxisOutstandingWrites(gem5::ruby::NodeID initiatorID,
                                    std::vector<std::vector<TransactionInfo>>& out) const;
    void importAxisOutstandingWrites(gem5::ruby::NodeID initiatorID,
                                    const std::vector<std::vector<TransactionInfo>>& in);

    bool exportAxiOutstandingTxns(gem5::ruby::NodeID initiatorID,
                                 std::vector<std::vector<TransactionInfo>>& out_reads,
                                 std::vector<std::vector<TransactionInfo>>& out_writes) const;
    void importAxiOutstandingTxns(gem5::ruby::NodeID initiatorID,
                                 const std::vector<std::vector<TransactionInfo>>& in_reads,
                                 const std::vector<std::vector<TransactionInfo>>& in_writes);

    /// Read/write traffic-monitor checkpoint fields in the current SimObject section.
    /// `serializeEndpointCheckpoint` uses registered node metadata (protocol) internally.
    void serializeEndpointCheckpoint(CheckpointOut &cp,
                                      gem5::ruby::NodeID initiatorId) const;
    /// Stash TM checkpoint from the current NI section (static: no `NocNetwork` pointer
    /// is required during `CheckpointIn` restore).
    static void unserializeEndpointCheckpointStash(CheckpointIn &cp,
                                                   gem5::ruby::NodeID initiatorId);
    /// Apply data loaded by `unserializeEndpointCheckpointStash` after `registerNode`.
    void applyDeferredEndpointCheckpoint(gem5::ruby::NodeID initiatorId);

    /** Period between live deadlock polls (NoC ticks); 0 disables polling. */
    Tick outstandingPollPeriodTicks() const { return m_outstanding_poll_period_ticks; }

    /** Scan outstanding queues and warn on stuck transactions (call from periodic event). */
    void pollOutstandingTransactions(Tick now) const;

    /** Wall-clock spacing for idle CSV heartbeats (NoC ticks); 0 if disabled. */
    Tick csvHeartbeatPeriodTicks() const;

    /**
     * If a per-node traffic CSV stream has had no row for >= one heartbeat period,
     * append a 0-byte synthetic row (link_id=-1) at `now` so parsers see time advance.
     */
    void logCsvHeartbeatsIfIdle(Tick now);

    // Mapping helpers
    int getLocalNmuIndex(gem5::ruby::NodeID global_id) const;

private:
    static constexpr size_t NUM_SUPPORTED_AXI_IDS = 4;
    Tick m_period_ticks;
    double m_axi_clk_period_ps;


    enum class Protocol {
        AXI,
        AXIS
    };

    enum class Role {
        MASTER,
        SLAVE
    };

    struct MonitorValues {
        virtual ~MonitorValues() = default;
    };

    struct AXIMonitorValues : public MonitorValues {
        std::array<std::deque<TransactionInfo>, NUM_SUPPORTED_AXI_IDS> m_outstandingReads;
        std::array<std::deque<TransactionInfo>, NUM_SUPPORTED_AXI_IDS> m_outstandingWrites;

        AXIMonitorValues() = default;
    };

    struct AXISMonitorValues : public MonitorValues {
        // Per-tdest outstanding write transactions for AXI-Stream.
        // Index by tdest; grows dynamically when new tdest values are seen.
        std::vector<std::deque<TransactionInfo>> m_axisWrites;
        std::deque<uint8_t> m_writeDataBuffer;

        AXISMonitorValues() = default;
    };

    struct NodeInfo {
        Protocol protocol;
        Role role;
        MonitorValues* monitorValues;
        int recordMode;
        std::unordered_map<int, int> linkIDs; // maps axi ID/tdest # to link # |||||  NOTE: multiple AXI IDs can share the same link
        std::ofstream csv1;
        std::ofstream csv2;
        /** Sim tick of last row on csv1/csv2; MaxTick means no row yet for that stream. */
        Tick lastCsvActivityTick1 = MaxTick;
        Tick lastCsvActivityTick2 = MaxTick;
        // "Mode to record to CSV File:\n"
        // "\t0: No data points exported to CSV"
        // "\t1: Per transaction granularity exported to CSV (required for latency and BW plots)"
        // "\t2: Every cycle information exported to CSV (required for ready/valid % plots)"
    };

    
    // Internal data
    int m_num_nodes;
    int m_next_local_node = 0;
    std::unordered_map<int,int> m_global_to_local_nmu;
    std::vector<int> m_local_to_global_nmu;
    std::vector<NodeInfo> m_nodeInfo;
    int m_next_link_id = 0;
    // Shared ready/valid CSV (mode 2): opened once if any node requests it
    std::ofstream m_readyValidCsv;
    bool m_readyValidCsvInitialized = false;

    // Aggregate Statistics Variables
    Tick m_minReadLatency;
    Tick m_maxReadLatency;
    Tick m_totalReadLatency;
    uint64_t m_completedReads;
    uint64_t m_totalReadBytes;

    Tick m_minWriteLatency;
    Tick m_maxWriteLatency;
    Tick m_totalWriteLatency;
    uint64_t m_completedWrites;
    uint64_t m_totalWriteBytes;

    // Overall Timing Window
    Tick m_firstRequestTime;
    Tick m_lastResponseTime;

    std::vector<PerNodeStats> m_perNodeReadStats;
    std::vector<PerNodeStats> m_perNodeWriteStats;
    
    // Back-reference to the network for address-to-destination resolution
    NocGarnetNetwork* m_net = nullptr;
    
    bool m_detailed_metrics = true;

    // Global link-id mapping CSV (created once when any node registers with record_mode > 0)
    std::ofstream m_linkMapCsv;
    bool m_linkMapCsvInitialized = false;

    /** Warn when latency exceeds this many NoC clock cycles (see m_period_ticks). */
    static constexpr uint64_t kSuspiciousLatencyNoCCycles = 5000;

    Tick suspiciousLatencyThresholdTicks() const;
    void aximmHighLatencyWarning(const char* channel_label,
        gem5::ruby::NodeID nmu, uint32_t axi_id, Tick latency_ticks) const;
    void axisHighLatencyWarning(
        gem5::ruby::NodeID nmu, int tdest, Tick latency_ticks) const;
    void warnOutstandingTransactionsPastThreshold(Tick now) const;

    /** Sim-time spacing for live outstanding polling (set in init). */
    Tick m_outstanding_poll_period_ticks = 0;

    /**
     * Dedupe keys for red ERROR lines so periodic polling does not spam the terminal
     * for the same stuck transaction.
     */
    mutable std::unordered_set<uint64_t> m_outstandingDeadlockWarned;

    /** NoC cycles without a CSV row before emitting a 0-byte idle heartbeat. */
    static constexpr uint64_t kCsvHeartbeatIdleNoCCycles = 100;

    /**
     * Synthetic idle row: link_id=-1, num_bytes=0, end=0; AXIMM adds latency=0.
     * When include_outstanding_writes is true, append outstanding_writes for AXIMM
     * write CSV (csv2) time-series plots.
     */
    static void writeTrafficCsvIdleRow(std::ofstream& os, Protocol protocol,
                                     Tick at_tick,
                                     bool include_outstanding_writes = false,
                                     size_t outstanding_writes = 0);

    static size_t countAxiOutstandingWrites(const AXIMonitorValues *axi_vals);
    static int resolveOrCreateLinkId(NodeInfo &ni,
                                   gem5::ruby::NodeID initiator_id,
                                   int receiver_id,
                                   int &next_link_id,
                                   std::ofstream &link_map_csv,
                                   bool link_map_initialized);
};

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif // __NOC_TRAFFIC_MONITOR_HH__
