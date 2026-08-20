#include "noc/endpoints/generator/AxiRandomTrafficGenerator.hh"

#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxiTrafficGenerator/strategies/AxiRandomStrategy.h"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/include/NsuInfo.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
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

inline ReadWriteMode parseRWMode(const std::string& s) {
    const std::string u = toUpper(s);
    if (u == "WRITE_ONLY") return ReadWriteMode::WRITE_ONLY;
    if (u == "SEQUENTIAL") return ReadWriteMode::SEQUENTIAL;
    if (u == "INTERLEAVED") return ReadWriteMode::INTERLEAVED;
    return ReadWriteMode::WRITE_ONLY;
}

inline NsuSelectionMode parseNsuSelectionMode(const std::string& s) {
    const std::string u = toUpper(s);
    if (u == "INTERLEAVE") return NsuSelectionMode::INTERLEAVE;
    if (u == "RANDOM") return NsuSelectionMode::RANDOM;
    if (u == "ROTATE") return NsuSelectionMode::ROTATE;
    return NsuSelectionMode::INTERLEAVE;
}

inline bool isPowerOfTwo(uint32_t value) {
    return value != 0 && (value & (value - 1)) == 0;
}
} // anonymous

namespace gem5 {
namespace noc {

AxiRandomTrafficGenerator::AxiRandomTrafficGenerator(const Params& p)
    : AXIMMTrafficGenerator(p)
{
    AxiRandomStrategy::Config cfg;
    cfg.seed = p.seed;

    cfg.nsu_selection = parseNsuSelectionMode(p.nsu_selection);
    cfg.nsu_index_distribution = parseDistribution(p.nsu_index_distribution);
    cfg.nsu_index_binomial_probability = p.nsu_index_binomial_probability;

    cfg.address_distribution = parseDistribution(p.address_distribution);
    cfg.address_binomial_probability = p.address_binomial_probability;
    cfg.address_increment = p.address_increment;

    cfg.transaction_size_distribution = parseDistribution(p.transaction_size_distribution);
    cfg.min_transaction_size_bytes = p.min_transaction_size_bytes;
    cfg.max_transaction_size_bytes = p.max_transaction_size_bytes;
    cfg.transaction_size_binomial_probability = p.transaction_size_binomial_probability;

    cfg.gap_distribution = parseDistribution(p.gap_distribution);
    cfg.min_gap_cycles = p.min_gap_cycles;
    cfg.max_gap_cycles = p.max_gap_cycles;
    cfg.gap_binomial_probability = p.gap_binomial_probability;

    cfg.awid_distribution = parseDistribution(p.awid_distribution);
    cfg.min_awid = p.min_awid;
    cfg.max_awid = p.max_awid;
    cfg.awid_binomial_probability = p.awid_binomial_probability;

    cfg.arid_distribution = parseDistribution(p.arid_distribution);
    cfg.min_arid = p.min_arid;
    cfg.max_arid = p.max_arid;
    cfg.arid_binomial_probability = p.arid_binomial_probability;

    cfg.read_write_mode = parseRWMode(p.read_write_mode);
    cfg.max_outstanding_writes = p.max_outstanding_writes;
    cfg.max_outstanding_reads = p.max_outstanding_reads;
    cfg.max_write_commands = p.max_write_commands;
    cfg.align_addresses = p.align_addresses;
    const uint32_t interface_bytes = std::max<uint32_t>(1, p.data_width / 8);
    cfg.beat_size_bytes = p.beat_size_bytes ? p.beat_size_bytes : interface_bytes;
    panic_if(!isPowerOfTwo(cfg.beat_size_bytes),
        "AxiRandomTrafficGenerator: beat_size_bytes (%u) must be a power of two",
        cfg.beat_size_bytes);
    panic_if(cfg.beat_size_bytes > interface_bytes,
        "AxiRandomTrafficGenerator: beat_size_bytes (%u) cannot exceed interface width (%u bytes)",
        cfg.beat_size_bytes, interface_bytes);

    
    // Bandwidth is set on the traffic generator base (TrafficGenerator params), not in strategy config

    auto* gen = axiGenerator();
    if (gen) {
        if (!gen->setMode(cfg)) {
            panic("AxiRandomTrafficGenerator: setMode failed");
        }
        gen->reset();
        // Base constructor already called updateAxiCurrentState() with default config.
        // Regenerate with our config so the first message uses the NSU list (base_addr/max_addr).
        updateAxiCurrentState();
    }
}

} // namespace noc
} // namespace gem5

