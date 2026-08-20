#include "AxisPacketStrategy.h"

#include <algorithm>
#include <sstream>

AxisPacketStrategy::AxisPacketStrategy()
    : AxisTrafficStrategy(),
      rng_(std::make_shared<std::mt19937>(1)),
      gap_dist_(0, 0)
{
    reset();
}

void
AxisPacketStrategy::configure(const Config& config)
{
    config_ = config;
    if (config_.max_payload_bytes < config_.min_payload_bytes) {
        std::swap(config_.max_payload_bytes, config_.min_payload_bytes);
    }

    rng_ = std::make_shared<std::mt19937>(config_.seed ^ 0x5eed1234u);
    gap_dist_ = std::uniform_int_distribution<uint32_t>(
        config_.min_gap_cycles,
        std::max(config_.min_gap_cycles, config_.max_gap_cycles));
    rebuildStream();
    reset();
}

void
AxisPacketStrategy::rebuildStream()
{
    const auto profile = axis_packet::parseProfile(config_.profile);
    stream_ = axis_packet::buildAxisPacketStream(
        profile,
        config_.max_packets,
        std::max<uint32_t>(1, config_.flow_count),
        config_.min_payload_bytes,
        config_.max_payload_bytes,
        config_.seed,
        config_.data_width,
        config_.tid_width,
        config_.tdest_width,
        config_.tid,
        config_.tdest,
        config_.tuser,
        config_.src_ip,
        config_.dst_ip,
        config_.src_port,
        config_.dst_port,
        config_.corrupt_ipv4_checksum,
        config_.corrupt_l4_checksum,
        config_.prefix_bytes,
        config_.prefix_value,
        config_.include_ethernet,
        config_.src_mac,
        config_.dst_mac,
        config_.ether_type);
}

void
AxisPacketStrategy::reset()
{
    resetCommonState();
    next_tvalid_ = false;
    next_tlast_ = false;
    next_tid_ = 0;
    next_tdest_ = 0;

    current_beat_index_ = 0;
    current_packets_sent_ = 0;
    current_gap_cycles_remaining_ = config_.initial_gap_cycles;

    next_beat_index_ = 0;
    next_packets_sent_ = 0;
    next_gap_cycles_remaining_ = config_.initial_gap_cycles;

    if (current_tdata_.size() > 0) {
        std::fill(current_tdata_.begin(), current_tdata_.end(), 0);
    }
    if (next_tdata_.size() > 0) {
        std::fill(next_tdata_.begin(), next_tdata_.end(), 0);
    }
    std::fill(current_tkeep_.begin(), current_tkeep_.end(), UBit(1, 0));
    std::fill(next_tkeep_.begin(), next_tkeep_.end(), UBit(1, 0));
    if (current_tuser_.size() > 0) {
        std::fill(current_tuser_.begin(), current_tuser_.end(), 0);
    }
    if (next_tuser_.size() > 0) {
        std::fill(next_tuser_.begin(), next_tuser_.end(), 0);
    }
}

bool
AxisPacketStrategy::hasMoreData() const
{
    return current_tvalid_ || current_beat_index_ < stream_.size();
}

void
AxisPacketStrategy::clearNextBeat()
{
    next_tvalid_ = false;
    next_tlast_ = false;
    next_tid_ = 0;
    next_tdest_ = 0;

    if (next_tdata_.size() > 0) {
        std::fill(next_tdata_.begin(), next_tdata_.end(), 0);
    }
    std::fill(next_tkeep_.begin(), next_tkeep_.end(), UBit(1, 0));
    if (next_tuser_.size() > 0) {
        std::fill(next_tuser_.begin(), next_tuser_.end(), 0);
    }
}

void
AxisPacketStrategy::loadNextBeat(const axis_packet::AxisBeat& beat)
{
    next_tvalid_ = beat.tvalid;
    next_tlast_ = beat.tlast;
    next_tid_ = beat.tid;
    next_tdest_ = beat.tdest;

    if (next_tdata_.size() > 0) {
        std::fill(next_tdata_.begin(), next_tdata_.end(), 0);
        const size_t bytes = std::min(next_tdata_.size(), beat.tdata.size());
        std::copy(beat.tdata.begin(), beat.tdata.begin() + bytes,
                  next_tdata_.begin());
    }

    for (size_t i = 0; i < next_tkeep_.size(); ++i) {
        next_tkeep_[i] = UBit(1, (beat.tkeep >> i) & 0x1);
    }

    if (next_tuser_.size() > 0) {
        std::fill(next_tuser_.begin(), next_tuser_.end(), 0);
        for (size_t i = 0; i < next_tuser_.size(); ++i) {
            next_tuser_[i] = static_cast<uint8_t>((beat.tuser >> (8 * i)) & 0xff);
        }
    }
}

void
AxisPacketStrategy::calculateNextValues(AxisInterface& channel)
{
    next_tvalid_ = current_tvalid_;
    next_tlast_ = current_tlast_;
    next_tid_ = current_tid_;
    next_tdest_ = current_tdest_;
    next_beat_index_ = current_beat_index_;
    next_packets_sent_ = current_packets_sent_;
    next_gap_cycles_remaining_ = current_gap_cycles_remaining_;

    if (!channel.getTReady()) {
        return;
    }

    if (current_tvalid_) {
        if (current_tlast_) {
            ++next_packets_sent_;
            if (next_beat_index_ + 1 < stream_.size()) {
                next_gap_cycles_remaining_ = gap_dist_(*rng_);
            }
        }
        ++next_beat_index_;
    }

    if (next_packets_sent_ >= config_.max_packets ||
        next_beat_index_ >= stream_.size()) {
        clearNextBeat();
        return;
    }

    if (next_gap_cycles_remaining_ > 0) {
        --next_gap_cycles_remaining_;
        clearNextBeat();
        return;
    }

    loadNextBeat(stream_[next_beat_index_]);
}

void
AxisPacketStrategy::tick(AxisInterface& channel)
{
    (void)channel;

    current_tvalid_ = next_tvalid_;
    current_tlast_ = next_tlast_;
    current_tid_ = next_tid_;
    current_tdest_ = next_tdest_;

    if (current_tdata_.size() > 0) {
        std::copy(next_tdata_.begin(), next_tdata_.end(), current_tdata_.begin());
    }
    std::copy(next_tkeep_.begin(), next_tkeep_.end(), current_tkeep_.begin());
    if (current_tuser_.size() > 0) {
        std::copy(next_tuser_.begin(), next_tuser_.end(), current_tuser_.begin());
    }

    current_beat_index_ = next_beat_index_;
    current_packets_sent_ = next_packets_sent_;
    current_gap_cycles_remaining_ = next_gap_cycles_remaining_;
}

std::string
AxisPacketStrategy::getConfigString() const
{
    std::ostringstream os;
    os << "mode=packet"
       << ",profile=" << config_.profile
       << ",packets=" << config_.max_packets
       << ",payload=" << config_.min_payload_bytes
       << "-" << config_.max_payload_bytes
       << ",corrupt_ipv4_checksum=" << config_.corrupt_ipv4_checksum
       << ",corrupt_l4_checksum=" << config_.corrupt_l4_checksum
       << ",prefix_bytes=" << config_.prefix_bytes
       << ",prefix_value=" << config_.prefix_value;
    return os.str();
}
