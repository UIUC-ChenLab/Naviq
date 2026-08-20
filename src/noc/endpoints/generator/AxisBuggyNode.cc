#include "noc/endpoints/generator/AxisBuggyNode.hh"

#include "sim/core.hh"

#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxisTrafficGenerator/AxisTrafficGenerator.h"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxisTrafficGenerator/strategies/AxisRandomStrategy.h"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/include/AxisInterface.h"

#include <algorithm>
#include <cmath>
#include <cctype>
#include <cstring>
#include <iostream>
#include <limits>
#include <string>

namespace {
inline std::string
toUpper(std::string s)
{
    std::transform(s.begin(), s.end(), s.begin(),
        [](unsigned char c) { return std::toupper(c); });
    return s;
}
} // anonymous namespace

namespace gem5 {
namespace noc {

DistributionType
AxisBuggyGenerator::parseDistribution(const std::string& s)
{
    const std::string u = toUpper(s);
    if (u == "UNIFORM")
        return DistributionType::UNIFORM;
    if (u == "BINOMIAL")
        return DistributionType::BINOMIAL;
    if (u == "INCREMENT")
        return DistributionType::INCREMENT;
    if (u == "FIXED")
        return DistributionType::FIXED;
    return DistributionType::UNIFORM;
}

namespace {

DistributionType
parseDistributionLocal(const std::string& s)
{
    const std::string u = toUpper(s);
    if (u == "UNIFORM")
        return DistributionType::UNIFORM;
    if (u == "BINOMIAL")
        return DistributionType::BINOMIAL;
    if (u == "INCREMENT")
        return DistributionType::INCREMENT;
    if (u == "FIXED")
        return DistributionType::FIXED;
    return DistributionType::UNIFORM;
}

AxisRandomStrategy::Config
makePrimaryConfig(const AxisBuggyGeneratorParams& p)
{
    AxisRandomStrategy::Config cfg;
    cfg.seed = p.seed;

    cfg.packet_size_distribution =
        parseDistributionLocal(p.packet_size_distribution);
    cfg.min_packet_size_bytes = p.min_packet_size_bytes;
    cfg.max_packet_size_bytes = p.max_packet_size_bytes;
    cfg.packet_size_binomial_probability = p.packet_size_binomial_probability;

    cfg.gap_distribution = parseDistributionLocal(p.gap_distribution);
    cfg.min_gap_cycles = p.min_gap_cycles;
    cfg.max_gap_cycles = p.max_gap_cycles;
    cfg.gap_binomial_probability = p.gap_binomial_probability;

    cfg.tid_distribution = parseDistributionLocal(p.tid_distribution);
    cfg.min_tid = p.min_tid;
    cfg.max_tid = p.max_tid;
    cfg.tid_binomial_probability = p.tid_binomial_probability;

    cfg.tdest_distribution =
        parseDistributionLocal(p.tdest_distribution);
    cfg.min_tdest = p.min_tdest;
    cfg.max_tdest = p.max_tdest;
    cfg.tdest_binomial_probability = p.tdest_binomial_probability;

    cfg.max_packets = p.max_packets;
    return cfg;
}

AxisRandomStrategy::Config
makeSecondConfig(const AxisBuggyGeneratorParams& p)
{
    AxisRandomStrategy::Config cfg;
    cfg.seed = p.second_seed;

    cfg.packet_size_distribution =
        parseDistributionLocal(p.second_packet_size_distribution);
    cfg.min_packet_size_bytes = p.second_min_packet_size_bytes;
    cfg.max_packet_size_bytes = p.second_max_packet_size_bytes;
    cfg.packet_size_binomial_probability =
        p.second_packet_size_binomial_probability;

    cfg.gap_distribution =
        parseDistributionLocal(p.second_gap_distribution);
    cfg.min_gap_cycles = p.second_min_gap_cycles;
    cfg.max_gap_cycles = p.second_max_gap_cycles;
    cfg.gap_binomial_probability = p.second_gap_binomial_probability;

    cfg.tid_distribution =
        parseDistributionLocal(p.second_tid_distribution);
    cfg.min_tid = p.second_min_tid;
    cfg.max_tid = p.second_max_tid;
    cfg.tid_binomial_probability = p.second_tid_binomial_probability;

    cfg.tdest_distribution =
        parseDistributionLocal(p.second_tdest_distribution);
    cfg.min_tdest = p.second_min_tdest;
    cfg.max_tdest = p.second_max_tdest;
    cfg.tdest_binomial_probability = p.second_tdest_binomial_probability;

    cfg.max_packets = p.second_max_packets;
    return cfg;
}

} // anonymous namespace

struct AxisBuggyGenerator::MasterPort
{
    MasterPort(uint32_t data_width, uint32_t tid_width, uint32_t tdest_width,
               uint32_t tuser_width, const AxisRandomStrategy::Config& cfg,
               uint64_t seed, bool tid_corrupt_enable,
               double tid_corrupt_chance, bool stall_drop_tvalid_enable,
               double stall_drop_tvalid_chance,
               bool stall_mutate_payload_enable,
               double stall_mutate_payload_chance,
               bool stall_drop_tlast_enable,
               double stall_drop_tlast_chance, uint8_t valid_percent,
               uint32_t valid_percent_start_after_packets)
        : dataWidthBits(data_width),
          tidWidth(tid_width),
          tdestWidth(tdest_width),
          tuserWidth(tuser_width),
          signals(std::make_shared<AxisInterface>(
              data_width, tid_width, tdest_width, tuser_width)),
          generator(std::make_unique<AxisTrafficGenerator>(signals)),
          currentMasterState(data_width, tid_width, tdest_width),
          stalledBeatSnapshot(data_width, tid_width, tdest_width),
          tidCorruptEnable(tid_corrupt_enable),
          tidCorruptChance(tid_corrupt_chance),
          rng(seed ? seed : std::random_device{}()),
          stallDropTvalidEnable(stall_drop_tvalid_enable),
          stallDropTvalidChance(stall_drop_tvalid_chance),
          stallMutatePayloadEnable(stall_mutate_payload_enable),
          stallMutatePayloadChance(stall_mutate_payload_chance),
          stallDropTlastEnable(stall_drop_tlast_enable),
          stallDropTlastChance(stall_drop_tlast_chance),
          validPercent(valid_percent),
          validPercentStartAfterPackets(valid_percent_start_after_packets)
    {
        generator->setMode(cfg);
        generator->reset();

        // Default to ready until the NI drives otherwise.
        nocIfIn.tready = true;
        signals->setTReady(nocIfIn.tready);
        generator->update();
    }

