#include "noc/monitors/NocTrafficMonitor.hh" // Include the header file

#include <limits> // For numeric_limits (used indirectly via MaxTick)
#include <iostream>
#include <iomanip> // For std::fixed, std::setprecision
#include <cstdio>  // For std::snprintf
#include <algorithm> // For std::min, std::max, std::all_of (if needed)
#include <cmath>     // For potential calculations if needed
#include <fstream>   // For CSV output
#include <filesystem> // For creating directories
#include <sstream>    // For zero-padded formatting

#include "base/logging.hh" // For warn(), fatal()
#include "base/str.hh"     // csprintf
#include "sim/core.hh"     // For SimClock::Frequency
#include "noc/core/network/NocGarnetNetwork.hh"
#include "base/trace.hh"
#include "debug/NocPacketFlow.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{

namespace
{

constexpr const char *kRuntimeTraceDir = "src/noc/out/csv";

struct DeferredEndpointCkpt {
    bool has_axis_write_buf = false;
    std::vector<uint8_t> axis_write_buf;
    bool has_axis_outstanding_writes = false;
    std::vector<std::vector<TransactionInfo>> axis_outstanding_writes;
    bool has_axi_outstanding_txns = false;
    std::vector<std::vector<TransactionInfo>> axi_outstanding_reads;
    std::vector<std::vector<TransactionInfo>> axi_outstanding_writes;
};

std::unordered_map<int, DeferredEndpointCkpt> endpointCkptStash;

} // namespace

size_t
NocTrafficMonitor::countAxiOutstandingWrites(const AXIMonitorValues *axi_vals)
{
    if (!axi_vals) {
        return 0;
    }
    size_t total = 0;
    for (const auto &queue : axi_vals->m_outstandingWrites) {
        total += queue.size();
    }
    return total;
}

int
NocTrafficMonitor::resolveOrCreateLinkId(NodeInfo &ni,
                                         gem5::ruby::NodeID initiator_id,
                                         int receiver_id,
                                         int &next_link_id,
                                         std::ofstream &link_map_csv,
                                         bool link_map_initialized)
{
    auto it = ni.linkIDs.find(receiver_id);
    if (it != ni.linkIDs.end()) {
        return it->second;
    }
    const int link = next_link_id++;
    ni.linkIDs[receiver_id] = link;
    if (link_map_initialized && link_map_csv.is_open()) {
        link_map_csv << link << "," << initiator_id << "," << receiver_id
                     << "\n";
        link_map_csv.flush();
    }
    return link;
}

// Constructor: Initialize statistics variables
NocTrafficMonitor::NocTrafficMonitor() :
    m_period_ticks(0), m_axi_clk_period_ps(0), m_num_nodes(0), /*m_num_nsu(0),*/
    m_minReadLatency(MaxTick), m_maxReadLatency(0), m_totalReadLatency(0),
    m_completedReads(0), m_totalReadBytes(0),
    m_minWriteLatency(MaxTick), m_maxWriteLatency(0), m_totalWriteLatency(0),
    m_completedWrites(0), m_totalWriteBytes(0),
    m_firstRequestTime(MaxTick), m_lastResponseTime(0)
{}

// Initialization function called after construction
void NocTrafficMonitor::init(Tick period_ticks, int num_nodes) {
    DPRINTF(NocPacketFlow, "NocTrafficMonitor::init(period_ticks=%lu, num_nodes=%d): clearing monitor state\n",
            (uint64_t)period_ticks, num_nodes);
    // Store the passed-in values
    m_period_ticks = period_ticks;
    m_num_nodes = num_nodes;
    m_next_local_node = 0;
    m_global_to_local_nmu.clear();
    m_local_to_global_nmu.assign(std::max(0, num_nodes), -1);

    // Calculate ps period (ensure Frequency is not zero)
    if (gem5::sim_clock::Frequency > 0 && m_period_ticks > 0) {
         m_axi_clk_period_ps = (double)m_period_ticks * 1.0e12 / gem5::sim_clock::Frequency;
    } else {
         warn("NocTrafficMonitor::init: Invalid clock period (%llu ticks) or frequency. Setting ps period to 0.",
              m_period_ticks);
         m_axi_clk_period_ps = 0.0;
         // Also invalidate period_ticks if it was zero?
         if (m_period_ticks <= 0) m_period_ticks = 0;
    }


    if (num_nodes > 0) {
        m_nodeInfo.clear(); // will resize dynamically based on global IDs
        m_perNodeReadStats.resize(num_nodes);
    } else {
        warn("NocTrafficMonitor::init: num_nodes is zero or negative (%d). Node info vector will be empty.", num_nodes);
        m_perNodeReadStats.clear();
    }

    m_outstandingDeadlockWarned.clear();
    if (m_period_ticks > 0) {
        // Poll every 500 NoC cycles so stuck work is reported during simulation
        // (before / between 5000-cycle age threshold crossings).
        m_outstanding_poll_period_ticks = 500 * m_period_ticks;
    } else {
        m_outstanding_poll_period_ticks = 0;
    }
}

void NocTrafficMonitor::registerNode(int node_index, std::string protocol, std::string role, int record_mode) {
    if (node_index < 0) {
        panic("NocTrafficMonitor::registerNode: negative node_index %d", node_index);
        return;
    }
    if (role == "Master") {
        // assign a local NMU index
        if (!m_global_to_local_nmu.count(node_index)) {
            if (m_next_local_node >= m_num_nodes) {
                panic("NocTrafficMonitor::registerNode: too many nodes registered (%d >= %d)", m_next_local_node, m_num_nodes);
            }
            m_global_to_local_nmu[node_index] = m_next_local_node;
            if (m_next_local_node >= static_cast<int>(m_local_to_global_nmu.size())) {
                m_local_to_global_nmu.resize(m_next_local_node + 1, -1);
            }
            m_local_to_global_nmu[m_next_local_node] = node_index;
            m_next_local_node++;
        }
        // resolve local index for this global node index
        int local = getLocalNmuIndex(node_index);
        if (local < 0) {
            panic("NocTrafficMonitor::registerNode: failed to resolve local index for global %d", node_index);
        }
        if (local >= static_cast<int>(m_nodeInfo.size())) {
            m_nodeInfo.resize(local + 1);
        }
        m_perNodeWriteStats.push_back(PerNodeStats());
        m_nodeInfo[local].recordMode = record_mode;
        if (protocol == "AXIMM") {
            m_nodeInfo[local].protocol = Protocol::AXI;
            m_nodeInfo[local].monitorValues = new AXIMonitorValues();
        } else if (protocol == "AXIS") {
            m_nodeInfo[local].protocol = Protocol::AXIS;
            m_nodeInfo[local].monitorValues = new AXISMonitorValues();
        } else {
            panic("NocTrafficMonitor::registerNode: Unsupported protocol %s", protocol.c_str());
        }
        m_nodeInfo[local].role = Role::MASTER;

        // create per-link CSV files
        if (record_mode > 0) {
            std::error_code fs_ec;
            std::filesystem::create_directories(kRuntimeTraceDir, fs_ec);
            if (fs_ec) {
                warn("Monitor: Failed to create directory %s: %s", kRuntimeTraceDir, fs_ec.message().c_str());
            }
            std::string suffix1, suffix2;
            if (protocol == "AXIMM") {
                suffix1 = "_read";
                suffix2 = "_write";
            } else {
                suffix1 = "_receiver";
                suffix2 = "_sender";
            }
            std::ostringstream node_id_ss;
            node_id_ss << std::setw(2) << std::setfill('0') << node_index;
            const std::string node_id_str = node_id_ss.str();
            const std::string base_dir = kRuntimeTraceDir;
            const std::string file1 = base_dir + "/nmu_" + node_id_str + "_" + protocol + suffix1 + ".csv";
            const std::string file2 = base_dir + "/nmu_" + node_id_str + "_" + protocol + suffix2 + ".csv";

            auto &ni = m_nodeInfo[local];
            ni.csv1.open(file1, std::ios::out | std::ios::trunc);
            if (!ni.csv1.is_open()) {
                warn("Monitor: Failed to open %s for writing", file1.c_str());
            } else {
                ni.csv1 << "ms,link_id,num_bytes,end";
                if (protocol == "AXIMM") ni.csv1 << ",latency";
                ni.csv1 << "\n";
                ni.csv1.flush();
            }
            ni.csv2.open(file2, std::ios::out | std::ios::trunc);
            if (!ni.csv2.is_open()) {
                warn("Monitor: Failed to open %s for writing", file2.c_str());
            } else {
                ni.csv2 << "ms,link_id,num_bytes,end";
                if (protocol == "AXIMM") {
                    ni.csv2 << ",latency,outstanding_writes";
                }
                ni.csv2 << "\n";
                ni.csv2.flush();
            }

            if (record_mode == 2 && !m_readyValidCsvInitialized) {
                const std::string file3 = base_dir + "/ready_valid.csv";
                m_readyValidCsv.open(file3, std::ios::out | std::ios::trunc);
                if (!m_readyValidCsv.is_open()) {
                    warn("Monitor: Failed to open %s for writing", file3.c_str());
                } else {
                    m_readyValidCsv << "ms,node_id,protocol,role,channel_name,ready,valid\n";
                    m_readyValidCsvInitialized = true;
                }
            }

            // Create global link id mapping CSV once
            if (!m_linkMapCsvInitialized) {
                const std::string mapFile = base_dir + "/link_id_mapping.csv";
                m_linkMapCsv.open(mapFile, std::ios::out | std::ios::trunc);
                if (!m_linkMapCsv.is_open()) {
                    warn("Monitor: Failed to open %s for writing", mapFile.c_str());
                } else {
                    m_linkMapCsv << "link_id,nmu_id,nsu_id\n";
                    m_linkMapCsvInitialized = true;
                }
            }
        }

    } else if (role == "Slave") {
        panic("NocTrafficMonitor::registerNode: adding slave node not yet supported");
    } else {
        panic("NocTrafficMonitor::registerNode: Unsupported role %s", role.c_str());
    }
}

int NocTrafficMonitor::getLocalNmuIndex(gem5::ruby::NodeID global_id) const {
    auto it = m_global_to_local_nmu.find(static_cast<int>(global_id));
    if (it == m_global_to_local_nmu.end()) return -1;
    return it->second;
}

Tick
NocTrafficMonitor::suspiciousLatencyThresholdTicks() const
{
    if (m_period_ticks == 0) {
        return MaxTick;
    }
    return static_cast<Tick>(kSuspiciousLatencyNoCCycles) * m_period_ticks;
}

