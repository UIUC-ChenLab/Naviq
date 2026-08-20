#ifndef AXI_TRAFFIC_STRATEGY_H
#define AXI_TRAFFIC_STRATEGY_H

#include "AxiCommand.h"
#include "DataView.h"
#include "AxiInterface.h"
#include <vector>
#include <string>
#include <cstdint>
#include <memory>
#include <tuple>
#include <deque>
#include <map>
#include <unordered_map>

// Enum for read/write ordering modes
enum class ReadWriteMode {
    WRITE_ONLY,        // Only generate write commands
    INTERLEAVED,       // Mix writes and reads: write, then read after gap, repeat
    SEQUENTIAL         // Complete all writes first, then do all reads
};

// Abstract base class for AXI traffic generation strategies
// Each mode (random, file stream) implements this interface
class AxiTrafficStrategy {
protected:
    // Structure to track sent write requests (for interleaved and sequential read generation)
    struct WriteRequestInfo {
        uint64_t addr;
        uint32_t id;
        uint32_t transaction_size_bytes;
        std::shared_ptr<std::vector<uint8_t>> write_data;  // Optional: stored when verification is enabled
        
        WriteRequestInfo(uint64_t a, uint32_t i, uint32_t size) 
            : addr(a), id(i), transaction_size_bytes(size), write_data(nullptr) {}
        
        WriteRequestInfo(uint64_t a, uint32_t i, uint32_t size, std::shared_ptr<std::vector<uint8_t>> data) 
            : addr(a), id(i), transaction_size_bytes(size), write_data(data) {}
    };
    
    // Track sent write requests organized by AXI ID
    // Outer vector is indexed by AXI ID, each deque contains write requests in order for that ID
    std::vector<std::deque<WriteRequestInfo>> sent_write_requests_by_id_;
    
    // Track write requests that have received bresp (can issue reads for these)
    std::deque<WriteRequestInfo> finished_writes_;
    
    // Structure to track sent read requests
    struct ReadRequestInfo {
        uint64_t addr;
        uint32_t id;
        uint32_t transaction_size_bytes;
        
        ReadRequestInfo(uint64_t a, uint32_t i, uint32_t size) 
            : addr(a), id(i), transaction_size_bytes(size) {}
    };
    
    // Track sent read requests organized by AXI ID
    // Outer vector is indexed by AXI ID, each deque contains read requests in order for that ID
    std::vector<std::deque<ReadRequestInfo>> sent_read_requests_by_id_;
    
    // Read-write verification support (optional)
    bool enable_read_write_verification_;
    
    // Map to store write data by address when writes complete (for verification)
    // Key: address, Value: pair of (size, data)
    std::map<uint64_t, std::pair<uint32_t, std::shared_ptr<std::vector<uint8_t>>>> completed_write_data_;
    
    // Track accumulated read data for in-flight reads (by address)
    // Key: address, Value: accumulated read data buffer
    std::unordered_map<uint64_t, std::vector<uint8_t>> in_flight_read_data_;
    
    // Verification statistics
    uint64_t read_write_comparisons_;
    uint64_t read_write_mismatches_;
    
    // Helper to get the maximum AXI ID value (for sizing the vector)
    // Derived classes must implement this to return their max_awid value
    virtual size_t getMaxAxiId() const = 0;
    
    // Helper to get the maximum AR ID value (for sizing read request tracking)
    // By default, uses the same as getMaxAxiId(), but can be overridden if different
    virtual size_t getMaxArId() const { return getMaxAxiId(); }
    
    // Process bresp from AxiInterface and move completed writes to finished_writes_
    // If verification is enabled, stores write data for later comparison
    void processBResponses(const AxiInterface& axi_interface);
    
    // Process rresp from AxiInterface and mark completed reads
    // Called when RLAST is asserted on the R channel
    // If verification is enabled, compares read data with stored write data
    void processRResponses(const AxiInterface& axi_interface);
    
    // Track a sent write request (call after getNextWriteCommand returns a command)
    // If verification is enabled, extracts and stores write data from the command
    void trackSentWriteRequest(uint32_t awid, uint64_t addr, uint32_t transaction_size_bytes, 
                               const std::shared_ptr<AxiWriteCommand>& write_cmd = nullptr);
    