    uint32_t dataWidthBits;
    uint32_t tidWidth;
    uint32_t tdestWidth;
    uint32_t tuserWidth;

    std::shared_ptr<AxisInterface> signals;
    std::unique_ptr<AxisTrafficGenerator> generator;

    axisSlaveState nocIfIn{};
    axisMasterState currentMasterState;
    axisMasterState stalledBeatSnapshot;
    bool holdValidUntilHandshake = false;

    bool tidCorruptEnable = false;
    double tidCorruptChance = 0.0;
    bool tidCorruptDone = false;
    std::mt19937_64 rng;
    std::uniform_real_distribution<double> prob01{0.0, 1.0};

    bool stallDropTvalidEnable = false;
    double stallDropTvalidChance = 0.0;
    bool pendingDropTvalidNext = false;

    bool stallMutatePayloadEnable = false;
    double stallMutatePayloadChance = 0.0;
    bool pendingMutatePayloadNext = false;

    bool stallDropTlastEnable = false;
    double stallDropTlastChance = 0.0;
    bool pendingDropTlastNext = false;

    uint8_t validPercent = 100;
    uint32_t validPercentStartAfterPackets = 0;
    uint32_t packetsCompletedOnLink = 0;
    bool validAllowThisCycle = true;
    std::uniform_int_distribution<int> dist100{0, 99};