void
NocTrafficMonitor::aximmHighLatencyWarning(const char* channel_label,
    gem5::ruby::NodeID nmu, uint32_t axi_id, Tick latency_ticks) const
{
    const Tick thr = suspiciousLatencyThresholdTicks();
    if (thr == MaxTick || latency_ticks <= thr) {
        return;
    }
    const uint64_t noc_cycles =
        m_period_ticks ? (latency_ticks / m_period_ticks) : 0ULL;
    std::cout << "\033[31mMonitor: WARNING: suspiciously long AXIMM "
              << channel_label << " response latency: NMU " << static_cast<int>(nmu)
              << " AXI id " << static_cast<int>(axi_id) << ", "
              << noc_cycles << " NoC cycles (" << latency_ticks << " ticks)"
              << "\033[0m" << std::endl;
}

void
NocTrafficMonitor::axisHighLatencyWarning(
    gem5::ruby::NodeID nmu, int tdest, Tick latency_ticks) const
{
    if (latency_ticks == MaxTick) {
        return;
    }
    const Tick thr = suspiciousLatencyThresholdTicks();
    if (thr == MaxTick || latency_ticks <= thr) {
        return;
    }
    const uint64_t noc_cycles =
        m_period_ticks ? (latency_ticks / m_period_ticks) : 0ULL;
    std::cout << "\033[31mMonitor: WARNING: suspiciously long AXIS "
              << "master-to-slave latency (tlast): NMU " << static_cast<int>(nmu)
              << " tdest " << tdest << ", " << noc_cycles << " NoC cycles ("
              << latency_ticks << " ticks)"
              << "\033[0m" << std::endl;
}

void
NocTrafficMonitor::warnOutstandingTransactionsPastThreshold(Tick now) const
{
    const Tick thr = suspiciousLatencyThresholdTicks();
    if (thr == MaxTick) {
        return;
    }

    const auto warn_one = [&](int local_idx, gem5::ruby::NodeID global_nmu,
                              uint8_t channel_kind, const char* proto_tag,
                              const char* rw_tag, uint32_t id_or_tdest,
                              const TransactionInfo& info) {
        if (now < info.startTime) {
            return;
        }
        const Tick age = now - info.startTime;
        if (age <= thr) {
            return;
        }
        uint64_t key = (uint64_t)(uint32_t)local_idx;
        key ^= (uint64_t)info.startTime * 0x9e3779b97f4a7c15ULL;
        key ^= (uint64_t)id_or_tdest << 20;
        key ^= (uint64_t)channel_kind << 28;
        if (!m_outstandingDeadlockWarned.insert(key).second) {
            return;
        }
        const uint64_t age_cyc = m_period_ticks ? (age / m_period_ticks) : 0ULL;
        std::cout << "\033[31mMonitor: WARNING: " << proto_tag
                  << " transaction still outstanding (age > " << kSuspiciousLatencyNoCCycles
                  << " NoC cycles): NMU " << static_cast<int>(global_nmu) << " " << rw_tag
                  << " " << static_cast<int>(id_or_tdest) << ", age " << age_cyc
                  << " NoC cycles (" << age << " ticks) startTime=" << info.startTime
                  << " now=" << now
                  << "\033[0m" << std::endl;
    };

    for (int local = 0; local < static_cast<int>(m_nodeInfo.size()); ++local) {
        const int global = (local < static_cast<int>(m_local_to_global_nmu.size()))
            ? m_local_to_global_nmu[local]
            : -1;
        if (global < 0) {
            continue;
        }
        const gem5::ruby::NodeID gnode = static_cast<gem5::ruby::NodeID>(global);
        const auto& ni = m_nodeInfo[local];

        if (ni.protocol == Protocol::AXI) {
            auto* av = static_cast<AXIMonitorValues*>(ni.monitorValues);
            if (!av) {
                continue;
            }
            for (uint32_t id = 0; id < NUM_SUPPORTED_AXI_IDS; ++id) {
                for (const auto& info : av->m_outstandingReads[id]) {
                    warn_one(local, gnode, 0, "AXIMM", "AR/R id", id, info);
                }
                for (const auto& info : av->m_outstandingWrites[id]) {
                    warn_one(local, gnode, 1, "AXIMM", "AW/W/B id", id, info);
                }
            }
        } else if (ni.protocol == Protocol::AXIS) {
            auto* av = static_cast<AXISMonitorValues*>(ni.monitorValues);
            if (!av) {
                continue;
            }
            for (size_t tdest = 0; tdest < av->m_axisWrites.size(); ++tdest) {
                for (const auto& info : av->m_axisWrites[tdest]) {
                    warn_one(local, gnode, 2, "AXIS", "tdest",
                        static_cast<uint32_t>(tdest), info);
                }
            }
        }
    }
}

void
NocTrafficMonitor::pollOutstandingTransactions(Tick now) const
{
    warnOutstandingTransactionsPastThreshold(now);
}

bool
NocTrafficMonitor::exportAxisWriteDataBuffer(gem5::ruby::NodeID initiatorID,
                                            std::vector<uint8_t>& out) const
{
    out.clear();
    const int local = getLocalNmuIndex(initiatorID);
    if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
        return false;
    }
    if (m_nodeInfo[local].protocol != Protocol::AXIS) {
        return false;
    }
    auto* axisVals = static_cast<AXISMonitorValues*>(m_nodeInfo[local].monitorValues);
    if (!axisVals) {
        return false;
    }
    out.assign(axisVals->m_writeDataBuffer.begin(), axisVals->m_writeDataBuffer.end());
    return true;
}

void
NocTrafficMonitor::importAxisWriteDataBuffer(gem5::ruby::NodeID initiatorID,
                                            const std::vector<uint8_t>& in)
{
    const int local = getLocalNmuIndex(initiatorID);
    if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
        // The NI should only call this after registerNode(), so treat as fatal.
        panic("NocTrafficMonitor::importAxisWriteDataBuffer: AXIS node %d not registered",
              (int)initiatorID);
    }
    if (m_nodeInfo[local].protocol != Protocol::AXIS) {
        panic("NocTrafficMonitor::importAxisWriteDataBuffer: node %d is not AXIS",
              (int)initiatorID);
    }
    auto* axisVals = static_cast<AXISMonitorValues*>(m_nodeInfo[local].monitorValues);
    if (!axisVals) {
        panic("NocTrafficMonitor::importAxisWriteDataBuffer: missing AXISMonitorValues");
    }
    axisVals->m_writeDataBuffer.clear();
    for (uint8_t b : in) {
        axisVals->m_writeDataBuffer.push_back(b);
    }
}

bool
NocTrafficMonitor::exportAxisOutstandingWrites(
    gem5::ruby::NodeID initiatorID,
    std::vector<std::vector<TransactionInfo>>& out) const
{
    out.clear();
    const int local = getLocalNmuIndex(initiatorID);
    if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
        return false;
    }
    if (m_nodeInfo[local].protocol != Protocol::AXIS) {
        return false;
    }
    auto* axisVals = static_cast<AXISMonitorValues*>(m_nodeInfo[local].monitorValues);
    if (!axisVals) {
        return false;
    }

    out.resize(axisVals->m_axisWrites.size());
    for (size_t tdest = 0; tdest < axisVals->m_axisWrites.size(); ++tdest) {
        const auto& dq = axisVals->m_axisWrites[tdest];
        out[tdest].assign(dq.begin(), dq.end());
    }
    return true;
}

void
NocTrafficMonitor::importAxisOutstandingWrites(
    gem5::ruby::NodeID initiatorID,
    const std::vector<std::vector<TransactionInfo>>& in)
{
    const int local = getLocalNmuIndex(initiatorID);
    if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
        panic("NocTrafficMonitor::importAxisOutstandingWrites: AXIS node %d not registered",
              (int)initiatorID);
    }
    if (m_nodeInfo[local].protocol != Protocol::AXIS) {
        panic("NocTrafficMonitor::importAxisOutstandingWrites: node %d is not AXIS",
              (int)initiatorID);
    }
    auto* axisVals = static_cast<AXISMonitorValues*>(m_nodeInfo[local].monitorValues);
    if (!axisVals) {
        panic("NocTrafficMonitor::importAxisOutstandingWrites: missing AXISMonitorValues");
    }

    axisVals->m_axisWrites.clear();
    axisVals->m_axisWrites.resize(in.size());
    for (size_t tdest = 0; tdest < in.size(); ++tdest) {
        auto& dq = axisVals->m_axisWrites[tdest];
        dq.clear();
        for (const auto& ti : in[tdest]) {
            dq.push_back(ti);
        }
    }
}

bool
NocTrafficMonitor::exportAxiOutstandingTxns(
    gem5::ruby::NodeID initiatorID,
    std::vector<std::vector<TransactionInfo>>& out_reads,
    std::vector<std::vector<TransactionInfo>>& out_writes) const
{
    out_reads.clear();
    out_writes.clear();
    const int local = getLocalNmuIndex(initiatorID);
    if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
        return false;
    }
    if (m_nodeInfo[local].protocol != Protocol::AXI) {
        return false;
    }
    auto* axiVals = static_cast<AXIMonitorValues*>(m_nodeInfo[local].monitorValues);
    if (!axiVals) {
        return false;
    }

    out_reads.resize(NUM_SUPPORTED_AXI_IDS);
    out_writes.resize(NUM_SUPPORTED_AXI_IDS);
    for (size_t id = 0; id < NUM_SUPPORTED_AXI_IDS; ++id) {
        out_reads[id].assign(axiVals->m_outstandingReads[id].begin(),
                             axiVals->m_outstandingReads[id].end());
        out_writes[id].assign(axiVals->m_outstandingWrites[id].begin(),
                              axiVals->m_outstandingWrites[id].end());
    }
    return true;
}

void
NocTrafficMonitor::importAxiOutstandingTxns(
    gem5::ruby::NodeID initiatorID,
    const std::vector<std::vector<TransactionInfo>>& in_reads,
    const std::vector<std::vector<TransactionInfo>>& in_writes)
{
    const int local = getLocalNmuIndex(initiatorID);
    if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
        panic("NocTrafficMonitor::importAxiOutstandingTxns: AXIMM node %d not registered",
              (int)initiatorID);
    }
    if (m_nodeInfo[local].protocol != Protocol::AXI) {
        panic("NocTrafficMonitor::importAxiOutstandingTxns: node %d is not AXIMM",
              (int)initiatorID);
    }
    auto* axiVals = static_cast<AXIMonitorValues*>(m_nodeInfo[local].monitorValues);
    if (!axiVals) {
        panic("NocTrafficMonitor::importAxiOutstandingTxns: missing AXIMonitorValues");
    }

    // Clear then refill each supported AXI ID.
    for (size_t id = 0; id < NUM_SUPPORTED_AXI_IDS; ++id) {
        axiVals->m_outstandingReads[id].clear();
        axiVals->m_outstandingWrites[id].clear();
    }

    const size_t n_ids = std::min({in_reads.size(), in_writes.size(), NUM_SUPPORTED_AXI_IDS});
    for (size_t id = 0; id < n_ids; ++id) {
        for (const auto& ti : in_reads[id]) {
            axiVals->m_outstandingReads[id].push_back(ti);
        }
        for (const auto& ti : in_writes[id]) {
            axiVals->m_outstandingWrites[id].push_back(ti);
        }
    }
}

