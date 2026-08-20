#include "AxiTrafficStrategy.h"
#include <cstring>

AxiTrafficStrategy::AxiTrafficStrategy()
    : enable_read_write_verification_(true),
      read_write_comparisons_(0),
      read_write_mismatches_(0)
{
}

void AxiTrafficStrategy::processResponses(const AxiInterface& axi_interface) {
    processBResponses(axi_interface);
    processRResponses(axi_interface);
}

void AxiTrafficStrategy::initializeWriteRequestTracking() {
    size_t max_id = getMaxAxiId();
    sent_write_requests_by_id_.clear();
    sent_write_requests_by_id_.resize(max_id + 1);
    finished_writes_.clear();
    if (enable_read_write_verification_) {
        completed_write_data_.clear();
    }
}

void AxiTrafficStrategy::processBResponses(const AxiInterface& axi_interface) {
    const AxiBChannel& b_channel = axi_interface.getBChannel();
    
    // Check if bresp is valid and ready (handshake complete)
    if (b_channel.getBValid() && b_channel.getBReady()) {
        uint64_t bid = b_channel.getBId();
        size_t max_id = getMaxAxiId();
        
        // Bounds check to prevent out-of-bounds access
        if (bid <= max_id && bid < sent_write_requests_by_id_.size()) {
            std::deque<WriteRequestInfo>& id_queue = sent_write_requests_by_id_[bid];
            
            // Pop the head of this ID's queue (bresps must be in order within an ID)
            if (!id_queue.empty()) {
                WriteRequestInfo completed_write = id_queue.front();
                id_queue.pop_front();
                
                // If verification is enabled, store write data by address for later comparison
                if (enable_read_write_verification_ && completed_write.write_data) {
                    completed_write_data_[completed_write.addr] = std::make_pair(
                        completed_write.transaction_size_bytes,
                        completed_write.write_data
                    );
                }
                
                // Move to finished_writes_ deque (order may be out of order across IDs)
                finished_writes_.push_back(completed_write);
            }
        }
    }
}

bool AxiTrafficStrategy::allWritesCompleted() const {
    // Check if all ID queues are empty
    for (const auto& id_queue : sent_write_requests_by_id_) {
        if (!id_queue.empty()) {
            return false;
        }
    }
    return true;
}

size_t AxiTrafficStrategy::countOutstandingWrites() const {
    size_t count = 0;
    for (const auto& id_queue : sent_write_requests_by_id_) {
        count += id_queue.size();
    }
    return count;
}

void AxiTrafficStrategy::initializeReadRequestTracking() {
    size_t max_arid = getMaxArId();
    sent_read_requests_by_id_.clear();
    sent_read_requests_by_id_.resize(max_arid + 1);
    if (enable_read_write_verification_) {
        in_flight_read_data_.clear();
    }
}

void AxiTrafficStrategy::processRResponses(const AxiInterface& axi_interface) {
    const AxiRChannel& r_channel = axi_interface.getRChannel();
    
    // Check if rresp is valid and ready (handshake complete)
    if (r_channel.getRValid() && r_channel.getRReady()) {
        uint64_t rid = r_channel.getRId();
        size_t max_arid = getMaxArId();
        
        // Bounds check to prevent out-of-bounds access
        if (rid <= max_arid && rid < sent_read_requests_by_id_.size()) {
            std::deque<ReadRequestInfo>& id_queue = sent_read_requests_by_id_[rid];
            
            if (!id_queue.empty()) {
                const ReadRequestInfo& read_info = id_queue.front();
                uint64_t read_addr = read_info.addr;
                uint32_t read_size = read_info.transaction_size_bytes;
                
                // Accumulate read data if verification is enabled
                if (enable_read_write_verification_) {
                    const DataView& r_data = r_channel.getRData();
                    size_t bytes_per_beat = r_data.size();
                    
                    // Initialize or extend the accumulated read data buffer
                    if (in_flight_read_data_.find(read_addr) == in_flight_read_data_.end()) {
                        in_flight_read_data_[read_addr] = std::vector<uint8_t>();
                        in_flight_read_data_[read_addr].reserve(read_size);
                    }
                    
                    // Append this beat's data (only up to transaction size)
                    auto& acc_data = in_flight_read_data_[read_addr];
                    size_t remaining = read_size - acc_data.size();
                    size_t bytes_to_copy = std::min(bytes_per_beat, remaining);
                    acc_data.insert(acc_data.end(), r_data.data(), r_data.data() + bytes_to_copy);
                }
                
                // Process when RLAST is asserted (completes the read transaction)
                if (r_channel.getRLast()) {
                    // Verify read data if verification is enabled
                    if (enable_read_write_verification_) {
                        auto it = in_flight_read_data_.find(read_addr);
                        if (it != in_flight_read_data_.end()) {
                            const std::vector<uint8_t>& read_data = it->second;
                            
                            // Only verify if we have the expected amount of data
                            if (read_data.size() == read_size) {
                                // Compare with stored write data
                                bool match = verifyReadData(read_addr, read_size, read_data.data());
                                read_write_comparisons_++;
                                if (!match) {
                                    read_write_mismatches_++;
                                }
                            }
                            
                            // Clean up accumulated data
                            in_flight_read_data_.erase(it);
                        }
                    }
                    
                    // Pop the head of this ID's queue (rresps must be in order within an ID)
                    id_queue.pop_front();
                }
            }
        }
    }
}

