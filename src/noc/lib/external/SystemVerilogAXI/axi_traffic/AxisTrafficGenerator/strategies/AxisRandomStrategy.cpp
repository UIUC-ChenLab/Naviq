#include "AxisRandomStrategy.h"

AxisRandomStrategy::AxisRandomStrategy()
    : AxisTrafficStrategy(),
    rng_(std::make_shared<std::mt19937>(std::chrono::steady_clock::now().time_since_epoch().count())),
    packet_size_dist_(createDistribution<uint32_t>(rng_, DistributionType::UNIFORM, 64, 1500)),
    gap_dist_(createDistribution<uint32_t>(rng_, DistributionType::UNIFORM, 0, 10)),
    tid_dist_(createDistribution<uint64_t>(rng_, DistributionType::FIXED, 0)),
    tdest_dist_(createDistribution<uint64_t>(rng_, DistributionType::FIXED, 0)),
    byte_dist_(createDistribution<uint8_t>(rng_, DistributionType::UNIFORM, 0, 255)),
    current_packet_counter_(0),
    current_in_packet_(false)
{
    reset();
}

void AxisRandomStrategy::configure(const Config& config) {
    config_ = config;
    
    // Initialize RNG with seed
    if (config_.seed == 0) {
        rng_ = std::make_shared<std::mt19937>(std::chrono::steady_clock::now().time_since_epoch().count());
    } else {
        rng_ = std::make_shared<std::mt19937>(config_.seed);
    }
    
    // Set up all distributions using factory functions with individual probabilities
    packet_size_dist_ = createDistribution<uint32_t>(
        rng_,
        config_.packet_size_distribution,
        config_.min_packet_size_bytes,
        config_.max_packet_size_bytes,
        config_.packet_size_binomial_probability
    );
    
    gap_dist_ = createDistribution<uint32_t>(
        rng_,
        config_.gap_distribution,
        config_.min_gap_cycles,
        config_.max_gap_cycles,
        config_.gap_binomial_probability
    );
    
    // TID distribution
    tid_dist_ = createDistribution<uint64_t>(
        rng_,
        config_.tid_distribution,
        config_.min_tid,
        config_.max_tid,
        config_.tid_binomial_probability
    );
    
    // TDest distribution
    tdest_dist_ = createDistribution<uint64_t>(
        rng_,
        config_.tdest_distribution,
        config_.min_tdest,
        config_.max_tdest,
        config_.tdest_binomial_probability
    );
    
    // Byte distribution (always uniform for random data generation)
    byte_dist_ = createDistribution<uint8_t>(
        rng_,
        DistributionType::UNIFORM,
        0,
        255,
        0.5  // Not used for uniform
    );
    
    reset();
}

void AxisRandomStrategy::reset() {
    resetCommonState();
    
    current_packet_size_bytes_ = 0;
    current_bytes_sent_in_packet_ = 0;
    gap_cycles_remaining_ = 0;
    current_packet_counter_ = 0;
    current_in_packet_ = false;

    next_packet_size_bytes_ = 0;
    next_bytes_sent_in_packet_ = 0;
    next_gap_cycles_remaining_ = 0;
    next_packet_counter_ = 0;
    next_in_packet_ = false;
    
    // Start with a gap if configured
    if (config_.min_gap_cycles > 0 || config_.max_gap_cycles > 0) {
        // Distribution handles offset internally, returns value in [min, max]
        gap_cycles_remaining_ = gap_dist_->sample();
    }
}

void AxisRandomStrategy::startNewPacket() {
    // Determine packet size using polymorphic distribution
    // Distribution handles offset internally, returns value in [min, max]
    next_packet_size_bytes_ = packet_size_dist_->sample();
    
    next_in_packet_ = true;
    next_packet_counter_ = current_packet_counter_ + 1;
}