void
NocTrafficMonitor::serializeEndpointCheckpoint(CheckpointOut &cp,
                                              gem5::ruby::NodeID initiatorId) const
{
    bool tm_axis_has_write_buf = false;
    bool tm_axis_has_outstanding = false;
    bool tm_axi_has_outstanding = false;
    std::vector<uint8_t> tm_axis_write_buf;
    std::vector<std::vector<TransactionInfo>> tm_axis_outstanding;
    std::vector<std::vector<TransactionInfo>> tm_axi_out_reads;
    std::vector<std::vector<TransactionInfo>> tm_axi_out_writes;

    tm_axis_has_write_buf =
        exportAxisWriteDataBuffer(initiatorId, tm_axis_write_buf);
    tm_axis_has_outstanding =
        exportAxisOutstandingWrites(initiatorId, tm_axis_outstanding);
    tm_axi_has_outstanding =
        exportAxiOutstandingTxns(initiatorId, tm_axi_out_reads, tm_axi_out_writes);

    ::gem5::paramOut(cp, "tm_axis_has_write_buf", tm_axis_has_write_buf);
    ::gem5::paramOut(cp, "tm_axis_has_outstanding_writes", tm_axis_has_outstanding);
    ::gem5::paramOut(cp, "tm_axi_has_outstanding_txns", tm_axi_has_outstanding);

    if (tm_axis_has_write_buf) {
        ::gem5::arrayParamOut(cp, "tm_axis_write_buf", tm_axis_write_buf);
    }
    if (tm_axis_has_outstanding) {
        ::gem5::paramOut(cp, "tm_axis_outstanding_tdest_n",
                        (uint64_t)tm_axis_outstanding.size());
        for (size_t tdest = 0; tdest < tm_axis_outstanding.size(); ++tdest) {
            const auto &vec = tm_axis_outstanding[tdest];
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("tm_axis_tdest_%d", (int)tdest));
            ::gem5::paramOut(cp, "n", (uint64_t)vec.size());
            for (size_t i = 0; i < vec.size(); ++i) {
                Serializable::ScopedCheckpointSection sec2(
                    cp, csprintf("e%d", (int)i));
                ::gem5::paramOut(cp, "startTime", (uint64_t)vec[i].startTime);
                ::gem5::paramOut(cp, "dataSize", (uint64_t)vec[i].dataSize);
                ::gem5::paramOut(cp, "receiverID", (int64_t)vec[i].receiverID);
            }
        }
    }
    if (tm_axi_has_outstanding) {
        ::gem5::paramOut(cp, "tm_axi_id_n", (uint64_t)tm_axi_out_reads.size());
        for (size_t id = 0; id < tm_axi_out_reads.size(); ++id) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("tm_axi_id_%d", (int)id));
            const auto &rvec = tm_axi_out_reads[id];
            const auto &wvec = tm_axi_out_writes[id];
            ::gem5::paramOut(cp, "reads_n", (uint64_t)rvec.size());
            for (size_t i = 0; i < rvec.size(); ++i) {
                Serializable::ScopedCheckpointSection sec2(
                    cp, csprintf("r%d", (int)i));
                ::gem5::paramOut(cp, "startTime", (uint64_t)rvec[i].startTime);
                ::gem5::paramOut(cp, "dataSize", (uint64_t)rvec[i].dataSize);
                ::gem5::paramOut(cp, "receiverID", (int64_t)rvec[i].receiverID);
            }
            ::gem5::paramOut(cp, "writes_n", (uint64_t)wvec.size());
            for (size_t i = 0; i < wvec.size(); ++i) {
                Serializable::ScopedCheckpointSection sec2(
                    cp, csprintf("w%d", (int)i));
                ::gem5::paramOut(cp, "startTime", (uint64_t)wvec[i].startTime);
                ::gem5::paramOut(cp, "dataSize", (uint64_t)wvec[i].dataSize);
                ::gem5::paramOut(cp, "receiverID", (int64_t)wvec[i].receiverID);
            }
        }
    }
}

void
NocTrafficMonitor::unserializeEndpointCheckpointStash(CheckpointIn &cp,
                                                      gem5::ruby::NodeID initiatorId)
{
    const int key = static_cast<int>(initiatorId);
    endpointCkptStash.erase(key);

    bool tm_axis_has_buf = false;
    bool tm_axis_has_out = false;
    bool tm_axi_has_out = false;
    optParamIn(cp, "tm_axis_has_write_buf", tm_axis_has_buf, false);
    optParamIn(cp, "tm_axis_has_outstanding_writes", tm_axis_has_out, false);
    optParamIn(cp, "tm_axi_has_outstanding_txns", tm_axi_has_out, false);

    if (!tm_axis_has_buf && !tm_axis_has_out && !tm_axi_has_out) {
        DPRINTF(NocPacketFlow, "TM ckpt stash: node %d had no TM fields\n", (int)initiatorId);
        return;
    }

    DeferredEndpointCkpt stash;
    stash.has_axis_write_buf = tm_axis_has_buf;
    stash.has_axis_outstanding_writes = tm_axis_has_out;
    stash.has_axi_outstanding_txns = tm_axi_has_out;

    if (tm_axis_has_buf) {
        ::gem5::arrayParamIn(cp, "tm_axis_write_buf", stash.axis_write_buf);
        DPRINTF(NocPacketFlow, "TM ckpt stash: node %d axis_write_buf bytes=%zu\n",
                (int)initiatorId, stash.axis_write_buf.size());
    }
    if (tm_axis_has_out) {
        uint64_t tdest_n = 0;
        ::gem5::paramIn(cp, "tm_axis_outstanding_tdest_n", tdest_n);
        stash.axis_outstanding_writes.resize(tdest_n);
        for (size_t tdest = 0; tdest < tdest_n; ++tdest) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("tm_axis_tdest_%d", (int)tdest));
            uint64_t n = 0;
            ::gem5::paramIn(cp, "n", n);
            auto &vec = stash.axis_outstanding_writes[tdest];
            vec.resize(n);
            for (size_t i = 0; i < n; ++i) {
                Serializable::ScopedCheckpointSection sec2(
                    cp, csprintf("e%d", (int)i));
                uint64_t tmp = 0;
                ::gem5::paramIn(cp, "startTime", tmp);
                vec[i].startTime = (Tick)tmp;
                ::gem5::paramIn(cp, "dataSize", tmp);
                vec[i].dataSize = tmp;
                int64_t rid = -1;
                ::gem5::paramIn(cp, "receiverID", rid);
                vec[i].receiverID = (gem5::ruby::NodeID)rid;
            }
        }
    }
    if (tm_axi_has_out) {
        uint64_t id_n = 0;
        ::gem5::paramIn(cp, "tm_axi_id_n", id_n);
        stash.axi_outstanding_reads.resize(id_n);
        stash.axi_outstanding_writes.resize(id_n);
        for (size_t id = 0; id < id_n; ++id) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("tm_axi_id_%d", (int)id));
            uint64_t rn = 0, wn = 0;
            ::gem5::paramIn(cp, "reads_n", rn);
            ::gem5::paramIn(cp, "writes_n", wn);
            auto &rvec = stash.axi_outstanding_reads[id];
            auto &wvec = stash.axi_outstanding_writes[id];
            rvec.resize(rn);
            for (size_t i = 0; i < rn; ++i) {
                Serializable::ScopedCheckpointSection sec2(
                    cp, csprintf("r%d", (int)i));
                uint64_t tmp = 0;
                ::gem5::paramIn(cp, "startTime", tmp);
                rvec[i].startTime = (Tick)tmp;
                ::gem5::paramIn(cp, "dataSize", tmp);
                rvec[i].dataSize = tmp;
                int64_t rid = -1;
                ::gem5::paramIn(cp, "receiverID", rid);
                rvec[i].receiverID = (gem5::ruby::NodeID)rid;
            }
            wvec.resize(wn);
            for (size_t i = 0; i < wn; ++i) {
                Serializable::ScopedCheckpointSection sec2(
                    cp, csprintf("w%d", (int)i));
                uint64_t tmp = 0;
                ::gem5::paramIn(cp, "startTime", tmp);
                wvec[i].startTime = (Tick)tmp;
                ::gem5::paramIn(cp, "dataSize", tmp);
                wvec[i].dataSize = tmp;
                int64_t rid = -1;
                ::gem5::paramIn(cp, "receiverID", rid);
                wvec[i].receiverID = (gem5::ruby::NodeID)rid;
            }
        }
    }
    endpointCkptStash.emplace(key, std::move(stash));
}

void
NocTrafficMonitor::applyDeferredEndpointCheckpoint(gem5::ruby::NodeID initiatorId)
{
    const int key = static_cast<int>(initiatorId);
    auto it = endpointCkptStash.find(key);
    if (it == endpointCkptStash.end()) {
        DPRINTF(NocPacketFlow, "TM ckpt apply: node %d no stashed data\n", (int)initiatorId);
        return;
    }
    DeferredEndpointCkpt d = std::move(it->second);
    endpointCkptStash.erase(it);

    const int local = getLocalNmuIndex(initiatorId);
    if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
        panic("NocTrafficMonitor::applyDeferredEndpointCheckpoint: "
              "node %d not registered",
              key);
    }
    const Protocol p = m_nodeInfo[local].protocol;

    if (d.has_axis_write_buf || d.has_axis_outstanding_writes) {
        panic_if(p != Protocol::AXIS,
                   "NocTrafficMonitor::applyDeferredEndpointCheckpoint: "
                   "AXIS checkpoint data for non-AXIS node %d",
                   key);
        if (d.has_axis_write_buf) {
            DPRINTF(NocPacketFlow, "TM ckpt apply: node %d importing axis_write_buf bytes=%zu\n",
                    (int)initiatorId, d.axis_write_buf.size());
            importAxisWriteDataBuffer(initiatorId, d.axis_write_buf);
        }
        if (d.has_axis_outstanding_writes) {
            importAxisOutstandingWrites(initiatorId, d.axis_outstanding_writes);
        }
    }
    if (d.has_axi_outstanding_txns) {
        panic_if(p != Protocol::AXI,
                   "NocTrafficMonitor::applyDeferredEndpointCheckpoint: "
                   "AXI checkpoint data for non-AXI node %d",
                   key);
        importAxiOutstandingTxns(initiatorId, d.axi_outstanding_reads,
                                 d.axi_outstanding_writes);
    }
}

