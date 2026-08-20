#include "noc/endpoints/generator/AxisPacketTrafficGenerator.hh"

#include "noc/lib/AxisPacketUtils.hh"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxisTrafficGenerator/strategies/AxisPacketStrategy.h"

namespace gem5
{
namespace noc
{

AxisPacketTrafficGenerator::AxisPacketTrafficGenerator(const Params& p)
    : AXISTrafficGenerator(p)
{
    AxisPacketStrategy::Config cfg;
    cfg.profile = p.profile;
    cfg.max_packets = p.max_packets;
    cfg.seed = p.seed;
    cfg.min_payload_bytes = p.min_payload_bytes;
    cfg.max_payload_bytes = p.max_payload_bytes;
    cfg.flow_count = p.flow_count;
    cfg.min_gap_cycles = p.min_gap_cycles;
    cfg.max_gap_cycles = p.max_gap_cycles;
    cfg.initial_gap_cycles = p.initial_gap_cycles;
    cfg.data_width = p.data_width;
    cfg.tid_width = p.tid_width;
    cfg.tdest_width = p.tdest_width;
    cfg.tid = p.tid;
    cfg.tdest = p.tdest;
    cfg.tuser = p.tuser;
    cfg.src_ip = axis_packet::parseIpv4Address(p.src_ip, 0xc0a80164u);
    cfg.dst_ip = axis_packet::parseIpv4Address(p.dst_ip, 0x08080808u);
    cfg.src_port = p.src_port;
    cfg.dst_port = p.dst_port;
    cfg.corrupt_ipv4_checksum = p.corrupt_ipv4_checksum;
    cfg.corrupt_l4_checksum = p.corrupt_l4_checksum;
    cfg.prefix_bytes = p.prefix_bytes;
    cfg.prefix_value = p.prefix_value;

    auto* gen = axisGenerator();
    if (gen) {
        gen->setMode(cfg);
        gen->reset();
        updateAxisCurrentState();
    }
}

} // namespace noc
} // namespace gem5