    bool portAssigned = false;
};

AxisBuggyGenerator::AxisBuggyGenerator(const Params& p)
    : NocNode(p)
{
    maxPorts = p.second_master_enable ? 2 : 1;
    if (portEndpointNames.size() < static_cast<size_t>(maxPorts)) {
        panic("AxisBuggyGenerator: expected at least %d port endpoint names, got %zu",
              maxPorts, portEndpointNames.size());
    }
    if (clockDomains.size() < static_cast<size_t>(maxPorts)) {
        panic("AxisBuggyGenerator: expected at least %d clock domains, got %zu",
              maxPorts, clockDomains.size());
    }

    m_masters.emplace_back(std::make_unique<MasterPort>(
        p.data_width, p.tid_width, p.tdest_width, p.tuser_width,
        makePrimaryConfig(p), p.seed, p.tid_corrupt_enable,
        p.tid_corrupt_chance, p.stall_drop_tvalid_enable,
        p.stall_drop_tvalid_chance, p.stall_mutate_payload_enable,
        p.stall_mutate_payload_chance, p.stall_drop_tlast_enable,
        p.stall_drop_tlast_chance, p.valid_percent,
        static_cast<uint32_t>(std::floor(
            static_cast<double>(p.max_packets) *
            std::clamp(p.valid_percent_start_fraction, 0.0, 1.0)))));
    refreshCurrentState(*m_masters.back());

    if (p.second_master_enable) {
        m_masters.emplace_back(std::make_unique<MasterPort>(
            p.second_data_width, p.second_tid_width, p.second_tdest_width,
            p.second_tuser_width, makeSecondConfig(p), p.second_seed,
            p.second_tid_corrupt_enable, p.second_tid_corrupt_chance,
            p.second_stall_drop_tvalid_enable,
            p.second_stall_drop_tvalid_chance,
            p.second_stall_mutate_payload_enable,
            p.second_stall_mutate_payload_chance,
            p.second_stall_drop_tlast_enable,
            p.second_stall_drop_tlast_chance, p.second_valid_percent,
            static_cast<uint32_t>(std::floor(
                static_cast<double>(p.second_max_packets) *
                std::clamp(p.second_valid_percent_start_fraction, 0.0, 1.0)))));
        refreshCurrentState(*m_masters.back());
    }
}

AxisBuggyGenerator::~AxisBuggyGenerator() = default;

void
AxisBuggyGenerator::mutateOutgoing(axisMasterState& state)
{
    (void)state;
}

void
AxisBuggyGenerator::mutateOutgoing(MasterPort& master, axisMasterState& state)
{
    // Apply any previously-armed (next-cycle) mutations first.
    if (master.pendingDropTvalidNext) {
        state.data.tvalid = false;
        master.pendingDropTvalidNext = false;
    }
    if (master.pendingMutatePayloadNext) {
        mutatePayload(master, state);
        master.pendingMutatePayloadNext = false;
    }
    if (master.pendingDropTlastNext) {
        state.data.tlast = false;
        master.pendingDropTlastNext = false;
    }

    // --- Single-beat TID corruption ---
    if (master.tidCorruptEnable && !master.tidCorruptDone &&
        state.data.tvalid) {
        const double roll = master.prob01(master.rng);
        if (roll < master.tidCorruptChance) {
            const uint64_t max_tid =
                (master.tidWidth >= 64) ? std::numeric_limits<uint64_t>::max()
                                        : ((1ULL << master.tidWidth) - 1ULL);

            const uint64_t old_tid = static_cast<uint64_t>(state.data.tid) & max_tid;

            std::uniform_int_distribution<uint64_t> dist(0, max_tid);
            uint64_t new_tid = old_tid;
            for (int i = 0; i < 8 && new_tid == old_tid; ++i) {
                new_tid = dist(master.rng);
            }
            if (new_tid == old_tid) {
                new_tid = (old_tid + 1) & max_tid;
            }

            state.data.tid = static_cast<decltype(state.data.tid)>(new_tid);
            master.tidCorruptDone = true;
        }
    }

    // --- Stall-triggered "next cycle" injections ---
    const bool stalled = state.data.tvalid && !master.nocIfIn.tready;
    const bool stalled_tlast = stalled && state.data.tlast;

    if (stalled && master.stallDropTvalidEnable) {
        if (master.prob01(master.rng) < master.stallDropTvalidChance) {
            master.pendingDropTvalidNext = true;
        }
    }

    if (stalled && master.stallMutatePayloadEnable) {
        if (master.prob01(master.rng) < master.stallMutatePayloadChance) {
            master.pendingMutatePayloadNext = true;
        }
    }

    if (stalled_tlast && master.stallDropTlastEnable) {
        if (master.prob01(master.rng) < master.stallDropTlastChance) {
            master.pendingDropTlastNext = true;
        }
    }
}

void
AxisBuggyGenerator::mutatePayload(MasterPort& master, axisMasterState& state)
{
    if (!state.data.tvalid)
        return;

    const uint64_t tkeep = state.data.tkeep;
    const size_t bytes = state.data.tdata.size();

    // Prefer mutating an actually-valid byte lane (as indicated by TKEEP).
    size_t idx = bytes;
    for (size_t i = 0; i < std::min<size_t>(bytes, 64); ++i) {
        if (tkeep & (1ULL << i)) {
            idx = i;
            break;
        }
    }

    if (idx < bytes) {
        const uint8_t old = state.data.tdata[idx];
        uint8_t neu = old;
        for (int tries = 0; tries < 8 && neu == old; ++tries) {
            neu = static_cast<uint8_t>(master.rng() & 0xFF);
        }
        if (neu == old)
            neu = static_cast<uint8_t>(old ^ 0xFF);
        state.data.tdata[idx] = neu;
        return;
    }

    // Fallback: perturb TDEST within its width.
    const uint64_t max_tdest =
        (master.tdestWidth >= 64) ? std::numeric_limits<uint64_t>::max()
                                  : ((1ULL << master.tdestWidth) - 1ULL);
    const uint64_t old_tdest = static_cast<uint64_t>(state.data.tdest) & max_tdest;
    const uint64_t new_tdest = (old_tdest + 1) & max_tdest;
    state.data.tdest = static_cast<decltype(state.data.tdest)>(new_tdest);
}

bool
AxisBuggyGenerator::done()
{
    for (const auto& master : m_masters) {
        if (!master->generator->isDone())
            return false;
    }
    return true;
}

void
AxisBuggyGenerator::update(int portID, State* inputNocInterfaceState)
{
    if (portID < 0 || portID >= static_cast<int>(m_masters.size())) {
        panic("AxisBuggyGenerator::update invalid portID %d", portID);
    }

    auto* axisSlave = dynamic_cast<axisSlaveState*>(inputNocInterfaceState);
    if (!axisSlave)
        panic("AxisBuggyGenerator::update expected axisSlaveState");

    MasterPort& master = *m_masters[portID];
    master.nocIfIn = *axisSlave;
    m_lastUpdatedPort = portID;

    // Throttle visible TVALID without letting the generator see a false handshake:
    // when we will mask strategy TVALID low, deassert TREADY into the interface so
    // AxisRandomStrategy::calculateNextValues does not advance on sink-ready alone.
    const bool raw_valid = master.signals->getTValid();
    const bool throttle_phase =
        master.packetsCompletedOnLink >= master.validPercentStartAfterPackets;
    // AXIS master: cannot deassert TVALID (or change payload) while stalled
    // (TVALID && !TREADY). NocInterface::ProtocolChecker enforces this.
    if (master.holdValidUntilHandshake) {
        master.validAllowThisCycle = true;
    } else if (throttle_phase && raw_valid) {
        const int roll = master.dist100(master.rng);
        master.validAllowThisCycle =
            roll < static_cast<int>(master.validPercent);
    } else {
        master.validAllowThisCycle = true;
    }
    const bool gen_tready =
        master.nocIfIn.tready && (!raw_valid || master.validAllowThisCycle);
    master.signals->setTReady(gen_tready);
    master.generator->update();
}

State*
AxisBuggyGenerator::getCurrentState(int portID)
{
    if (portID < 0 || portID >= static_cast<int>(m_masters.size()))
        panic("AxisBuggyGenerator::getCurrentState invalid portID %d", portID);
    return &m_masters[portID]->currentMasterState;
}

int
AxisBuggyGenerator::assignPort(const std::string& endpointName)
{
    for (int port = 0; port < maxPorts; ++port) {
        if (endpointName == portEndpointNames[port] &&
            !m_masters[port]->portAssigned) {
            m_masters[port]->portAssigned = true;
            return port;
        }
    }
    panic("AxisBuggyGenerator::assignPort invalid endpointName: %s",
          endpointName.c_str());
}

bool
AxisBuggyGenerator::tick(int clockDomain)
{
    if (m_lastUpdatedPort < 0 ||
        m_lastUpdatedPort >= static_cast<int>(m_masters.size())) {
        return false;
    }

    const int portID = m_lastUpdatedPort;
    if (clockDomain != clockDomains[portID])
        return false;
    MasterPort& master = *m_masters[portID];

    // NI tready was updated in update() this cycle. If we advance the external
    // generator while (TVALID && !TREADY), the strategy can change TLAST (or the
    // whole beat) without a link handshake — NocInterface::ProtocolChecker flags
    // that as "last deasserted before handshake". Freeze the generator until
    // TREADY is seen, then tick once when the beat can complete.
    const bool stalled =
        master.currentMasterState.data.tvalid && !master.nocIfIn.tready;
    if (stalled) {
        master.stalledBeatSnapshot = master.currentMasterState;
        master.holdValidUntilHandshake = true;
    } else {
        master.holdValidUntilHandshake = false;
        master.generator->tick();
    }

    refreshCurrentState(master);

    if (master.nocIfIn.tready && master.currentMasterState.data.tvalid &&
        master.currentMasterState.data.tlast) {
        master.packetsCompletedOnLink++;
    }

    // std::cout << name() << " port=" << portID << " t=" << curTick()
    //           << " tvalid=" << static_cast<unsigned>(
    //                  master.currentMasterState.data.tvalid)
    //           << " tid=" << master.currentMasterState.data.tid
    //           << " tdest=" << master.currentMasterState.data.tdest
    //           << " tready=" << static_cast<unsigned>(master.nocIfIn.tready)
    //           << '\n';

    m_lastUpdatedPort = -1;
    return true;
}

void
AxisBuggyGenerator::refreshCurrentState(MasterPort& master)
{
    if (master.holdValidUntilHandshake) {
        // Replay the exact stalled beat; do not throttle or mutate until handshake.
        master.currentMasterState = master.stalledBeatSnapshot;
    } else {
        copyAxisValuesFromChannel(master, master.currentMasterState);
        applyValidPercentToOutgoing(master, master.currentMasterState);

        // Bug injection hook points.
        mutateOutgoing(master, master.currentMasterState);
        mutateOutgoing(master.currentMasterState);
        if (m_outMutator) {
            m_outMutator(master.currentMasterState);
        }
    }
}

void
AxisBuggyGenerator::applyValidPercentToOutgoing(MasterPort& master,
                                           axisMasterState& state)
{
    if (master.packetsCompletedOnLink < master.validPercentStartAfterPackets)
        return;
    if (!state.data.tvalid)
        return;
    if (!master.validAllowThisCycle)
        state.data.tvalid = false;
}

void
AxisBuggyGenerator::copyAxisValuesFromChannel(MasterPort& master,
                                         axisMasterState& state)
{
    axisData& dst = state.data;

    const size_t bytes = master.signals->getTData().size();
    if (dst.tdata.size() < bytes)
        panic("AxisBuggyGenerator: TDATA size from signals is larger than expected");
    std::memcpy(dst.tdata.data(), master.signals->getTData().data(), bytes);

    dst.tid = master.signals->getTId();
    dst.tdest = master.signals->getTDest();
    dst.tlast = master.signals->getTLast();
    dst.tvalid = master.signals->getTValid();

    dst.tkeep = 0;
    for (size_t i = 0; i < master.signals->getTKeep().size(); ++i) {
        if (master.signals->getTKeep()[i].u64())
            dst.tkeep |= (1ULL << i);
    }

    if (master.signals->getTUser().size() > 0) {
        dst.tuser = master.signals->getTUser()[0];
    }
}

} // namespace noc
} // namespace gem5