void NocTrafficMonitor::logWriteData(std::string protocol, gem5::ruby::NodeID initiatorID, const std::vector<uint8_t>& beatBytes) {
    if (protocol == "AXIS") {
        int local = getLocalNmuIndex(initiatorID);
        if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
            panic("NocTrafficMonitor::logWriteData: AXIS node %d not registered (no local index)", (int)initiatorID);
        }
        auto* axisVals = static_cast<AXISMonitorValues*>(m_nodeInfo[local].monitorValues);
        if (!axisVals) panic("Monitor: AXIS node without AXISMonitorValues");

        for (uint8_t b : beatBytes) axisVals->m_writeDataBuffer.push_back(b);
        {
            std::ostringstream oss;
            oss << std::hex << std::setfill('0');
            for (size_t i = 0; i < beatBytes.size(); ++i) {
                oss << std::setw(2) << static_cast<unsigned int>(beatBytes[i]);
                if (i + 1 < beatBytes.size()) oss << " ";
            }
            // std::cout << "Monitor: logWriteData AXIS NMU " << initiatorID
            //           << " enqueued " << beatBytes.size() << " bytes: "
            //           << oss.str() << std::endl;
        }
    } else {
        panic("NocTrafficMonitor::logWriteData: Unsupported protocol %s", protocol.c_str());
    }
}

void NocTrafficMonitor::checkWriteData(std::string protocol, gem5::ruby::NodeID initiatorID, const std::vector<uint8_t>& incomingBytes) {
    if (protocol == "AXIS") {
        {
            std::ostringstream oss;
            oss << std::hex << std::setfill('0');
            for (size_t i = 0; i < incomingBytes.size(); ++i) {
                oss << std::setw(2) << static_cast<unsigned int>(incomingBytes[i]);
                if (i + 1 < incomingBytes.size()) oss << " ";
            }
            // std::cout << "Monitor: checkWriteData AXIS NMU " << initiatorID
            //           << " checking " << incomingBytes.size() << " bytes: "
            //           << oss.str() << std::endl;
        }
        int local = getLocalNmuIndex(initiatorID);
        if (local < 0 || local >= static_cast<int>(m_nodeInfo.size())) {
            panic("NocTrafficMonitor::checkWriteData: AXIS node %d not registered (no local index)", (int)initiatorID);
        }
        auto* axisVals = static_cast<AXISMonitorValues*>(m_nodeInfo[local].monitorValues);
        if (!axisVals) panic("Monitor: AXIS node without AXISMonitorValues");

        auto& write_deque = axisVals->m_writeDataBuffer;
        size_t num_bytes = incomingBytes.size();

        if (write_deque.size() < num_bytes) {
            panic("NocTrafficMonitor::checkWriteData: Not enough data in write_deque! "
                  "Deque size: %zu, incoming: %zu",
                  write_deque.size(), num_bytes);
        }

        std::ptrdiff_t mismatch_idx = -1;

        for (size_t i = 0; i < num_bytes; ++i) {
            uint8_t expected = write_deque[i];
            uint8_t actual   = incomingBytes[i];

            if (expected != actual) {
                mismatch_idx = static_cast<std::ptrdiff_t>(i);
                break;
            }
        }

        if (mismatch_idx >= 0) {
            std::string expectedStr;
            std::string actualStr;
            const size_t cmp_n = std::min(write_deque.size(), num_bytes);
            expectedStr.reserve(cmp_n * 3);
            actualStr.reserve(cmp_n * 3);

            for (size_t i = 0; i < cmp_n; ++i) {
                char buf[4];
                std::snprintf(buf, sizeof(buf), "%02x",
                              static_cast<unsigned int>(write_deque[i]));
                expectedStr += buf;
                if (i + 1 < cmp_n) expectedStr += " ";

                std::snprintf(buf, sizeof(buf), "%02x",
                              static_cast<unsigned int>(incomingBytes[i]));
                actualStr += buf;
                if (i + 1 < cmp_n) actualStr += " ";
            }

            panic("NocTrafficMonitor::checkWriteData: AXIS data mismatch at byte %ld (showing first %ld bytes).\nExpected:\n%s\nActual:\n%s",
                 mismatch_idx, cmp_n, expectedStr.c_str(), actualStr.c_str());
        }

        // Consume the compared bytes (min of expected/incoming)
        size_t consume_n = std::min(write_deque.size(), num_bytes);
        write_deque.erase(write_deque.begin(),
                          write_deque.begin() + consume_n);
        
    } else {
        panic("NocTrafficMonitor::checkWriteData: Unsupported protocol %s",
              protocol.c_str());
    }
}

// Called when AR or AW is sent from AXIMM NMU/Initiator
// Or when a write is sent from AXIS NMU
void NocTrafficMonitor::recordRequestStart(
    std::string protocol,
    gem5::ruby::NodeID initiatorID,
    Tick time,
    const std::variant<aximmRWAddr, axisData>& payload_in)
{
    if (protocol == "AXIMM") {
        // Update overall time window start if this is the first request
        const aximmRWAddr* payload = std::get_if<aximmRWAddr>(&payload_in);
        if (!payload) {
            panic("recordRequestStart: payload is not aximmRWAddr for protocol AXIMM!");
        }

        const uint32_t id = payload->id;
        const uint64_t size_bytes = static_cast<uint64_t>(payload->getTotalByteSize());

        if (m_firstRequestTime == MaxTick) {
            m_firstRequestTime = time;
        }
        if (id >= NUM_SUPPORTED_AXI_IDS) {
            warn("Monitor: AXI ID %u out of bounds (0-%d) for Node %d. Ignoring request start.",
                id, NUM_SUPPORTED_AXI_IDS - 1, initiatorID);
            return;
        }

        TransactionInfo info;
        info.startTime = time;
        info.dataSize = size_bytes;
        // Compute receiver via address map if context available
        if (m_net) {
            auto dest = m_net->getDestFromAddress(static_cast<gem5::noc::garnet::Addr>(payload->addr));
            if(dest > m_num_nodes) {
                // Unmapped address (e.g. kernel virtual address 0xffffffe000c04000).
                // The NMU will handle this via handleReadDecErr/handleWriteDecErr.
                // Just skip monitoring for this request.
                warn_once("Monitor: Skipping unmapped address %#x (dest node ID %lu > %d nodes)",
                    payload->addr, dest, m_num_nodes);
                return;
            }
            info.receiverID = dest;
        } else {
            panic("Monitor: No network context available to derive receiver from address!");
        }


        int local_req = getLocalNmuIndex(initiatorID);
        if (local_req < 0 || local_req >= static_cast<int>(m_nodeInfo.size())) {
            panic("Monitor: AXIMM node %d not registered (no local index)", (int)initiatorID);
        }
        auto* axiVals_req = static_cast<AXIMonitorValues*>(m_nodeInfo[local_req].monitorValues);
        if (!axiVals_req) panic("Monitor: AXIMM node without AXIMonitorValues");
        if (payload->cmd == AximmCommand::WRITE) {
            axiVals_req->m_outstandingWrites[id].push_back(info);
            if (local_req >= 0 &&
                local_req < static_cast<int>(m_nodeInfo.size()) &&
                m_nodeInfo[local_req].recordMode > 0 &&
                m_nodeInfo[local_req].protocol == Protocol::AXI) {
                auto &ni = m_nodeInfo[local_req];
                if (ni.csv2.is_open()) {
                    const int link = resolveOrCreateLinkId(
                        ni, initiatorID, info.receiverID, m_next_link_id,
                        m_linkMapCsv, m_linkMapCsvInitialized);
                    const size_t outstanding =
                        countAxiOutstandingWrites(axiVals_req);
                    const double time_ms =
                        ((double)time) * 1000.0 /
                        (double)gem5::sim_clock::Frequency;
                    ni.csv2 << std::fixed << std::setprecision(6) << time_ms
                            << "," << link << "," << size_bytes << ",0,0,"
                            << outstanding << "\n";
                    ni.csv2.flush();
                    ni.lastCsvActivityTick2 = time;
                }
            }
            // printf("Monitor: Start write NodeID %d, AxiID %d, Time %lu, Size %lu\n", (int)initiatorID, (int)id, time, size_bytes);
            // DPRINTF(YourDebugFlag, "Monitor: Start Write ID %d, Time %llu, Size %lu\n", (int)id, time, size_bytes);
        } else {
            axiVals_req->m_outstandingReads[id].push_back(info);
            // printf("Monitor: Start Read NodeID %d, AxiID %d, Time %lu, Size %lu\n", (int)initiatorID, (int)id, time, size_bytes);
            // DPRINTF(YourDebugFlag, "Monitor: Start Read ID %d, Time %llu, Size %lu\n", (int)id, time, size_bytes);
        }
    } else if (protocol == "AXIS") {
        // parameter "id" is not used in this mode
        
        const axisData* payload = std::get_if<axisData>(&payload_in);
        if (!payload) {
            panic("recordRequestStart: payload is not axisData for protocol AXIS!");
        }

        if (m_firstRequestTime == MaxTick) {
            m_firstRequestTime = time;
        }

        int local = getLocalNmuIndex(initiatorID);
        int tdest = payload->tdest;

        // Check if tdest exists in nodeInfo[local].linkIDs
        int link;
        auto &linkIDs = m_nodeInfo[local].linkIDs;

        int nsu_id = -1;
        if (m_net) {
            nsu_id = m_net->getAxisDestNi(static_cast<int>(initiatorID), tdest);
        }

        if (linkIDs.find(nsu_id) == linkIDs.end()) {
            // not found, create new mapping to next linkID
            link = m_next_link_id++;
            linkIDs[nsu_id] = link;
            // Write mapping (nmu_id -> nsu_id) if csv enabled
            if (m_linkMapCsvInitialized && m_linkMapCsv.is_open()) {
                m_linkMapCsv << link << "," << initiatorID << "," << nsu_id << "\n";
                m_linkMapCsv.flush();
            }
        } else {
            // found, use existing linkID
            link = linkIDs[nsu_id];
        }

        // Check bounds before accessing m_axisWrites
        if (local >= 0 && local < static_cast<int>(m_nodeInfo.size())) {
            auto* axisVals_req = static_cast<AXISMonitorValues*>(m_nodeInfo[local].monitorValues);
            if (!axisVals_req) panic("Monitor: AXIS node without AXISMonitorValues");

            // only record latency values if tlast
            if (payload->tlast) {
                TransactionInfo info;
                info.startTime = time;
                info.dataSize = static_cast<uint64_t>(payload->getTotalByteSize());
                // Ensure per-tdest deque exists; index by numeric tdest.
                if (tdest < 0) {
                    panic("Monitor: Negative tdest %d for AXIS payload", tdest);
                }
                if (static_cast<size_t>(tdest) >= axisVals_req->m_axisWrites.size()) {
                    axisVals_req->m_axisWrites.resize(static_cast<size_t>(tdest) + 1);
                }
                axisVals_req->m_axisWrites[static_cast<size_t>(tdest)].push_back(info);
            }

            // otherwise update bandwidth values
            if (local >= 0 && local < static_cast<int>(m_perNodeWriteStats.size())) {
                m_perNodeWriteStats[local].recordAxisSenderBandwidth(time, payload->getTotalByteSize(), m_period_ticks);
            }

        } else {
            // Skip recording if arrays not properly sized (e.g., AXIS-only mode)
            // This is a workaround - ideally init() should be called with total NMU count
        }

        // CSV logging (mode >= 1): sender side per-beat log
        if (local >= 0 && local < static_cast<int>(m_nodeInfo.size()) && m_nodeInfo[local].recordMode > 0) {
            auto &ni = m_nodeInfo[local];
            if (ni.csv2.is_open()) {
                double time_ms = ((double)time) * 1000.0 / (double)gem5::sim_clock::Frequency;
                uint64_t num_bytes = payload->getTotalByteSize();
                int end_flag = payload->tlast ? 1 : 0;
                ni.csv2 << std::fixed << std::setprecision(6) << time_ms << "," << link << "," << num_bytes << "," << end_flag;
                ni.csv2 << "\n";
                ni.csv2.flush();
                ni.lastCsvActivityTick2 = time;
            }
        }
        
    }

}

