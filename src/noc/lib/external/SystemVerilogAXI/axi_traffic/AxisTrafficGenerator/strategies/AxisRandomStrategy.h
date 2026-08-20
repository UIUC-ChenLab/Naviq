#ifndef AXIS_RANDOM_STRATEGY_H
#define AXIS_RANDOM_STRATEGY_H

#include "AxisTrafficStrategy.h"
#include "Distribution.h"
#include <random>
#include <cstdint>
#include <string>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <iostream>
#include <fstream>
#include <sstream>
#include <json/json.hpp>
#include <memory>


// Random traffic generation strategy
// Generates random packet traffic with configurable parameters
class AxisRandomStrategy : public AxisTrafficStrategy {
public:
    struct Config {
        uint64_t seed = 0;                   // RNG seed (0 = time-based)
        
        // Packet size distribution parameters
        DistributionType packet_size_distribution = DistributionType::UNIFORM;
        uint32_t min_packet_size_bytes = 64;    // Minimum bytes per packet
        uint32_t max_packet_size_bytes = 1500;  // Maximum bytes per packet
        double packet_size_binomial_probability = 0.5;   // Probability for binomial distribution (0.0-1.0)
        
        // Gap distribution parameters
        DistributionType gap_distribution = DistributionType::UNIFORM;
        uint32_t min_gap_cycles = 0;         // Minimum idle cycles between packets
        uint32_t max_gap_cycles = 10;        // Maximum idle cycles between packets
        double gap_binomial_probability = 0.5;   // Probability for binomial distribution (0.0-1.0)
        
        // TID distribution parameters
        DistributionType tid_distribution = DistributionType::UNIFORM;
        uint64_t min_tid = 0;
        uint64_t max_tid = UINT64_MAX;
        double tid_binomial_probability = 0.5;   // Probability for binomial distribution (0.0-1.0)
        
        // TDest distribution parameters
        DistributionType tdest_distribution = DistributionType::UNIFORM;
        uint64_t min_tdest = 0;
        uint64_t max_tdest = UINT64_MAX;
        double tdest_binomial_probability = 0.5;   // Probability for binomial distribution (0.0-1.0)
        
        // Packet count limit
        uint64_t max_packets = 100;                  // Maximum number of packets to send (0 = unlimited)
    };
    
    AxisRandomStrategy();
    
    ~AxisRandomStrategy() override = default;
    
    // Configure the strategy programmatically
    void configure(const Config& config);
    
    // AxisTrafficStrategy interface
    void tick(AxisInterface& channel) override;
    void calculateNextValues(AxisInterface& channel) override;
    bool hasMoreData() const override;
    void reset() override;
    std::string getModeName() const override { return "random"; }
    std::string getConfigString() const override;

private:
    Config config_;
    
    // Random number generator (shared across all distributions)
    std::shared_ptr<std::mt19937> rng_;
    
    // All distributions using polymorphic wrappers
    std::unique_ptr<Distribution<uint32_t>> packet_size_dist_;
    std::unique_ptr<Distribution<uint32_t>> gap_dist_;
    std::unique_ptr<Distribution<uint64_t>> tid_dist_;
    std::unique_ptr<Distribution<uint64_t>> tdest_dist_;
    std::unique_ptr<Distribution<uint8_t>> byte_dist_;
    
    // State
    uint32_t current_packet_size_bytes_;
    uint32_t current_bytes_sent_in_packet_;
    uint32_t gap_cycles_remaining_;
    uint64_t current_packet_counter_;
    bool current_in_packet_;


    // SNext tate
    uint32_t next_packet_size_bytes_;
    uint32_t next_bytes_sent_in_packet_;
    uint32_t next_gap_cycles_remaining_;
    uint64_t next_packet_counter_;
    bool next_in_packet_;
    
    // Helper methods
    void generateRandomData(DataView& tdata);
    void generateRandomUserData(DataView& tuser);
    void startNewPacket();
};

#endif // AXIS_RANDOM_STRATEGY_H

