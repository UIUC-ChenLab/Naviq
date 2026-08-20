#ifndef AXIS_PCAP_STRATEGY_H
#define AXIS_PCAP_STRATEGY_H

#include "AxisTrafficStrategy.h"
#include <pcap/pcap.h>
#include <cstring>
#include <string>
#include <algorithm>
#include <fstream>
#include <sstream>
#include <iostream>
#include <cstdint>
#include <cmath>
#include <memory>
#include <vector>

// PCAP replay traffic generation strategy
// Reads and replays packets from a PCAP file with timing information
class AxisPcapStrategy : public AxisTrafficStrategy {
public:
    struct Config {
        std::string pcap_file_path = "data/pcap/test.pcap";
        double speed_multiplier = 1.0;        // 1.0 = real-time, 2.0 = 2x speed, etc.
        bool preserve_timestamps = true;      // Use original packet timings
        uint64_t max_packets = 0;            // Maximum packets to replay (0 = all)
        double clock_period_ns = 1.0;   // Clock period in nanoseconds
        uint64_t tdest = 0; // destination TID for packets
    };
    
    AxisPcapStrategy();
    
    ~AxisPcapStrategy() override;
    
    // Configure the strategy programmatically
    void configure(const Config& config);
    
    // AxisTrafficStrategy interface
    void tick(AxisInterface& channel) override;
    void calculateNextValues(AxisInterface& channel) override;

    bool hasMoreData() const override { return !finished_; }
    void reset() override;
    std::string getModeName() const override { return "pcap_replay"; }
    std::string getConfigString() const override;
    
    // Get replay statistics
    uint64_t getPacketsSent() const { return current_packet_counter_; }

private:
    Config config_;
    
    // PCAP file info
    pcap_t* pcap_handle_;
    int precision_type_;
    bool finished_;

    // Simulation timing
    uint64_t simulation_time_cycles_;
    uint64_t first_packet_timestamp_us_;
    
    // Current State
    uint64_t current_packet_counter_;
    size_t current_bytes_sent_in_packet_;
    bool current_in_packet_;
    size_t current_packet_size_bytes_;
    uint64_t current_packet_timestamp_us_;
    
    // Next state
    uint32_t next_packet_size_bytes_;
    uint32_t next_bytes_sent_in_packet_;
    bool next_in_packet_;
    uint64_t next_packet_timestamp_us_;
    uint64_t next_packet_counter_;
    
    // Helper methods
    bool loadPcapFile(const std::string& file_path);
    bool parsePcapFile(std::ifstream& file);
    void startNextPacket();
    uint64_t calculateNextPacketCycle() const;
};

#endif // AXIS_PCAP_STRATEGY_H