    // Track a sent read request (call after getNextReadCommand returns a command)
    void trackSentReadRequest(uint32_t arid, uint64_t addr, uint32_t transaction_size_bytes);
    
    // Check if all sent write requests have received bresp
    bool allWritesCompleted() const;
    
    // Check if all sent read requests have received rresp with RLAST
    bool allReadsCompleted() const;
    
    // Count total outstanding writes across all IDs
    size_t countOutstandingWrites() const;
    
    // Count total outstanding reads across all IDs
    size_t countOutstandingReads() const;
    
    // Initialize the sent_write_requests_by_id_ vector (call from derived class reset())
    void initializeWriteRequestTracking();
    
    // Initialize the sent_read_requests_by_id_ vector (call from derived class reset())
    void initializeReadRequestTracking();
    
    // Constructor (protected since this is an abstract base class)
    AxiTrafficStrategy();
    
    // Compare read data with stored write data for a given address
    // Returns true if data matches, false otherwise
    // If no write data exists for the address, returns false
    bool verifyReadData(uint64_t addr, uint32_t size, const uint8_t* read_data);
    
public:
    virtual ~AxiTrafficStrategy() = default;
    
    // Process responses from the AXI interface (e.g., write response bresp)
    // This should be called before getNextWriteCommand/getNextReadCommand to update internal state
    // based on completed transactions
    virtual void processResponses(const AxiInterface& axi_interface);
    
    // Get next write command
    // Returns a write command if one should be generated, nullptr otherwise
    // The command should be properly configured with address, data, ID, etc.
    // The strategy internally decides whether to generate a write command
    // based on its current state (ReadWriteMode, phase, etc.)
    // All sizes and DataViews are inferred from the provided AxiInterface
    // Note: This method does NOT process responses - call processResponses() separately
    virtual std::shared_ptr<AxiWriteCommand> getNextWriteCommand(
        const AxiInterface& axi_interface
    ) = 0;
    
    // Get next read command
    // Returns a read command if one should be generated, nullptr otherwise
    // The command should be properly configured with address, ID, etc.
    // The strategy internally decides whether to generate a read command
    // based on its current state (ReadWriteMode, phase, etc.)
    // All sizes and DataViews are inferred from the provided AxiInterface
    // Note: This method does NOT process responses - call processResponses() separately
    virtual std::shared_ptr<AxiReadCommand> getNextReadCommand(
        const AxiInterface& axi_interface
    ) = 0;
    
    // Check if there's more data to generate
    // Returns true if more data can be generated, false if done
    virtual bool hasMoreData() const = 0;
    
    // Reset the strategy to initial state
    virtual void reset() = 0;
    
    // Get strategy-specific configuration name/identifier
    virtual std::string getModeName() const = 0;
    
    // Get configuration parameters (for saving/loading state)
    // Returns a JSON-like string or empty if not applicable
    virtual std::string getConfigString() const { return ""; }
    
    // Get the current read/write mode
    virtual ReadWriteMode getReadWriteMode() const = 0;
    
    // Check if we're currently in write phase (for sequential mode)
    virtual bool isInWritePhase() const = 0;
    
    // Check if the strategy is fully done
    // For WRITE_ONLY mode: returns true when all writes have been sent and completed
    // For INTERLEAVED and SEQUENTIAL modes: returns true when all writes and reads have been
    // sent and all responses have been received
    virtual bool isFullyDone() const;
    
    // Enable or disable read-write verification
    // When enabled, write data is stored when writes complete, and read data is compared
    // when reads complete to verify data integrity
    void setReadWriteVerification(bool enable);
    
    // Check if read-write verification is enabled
    bool isReadWriteVerificationEnabled() const { return enable_read_write_verification_; }
    
    // Get verification statistics
    uint64_t getReadWriteComparisons() const { return read_write_comparisons_; }
    uint64_t getReadWriteMismatches() const { return read_write_mismatches_; }
    
    // Reset verification statistics (clears counters but keeps verification enabled/disabled state)
    void resetVerificationStatistics();
};

#endif // AXI_TRAFFIC_STRATEGY_H