// Backward-compatible overload
void NocTrafficMonitor::recordRequestStart(gem5::ruby::NodeID initiatorID,
                                           uint32_t id,
                                           Tick time,
                                           uint64_t size_bytes,
                                           AximmCommand axiType)
{
    if (m_firstRequestTime == MaxTick) {
        m_firstRequestTime = time;
    }
    if (id >= NUM_SUPPORTED_AXI_IDS) {
        warn("Monitor: AXI ID %u out of bounds (0-%d) for Node %d. Ignoring request start.",
             id, NUM_SUPPORTED_AXI_IDS - 1, initiatorID);
        return;
    }

    TransactionInfo info;
    info.startTime = time;
    info.dataSize = size_bytes;

    int local_over = getLocalNmuIndex(initiatorID);
    if (local_over < 0 || local_over >= static_cast<int>(m_nodeInfo.size())) {
        panic("Monitor: AXIMM node %d not registered (no local index)", (int)initiatorID);
    }
    auto* axiVals_over = static_cast<AXIMonitorValues*>(m_nodeInfo[local_over].monitorValues);
    if (!axiVals_over) panic("Monitor: AXIMM node without AXIMonitorValues");
    if (axiType == AximmCommand::WRITE) {
        axiVals_over->m_outstandingWrites[id].push_back(info);
    } else {
        axiVals_over->m_outstandingReads[id].push_back(info);
    }
}

// Called when the LAST beat of Read Data (R) arrives at NMU (via RROB)
void NocTrafficMonitor::recordReadResponseEnd(gem5::ruby::NodeID initiatorID, uint32_t id, Tick time) {
    // Update overall time window end
    m_lastResponseTime = std::max(m_lastResponseTime, time);
    int local_rr = getLocalNmuIndex(initiatorID);
    if (local_rr < 0 || local_rr >= static_cast<int>(m_nodeInfo.size())) {
        panic("Monitor: AXIMM node %d not registered (no local index)", (int)initiatorID);
    }
    auto* axiVals_rr = static_cast<AXIMonitorValues*>(m_nodeInfo[local_rr].monitorValues);
    if (!axiVals_rr) panic("Monitor: AXIMM node without AXIMonitorValues");
    auto& read_deque = axiVals_rr->m_outstandingReads[id];
    if (!read_deque.empty()) {
        // Get the info for the OLDEST outstanding request (front of deque)
        TransactionInfo info = read_deque.front();
        // Ensure latency is non-negative (time should not go backwards)
        Tick latency = (time >= info.startTime) ? (time - info.startTime) : 0;
        if (time < info.startTime) {
             warn("Monitor: Read response time %llu is earlier than request time %llu for ID %d", time, info.startTime, (int)id);
        }

        aximmHighLatencyWarning("read", initiatorID, id, latency);

        // Update stats
        m_totalReadLatency += latency;
        m_minReadLatency = std::min(m_minReadLatency, latency);
        m_maxReadLatency = std::max(m_maxReadLatency, latency);
        m_completedReads++;
        m_totalReadBytes += info.dataSize; // Accumulate expected/transferred size
        // printf("Monitor: NMU %d Finished Read request #%d, latency = %lu\n",(int)initiatorID, (int)id, latency);

        // DPRINTF(YourDebugFlag, "Monitor: End Read ID %d, Time %llu, Latency %llu\n", (int)id, time, latency);
        int num_outstanding = -1;
        for (const auto& queue : axiVals_rr->m_outstandingReads) {
            num_outstanding += queue.size();
        }

        int local = getLocalNmuIndex(initiatorID);
        if (local >= 0 && local < static_cast<int>(m_perNodeReadStats.size())) {
            m_perNodeReadStats[local].recordCompletion(latency, info.dataSize, info.startTime, time, num_outstanding, m_period_ticks, true, m_detailed_metrics);
        }

        // CSV logging (mode >= 1): read logging (csv1 = read)
        if (local >= 0 && local < static_cast<int>(m_nodeInfo.size()) && m_nodeInfo[local].recordMode > 0) {
            auto &ni = m_nodeInfo[local];
            int link;
            
            // get link id for this receiver
            if (info.receiverID != -1) {
                auto &linkIDs = ni.linkIDs;
                if (linkIDs.find(info.receiverID) == linkIDs.end()) {
                    // not found, create new mapping to next linkID
                    link = m_next_link_id++;
                    linkIDs[info.receiverID] = link;
                    // Write mapping (nmu_id -> nsu_id) if csv enabled
                    if (m_linkMapCsvInitialized && m_linkMapCsv.is_open()) {
                        m_linkMapCsv << link << "," << initiatorID << "," << info.receiverID << "\n";
                        m_linkMapCsv.flush();
                    }
                } else {
                    // found, use existing linkID
                    link = linkIDs[info.receiverID];
                }
            } else {
                panic("Monitor: Read response from unknown receiver ID %d", info.receiverID);
            }

            if (ni.csv1.is_open()) {
                double time_ms = ((double)time) * 1000.0 / (double)gem5::sim_clock::Frequency;
                int end_flag = 1;
                ni.csv1 << std::fixed << std::setprecision(6) << time_ms << "," << link << "," << info.dataSize << "," << end_flag << "," << latency;
                ni.csv1 << "\n";
                ni.csv1.flush();
                ni.lastCsvActivityTick1 = time;
            }
        }

        // Remove from outstanding map
        read_deque.pop_front();
    } else {
        // This might happen if a response arrives for a request started before monitoring began,
        // or if there's an ID mismatch/reuse issue.
        warn("Monitor: Received read response for unknown/duplicate AXI ID %d at time %llu", (int)id, time);
    }
}

// Called when Write Response (B) arrives at NMU
// or when axis slave receives a beat
// TODO: clean up initiatorID/src_nmu this is confusing and ugly
// TODO: WHYYY IS THIS BEING CALLED EARLY??
void NocTrafficMonitor::recordWriteResponseEnd(std::string protocol, uint32_t src_nmu, bool axisTlast, int axisTdest, uint64_t num_bytes, gem5::ruby::NodeID initiatorID, uint32_t id, Tick time) {
    if (protocol == "AXIMM") { // Update overall time window end
        m_lastResponseTime = std::max(m_lastResponseTime, time);

        int local_wr = getLocalNmuIndex(initiatorID);
        if (local_wr < 0 || local_wr >= static_cast<int>(m_nodeInfo.size())) {
            panic("Monitor: AXIMM node %d not registered (no local index)", (int)initiatorID);
        }
        auto* axiVals_wr = static_cast<AXIMonitorValues*>(m_nodeInfo[local_wr].monitorValues);
        if (!axiVals_wr) panic("Monitor: AXIMM node without AXIMonitorValues");
        auto& write_deque = axiVals_wr->m_outstandingWrites[id];
        if (!write_deque.empty()) {
            // Get the info for the OLDEST outstanding request (front of deque)
            TransactionInfo info = write_deque.front();
            // Ensure latency is non-negative
            Tick latency = (time >= info.startTime) ? (time - info.startTime) : 0;
            if (time < info.startTime) {
                warn("Monitor: Write response time %llu is earlier than request time %llu for ID %d", time, info.startTime, (int)id);
            }

            aximmHighLatencyWarning("write", initiatorID, id, latency);

            // Update stats
            m_totalWriteLatency += latency;
            m_minWriteLatency = std::min(m_minWriteLatency, latency);
            m_maxWriteLatency = std::max(m_maxWriteLatency, latency);
            m_completedWrites++;
            m_totalWriteBytes += info.dataSize; // Accumulate expected/transferred size
            // printf("Monitor: NMU #%d Finished Write request #%d, latency = %lu\n",(int)initiatorID, (int)id, latency);

            // DPRINTF(YourDebugFlag, "Monitor: End Write ID %d, Time %llu, Latency %llu\n", (int)id, time, latency);
            int num_outstanding = -1;
            for (const auto& queue : axiVals_wr->m_outstandingWrites) {
                num_outstanding += queue.size();
            }
            int local = getLocalNmuIndex(initiatorID);
            if (local >= 0 && local < static_cast<int>(m_perNodeWriteStats.size())) {
                m_perNodeWriteStats[local].recordCompletion(latency, info.dataSize, info.startTime, time, num_outstanding, m_period_ticks, true, m_detailed_metrics);
            }

            // CSV logging (mode >= 1): write logging (csv2 = write)
            if (local >= 0 && local < static_cast<int>(m_nodeInfo.size()) && m_nodeInfo[local].recordMode > 0) {
                auto &ni = m_nodeInfo[local];
                int link;
                if (info.receiverID != -1) {
                    auto &linkIDs = ni.linkIDs;
                    if (linkIDs.find(info.receiverID) == linkIDs.end()) {
                        // not found, create new mapping to next linkID
                        link = m_next_link_id++;
                        linkIDs[info.receiverID] = link;
                        // Write mapping (nmu_id -> nsu_id) if csv enabled
                        if (m_linkMapCsvInitialized && m_linkMapCsv.is_open()) {
                            m_linkMapCsv << link << "," << initiatorID << "," << info.receiverID << "\n";
                            m_linkMapCsv.flush();
                        }
                    } else {
                        // found, use existing linkID
                        link = linkIDs[info.receiverID];
                    }
                } else {
                    panic("Monitor: Write response from unknown receiver ID %d", info.receiverID);
                }

                if (ni.csv2.is_open()) {
                    double time_ms = ((double)time) * 1000.0 / (double)gem5::sim_clock::Frequency;
                    const int end_flag = 1;
                    write_deque.pop_front();
                    const size_t outstanding =
                        countAxiOutstandingWrites(axiVals_wr);
                    ni.csv2 << std::fixed << std::setprecision(6) << time_ms
                            << "," << link << "," << info.dataSize << ","
                            << end_flag << "," << latency << ","
                            << outstanding << "\n";
                    ni.csv2.flush();
                    ni.lastCsvActivityTick2 = time;
                } else {
                    write_deque.pop_front();
                }
            } else {
                write_deque.pop_front();
            }
        } else {
            warn("Monitor: Received write response for unknown/duplicate AXI ID %d at time %llu", (int)id, time);
        }
    } else if (protocol == "AXIS") {
        m_lastResponseTime = std::max(m_lastResponseTime, time);
        
        // Bounds check for AXIS
        int local = getLocalNmuIndex(src_nmu);
        if (local < 0 || local >= static_cast<int>(m_num_nodes)) {
            // Skip if not properly sized for AXIS
            return;
        }
        
        auto* axisVals_wr = static_cast<AXISMonitorValues*>(m_nodeInfo[local].monitorValues);
        if (!axisVals_wr) panic("Monitor: AXIS node without AXISMonitorValues");


        // only record latency values if tlast
        Tick latency = MaxTick;
        // Default when not completing a transaction on this beat
        int num_outstanding = -1;
        if (axisTlast) { // Use the provided tdest to select the outstanding queue
            if (axisTdest < 0) panic("Monitor: Negative AXIS tdest %d for response (src %u)", axisTdest, src_nmu);
            size_t chosen_idx = static_cast<size_t>(axisTdest);
            if (chosen_idx >= axisVals_wr->m_axisWrites.size()) {
                panic("Monitor: AXIS tlast received for unknown tdest %d (src %u)", axisTdest, src_nmu);
            }
            auto& write_deque = axisVals_wr->m_axisWrites[chosen_idx];
            if (write_deque.empty()) panic("Monitor: AXIS tlast received for tdest %d with empty outstanding queue (src %u)", axisTdest, src_nmu);

            TransactionInfo info = write_deque.front();

            latency = (time >= info.startTime) ? (time - info.startTime) : 0;
            if (time < info.startTime) warn("AXIS recieved beat earlier than start (src %u)", src_nmu);

            axisHighLatencyWarning(src_nmu, axisTdest, latency);

            // Note: num_outstanding is not defined for AXIS case
            write_deque.pop_front();
        }

        m_perNodeWriteStats[local].recordCompletion(latency, num_bytes, 0, time, num_outstanding, m_period_ticks, axisTlast, m_detailed_metrics);
        m_perNodeWriteStats[local].recordAxisReceiverBandwidth(time, num_bytes, m_period_ticks);


        // CSV logging (mode >= 1): receiver side per-beat log
        if (local < static_cast<int>(m_nodeInfo.size()) && m_nodeInfo[local].recordMode > 0) {
            auto &ni = m_nodeInfo[local];

            int link;
            if (initiatorID != -1) {
                auto &linkIDs = ni.linkIDs;
                if (linkIDs.find(initiatorID) == linkIDs.end()) {
                    panic("Monitor: AXI Stream write sent by sender node %d to receiver node %d improperly logged", src_nmu, initiatorID);
                } else {
                    // found, use existing linkID
                    link = linkIDs[initiatorID];
                }
            } // else {
            //     warn("Monitor: AXI Stream received data with no receiver ID");
            // }

            if (ni.csv1.is_open()) {
                double time_ms = ((double)time) * 1000.0 / (double)gem5::sim_clock::Frequency;
                int end_flag = axisTlast ? 1 : 0;
                ni.csv1 << std::fixed << std::setprecision(6) << time_ms << "," << link << "," << num_bytes << "," << end_flag;
                ni.csv1 << "\n";
                ni.csv1.flush();
                ni.lastCsvActivityTick1 = time;
            }
        }
    }
}

