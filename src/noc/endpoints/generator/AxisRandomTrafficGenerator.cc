#include "noc/endpoints/generator/AxisRandomTrafficGenerator.hh"

#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxisTrafficGenerator/strategies/AxisRandomStrategy.h"

#include <algorithm>
#include <cctype>
#include <string>

namespace {
inline std::string toUpper(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){ return std::toupper(c); });
    return s;
}

inline DistributionType parseDistribution(const std::string& s) {
    const std::string u = toUpper(s);
    if (u == "UNIFORM") return DistributionType::UNIFORM;
    if (u == "BINOMIAL") return DistributionType::BINOMIAL;
    if (u == "INCREMENT") return DistributionType::INCREMENT;
    if (u == "FIXED") return DistributionType::FIXED;
    return DistributionType::UNIFORM;
}
} // anonymous

namespace gem5 {
namespace noc {

AxisRandomTrafficGenerator::AxisRandomTrafficGenerator(const Params& p)
    : AXISTrafficGenerator(p)
{
    AxisRandomStrategy::Config cfg;
    cfg.seed = p.seed;

    cfg.packet_size_distribution = parseDistribution(p.packet_size_distribution);
    cfg.min_packet_size_bytes = p.min_packet_size_bytes;
    cfg.max_packet_size_bytes = p.max_packet_size_bytes;
    cfg.packet_size_binomial_probability = p.packet_size_binomial_probability;

    cfg.gap_distribution = parseDistribution(p.gap_distribution);
    cfg.min_gap_cycles = p.min_gap_cycles;
    cfg.max_gap_cycles = p.max_gap_cycles;
    cfg.gap_binomial_probability = p.gap_binomial_probability;

    cfg.tid_distribution = parseDistribution(p.tid_distribution);
    cfg.min_tid = p.min_tid;
    cfg.max_tid = p.max_tid;
    cfg.tid_binomial_probability = p.tid_binomial_probability;

    cfg.tdest_distribution = parseDistribution(p.tdest_distribution);
    cfg.min_tdest = p.min_tdest;
    cfg.max_tdest = p.max_tdest;
    cfg.tdest_binomial_probability = p.tdest_binomial_probability;

    cfg.max_packets = p.max_packets;

    auto* gen = axisGenerator();
    if (gen) {
        gen->setMode(cfg);
        gen->reset();
        updateAxisCurrentState();
    }
}

bool
AxisRandomTrafficGenerator::tick(int clockDomain)
{
    const bool did_tick = TrafficGenerator::tick(clockDomain);
    if (did_tick) {
        ticksExecuted++;
    }
    return did_tick;
}

void
AxisRandomTrafficGenerator::serializeNocNodeState(CheckpointOut &cp) const
{
    // Intentionally minimal: store only how many times we've been ticked.
    paramOut(cp, "artg_ticks_executed", ticksExecuted);
}

void
AxisRandomTrafficGenerator::unserializeNocNodeState(CheckpointIn &cp)
{
    uint64_t target_ticks = 0;
    // Backward compatible: older checkpoints won't have this key.
    optParamIn(cp, "artg_ticks_executed", target_ticks, /*do_warn=*/false);

    ticksExecuted = 0;

    // Rewind generator to its initial state, then replay ticks.
    auto* gen = axisGenerator();
    if (gen) {
        gen->reset();
        updateAxisCurrentState();

        for (uint64_t i = 0; i < target_ticks; ++i) {
            std::get<AxisTrafficGenerator>(trafficGenerator).tick();
        }

        // Refresh state visible to the NI after the replay.
        updateAxisCurrentState();
    }

    ticksExecuted = target_ticks;
}

} // namespace noc
} // namespace gem5


