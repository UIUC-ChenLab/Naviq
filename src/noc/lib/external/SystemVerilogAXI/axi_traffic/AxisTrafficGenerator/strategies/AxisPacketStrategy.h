#ifndef AXIS_PACKET_STRATEGY_H
#define AXIS_PACKET_STRATEGY_H

#include "AxisTrafficStrategy.h"
#include "AxisPacketUtils.h"

#include <cstdint>
#include <memory>
#include <random>
#include <string>
#include <vector>

class AxisPacketStrategy : public AxisTrafficStrategy
{
  public:
    struct Config {
        std::string profile = "mixed_tcp_udp";
        uint32_t max_packets = 16;
        uint32_t seed = 1;
        uint32_t min_payload_bytes = 16;
        uint32_t max_payload_bytes = 64;
        uint32_t flow_count = 1;
        uint32_t min_gap_cycles = 0;
        uint32_t max_gap_cycles = 0;
        uint32_t initial_gap_cycles = 0;
        uint32_t data_width = 512;
        uint32_t tid_width = 16;
        uint32_t tdest_width = 12;
        uint32_t tid = 0;
        uint32_t tdest = 0;
        uint32_t tuser = 0;
        uint32_t src_ip = 0xc0a80164u;
        uint32_t dst_ip = 0x08080808u;
        uint16_t src_port = 12345;
        uint16_t dst_port = 80;
        bool corrupt_ipv4_checksum = false;
        bool corrupt_l4_checksum = false;
        uint32_t prefix_bytes = 0;
        uint32_t prefix_value = 0;
        bool include_ethernet = false;
        uint64_t src_mac = 0x020000000001ULL;
        uint64_t dst_mac = 0x020000000002ULL;
        uint16_t ether_type = 0x0800;
    };

    AxisPacketStrategy();

    void configure(const Config& config);
    void tick(AxisInterface& channel) override;
    void calculateNextValues(AxisInterface& channel) override;
    bool hasMoreData() const override;
    void reset() override;
    std::string getModeName() const override { return "packet"; }
    std::string getConfigString() const override;

  private:
    Config config_;
    std::vector<axis_packet::AxisBeat> stream_;
    std::shared_ptr<std::mt19937> rng_;
    std::uniform_int_distribution<uint32_t> gap_dist_;

    size_t current_beat_index_;
    uint32_t current_packets_sent_;
    uint32_t current_gap_cycles_remaining_;

    size_t next_beat_index_;
    uint32_t next_packets_sent_;
    uint32_t next_gap_cycles_remaining_;

    void rebuildStream();
    void clearNextBeat();
    void loadNextBeat(const axis_packet::AxisBeat& beat);
};

#endif // AXIS_PACKET_STRATEGY_H