// Backward-compatible overload (legacy callers)
void NocTrafficMonitor::recordWriteResponseEnd(gem5::ruby::NodeID initiatorID,
                                               uint32_t id,
                                               Tick time)
{
    recordWriteResponseEnd("AXIMM", 0 /*src_nmu unused for AXIMM*/, false /*axisTlast unused for AXIMM*/, 0, 0, initiatorID, id, time);
}

// // Called when AXIS write arrives at NSU
// void NocTrafficMonitor::recordAXISWrite(gem5::ruby::NodeID initiatorID, uint32_t id, Tick time) {
//     // Update overall time window end
//     m_lastResponseTime = std::max(m_lastResponseTime, time);

//     auto& write_deque = m_outstandingWrites[initiatorID-m_num_nsu][id];
//     if (!write_deque.empty()) {
//         // Get the info for the OLDEST outstanding request (front of deque)
//         TransactionInfo info = write_deque.front();
//         // Ensure latency is non-negative
//         Tick latency = (time >= info.startTime) ? (time - info.startTime) : 0;
//          if (time < info.startTime) {
//              warn("Monitor: Write response time %llu is earlier than request time %llu for ID %d", time, info.startTime, (int)id);
//         }

//         // Update stats
//         m_totalWriteLatency += latency;
//         m_minWriteLatency = std::min(m_minWriteLatency, latency);
//         m_maxWriteLatency = std::max(m_maxWriteLatency, latency);
//         m_completedWrites++;
//         m_totalWriteBytes += info.dataSize; // Accumulate expected/transferred size
//         // printf("Monitor: NMU #%d Finished Write request #%d, latency = %lu\n",(int)initiatorID, (int)id, latency);

//         // DPRINTF(YourDebugFlag, "Monitor: End Write ID %d, Time %llu, Latency %llu\n", (int)id, time, latency);
//         int num_outstanding = -1;
//         for (const auto& queue : m_outstandingWrites[initiatorID-m_num_nsu]) {
//             num_outstanding += queue.size();
//         }
//         m_perNodeWriteStats[initiatorID-m_num_nsu].recordCompletion(latency, info.dataSize, info.startTime, time, num_outstanding, m_period_ticks);
//         // Remove from outstanding map
//         write_deque.pop_front();
//     } else {
//         warn("Monitor: Received write response for unknown/duplicate AXI ID %d at time %llu", (int)id, time);
//     }
// }

void PerNodeStats::recordCompletion(Tick latency, uint64_t dataSize, Tick startTime, Tick endTime, int num_outstanding, Tick period_ticks, bool increment, bool detailed_metrics) {
    if (latency != MaxTick) {
         totalLatency += latency;
         minLatency = std::min(minLatency, latency);
         maxLatency = std::max(maxLatency, latency);
         if (detailed_metrics) {
             latencies.push_back(latency);
         }
    }
    if (increment) completedCount++;
    totalBytes += dataSize;
    if (startTime < currentStartTime){
        currentStartTime = startTime;
    }
    if (endTime > currentEndTime){
        currentEndTime = endTime;
    }
    totalTime = currentEndTime - currentStartTime;
}

void PerNodeStats::recordAxisSenderBandwidth(Tick time, uint64_t dataSize, Tick period_ticks) {
    isAxis = true;
    if(firstSenderTransactionTime == MaxTick) {
        firstSenderTransactionTime = time;
    }
    if(lastSenderTransactionTime < time) {
        lastSenderTransactionTime = time;
    }
    senderBytesTransferred += dataSize;
}

void PerNodeStats::recordAxisReceiverBandwidth(Tick time, uint64_t dataSize, Tick period_ticks) {
    isAxis = true;
    if(firstReceiverTransactionTime == MaxTick) {
        firstReceiverTransactionTime = time;
    }
    if(lastReceiverTransactionTime < time) {
        lastReceiverTransactionTime = time;
    }
    receiverBytesTransferred += dataSize;
}

Tick
NocTrafficMonitor::csvHeartbeatPeriodTicks() const
{
    if (m_period_ticks == 0) {
        return 0;
    }
    return static_cast<Tick>(kCsvHeartbeatIdleNoCCycles) * m_period_ticks;
}

void
NocTrafficMonitor::writeTrafficCsvIdleRow(
    std::ofstream& os, Protocol protocol, Tick at_tick,
    bool include_outstanding_writes, size_t outstanding_writes)
{
    if (!os.is_open()) {
        return;
    }
    const double time_ms =
        ((double)at_tick) * 1000.0 / (double)gem5::sim_clock::Frequency;
    os << std::fixed << std::setprecision(6) << time_ms << ",-1,0,0";
    if (protocol == Protocol::AXI) {
        os << ",0";
        if (include_outstanding_writes) {
            os << "," << outstanding_writes;
        }
    }
    os << "\n";
}

void
NocTrafficMonitor::logCsvHeartbeatsIfIdle(Tick now)
{
    const Tick period = csvHeartbeatPeriodTicks();
    if (period == 0) {
        return;
    }
    for (auto &ni : m_nodeInfo) {
        if (ni.recordMode <= 0) {
            continue;
        }
        if (ni.csv1.is_open()) {
            const Tick last = ni.lastCsvActivityTick1;
            if (last == MaxTick) {
                if (now >= period) {
                    writeTrafficCsvIdleRow(ni.csv1, ni.protocol, now);
                    ni.lastCsvActivityTick1 = now;
                }
            } else if (now >= last + period) {
                writeTrafficCsvIdleRow(ni.csv1, ni.protocol, now);
                ni.lastCsvActivityTick1 = now;
            }
        }
        if (ni.csv2.is_open()) {
            const Tick last = ni.lastCsvActivityTick2;
            const bool write_idle = (last == MaxTick && now >= period) ||
                                    (last != MaxTick && now >= last + period);
            if (write_idle) {
                size_t outstanding_writes = 0;
                bool include_outstanding = false;
                if (ni.protocol == Protocol::AXI) {
                    auto *axi_vals =
                        static_cast<AXIMonitorValues *>(ni.monitorValues);
                    outstanding_writes = countAxiOutstandingWrites(axi_vals);
                    include_outstanding = true;
                }
                writeTrafficCsvIdleRow(
                    ni.csv2, ni.protocol, now, include_outstanding,
                    outstanding_writes);
                ni.lastCsvActivityTick2 = now;
            }
        }
    }
}

void NocTrafficMonitor::outputCSV() {
    // Close any open per-node CSV streams
    for (auto &ni : m_nodeInfo) {
        if (ni.csv1.is_open()) {
            ni.csv1.flush();
            ni.csv1.close();
        }
        if (ni.csv2.is_open()) {
            ni.csv2.flush();
            ni.csv2.close();
        }
    }
    // Close shared ready/valid CSV if open
    if (m_readyValidCsv.is_open()) {
        m_readyValidCsv.flush();
        m_readyValidCsv.close();
        m_readyValidCsvInitialized = false;
    }
    // Close link-id mapping CSV if open
    if (m_linkMapCsv.is_open()) {
        m_linkMapCsv.flush();
        m_linkMapCsv.close();
        m_linkMapCsvInitialized = false;
    }
}

