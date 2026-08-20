#include "AxisPcapStrategy.h"



AxisPcapStrategy::AxisPcapStrategy(

) :
    AxisTrafficStrategy(),
    pcap_handle_(nullptr),
    precision_type_(PCAP_TSTAMP_PRECISION_MICRO),
    simulation_time_cycles_(0),
    first_packet_timestamp_us_(0),
    current_bytes_sent_in_packet_(0),
    current_packet_counter_(0),
    current_in_packet_(false),
    finished_(false)
{
}

AxisPcapStrategy::~AxisPcapStrategy() {
    if (pcap_handle_) {
        pcap_close(pcap_handle_);
        pcap_handle_ = nullptr;
    }
}

void AxisPcapStrategy::configure(const Config& config) {
    config_ = config;
    loadPcapFile(config_.pcap_file_path);
}

bool AxisPcapStrategy::loadPcapFile(const std::string& file_path) {

    char errbuf[PCAP_ERRBUF_SIZE]{0};
    if (pcap_handle_) {
        pcap_close(pcap_handle_);
        pcap_handle_ = nullptr;
    }
    pcap_handle_ = pcap_open_offline(file_path.c_str(), errbuf);
    if (!pcap_handle_) {
        std::cerr << "pcap_open_offline failed: " << errbuf << "\n";
        return false;
    }

    precision_type_ = pcap_get_tstamp_precision(pcap_handle_); // PCAP_TSTAMP_PRECISION_MICRO/NANO
    // const char* prec_str =
    //     (precision_type_ == PCAP_TSTAMP_PRECISION_NANO) ? "ns" :
    //     (precision_type_ == PCAP_TSTAMP_PRECISION_MICRO) ? "us" : "unknown";
    
    return true;
}

void AxisPcapStrategy::reset() {
    resetCommonState();
    
    simulation_time_cycles_ = 0;
    current_bytes_sent_in_packet_ = 0;
    current_packet_counter_ = 0;
    current_in_packet_ = false;
    finished_ = false;

    current_packet_size_bytes_ = 0;
    current_packet_timestamp_us_ = 0;
    current_packet_counter_ = 0;
    current_in_packet_ = false;
    current_tvalid_ = false;
    current_tlast_ = false;
    current_tid_ = 0;
    current_tdest_ = 0;

    next_packet_size_bytes_ = 0;
    next_bytes_sent_in_packet_ = 0;
    next_packet_counter_ = 0;
    next_in_packet_ = false;
    next_tid_ = 0;
    next_tdest_ = 0;
    next_tdata_ = current_tdata_;
    next_tkeep_ = current_tkeep_;
    next_tuser_ = current_tuser_;
    next_tvalid_ = false;
    next_tlast_ = false;
    
    loadPcapFile(config_.pcap_file_path);
}

void AxisPcapStrategy::calculateNextValues(AxisInterface& channel) {

    // Copy current state to next state
    next_packet_size_bytes_ = current_packet_size_bytes_;
    next_bytes_sent_in_packet_ = current_bytes_sent_in_packet_;
    next_packet_counter_ = current_packet_counter_;
    next_in_packet_ = current_in_packet_;
    next_tid_ = current_tid_;
    next_tdest_ = current_tdest_;
    next_tvalid_ = current_tvalid_;
    next_tlast_ = current_tlast_;
    next_packet_timestamp_us_ = current_packet_timestamp_us_;



    // Only advance state if tready is asserted
    bool tready = channel.getTReady();
    if (!tready) {
        return;
    }
    
    if (finished_) {
        next_tvalid_ = false;
        return;
    }
    
    // Handle end of packet from previous cycle
    if (current_tlast_) {
        next_in_packet_ = false;
    }
    
    // Get channel width from the interface
    size_t keep_width = channel.getTKeep().size();
    
    // Continue current packet or start new one
    if (!next_in_packet_) {
        if (config_.max_packets != 0 && current_packet_counter_ >= config_.max_packets) {
            finished_ = true;
            current_tvalid_ = false;
            return;
        }
        // Start new packet
        pcap_pkthdr* next_packet_hdr = nullptr;
        const u_char* next_packet_data = nullptr;
        int rc = pcap_next_ex(pcap_handle_, &next_packet_hdr, &next_packet_data);
        if (rc != 1) {
            finished_ = true;
            current_tvalid_ = false;
            return;
        }
        uint64_t packet_subsec = next_packet_hdr->ts.tv_usec;
        if (precision_type_ == PCAP_TSTAMP_PRECISION_NANO) {
            packet_subsec /= 1000;
        }
        next_packet_timestamp_us_ = next_packet_hdr->ts.tv_sec * 1000000 + packet_subsec;
        if (current_packet_counter_ == 0) {
            first_packet_timestamp_us_ = next_packet_timestamp_us_;
        }
        next_packet_counter_ = current_packet_counter_ + 1;
        next_bytes_sent_in_packet_ = 0;
        next_packet_size_bytes_ = next_packet_hdr->len;
        
        // Store packet data for this packet        
        next_in_packet_ = true;
    }

    uint64_t current_sim_time_ns = simulation_time_cycles_ * config_.clock_period_ns;
    uint64_t current_sim_time_us = current_sim_time_ns / 1000;

    uint64_t target_start_time_us = next_packet_timestamp_us_ - first_packet_timestamp_us_;

    if (current_sim_time_us < target_start_time_us && config_.preserve_timestamps) {
        next_tvalid_ = false;
        return;
    }


    // Determine how many bytes to send this beat
    size_t bytes_remaining = next_packet_size_bytes_ - next_bytes_sent_in_packet_;
    size_t bytes_to_send = std::min(bytes_remaining, keep_width);
    
    // Copy packet data to tdata
    std::fill(next_tdata_.begin(), next_tdata_.end(), 0x42); // Default fill
    
    // Set tkeep
    for(size_t i = 0; i < keep_width; i++) {
        if (i < bytes_to_send) {
            next_tkeep_[i] = UBit(1, 1);
        } else {
            next_tkeep_[i] = UBit(1, 0);
        }
    }

    next_tid_ = 0;
    next_tdest_ = config_.tdest;

    next_tvalid_ = (bytes_to_send > 0);
    next_bytes_sent_in_packet_ += bytes_to_send;
    next_tlast_ = (next_bytes_sent_in_packet_ >= next_packet_size_bytes_);
}

void AxisPcapStrategy::tick(AxisInterface& channel) {
    
    AxisTrafficStrategy::tick(channel);
    simulation_time_cycles_ += 1;
    current_packet_size_bytes_ = next_packet_size_bytes_;
    current_bytes_sent_in_packet_ = next_bytes_sent_in_packet_;
    current_packet_counter_ = next_packet_counter_;
    current_in_packet_ = next_in_packet_;
    current_packet_timestamp_us_ = next_packet_timestamp_us_;

}

std::string AxisPcapStrategy::getConfigString() const {
    std::ostringstream oss;
    oss << "mode=pcap_replay"
        << ",file=" << config_.pcap_file_path
        << ",speed_multiplier=" << config_.speed_multiplier
        << ",preserve_timestamps=" << (config_.preserve_timestamps ? "true" : "false")
        << ",max_packets=" << config_.max_packets
        << ",clock_period_ns=" << config_.clock_period_ns;
    return oss.str();
}

