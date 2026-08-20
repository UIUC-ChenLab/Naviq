#include "AxiRandomStrategy.h"
#include "AxiInterface.h"

AxiRandomStrategy::AxiRandomStrategy()
    : rng_(std::make_shared<std::mt19937>(std::chrono::steady_clock::now().time_since_epoch().count())),
    address_dist_(nullptr),
    transaction_size_dist_(createDistribution<uint32_t>(rng_, DistributionType::UNIFORM, 64, 512)),
    gap_dist_(createDistribution<uint32_t>(rng_, DistributionType::UNIFORM, 0, 10)),
    awid_dist_(createDistribution<uint64_t>(rng_, DistributionType::FIXED, 0)),
    arid_dist_(createDistribution<uint64_t>(rng_, DistributionType::FIXED, 0)),
    byte_dist_(createDistribution<uint8_t>(rng_, DistributionType::UNIFORM, 0, 255)),
    gap_cycles_remaining_(0),
    transaction_counter_(0),
    in_write_phase_(true),
    next_nsu_index_(0),
    next_nsu_sequence_index_(0),
    rotate_nsu_index_(0),
    rotate_current_addr_(0)
{
    reset();
}

void AxiRandomStrategy::configure(const Config& config) {
    config_ = config;
    
    // Initialize RNG with seed
    if (config_.seed == 0) {
        rng_ = std::make_shared<std::mt19937>(std::chrono::steady_clock::now().time_since_epoch().count());
    } else {
        rng_ = std::make_shared<std::mt19937>(config_.seed);
    }
    
    // Address distribution is per-NSU in generateAddressWithinNsu; no global address_dist_ needed
    address_dist_.reset();
    
    // Set up all distributions
    transaction_size_dist_ = createDistribution<uint32_t>(
        rng_,
        config_.transaction_size_distribution,
        config_.min_transaction_size_bytes,
        config_.max_transaction_size_bytes,
        config_.transaction_size_binomial_probability
    );
    
    gap_dist_ = createDistribution<uint32_t>(
        rng_,
        config_.gap_distribution,
        config_.min_gap_cycles,
        config_.max_gap_cycles,
        config_.gap_binomial_probability
    );
    
    // AWID distribution
    awid_dist_ = createDistribution<uint64_t>(
        rng_,
        config_.awid_distribution,
        config_.min_awid,
        config_.max_awid,
        config_.awid_binomial_probability
    );
    
    // ARID distribution
    arid_dist_ = createDistribution<uint64_t>(
        rng_,
        config_.arid_distribution,
        config_.min_arid,
        config_.max_arid,
        config_.arid_binomial_probability
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

void AxiRandomStrategy::setNsuList(const std::vector<NsuInfo>& list) {
    nsu_list_ = list;
    if (config_.nsu_selection == NsuSelectionMode::RANDOM) {
        uint64_t nsu_max_idx = static_cast<uint64_t>(nsu_list_.size() - 1);
        nsu_index_dist_ = createDistribution<uint64_t>(
            rng_,
            config_.nsu_index_distribution,
            0,
            nsu_max_idx,
            config_.nsu_index_binomial_probability
        );
    } else {
        nsu_index_dist_.reset();
    }
    increment_current_addr_per_nsu_.clear();
    for (const auto& nsu : nsu_list_) {
        increment_current_addr_per_nsu_.push_back(nsu.min_addr);
    }
    next_nsu_index_ = 0;
    next_nsu_sequence_index_ = 0;
    rotate_nsu_index_ = 0;
    rotate_current_addr_ = nsu_list_[0].min_addr;
}

void AxiRandomStrategy::reset() {
    gap_cycles_remaining_ = 0;
    transaction_counter_ = 0;
    in_write_phase_ = true;
    write_issue_reads_.clear();
    next_nsu_index_ = 0;
    next_nsu_sequence_index_ = 0;
    rotate_nsu_index_ = 0;
    if (!nsu_list_.empty()) {
        rotate_current_addr_ = nsu_list_[0].min_addr;
        for (size_t i = 0; i < increment_current_addr_per_nsu_.size() && i < nsu_list_.size(); ++i) {
            increment_current_addr_per_nsu_[i] = nsu_list_[i].min_addr;
        }
    }
    // Initialize write and read request tracking
    initializeWriteRequestTracking();
    initializeReadRequestTracking();
    
    // Start with a gap if configured
    if (config_.min_gap_cycles > 0 || config_.max_gap_cycles > 0) {
        gap_cycles_remaining_ = gap_dist_->sample();
    }
}

size_t AxiRandomStrategy::calculateNumBeats(uint32_t transaction_size_bytes, size_t data_width_bytes) const {
    return (transaction_size_bytes + data_width_bytes - 1) / data_width_bytes;  // Ceiling division
}

size_t AxiRandomStrategy::selectTargetNsu() {
    const size_t n = nsu_list_.size();
    if (!config_.nsu_sequence.empty()) {
        const size_t idx = config_.nsu_sequence[next_nsu_sequence_index_++ % config_.nsu_sequence.size()];
        return idx % n;
    }
    switch (config_.nsu_selection) {
        case NsuSelectionMode::INTERLEAVE:
            return (next_nsu_index_++) % n;
        case NsuSelectionMode::RANDOM:
            return static_cast<size_t>(nsu_index_dist_->sample());
        case NsuSelectionMode::ROTATE:
            return rotate_nsu_index_;
    }
    return 0;
}

uint64_t AxiRandomStrategy::generateAddressWithinNsu(size_t nsu_idx, uint32_t transaction_size_bytes) {
    if (nsu_idx >= nsu_list_.size()) return 0;
    const NsuInfo& nsu = nsu_list_[nsu_idx];
    uint64_t base = nsu.min_addr;
    uint64_t address_space = nsu.address_space;
    if (address_space == 0) return base;
    uint64_t nsu_max_inclusive = base + address_space - 1;
    uint64_t effective_max_start = (address_space >= transaction_size_bytes)
        ? (nsu_max_inclusive - transaction_size_bytes + 1)
        : base;

    // INTERLEAVE / RANDOM: use configured address distribution within this NSU's range (ROTATE handled in generateAddress)
    DistributionType dist_type = config_.address_distribution;
    uint64_t addr;
    if (dist_type == DistributionType::INCREMENT && nsu_idx < increment_current_addr_per_nsu_.size()) {
        uint64_t& cur = increment_current_addr_per_nsu_[nsu_idx];
        addr = cur;
        uint64_t increment = config_.align_addresses
            ? static_cast<uint64_t>(transaction_size_bytes)
            : config_.address_increment;
        cur = (cur + increment > effective_max_start) ? base : (cur + increment);
    } else {
        auto dist = createDistribution<uint64_t>(
            rng_,
            dist_type,
            base,
            effective_max_start,
            config_.address_binomial_probability
        );
        addr = dist->sample();
    }
    if (addr > effective_max_start) addr = effective_max_start;
    if (addr < base) addr = base;
    if (config_.align_addresses) {
        uint64_t mask = ~(static_cast<uint64_t>(transaction_size_bytes) - 1);
        addr = addr & mask;
        if (addr < base) addr = base;
    } else {
        uint64_t beat_mask = ~(static_cast<uint64_t>(config_.beat_size_bytes) - 1);
        addr = addr & beat_mask;
        if (addr < base) addr = base;
        if (addr > effective_max_start) addr = effective_max_start;
    }
    return addr;
}

uint64_t AxiRandomStrategy::generateAddress(uint32_t transaction_size_bytes) {
    if (config_.nsu_selection == NsuSelectionMode::ROTATE) {
        // ROTATE: one NSU at a time, increment address until end then next NSU
        if (rotate_nsu_index_ >= nsu_list_.size()) return 0;
        const NsuInfo& nsu = nsu_list_[rotate_nsu_index_];
        uint64_t base = nsu.min_addr;
        uint64_t nsu_max = (nsu.address_space > 0) ? (base + nsu.address_space - 1) : base;
        uint64_t effective_max = (nsu.address_space >= transaction_size_bytes)
            ? (nsu_max - transaction_size_bytes + 1) : base;
        uint64_t addr = rotate_current_addr_;
        uint64_t inc = config_.align_addresses
            ? static_cast<uint64_t>(transaction_size_bytes)
            : config_.address_increment;
        rotate_current_addr_ += inc;
        if (rotate_current_addr_ > nsu_max) {
            rotate_nsu_index_++;
            rotate_current_addr_ = (rotate_nsu_index_ < nsu_list_.size()) ? nsu_list_[rotate_nsu_index_].min_addr : 0;
        }
        if (addr > effective_max) addr = effective_max;
        if (addr < base) addr = base;
        if (config_.align_addresses) {
            uint64_t mask = ~(static_cast<uint64_t>(transaction_size_bytes) - 1);
            addr = addr & mask;
            if (addr < base) addr = base;
        } else {
            uint64_t beat_mask = ~(static_cast<uint64_t>(config_.beat_size_bytes) - 1);
            addr = addr & beat_mask;
            if (addr < base) addr = base;
            if (addr > effective_max) addr = effective_max;
        }
        return addr;
    }
    size_t nsu_idx = selectTargetNsu();
    return generateAddressWithinNsu(nsu_idx, transaction_size_bytes);
}

bool AxiRandomStrategy::addressRangesOverlap(uint64_t addr1, uint32_t size1, uint64_t addr2, uint32_t size2) const {
    // Calculate end addresses (exclusive)
    uint64_t end1 = addr1 + size1;
    uint64_t end2 = addr2 + size2;
    
    // Two ranges overlap if one starts before the other ends
    // and the other starts before the first ends
    return (addr1 < end2) && (addr2 < end1);
}

bool AxiRandomStrategy::overlapsWithOutstandingReads(uint64_t addr, uint32_t size) const {
    // Check all outstanding read requests across all IDs
    for (const auto& id_queue : sent_read_requests_by_id_) {
        for (const auto& read_info : id_queue) {
            if (addressRangesOverlap(addr, size, read_info.addr, read_info.transaction_size_bytes)) {
                return true;
            }
        }
    }
    return false;
}

std::optional<uint64_t> AxiRandomStrategy::generateAddressAvoidingReads(uint32_t transaction_size_bytes, size_t max_attempts) {
    size_t attempts = 0;
    
    while (attempts < max_attempts) {
        // Generate an address (alignment is handled inside generateAddress)
        uint64_t addr = generateAddress(transaction_size_bytes);
        
        // Check if it overlaps with outstanding reads
        if (!overlapsWithOutstandingReads(addr, transaction_size_bytes)) {
            return addr;
        }
        
        attempts++;
    }
    
    // If we couldn't find a non-overlapping address after max_attempts,
    // return nullopt to indicate failure (caller should handle this)
    return std::nullopt;
}

void AxiRandomStrategy::generateRandomData(std::vector<uint8_t>& data, size_t size) {
    data.resize(size);
    for (size_t i = 0; i < size; i++) {
        data[i] = byte_dist_->sample();
    }
}

void AxiRandomStrategy::processResponses(const AxiInterface& axi_interface) {
    // The base class handles both B and R channels. Calling processBResponses()
    // here as well double-counts a single B handshake in interleaved/sequential
    // traffic and can release follow-up reads too early.
    AxiTrafficStrategy::processResponses(axi_interface);
    if (config_.issue_reads_after_write_issue &&
        config_.read_write_mode == ReadWriteMode::INTERLEAVED) {
        // In this diagnostic mode reads are queued when writes are issued, so
        // B responses should not create a second read stream.
        finished_writes_.clear();
    }
}

bool AxiRandomStrategy::hasMoreData() const {
    if (config_.nsu_selection == NsuSelectionMode::ROTATE &&
        rotate_nsu_index_ >= nsu_list_.size()) {
        bool has_pending_reads = (config_.read_write_mode != ReadWriteMode::WRITE_ONLY) &&
                                 (!finished_writes_.empty() || !write_issue_reads_.empty());
        return has_pending_reads;
    }
    // Check if we can still generate write commands
    bool can_generate_writes = (config_.max_write_commands == 0) ||
                               (transaction_counter_ < config_.max_write_commands);
    // Check if there are reads we haven't sent yet (when not in WRITE_ONLY mode)
    bool has_pending_reads = (config_.read_write_mode != ReadWriteMode::WRITE_ONLY) &&
                             (!finished_writes_.empty() || !write_issue_reads_.empty());
    return can_generate_writes || has_pending_reads;
}

std::shared_ptr<AxiWriteCommand> AxiRandomStrategy::getNextWriteCommand(
    const AxiInterface& axi_interface
) {
    switch (config_.read_write_mode) {
        case ReadWriteMode::WRITE_ONLY: {
            // Check if we've reached the maximum number of write commands
            if (config_.max_write_commands > 0 && transaction_counter_ >= config_.max_write_commands) {
                return nullptr;
            }
            
            // Handle gap between transactions
            if (gap_cycles_remaining_ > 0) {
                gap_cycles_remaining_--;
                return nullptr;
            }

            size_t outstanding_count = countOutstandingWrites();
            if (outstanding_count >= config_.max_outstanding_writes) {
                return nullptr;
            }
                        
            // Generate transaction size (config is in bytes; do not divide by 8)
            uint32_t transaction_size_bytes = transaction_size_dist_->sample();
            
            // Generate address avoiding outstanding reads (alignment handled internally)
            std::optional<uint64_t> opt_addr = generateAddressAvoidingReads(transaction_size_bytes);
            if (!opt_addr) {
                // Couldn't find non-overlapping address, skip this cycle
                gap_cycles_remaining_--;
                return nullptr;
            }
            uint64_t addr = *opt_addr;
            
            // Create write command
            auto command = createWriteCommand(axi_interface, addr, transaction_size_bytes);
            
            // Extract ID from the command and track write request
            uint32_t write_id = static_cast<uint32_t>(command->getId().u64());
            trackSentWriteRequest(write_id, addr, transaction_size_bytes, command);
            
            // Update state
            transaction_counter_++;
            
            // Schedule next gap
            if (config_.min_gap_cycles > 0 || config_.max_gap_cycles > 0) {
                gap_cycles_remaining_ = gap_dist_->sample();
            }
        
            return command;

        }
        case ReadWriteMode::INTERLEAVED: {
            // For interleaved mode, extract write command logic
            // Check if we can generate a write command
            size_t outstanding_count = countOutstandingWrites();
            if (outstanding_count >= config_.max_outstanding_writes) {
                return nullptr;
            }
            
            // Check if we've reached the maximum number of write commands
            if (config_.max_write_commands > 0 && transaction_counter_ >= config_.max_write_commands) {
                return nullptr;
            }
            
            // Check gap between transactions
            if (gap_cycles_remaining_ > 0) {
                gap_cycles_remaining_--;
                return nullptr;
            }
            
            // Generate transaction size (config is in bytes; do not divide by 8)
            uint32_t transaction_size_bytes = transaction_size_dist_->sample();
            
            // Generate address avoiding outstanding reads (alignment handled internally)
            std::optional<uint64_t> opt_addr = generateAddressAvoidingReads(transaction_size_bytes);
            if (!opt_addr) {
                // Couldn't find non-overlapping address, skip this cycle
                gap_cycles_remaining_--;
                return nullptr;
            }
            uint64_t addr = *opt_addr;
              
            // Create write command
            auto write_cmd = createWriteCommand(axi_interface, addr, transaction_size_bytes);
            
            // Extract ID from the command and track write request
            uint32_t write_id = static_cast<uint32_t>(write_cmd->getId().u64());
            trackSentWriteRequest(write_id, addr, transaction_size_bytes, write_cmd);
            if (config_.issue_reads_after_write_issue) {
                write_issue_reads_.emplace_back(addr, write_id, transaction_size_bytes);
            }
            
            // Update state
            transaction_counter_++;
            
            // Schedule next gap
            if (config_.min_gap_cycles > 0 || config_.max_gap_cycles > 0) {
                gap_cycles_remaining_ = gap_dist_->sample();
            }
            
            return write_cmd;
        }
        case ReadWriteMode::SEQUENTIAL: {
            // In sequential mode, only generate writes in write phase
            if (!in_write_phase_) {
                return nullptr;
            }
            
            size_t outstanding_count = countOutstandingWrites();
            if (outstanding_count >= config_.max_outstanding_writes) {
                return nullptr;
            }

            // In write phase, generate a write command
            // Check if we've reached the maximum number of write commands
            if (config_.max_write_commands > 0 && transaction_counter_ >= config_.max_write_commands) {

                if (allWritesCompleted() && !finished_writes_.empty()) {
                    in_write_phase_ = false;
                }

                return nullptr;
            }

            
            // Handle gap between transactions
            if (gap_cycles_remaining_ > 0) {
                gap_cycles_remaining_--;
                return nullptr;
            }
            
            // Generate transaction size (config is in bytes; do not divide by 8)
            uint32_t transaction_size_bytes = transaction_size_dist_->sample();
            
            // Generate address avoiding outstanding reads (alignment handled internally)
            std::optional<uint64_t> opt_addr = generateAddressAvoidingReads(transaction_size_bytes);
            if (!opt_addr) {
                // Couldn't find non-overlapping address, skip this cycle
                if (config_.min_gap_cycles > 0 || config_.max_gap_cycles > 0) {
                    gap_cycles_remaining_--;
                }
                return nullptr;
            }
            uint64_t addr = *opt_addr;
            
            // Create write command
            auto command = createWriteCommand(axi_interface, addr, transaction_size_bytes);
            
            // Extract ID from the command and track write request
            uint32_t write_id = static_cast<uint32_t>(command->getId().u64());
            trackSentWriteRequest(write_id, addr, transaction_size_bytes, command);
            
            // Update state
            transaction_counter_++;
            
            // Schedule next gap
            if (config_.min_gap_cycles > 0 || config_.max_gap_cycles > 0) {
                gap_cycles_remaining_ = gap_dist_->sample();
            }
            
            return command;
        }
        default:
            return nullptr;
    }
}

std::shared_ptr<AxiReadCommand> AxiRandomStrategy::getNextReadCommand(
    const AxiInterface& axi_interface
) {
    switch (config_.read_write_mode) {
        case ReadWriteMode::WRITE_ONLY:
            return nullptr;
        case ReadWriteMode::INTERLEAVED: {
            // For interleaved mode, check if we should generate a read command (from finished writes)
            auto& ready_reads = config_.issue_reads_after_write_issue
                ? write_issue_reads_
                : finished_writes_;
            if (ready_reads.empty()) {
                return nullptr;
            }

            // Throttle read issue to the configured outstanding-read depth (0 = unlimited).
            // Real AXI masters cap in-flight reads; without this gem5 floods reads under load.
            if (config_.max_outstanding_reads != 0 &&
                countOutstandingReads() >= config_.max_outstanding_reads) {
                return nullptr;
            }
            
            // Generate read for the oldest finished write request
            const WriteRequestInfo& write_info = ready_reads.front();
            uint64_t read_addr = write_info.addr;
            uint32_t transaction_size = write_info.transaction_size_bytes;
            ready_reads.pop_front();
            
            // Create read command
            auto read_cmd = createReadCommand(axi_interface, read_addr, transaction_size);
            
            // Track the sent read request
            if (read_cmd) {
                uint32_t arid = static_cast<uint32_t>(read_cmd->getId().u64());
                trackSentReadRequest(arid, read_addr, transaction_size);
            }
            
            return read_cmd;
        }
        case ReadWriteMode::SEQUENTIAL: {
            // In sequential mode, only generate reads in read phase
            if (in_write_phase_) {
                return nullptr;
            }
            // Throttle read issue to the configured outstanding-read depth (0 = unlimited).
            if (config_.max_outstanding_reads != 0 &&
                countOutstandingReads() >= config_.max_outstanding_reads) {
                return nullptr;
            }
            if (!finished_writes_.empty()) {
                // Generate read for the oldest finished write request
                const WriteRequestInfo& write_info = finished_writes_.front();
                uint64_t read_addr = write_info.addr;
                uint32_t transaction_size_bytes = write_info.transaction_size_bytes;
                finished_writes_.pop_front();
                
                // Create read command
                auto read_cmd = createReadCommand(axi_interface, read_addr, transaction_size_bytes);
                
                // Track the sent read request
                if (read_cmd) {
                    uint32_t arid = static_cast<uint32_t>(read_cmd->getId().u64());
                    trackSentReadRequest(arid, read_addr, transaction_size_bytes);
                }
                
                return read_cmd;
            }
            return nullptr;  // No more addresses to read          
            
        }
        default:
            return nullptr;
    }
}

std::shared_ptr<AxiWriteCommand> AxiRandomStrategy::createWriteCommand(
    const AxiInterface& axi_interface,
    uint64_t addr,
    uint32_t transaction_size_bytes
) {
    // Extract sizes from AxiInterface
    size_t addr_width = axi_interface.getAwChannel().getAwAddrWidth();
    size_t data_width_bytes = axi_interface.getWChannel().getWDataWidthBytes();
    size_t beat_size_bytes = std::max<size_t>(1, config_.beat_size_bytes);
    size_t id_width = axi_interface.getAwChannel().getAwIdWidth();
    size_t aw_user_bytes = axi_interface.getAwChannel().getAwUserWidthBytes();
    size_t w_user_bytes = axi_interface.getWChannel().getWUserWidthBytes();
    
    // Calculate number of beats
    size_t num_beats = calculateNumBeats(transaction_size_bytes, beat_size_bytes);
    size_t total_data_size = num_beats * data_width_bytes;
    
    // Allocate new buffers for this transaction (not shared with channels)
    // W data buffer - sized for entire transaction
    auto w_data_buffer = std::make_shared<std::vector<uint8_t>>(total_data_size);
    std::shared_ptr<DataView> w_data_view = std::make_shared<DataView>(w_data_buffer, total_data_size, 0);
    
    // Generate random data and copy to w_data_view
    std::vector<uint8_t> random_data;
    generateRandomData(random_data, total_data_size);
    std::memcpy(w_data_view->data(), random_data.data(), total_data_size);
    
    // AW user buffer
    std::shared_ptr<DataView> aw_user_view;
    if (aw_user_bytes > 0) {
        auto aw_user_buffer = std::make_shared<std::vector<uint8_t>>(aw_user_bytes, 0);
        aw_user_view = std::make_shared<DataView>(aw_user_buffer, aw_user_bytes, 0);
    } else {
        aw_user_view = std::make_shared<DataView>();
    }
    
    // W user buffer
    std::shared_ptr<DataView> w_user_view;
    if (w_user_bytes > 0) {
        auto w_user_buffer = std::make_shared<std::vector<uint8_t>>(w_user_bytes, 0);
        w_user_view = std::make_shared<DataView>(w_user_buffer, w_user_bytes, 0);
    } else {
        w_user_view = std::make_shared<DataView>();
    }
    
    // Generate ID
    uint32_t awid = static_cast<uint32_t>(awid_dist_->sample());
    // Clamp to id_width
    if (id_width < 32) {
        uint32_t id_mask = (1U << id_width) - 1;
        awid = awid & id_mask;
    }
    
    // Create and return command
    return std::make_shared<AxiWriteCommand>(
        addr,
        addr_width,
        num_beats,
        beat_size_bytes,
        data_width_bytes,
        awid,
        id_width,
        aw_user_view,
        w_user_view,
        w_data_view
    );
}

std::shared_ptr<AxiReadCommand> AxiRandomStrategy::createReadCommand(
    const AxiInterface& axi_interface,
    uint64_t addr,
    uint32_t transaction_size_bytes
) {
    // Extract sizes from AxiInterface
    size_t addr_width = axi_interface.getArChannel().getArAddrWidth();
    size_t beat_size_bytes = std::max<size_t>(1, config_.beat_size_bytes);
    size_t id_width = axi_interface.getArChannel().getArIdWidth();
    size_t ar_user_width_bytes = axi_interface.getArChannel().getArUserWidthBytes();
    
    // Calculate number of beats
    size_t num_beats = calculateNumBeats(transaction_size_bytes, beat_size_bytes);
    
    // Allocate new buffer for AR user (not shared with channels)
    std::shared_ptr<DataView> ar_user_view;
    if (ar_user_width_bytes > 0) {
        auto ar_user_buffer = std::make_shared<std::vector<uint8_t>>(ar_user_width_bytes, 0);
        ar_user_view = std::make_shared<DataView>(ar_user_buffer, ar_user_width_bytes, 0);
    } else {
        ar_user_view = std::make_shared<DataView>();
    }
    
    // Generate ID
    uint32_t arid = static_cast<uint32_t>(arid_dist_->sample());
    // Clamp to id_width
    if (id_width < 32) {
        uint32_t id_mask = (1U << id_width) - 1;
        arid = arid & id_mask;
    }
    
    // Create and return command
    return std::make_shared<AxiReadCommand>(
        addr,
        addr_width,
        num_beats,
        beat_size_bytes,
        arid,
        id_width,
        ar_user_view
    );
}

std::string AxiRandomStrategy::getConfigString() const {
    std::ostringstream oss;
    oss << "mode=random"
        << ",seed=" << config_.seed
        << ",transaction_size=" << config_.min_transaction_size_bytes
        << "-" << config_.max_transaction_size_bytes;

    oss << ",nsu_count=" << nsu_list_.size();
    if (!config_.nsu_sequence.empty()) {
        oss << ",nsu_selection=sequence";
    } else if (config_.nsu_selection == NsuSelectionMode::INTERLEAVE) {
        oss << ",nsu_selection=interleave";
    } else if (config_.nsu_selection == NsuSelectionMode::RANDOM) {
        oss << ",nsu_selection=random";
    } else {
        oss << ",nsu_selection=rotate";
    }
    if (config_.read_write_mode == ReadWriteMode::WRITE_ONLY) {
        oss << ",read_write_mode=write_only";
    } else if (config_.read_write_mode == ReadWriteMode::INTERLEAVED) {
        oss << ",read_write_mode=interleaved";
    } else {
        oss << ",read_write_mode=sequential";
    }
    
    return oss.str();
}