void NocTrafficMonitor::recordReadyValidSignals(Tick tick, std::string protocol,
                                                gem5::ruby::NodeID node_id,
                                                std::string role,
                                                std::string channel_name,
                                                State* currentState,
                                                State* nodeState)
{
    const double time_ms =  ((double)tick) * 1000.0 / (double)gem5::sim_clock::Frequency;

    bool valid = false;
    bool ready = false;

    // masterState always refers to the AXI master
    // slaveState always refers to the AXI slave
    State* masterState = nullptr;
    State* slaveState  = nullptr;

    if (role == "Master") {
        masterState = nodeState;
        slaveState  = currentState;
    } else if (role == "Slave") {
        masterState = currentState;
        slaveState  = nodeState;
    } else {
        panic("Monitor: recordReadyValidSignals: unknown role %s",
              role.c_str());
    }

    // ---------------- AXIMM ----------------
    if (protocol == "AXIMM") {
        auto* m = dynamic_cast<aximmMasterState*>(masterState);
        auto* s = dynamic_cast<aximmSlaveState*>(slaveState);

        if (!m) panic("Monitor: masterState is not aximmMasterState");
        if (!s) panic("Monitor: slaveState is not aximmSlaveState");

        if (channel_name == "W") {
            valid = m->w.valid;
            ready = s->wReady;
        } else if (channel_name == "AW") {
            valid = m->aw.valid;
            ready = s->awReady;
        } else if (channel_name == "AR") {
            valid = m->ar.valid;
            ready = s->arReady;
        } else if (channel_name == "R") {
            valid = s->r.valid;
            ready = m->rReady;
        } else if (channel_name == "B") {
            valid = s->b.valid;
            ready = m->bReady;
        } else {
            panic("Monitor: unsupported AXIMM channel %s",
                  channel_name.c_str());
        }

    // ---------------- AXIS ----------------
    } else if (protocol == "AXIS") {
        auto* m = dynamic_cast<axisMasterState*>(masterState);
        auto* s = dynamic_cast<axisSlaveState*>(slaveState);

        if (!m) panic("Monitor: masterState is not axisMasterState");
        if (!s) panic("Monitor: slaveState is not axisSlaveState");

        if (channel_name == "W") {
            valid = m->data.tvalid;
            ready = s->tready;
        } else {
            panic("Monitor: unsupported AXIS channel %s",
                  channel_name.c_str());
        }

    } else {
        panic("Monitor: unsupported protocol %s", protocol.c_str());
    }

    // ---------------- CSV output ----------------
    if (m_readyValidCsvInitialized) {
        m_readyValidCsv
            << std::fixed << std::setprecision(6)
            << time_ms << ","
            << node_id << ","
            << protocol << ","
            << role << ","
            << channel_name << ","
            << (ready ? 1 : 0) << ","
            << (valid ? 1 : 0) << "\n";
    } else {
        warn("Monitor: recordReadyValidSignals: CSV not initialized");
    }
}

