#ifndef AXI_RANDOM_STRATEGY_H
#define AXI_RANDOM_STRATEGY_H

#include "AxiTrafficStrategy.h"
#include "Distribution.h"
#include "DataView.h"
#include "AxiInterface.h"
#include <algorithm>
#include <random>
#include <cstdint>
#include <string>
#include <vector>
#include <optional>
#include <deque>
#include <memory>
#include <cmath>
#include <iostream>
#include <sstream>
#include <chrono>
#include <cstring>

#include "NsuInfo.h"

// How to choose which AXI NSU to target for each request
enum class NsuSelectionMode {
    INTERLEAVE,  // Round-robin: NSU 0 -> 1 -> 2 -> ... with wrapping per request
    RANDOM,      // Random NSU index (uses Distribution settings for NSU index)
    ROTATE       // Sweep each NSU from min to max address (increment), then next NSU; forces address distribution to INCREMENT
};

// Random traffic generation strategy for AXI
// Generates random write/read transactions with configurable parameters
class AxiRandomStrategy : public AxiTrafficStrategy {
public:
    struct Config {
        uint64_t seed = 0;                   // RNG seed (0 = time-based)
        
        // NSU selection mode (NSU list is required and passed via AxiTrafficGenerator)
        NsuSelectionMode nsu_selection = NsuSelectionMode::INTERLEAVE;
        // Optional explicit NSU index sequence. When non-empty, this overrides
        // nsu_selection and cycles through the provided indices per request.
        std::vector<size_t> nsu_sequence;
        // For RANDOM NSU selection: distribution over NSU indices [0, nsu_list.size()-1]
        DistributionType nsu_index_distribution = DistributionType::UNIFORM;
        double nsu_index_binomial_probability = 0.5;
        
        // Address distribution parameters (within selected NSU; for ROTATE this is forced to INCREMENT)
        DistributionType address_distribution = DistributionType::UNIFORM;
        double address_binomial_probability = 0.5;
        uint64_t address_increment = 1;      // Increment value for INCREMENT distribution (typically data width in bytes)
        
        // Transaction size distribution parameters
        DistributionType transaction_size_distribution = DistributionType::UNIFORM;
        uint32_t min_transaction_size_bytes = 64;    // Minimum bytes per transaction
        uint32_t max_transaction_size_bytes = 512;   // Maximum bytes per transaction
        double transaction_size_binomial_probability = 0.5;
        
        // Gap distribution parameters (cycles between transactions)
        DistributionType gap_distribution = DistributionType::UNIFORM;
        uint32_t min_gap_cycles = 0;
        uint32_t max_gap_cycles = 10;
        double gap_binomial_probability = 0.5;
        
        // ID distribution parameters
        DistributionType awid_distribution = DistributionType::FIXED;
        uint64_t min_awid = 0;
        uint64_t max_awid = 15;
        double awid_binomial_probability = 0.5;
        
        DistributionType arid_distribution = DistributionType::FIXED;
        uint64_t min_arid = 0;
        uint64_t max_arid = 15;
        double arid_binomial_probability = 0.5;
        
        // Read/Write mode
        ReadWriteMode read_write_mode = ReadWriteMode::WRITE_ONLY;
        uint32_t max_outstanding_writes = 1;  // Maximum number of outstanding writes before issuing reads (for INTERLEAVED mode)
        uint32_t max_outstanding_reads = 0;   // Max outstanding reads (0 = unlimited); throttles read issue like real AXI masters
        bool issue_reads_after_write_issue = false;  // INTERLEAVED diagnostic: pair reads with write issue instead of B response
        
        // Command limits
        uint64_t max_write_commands = 0;      // Maximum number of write transactions to generate (0 = unlimited)
        
        bool align_addresses = true;          // Align addresses to transaction size
        uint32_t beat_size_bytes = 1;         // Min start-address alignment when align_addresses is false
    };
    
    AxiRandomStrategy();
    
    ~AxiRandomStrategy() override = default;
    
    // Configure the strategy programmatically
    void configure(const Config& config);
    
    // Set NSU list (called by AxiTrafficGenerator; must be called after configure when using NSU mode)
    void setNsuList(const std::vector<NsuInfo>& list);
    
    // AxiTrafficStrategy interface
    void processResponses(const AxiInterface& axi_interface) override;
    
