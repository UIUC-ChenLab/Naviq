#include "noc/endpoints/generator/AxisPcapTrafficGenerator.hh"

#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxisTrafficGenerator/strategies/AxisPcapStrategy.h"

#include <string>

namespace gem5 {
namespace noc {

AxisPcapTrafficGenerator::AxisPcapTrafficGenerator(const Params& p)
    : AXISTrafficGenerator(p)
{
    AxisPcapStrategy::Config cfg;
    cfg.pcap_file_path = p.pcap_file_path;
    cfg.speed_multiplier = p.speed_multiplier;
    cfg.preserve_timestamps = p.preserve_timestamps;
    cfg.max_packets = p.max_packets;
    cfg.clock_period_ns = p.clock_period_ns;
    cfg.tdest = p.tdest;

    auto* gen = axisGenerator();
    if (gen) {
        gen->setMode(cfg);
        gen->reset();
        updateAxisCurrentState();
    }
}

} // namespace noc
} // namespace gem5