// --- Updated printStats ---
void NocTrafficMonitor::printStats(Tick final_time) {
    warnOutstandingTransactionsPastThreshold(final_time);

    // Calculate duration and conversion factors (same as before)
    Tick effective_end_time = (m_lastResponseTime > m_firstRequestTime) ? m_lastResponseTime : final_time;
    Tick duration_ticks = (effective_end_time > m_firstRequestTime && m_firstRequestTime != MaxTick) ?
                          (effective_end_time - m_firstRequestTime) : 0;
    if (duration_ticks == 0 && (m_completedReads > 0 || m_completedWrites > 0)) {
         warn("Monitor: Transactions completed but measured duration is zero ticks.");
    }
    double ticks_per_second = (double)gem5::sim_clock::Frequency;
    double duration_sec = (duration_ticks > 0) ? ((double)duration_ticks / ticks_per_second) : 0.0;
    double axi_clk_period_sec = m_axi_clk_period_ps / 1.0e12;
    // double axi_clk_freq_hz = (axi_clk_period_sec > 1e-15) ? (1.0 / axi_clk_period_sec) : 0.0; // Avoid div by zero
    double ticks_to_axi_cycles_factor = (ticks_per_second * axi_clk_period_sec > 1e-15) ?
                                        (1.0 / (ticks_per_second * axi_clk_period_sec)) : 0.0;

    // --- Print Global Write Stats ---
    // std::cout << "=========================================================" << std::endl;
    // std::cout << ">>>>>> Global Traffic Monitor :: WRITE ANALYSIS >>>>>>" << std::endl;
    // std::cout << "=========================================================" << std::endl;
    // std::cout << "AXI Clock Period = " << m_axi_clk_period_ps << " ps ("
    //           << std::fixed << std::setprecision(3) << (axi_clk_freq_hz / 1e6) << " MHz)" << std::endl;
    // std::cout << "Measurement Duration = " << std::fixed << std::setprecision(3) << duration_sec * 1e9 << " ns ("
    //           << duration_ticks << " ticks)" << std::endl;
    // std::cout << "Completed Write Transactions = " << m_completedWrites << std::endl;
    // std::cout << "Total Write Bytes Transferred = " << m_totalWriteBytes << std::endl;

    // if (m_completedWrites > 0) {
    //     double avgWriteLatencyTicks = (double)m_totalWriteLatency / m_completedWrites;
    //     double avgWriteLatencyCycles = avgWriteLatencyTicks * ticks_to_axi_cycles_factor;
    //     double minWriteLatencyCycles = (double)m_minWriteLatency * ticks_to_axi_cycles_factor;
    //     double maxWriteLatencyCycles = (double)m_maxWriteLatency * ticks_to_axi_cycles_factor;

    //     std::cout << std::fixed << std::setprecision(2);
    //     std::cout << "Min Write Latency = " << minWriteLatencyCycles << " axi cycles (" << m_minWriteLatency << " ticks)" << std::endl;
    //     std::cout << "Max Write Latency = " << maxWriteLatencyCycles << " axi cycles (" << m_maxWriteLatency << " ticks)" << std::endl;
    //     std::cout << "Avg Write Latency = " << avgWriteLatencyCycles << " axi cycles (" << avgWriteLatencyTicks << " ticks)" << std::endl;

    //     if (duration_sec > 1e-12) {
    //         double writeBW_Bps = (double)m_totalWriteBytes / duration_sec;
    //         double writeBW_MBps = writeBW_Bps / (1024.0 * 1024.0);
    //         std::cout << std::fixed << std::setprecision(6);
    //         std::cout << "Actual Achieved Write Bandwidth = " << writeBW_MBps << " MB/s" << std::endl;
    //     } else { std::cout << "Actual Achieved Write Bandwidth = N/A (Duration too small)" << std::endl; }
    // } else { std::cout << "No write transactions completed." << std::endl; }
    // std::cout << "***************************************************" << std::endl;

    // // --- Print Global Read Stats ---
    // std::cout << "=========================================================" << std::endl;
    // std::cout << ">>>>>> Global Traffic Monitor :: READ ANALYSIS >>>>>>" << std::endl;
    // std::cout << "=========================================================" << std::endl;
    // std::cout << "Completed Read Transactions = " << m_completedReads << std::endl;
    // std::cout << "Total Read Bytes Transferred = " << m_totalReadBytes << std::endl;

    //  if (m_completedReads > 0) {
    //     double avgReadLatencyTicks = (double)m_totalReadLatency / m_completedReads;
    //     double avgReadLatencyCycles = avgReadLatencyTicks * ticks_to_axi_cycles_factor;
    //     double minReadLatencyCycles = (double)m_minReadLatency * ticks_to_axi_cycles_factor;
    //     double maxReadLatencyCycles = (double)m_maxReadLatency * ticks_to_axi_cycles_factor;
    //     // double read_duration = (double)m_totalReadLatency * m_axi_clk_period_ps / 1e12; // Convert to seconds

    //     std::cout << std::fixed << std::setprecision(2);
    //     std::cout << "Min Read Latency = " << minReadLatencyCycles << " axi cycles (" << m_minReadLatency << " ticks)" << std::endl;
    //     std::cout << "Max Read Latency = " << maxReadLatencyCycles << " axi cycles (" << m_maxReadLatency << " ticks)" << std::endl;
    //     std::cout << "Avg Read Latency = " << avgReadLatencyCycles << " axi cycles (" << avgReadLatencyTicks << " ticks)" << std::endl;

    //     if (duration_sec > 1e-12) {
    //         double readBW_Bps = (double)m_totalReadBytes / duration_sec;
    //         double readBW_MBps = readBW_Bps / (1000.0 * 1000.0);
    //         std::cout << std::fixed << std::setprecision(6);
    //         std::cout << "Actual Achieved Read Bandwidth = " << readBW_MBps << " MB/s" << std::endl;
    //     } else { std::cout << "Actual Achieved Read Bandwidth = N/A (Duration too small)" << std::endl; }
    // } else { std::cout << "No read transactions completed." << std::endl; }

    // --- Print Per-Node Write Stats ---

    for (int i=0; i<static_cast<int>(m_perNodeWriteStats.size()); ++i){
        int global_id = (i < static_cast<int>(m_local_to_global_nmu.size())) ? m_local_to_global_nmu[i] : -1;
        gem5::ruby::NodeID node = (gem5::ruby::NodeID) (global_id);
        PerNodeStats& stats = m_perNodeWriteStats[i];
        if (stats.isAxis) {
            std::cout << "=========================================================" << std::endl;
            std::cout << ">>>>>> AXI Stream Node ID: " << node << " Stats >>>>>>" << std::endl;
            std::cout << "=========================================================" << std::endl;
            std::cout << "  Completed Writes: " << stats.completedCount << std::endl;
            std::cout << "  Total Write Bytes: " << stats.totalBytes << std::endl;
            if (stats.completedCount > 0) {
                double avgLatTicks = (double)stats.totalLatency / stats.completedCount;
                double avgLatCycles = avgLatTicks * ticks_to_axi_cycles_factor;
                double minLatCycles = (double)stats.minLatency * ticks_to_axi_cycles_factor;
                double maxLatCycles = (double)stats.maxLatency * ticks_to_axi_cycles_factor;
                std::cout << std::fixed << std::setprecision(2);
                std::cout << "  Min Write Latency = " << minLatCycles << " axi cycles (" << stats.minLatency << " ticks)" << std::endl;
                std::cout << "  Max Write Latency = " << maxLatCycles << " axi cycles (" << stats.maxLatency << " ticks)" << std::endl;
                std::cout << "  Avg Write Latency = " << avgLatCycles << " axi cycles (" << avgLatTicks << " ticks)" << std::endl;
                if (!stats.latencies.empty()) {
                    std::vector<Tick> sorted_lats = stats.latencies;
                    std::sort(sorted_lats.begin(), sorted_lats.end());
                    auto get_pct = [&](double pct) {
                        size_t idx = std::min(sorted_lats.size() - 1, (size_t)(pct * sorted_lats.size()));
                        return (double)sorted_lats[idx] * ticks_to_axi_cycles_factor;
                    };
                    std::cout << "  P50 Write Latency = " << get_pct(0.50) << " axi cycles" << std::endl;
                    std::cout << "  P95 Write Latency = " << get_pct(0.95) << " axi cycles" << std::endl;
                    std::cout << "  P99 Write Latency = " << get_pct(0.99) << " axi cycles" << std::endl;
                    std::cout << "  P99.9 Write Latency = " << get_pct(0.999) << " axi cycles" << std::endl;
                }
                if (duration_sec > 1e-12) {
                    double sender_duration = (double)(stats.lastSenderTransactionTime - stats.firstSenderTransactionTime) / ticks_per_second;
                    double bw_sender_MBps = ((double)stats.senderBytesTransferred / (double)(1e6)) / sender_duration;
                    std::cout << std::fixed << std::setprecision(6);
                    std::cout << "  Achieved Sender BW = " << bw_sender_MBps << " MB/s" << std::endl;

                    double receiver_duration = (double)(stats.lastReceiverTransactionTime - stats.firstReceiverTransactionTime) / ticks_per_second;
                    double bw_receiver_MBps = ((double)stats.receiverBytesTransferred / (double)(1e6)) / receiver_duration;
                    std::cout << std::fixed << std::setprecision(6);
                    std::cout << "  Achieved Receiver BW = " << bw_receiver_MBps << " MB/s" << std::endl;
                } else { std::cout << "  Achieved BW = N/A" << std::endl; }
                std::cout << "***************************************************" << std::endl;
            }
        } else {
            std::cout << "=========================================================" << std::endl;
            std::cout << ">>>>>> AXI Node ID: " << node << " Stats >>>>>>" << std::endl;
            std::cout << "=========================================================" << std::endl;
            std::cout << "  Completed Writes: " << stats.completedCount << std::endl;
            std::cout << "  Total Write Bytes: " << stats.totalBytes << std::endl;
            if (stats.completedCount > 0) {
                double avgLatTicks = (double)stats.totalLatency / stats.completedCount;
                double avgLatCycles = avgLatTicks * ticks_to_axi_cycles_factor;
                double minLatCycles = (double)stats.minLatency * ticks_to_axi_cycles_factor;
                double maxLatCycles = (double)stats.maxLatency * ticks_to_axi_cycles_factor;
                double write_duration = (double)stats.totalTime / ticks_per_second;
                std::cout << std::fixed << std::setprecision(2);
                std::cout << "  Min Write Latency = " << minLatCycles << " axi cycles (" << stats.minLatency << " ticks)" << std::endl;
                std::cout << "  Max Write Latency = " << maxLatCycles << " axi cycles (" << stats.maxLatency << " ticks)" << std::endl;
                std::cout << "  Avg Write Latency = " << avgLatCycles << " axi cycles (" << avgLatTicks << " ticks)" << std::endl;
                if (!stats.latencies.empty()) {
                    std::vector<Tick> sorted_lats = stats.latencies;
                    std::sort(sorted_lats.begin(), sorted_lats.end());
                    auto get_pct = [&](double pct) {
                        size_t idx = std::min(sorted_lats.size() - 1, (size_t)(pct * sorted_lats.size()));
                        return (double)sorted_lats[idx] * ticks_to_axi_cycles_factor;
                    };
                    std::cout << "  P50 Write Latency = " << get_pct(0.50) << " axi cycles" << std::endl;
                    std::cout << "  P95 Write Latency = " << get_pct(0.95) << " axi cycles" << std::endl;
                    std::cout << "  P99 Write Latency = " << get_pct(0.99) << " axi cycles" << std::endl;
                    std::cout << "  P99.9 Write Latency = " << get_pct(0.999) << " axi cycles" << std::endl;
                }
                if (duration_sec > 1e-12) {
                    double bw_MBps = ((double)stats.totalBytes / 1.0e6) / (double)write_duration;
                    std::cout << std::fixed << std::setprecision(6);
                    std::cout << "  Achieved Write BW = " << bw_MBps << " MB/s" << std::endl;
                } else { std::cout << "  Achieved Write BW = N/A" << std::endl; }
            }

            std::cout << "***************************************************" << std::endl;

            stats = m_perNodeReadStats[i];
            std::cout << "  Completed Reads: " << stats.completedCount << std::endl;
            std::cout << "  Total Read Bytes: " << stats.totalBytes << std::endl;
            if (stats.completedCount > 0) {
                double avgLatTicks = (double)stats.totalLatency / stats.completedCount;
                double avgLatCycles = avgLatTicks * ticks_to_axi_cycles_factor;
                double minLatCycles = (double)stats.minLatency * ticks_to_axi_cycles_factor;
                double maxLatCycles = (double)stats.maxLatency * ticks_to_axi_cycles_factor;
                double read_duration = (double)stats.totalTime / ticks_per_second;
                std::cout << std::fixed << std::setprecision(2);
                std::cout << "  Min Read Latency = " << minLatCycles << " axi cycles (" << stats.minLatency << " ticks)" << std::endl;
                std::cout << "  Max Read Latency = " << maxLatCycles << " axi cycles (" << stats.maxLatency << " ticks)" << std::endl;
                std::cout << "  Avg Read Latency = " << avgLatCycles << " axi cycles (" << avgLatTicks << " ticks)" << std::endl;
                if (!stats.latencies.empty()) {
                    std::vector<Tick> sorted_lats = stats.latencies;
                    std::sort(sorted_lats.begin(), sorted_lats.end());
                    auto get_pct = [&](double pct) {
                        size_t idx = std::min(sorted_lats.size() - 1, (size_t)(pct * sorted_lats.size()));
                        return (double)sorted_lats[idx] * ticks_to_axi_cycles_factor;
                    };
                    std::cout << "  P50 Read Latency = " << get_pct(0.50) << " axi cycles" << std::endl;
                    std::cout << "  P95 Read Latency = " << get_pct(0.95) << " axi cycles" << std::endl;
                    std::cout << "  P99 Read Latency = " << get_pct(0.99) << " axi cycles" << std::endl;
                    std::cout << "  P99.9 Read Latency = " << get_pct(0.999) << " axi cycles" << std::endl;
                }
                if (read_duration > 1e-12) {
                    double bw_MBps = ((double)stats.totalBytes / 1.0e6) / read_duration;
                    std::cout << std::fixed << std::setprecision(6);
                    std::cout << "  Achieved Read BW = " << bw_MBps << " MB/s" << std::endl;
                } else { std::cout << "  Achieved Read BW = N/A" << std::endl; }
            }
        }
    }

    // --- Fairness Summary Block ---
    if (m_detailed_metrics) {
        std::vector<double> write_bw_list, read_bw_list;
        std::vector<double> write_lat_list, read_lat_list;

        for (int i = 0; i < static_cast<int>(m_perNodeWriteStats.size()); ++i) {
            const auto& w_stats = m_perNodeWriteStats[i];
            const auto& r_stats = m_perNodeReadStats[i];

            if (!w_stats.isAxis && w_stats.completedCount > 0) {
                double write_duration = (double)w_stats.totalTime / ticks_per_second;
                if (write_duration > 1e-12) {
                    write_bw_list.push_back(((double)w_stats.totalBytes / 1.0e6) / write_duration);
                }
                double avgLatTicks = (double)w_stats.totalLatency / w_stats.completedCount;
                write_lat_list.push_back(avgLatTicks * ticks_to_axi_cycles_factor);
            }

            if (!r_stats.isAxis && r_stats.completedCount > 0) {
                double read_duration = (double)r_stats.totalTime / ticks_per_second;
                if (read_duration > 1e-12) {
                    read_bw_list.push_back(((double)r_stats.totalBytes / 1.0e6) / read_duration);
                }
                double avgLatTicks = (double)r_stats.totalLatency / r_stats.completedCount;
                read_lat_list.push_back(avgLatTicks * ticks_to_axi_cycles_factor);
            }
        }

        auto print_fairness = [](const std::string& name, const std::vector<double>& values) {
            if (values.empty()) return;
            double sum = 0.0, sum_sq = 0.0, min_val = std::numeric_limits<double>::max(), max_val = 0.0;
            for (double v : values) {
                sum += v;
                sum_sq += v * v;
                min_val = std::min(min_val, v);
                max_val = std::max(max_val, v);
            }
            double n = values.size();
            double jfi = (sum * sum) / (n * sum_sq);
            double mean = sum / n;
            double variance = (sum_sq / n) - (mean * mean);
            double cv = (mean > 0) ? std::sqrt(std::max(0.0, variance)) / mean : 0.0;
            double maxmin = (min_val > 0) ? max_val / min_val : max_val;
            
            std::cout << "  " << std::left << std::setw(10) << name 
                      << " JFI = " << std::fixed << std::setprecision(4) << jfi 
                      << "  CV = " << std::fixed << std::setprecision(4) << cv 
                      << "  Max/Min = " << std::fixed << std::setprecision(2) << maxmin << std::endl;
        };

        if (write_bw_list.size() > 0 || read_bw_list.size() > 0) {
            std::cout << "=== Fairness Summary (across AXIMM NMUs) ===" << std::endl;
            print_fairness("Write BW", write_bw_list);
            print_fairness("Read BW", read_bw_list);
            print_fairness("Write Lat", write_lat_list);
            print_fairness("Read Lat", read_lat_list);
            std::cout << "===============================================" << std::endl;
        }
    }

    // Report outstanding transactions (same as before)
    uint64_t total_outstanding_reads = 0;
    for (const auto& ni : m_nodeInfo) {
        if (ni.monitorValues && ni.protocol == Protocol::AXI) {
            const auto* axi = static_cast<const AXIMonitorValues*>(ni.monitorValues);
            for (const auto& dq : axi->m_outstandingReads) total_outstanding_reads += dq.size();
        }
    }
    uint64_t total_outstanding_writes = 0;
    for (const auto& ni : m_nodeInfo) {
        if (ni.monitorValues) {
            if (ni.protocol == Protocol::AXI) {
                const auto* axi = static_cast<const AXIMonitorValues*>(ni.monitorValues);
                for (const auto& dq : axi->m_outstandingWrites) total_outstanding_writes += dq.size();
            } else if (ni.protocol == Protocol::AXIS) {
                const auto* axis = static_cast<const AXISMonitorValues*>(ni.monitorValues);
                for (const auto& dq : axis->m_axisWrites) total_outstanding_writes += dq.size();
            }
        }
    }

    if (total_outstanding_reads > 0) { warn("Monitor: %lu read transactions still outstanding at end.", total_outstanding_reads); }
    if (total_outstanding_writes > 0) { warn("Monitor: %lu write transactions still outstanding at end.", total_outstanding_writes); }
}


}
}
}
