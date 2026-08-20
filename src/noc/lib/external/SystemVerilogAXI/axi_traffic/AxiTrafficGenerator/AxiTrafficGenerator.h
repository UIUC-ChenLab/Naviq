#ifndef AXI_TRAFFIC_GENERATOR_H
#define AXI_TRAFFIC_GENERATOR_H

#include <cstdint>
#include <cstdbool>
#include <vector>
#include <memory>
#include <string>
#include <tuple>
#include "AxiInterface.h"
#include "DataView.h"
#include "AxiCommand.h"
#include "AxiTrafficStrategy.h"
#include "NsuInfo.h"

#include "AxiRandomStrategy.h"
#include "AxiFileStrategy.h"

// Generation modes
enum class AxiGenerationMode {
    RANDOM,
    FILE_STREAM
};

// C++ class for AXI traffic generation
class AxiTrafficGenerator {
public:
    // Constructor
    // axi_interface: shared pointer to the AXI interface
    // enable_verification: if true, enables read-write verification on strategies
    // nsu_list: list of NSUs (min_addr, address_space) - required; passed to random strategy
    AxiTrafficGenerator(std::shared_ptr<AxiInterface> axi_interface,
                        std::vector<NsuInfo> nsu_list,
                        bool enable_verification = true);
    
    ~AxiTrafficGenerator() = default;
    
    // Reset the generator
    void reset();
    
    // Load configuration from file
    bool loadConfigFile(const char* config_path);
    
    // Set the generation mode
    // mode: the generation mode to use
    // Returns true on success, false on error
    bool setMode(AxiGenerationMode mode);
    
    // Set mode to RANDOM with configuration struct
    // config: AxiRandomStrategy configuration
    // Returns true on success, false on error
    bool setMode(const AxiRandomStrategy::Config& config);
    
    // Set mode to FILE_STREAM with configuration struct
    // config: AxiFileStrategy configuration
    // Returns true on success, false on error
    // bool setMode(const AxiFileStrategy::Config& config);

    void setNsuList(const std::vector<NsuInfo>& nsu_list);
    
    // Check if the generator is done (no more data to generate)
    // Returns true if done, false if more data is available
    bool isDone() const;
    
    // Generate traffic for the next clock cycle
    // Uses the strategy to get next commands and applies them to the channels
    void generateNextCycle();
    
    // Update responses from the AXI interface
    // Reads the B and R channels from the AxiInterface to update strategy state
    // force_readys_high: if true, sets the BReady and RReady signals to high
    // if false, leaves the BReady and RReady signals as they are
    void updateResponses(bool force_readys_high = true);
    
    // Get Write Address, Write Data, Read Address, Write Response, Read Data channels (for monitoring)
    const AxiAwChannel& getAwChannel() const { return axi_interface_->getAwChannel(); }
    const AxiWChannel& getWChannel() const { return axi_interface_->getWChannel(); }
    const AxiArChannel& getArChannel() const { return axi_interface_->getArChannel(); }
    const AxiBChannel& getBChannel() const { return axi_interface_->getBChannel(); }
    const AxiRChannel& getRChannel() const { return axi_interface_->getRChannel(); }
    
    // Non-const accessors
    AxiAwChannel& getAwChannel() { return axi_interface_->getAwChannel(); }
    AxiWChannel& getWChannel() { return axi_interface_->getWChannel(); }
    AxiArChannel& getArChannel() { return axi_interface_->getArChannel(); }
    AxiBChannel& getBChannel() { return axi_interface_->getBChannel(); }
    AxiRChannel& getRChannel() { return axi_interface_->getRChannel(); }

    // Get current configuration from the AXI interface
    size_t getDataWidthBytes() const { return axi_interface_->getWChannel().getWDataWidthBytes(); }
    size_t getAddrWidth() const { return axi_interface_->getAwChannel().getAwAddrWidth(); }
    size_t getIdWidth() const { return axi_interface_->getAwChannel().getAwIdWidth(); }
    size_t getAwUserWidthBytes() const { return axi_interface_->getAwChannel().getAwUserWidthBytes(); }
    size_t getWUserWidthBytes() const { return axi_interface_->getWChannel().getWUserWidthBytes(); }
    size_t getBUserWidthBytes() const { return axi_interface_->getBChannel().getBUserWidthBytes(); }
    size_t getArUserWidthBytes() const { return axi_interface_->getArChannel().getArUserWidthBytes(); }
    size_t getRUserWidthBytes() const { return axi_interface_->getRChannel().getRUserWidthBytes(); }
    size_t getStrbWidth() const { return axi_interface_->getWChannel().getWDataWidthBytes(); }
    AxiGenerationMode getCurrentMode() const { return current_mode_; }
    std::string getModeName() const;
    std::string getStrategyConfig() const;
    
    // Get verification statistics
    // Returns a tuple of (matching_count, failed_count)
    // matching_count: number of read-write comparisons that matched
    // failed_count: number of read-write comparisons that failed (mismatched)
    std::tuple<uint64_t, uint64_t> reportStatistics() const;

    // Set bandwidth limits (called by host/traffic generator base; not part of strategy config)
    // max_write_bandwidth_mbps, max_read_bandwidth_mbps: MB/s (0 = unlimited)
    // clock_period_ns: clock period in nanoseconds
    void setBandwidthLimits(double max_write_bandwidth_mbps,
                            double max_read_bandwidth_mbps,
                            double clock_period_ns);

private:
    // Shared pointer to the AXI interface (channels are owned by the interface)
    std::shared_ptr<AxiInterface> axi_interface_;
    
    // NSU list passed at construction; given to random strategy when setMode(Config) is used
    std::vector<NsuInfo> nsu_list_;
    
    AxiGenerationMode current_mode_;
    
    // Whether read-write verification is enabled
    bool enable_verification_;
    
    // Strategy for generating traffic
    std::unique_ptr<AxiTrafficStrategy> strategy_;
    
    // Active commands being executed
    std::shared_ptr<AxiWriteCommand> active_write_command_;
    std::shared_ptr<AxiReadCommand> active_read_command_;
    
    // Helper function to create strategy based on mode
    std::unique_ptr<AxiTrafficStrategy> createStrategy(AxiGenerationMode mode);
    
    // Helper function to configure verification on the current strategy
    void configureVerification();
    
    // Bandwidth limiting (used when random strategy config specifies limits)
    void updateBandwidthState();
    void resetBandwidthState();
    bool isWriteBandwidthExceeded() const;
    bool isReadBandwidthExceeded() const;
    
    double write_bandwidth_budget_bytes_;
    double read_bandwidth_budget_bytes_;
    double write_bandwidth_bytes_per_cycle_;
    double read_bandwidth_bytes_per_cycle_;
};

#endif // AXI_TRAFFIC_GENERATOR_H