void AxisRandomStrategy::calculateNextValues(AxisInterface& channel) {


    // Copy current state to next state
    next_packet_size_bytes_ = current_packet_size_bytes_;
    next_bytes_sent_in_packet_ = current_bytes_sent_in_packet_;
    next_gap_cycles_remaining_ = gap_cycles_remaining_;
    next_packet_counter_ = current_packet_counter_;
    next_in_packet_ = current_in_packet_;
    next_tid_ = current_tid_;
    next_tdest_ = current_tdest_;
    next_tvalid_ = current_tvalid_;
    next_tlast_ = current_tlast_;

    // Only advance state if tready is asserted
    bool tready = channel.getTReady();
    if (!tready) {
        // When tready is false, preserve current state (already copied above)
        return;
    }

    next_tlast_ = false;
    next_tvalid_ = false;

    if (current_tlast_) {
        next_in_packet_ = false;
        // Schedule next gap
        if (config_.min_gap_cycles > 0 || config_.max_gap_cycles > 0) {
            // Distribution handles offset internally, returns value in [min, max]
            next_gap_cycles_remaining_ = gap_dist_->sample();
        }
    }
    
    // Check if we've reached the maximum number of packets
    // Evaluate the post-handshake state. On the TLAST handshake the current
    // state still says that we are in a packet, but next_in_packet_ has been
    // cleared above. Using the current state here starts an extra packet and
    // makes finite generators run indefinitely.
    if (config_.max_packets > 0 &&
        next_packet_counter_ >= config_.max_packets &&
        !next_in_packet_) {
        next_tvalid_ = false;
        return; // No more packets to generate
    }
    
    // Handle gap between packets
    if (gap_cycles_remaining_ > 0) {
        next_gap_cycles_remaining_--;
        next_tvalid_ = false;
        return; // No valid data this cycle
    }
    
    // Start a new packet if needed
    if (!next_in_packet_) {        
        startNewPacket();
        
        // Set TID and TDest for this packet using distributions
        // Use FIXED distribution type if you want non-random values
        next_tid_ = tid_dist_->sample();
        next_tdest_ = tdest_dist_->sample();

        int32_t bytes_remaining = next_packet_size_bytes_;
        size_t keep_width = channel.getTKeep().size();
        int32_t bytes_this_beat = std::min(bytes_remaining, (int32_t)keep_width);
        for (size_t i = 0; i < current_tkeep_.size(); i++) {
            if (i < bytes_this_beat) {
                next_tkeep_[i] = UBit(1, 1);
            } else {
                next_tkeep_[i] = UBit(1, 0);
            }
        }
        generateRandomData(next_tdata_);
        next_tlast_ = (bytes_this_beat >= next_packet_size_bytes_);
        next_bytes_sent_in_packet_ = bytes_this_beat;
        next_tvalid_ = true;

    } else {

        // Get channel width from the interface
        size_t keep_width = channel.getTKeep().size();
        int32_t bytes_remaining = current_packet_size_bytes_ - current_bytes_sent_in_packet_;
        int32_t bytes_this_beat = std::min(bytes_remaining, (int32_t)keep_width);

        // Set tkeep - all bytes valid for this beat
        for (size_t i = 0; i < keep_width; i++) {
            if (i < bytes_this_beat) {
                next_tkeep_[i] = UBit(1, 1);
            } else {
                next_tkeep_[i] = UBit(1, 0);
            }
        }
        generateRandomData(next_tdata_);
        next_tlast_ = (current_bytes_sent_in_packet_ + bytes_this_beat >= current_packet_size_bytes_);
        next_bytes_sent_in_packet_ = current_bytes_sent_in_packet_ + bytes_this_beat;

        next_tvalid_ = true;
    }

}

bool AxisRandomStrategy::hasMoreData() const {
    // If max_packets is 0, unlimited packets (always return true)
    if (config_.max_packets == 0) {
        return true;
    }
    // Otherwise, check if we've sent fewer than max_packets
    return current_packet_counter_ < config_.max_packets;
}

void AxisRandomStrategy::generateRandomData(DataView& tdata) {
    for (size_t i = 0; i < tdata.size(); i++) {
        tdata[i] = byte_dist_->sample();
    }
}

void AxisRandomStrategy::generateRandomUserData(DataView& tuser) {
    for (size_t i = 0; i < tuser.size(); i++) {
        tuser[i] = byte_dist_->sample();
    }
}

void AxisRandomStrategy::tick(AxisInterface& channel) {

    AxisTrafficStrategy::tick(channel);

    current_packet_size_bytes_ = next_packet_size_bytes_;
    current_bytes_sent_in_packet_ = next_bytes_sent_in_packet_;
    gap_cycles_remaining_ = next_gap_cycles_remaining_;
    current_packet_counter_ = next_packet_counter_;
    current_in_packet_ = next_in_packet_;

}

std::string AxisRandomStrategy::getConfigString() const {
    std::ostringstream oss;
    oss << "mode=random"
        << ",seed=" << config_.seed;
    
    // Packet size distribution
    oss << ",packet_size=" << config_.min_packet_size_bytes 
        << "-" << config_.max_packet_size_bytes;
    if (config_.packet_size_distribution == DistributionType::UNIFORM) {
        oss << ",packet_size_dist=uniform";
    } else if (config_.packet_size_distribution == DistributionType::BINOMIAL) {
        oss << ",packet_size_dist=binomial"
            << ",packet_size_binomial_prob=" << config_.packet_size_binomial_probability;
    } else if (config_.packet_size_distribution == DistributionType::FIXED) {
        oss << ",packet_size_dist=fixed";
    }
    
    // Gap distribution
    oss << ",gap=" << config_.min_gap_cycles 
        << "-" << config_.max_gap_cycles;
    if (config_.gap_distribution == DistributionType::UNIFORM) {
        oss << ",gap_dist=uniform";
    } else if (config_.gap_distribution == DistributionType::BINOMIAL) {
        oss << ",gap_dist=binomial"
            << ",gap_binomial_prob=" << config_.gap_binomial_probability;
    } else if (config_.gap_distribution == DistributionType::FIXED) {
        oss << ",gap_dist=fixed";
    }
    
    // TID distribution
    oss << ",tid=" << config_.min_tid 
        << "-" << config_.max_tid;
    if (config_.tid_distribution == DistributionType::UNIFORM) {
        oss << ",tid_dist=uniform";
    } else if (config_.tid_distribution == DistributionType::BINOMIAL) {
        oss << ",tid_dist=binomial"
            << ",tid_binomial_prob=" << config_.tid_binomial_probability;
    } else if (config_.tid_distribution == DistributionType::FIXED) {
        oss << ",tid_dist=fixed";
    }
    
    // TDest distribution
    oss << ",tdest=" << config_.min_tdest 
        << "-" << config_.max_tdest;
    if (config_.tdest_distribution == DistributionType::UNIFORM) {
        oss << ",tdest_dist=uniform";
    } else if (config_.tdest_distribution == DistributionType::BINOMIAL) {
        oss << ",tdest_dist=binomial"
            << ",tdest_binomial_prob=" << config_.tdest_binomial_probability;
    } else if (config_.tdest_distribution == DistributionType::FIXED) {
        oss << ",tdest_dist=fixed";
    }
    
    // Max packets
    if (config_.max_packets > 0) {
        oss << ",max_packets=" << config_.max_packets;
    }
    
    return oss.str();
}