    std::shared_ptr<AxiWriteCommand> getNextWriteCommand(
        const AxiInterface& axi_interface
    ) override;
    
    std::shared_ptr<AxiReadCommand> getNextReadCommand(
        const AxiInterface& axi_interface
    ) override;
    
    bool hasMoreData() const override;
    void reset() override;
    std::string getModeName() const override { return "random"; }
    std::string getConfigString() const override;
    ReadWriteMode getReadWriteMode() const override { return config_.read_write_mode; }
    bool isInWritePhase() const override { return in_write_phase_; }

private:
    Config config_;
    
    // NSU list (set by AxiTrafficGenerator via setNsuList, not from config)
    std::vector<NsuInfo> nsu_list_;
    
    // Random number generator (shared across all distributions)
    std::shared_ptr<std::mt19937> rng_;
    
    // All distributions using polymorphic wrappers
    std::unique_ptr<Distribution<uint64_t>> address_dist_;
    std::unique_ptr<Distribution<uint32_t>> transaction_size_dist_;
    std::unique_ptr<Distribution<uint32_t>> gap_dist_;
    std::unique_ptr<Distribution<uint64_t>> awid_dist_;
    std::unique_ptr<Distribution<uint64_t>> arid_dist_;
    std::unique_ptr<Distribution<uint8_t>> byte_dist_;
    
    // State
    uint32_t gap_cycles_remaining_;
    uint64_t transaction_counter_;
    bool in_write_phase_;
    std::deque<WriteRequestInfo> write_issue_reads_;
    
    // NSU selection state
    size_t next_nsu_index_;  // For INTERLEAVE: round-robin index
    size_t next_nsu_sequence_index_;  // For explicit NSU sequences
    std::unique_ptr<Distribution<uint64_t>> nsu_index_dist_;  // For RANDOM: distribution over NSU indices
    size_t rotate_nsu_index_;   // For ROTATE: current NSU being swept
    uint64_t rotate_current_addr_;  // For ROTATE: current address within current NSU
    std::vector<uint64_t> increment_current_addr_per_nsu_;  // For INTERLEAVE/RANDOM with INCREMENT: current addr per NSU
    
    // Helper to get the maximum AXI ID value (for sizing the vector)
    size_t getMaxAxiId() const override { return config_.max_awid; }
    
    // Helper methods
    void generateRandomData(std::vector<uint8_t>& data, size_t size);
    size_t calculateNumBeats(uint32_t transaction_size_bytes, size_t data_width) const;
    uint64_t generateAddress(uint32_t transaction_size_bytes);
    
    // NSU-based address generation: select target NSU then address within it
    size_t selectTargetNsu();  // INTERLEAVE/RANDOM: returns NSU index for this request
    uint64_t generateAddressWithinNsu(size_t nsu_idx, uint32_t transaction_size_bytes);
    
    // Generate address that doesn't overlap with outstanding reads
    // transaction_size_bytes: size of the transaction to generate address for
    // max_attempts: maximum number of attempts to generate a non-overlapping address (default 100)
    // Returns the generated address, or std::nullopt if unable to find non-overlapping address after max_attempts
    std::optional<uint64_t> generateAddressAvoidingReads(uint32_t transaction_size_bytes, size_t max_attempts = 100);
    
    // Check if two address ranges overlap
    // addr1, size1: first address range
    // addr2, size2: second address range
    // Returns true if ranges overlap (share any byte)
    bool addressRangesOverlap(uint64_t addr1, uint32_t size1, uint64_t addr2, uint32_t size2) const;
    
    // Check if an address range overlaps with any outstanding read
    // Uses sent_read_requests_by_id_ to check all pending read requests
    // addr: start address
    // size: size in bytes
    // Returns true if overlaps with any outstanding read
    bool overlapsWithOutstandingReads(uint64_t addr, uint32_t size) const;

    // Helper methods for creating commands
    // These methods allocate new buffers sized for the transaction (not shared with channels)
    std::shared_ptr<AxiWriteCommand> createWriteCommand(
        const AxiInterface& axi_interface,
        uint64_t addr,
        uint32_t transaction_size_bytes
    );
    
    std::shared_ptr<AxiReadCommand> createReadCommand(
        const AxiInterface& axi_interface,
        uint64_t addr,
        uint32_t transaction_size_bytes
    );

};

#endif // AXI_RANDOM_STRATEGY_H
