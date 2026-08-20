#include "AxisTrafficStrategy.h"

AxisTrafficStrategy::AxisTrafficStrategy()
    : current_tvalid_(false),
    current_tlast_(false),
    current_tid_(0),
    current_tdest_(0)
{   

}

void AxisTrafficStrategy::initializeBuffers(AxisInterface& channel) {
    // Initialize tdata buffer and view
    size_t tdata_size = channel.getTData().size();
    if (!current_tdata_buffer_ || current_tdata_.size() != tdata_size) {
        current_tdata_buffer_ = std::make_shared<std::vector<uint8_t>>(tdata_size, 0);
        current_tdata_ = DataView(current_tdata_buffer_, tdata_size, 0);
    }
    if (!next_tdata_buffer_ || next_tdata_.size() != tdata_size) {
        next_tdata_buffer_ = std::make_shared<std::vector<uint8_t>>(tdata_size, 0);
        next_tdata_ = DataView(next_tdata_buffer_, tdata_size, 0);
    }
    
    // Initialize tkeep vector
    size_t tkeep_size = channel.getTKeep().size();
    if (current_tkeep_.size() != tkeep_size) {
        current_tkeep_.clear();
        for(int i = 0; i < tkeep_size; i++) {
            current_tkeep_.push_back(UBit(1, 0));
        }
    }
    if (next_tkeep_.size() != tkeep_size) {
        next_tkeep_.clear();
        for(int i = 0; i < tkeep_size; i++) {
            next_tkeep_.push_back(UBit(1, 0));
        }
    }
    
    // Initialize tuser buffer and view
    size_t tuser_size = channel.getTUser().size();
    if (tuser_size > 0) {
        if (!current_tuser_buffer_ || current_tuser_.size() != tuser_size) {
            current_tuser_buffer_ = std::make_shared<std::vector<uint8_t>>(tuser_size, 0);
            current_tuser_ = DataView(current_tuser_buffer_, tuser_size, 0);
        }
        if (!next_tuser_buffer_ || next_tuser_.size() != tuser_size) {
            next_tuser_buffer_ = std::make_shared<std::vector<uint8_t>>(tuser_size, 0);
            next_tuser_ = DataView(next_tuser_buffer_, tuser_size, 0);
        }
    }
}

void AxisTrafficStrategy::resetCommonState() {
    current_tvalid_ = false;
    current_tlast_ = false;
    current_tid_ = 0;
    current_tdest_ = 0;
}

void AxisTrafficStrategy::setInterfaceValues(
    AxisInterface& channel
) {

    // Copy stored state to channel
    channel.setTValid(current_tvalid_);
    channel.setTLast(current_tlast_);
    channel.setTId(current_tid_);
    channel.setTDest(current_tdest_);
    channel.setTData(current_tdata_);
    channel.setTKeep(current_tkeep_);
    if (current_tuser_.size() > 0) {
        channel.setTUser(current_tuser_);
    }
}

void AxisTrafficStrategy::tick(AxisInterface& channel) {
    // Copy next state to current state
    current_tvalid_ = next_tvalid_;
    current_tlast_ = next_tlast_;
    current_tid_ = next_tid_;
    current_tdest_ = next_tdest_;

    // Copy next state to current state
    current_tdata_ = next_tdata_;
    if (next_tdata_.size() > 0) {
        std::copy(next_tkeep_.begin(), next_tkeep_.end(), current_tkeep_.begin());
        std::copy(next_tdata_.begin(), next_tdata_.end(), current_tdata_.begin());
    }
    if (next_tuser_.size() > 0) {
        std::copy(next_tuser_.begin(), next_tuser_.end(), current_tuser_.begin());
    }   
}