void AxiTrafficStrategy::trackSentWriteRequest(uint32_t awid, uint64_t addr, uint32_t transaction_size_bytes,
                                               const std::shared_ptr<AxiWriteCommand>& write_cmd) {
    size_t max_id = getMaxAxiId();
    
    // Bounds check to prevent out-of-bounds access
    if (awid <= max_id && awid < sent_write_requests_by_id_.size()) {
        std::shared_ptr<std::vector<uint8_t>> write_data = nullptr;
        
        // If verification is enabled, extract write data from the command
        if (enable_read_write_verification_ && write_cmd) {
            auto wdata_view = write_cmd->getWData();
            if (wdata_view && wdata_view->size() > 0) {
                // Copy the write data (only copy the transaction size, not the full buffer)
                size_t data_size = std::min(static_cast<size_t>(transaction_size_bytes), wdata_view->size());
                write_data = std::make_shared<std::vector<uint8_t>>(
                    wdata_view->data(), 
                    wdata_view->data() + data_size
                );
            }
        }
        
        if (write_data) {
            sent_write_requests_by_id_[awid].emplace_back(addr, awid, transaction_size_bytes, write_data);
        } else {
            sent_write_requests_by_id_[awid].emplace_back(addr, awid, transaction_size_bytes);
        }
    }
}

void AxiTrafficStrategy::trackSentReadRequest(uint32_t arid, uint64_t addr, uint32_t transaction_size_bytes) {
    size_t max_arid = getMaxArId();
    
    // Bounds check to prevent out-of-bounds access
    if (arid <= max_arid && arid < sent_read_requests_by_id_.size()) {
        sent_read_requests_by_id_[arid].emplace_back(addr, arid, transaction_size_bytes);
    }
}

bool AxiTrafficStrategy::allReadsCompleted() const {
    // Check if all ID queues are empty
    for (const auto& id_queue : sent_read_requests_by_id_) {
        if (!id_queue.empty()) {
            return false;
        }
    }
    return true;
}

size_t AxiTrafficStrategy::countOutstandingReads() const {
    size_t count = 0;
    for (const auto& id_queue : sent_read_requests_by_id_) {
        count += id_queue.size();
    }
    return count;
}

bool AxiTrafficStrategy::isFullyDone() const {
    ReadWriteMode mode = getReadWriteMode();
    
    // For WRITE_ONLY mode: check if all writes are completed and no more data to generate
    if (mode == ReadWriteMode::WRITE_ONLY) {
        return !hasMoreData() && allWritesCompleted();
    }
    
    // For INTERLEAVED and SEQUENTIAL modes: check if all writes and reads are completed
    // and no more data to generate
    return !hasMoreData() && allWritesCompleted() && allReadsCompleted();
}

void AxiTrafficStrategy::setReadWriteVerification(bool enable) {
    enable_read_write_verification_ = enable;
    if (!enable) {
        // Clear verification data when disabling
        completed_write_data_.clear();
        in_flight_read_data_.clear();
    }
    // Always reset statistics when changing verification state
    resetVerificationStatistics();
}

void AxiTrafficStrategy::resetVerificationStatistics() {
    read_write_comparisons_ = 0;
    read_write_mismatches_ = 0;
    if (!enable_read_write_verification_) {
        // Also clear data structures when statistics are reset and verification is disabled
        completed_write_data_.clear();
        in_flight_read_data_.clear();
    }
}

bool AxiTrafficStrategy::verifyReadData(uint64_t addr, uint32_t size, const uint8_t* read_data) {
    // Look up stored write data for this address
    auto it = completed_write_data_.find(addr);
    if (it == completed_write_data_.end()) {
        // No write data stored for this address
        return false;
    }
    
    uint32_t stored_size = it->second.first;
    const std::shared_ptr<std::vector<uint8_t>>& stored_data = it->second.second;
    
    // Check if sizes match
    if (stored_size != size) {
        return false;
    }
    
    // Compare data byte by byte
    if (stored_data->size() < size) {
        return false;
    }
    
    return std::memcmp(stored_data->data(), read_data, size) == 0;
}

