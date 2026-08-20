#include "AxiTrafficGenerator.h"
#include "AxiTrafficStrategy.h"
#include <cstring>
#include <iostream>
#include <stdexcept>

AxiTrafficGenerator::AxiTrafficGenerator(std::shared_ptr<AxiInterface> axi_interface,
                                         std::vector<NsuInfo> nsu_list,
                                         bool enable_verification)
    : axi_interface_(std::move(axi_interface)),
      current_mode_(AxiGenerationMode::RANDOM),
      enable_verification_(enable_verification),
      active_write_command_(nullptr),
      active_read_command_(nullptr),
      nsu_list_(nsu_list),
      write_bandwidth_budget_bytes_(0.0),
      read_bandwidth_budget_bytes_(0.0),
      write_bandwidth_bytes_per_cycle_(0.0),
      read_bandwidth_bytes_per_cycle_(0.0)
{
    if (nsu_list_.empty()) {
        throw std::invalid_argument("AxiTrafficGenerator: nsu_list must not be empty");
    }
    setMode(AxiGenerationMode::RANDOM);
    reset();
}

void AxiTrafficGenerator::reset() {
    axi_interface_->clear();
    active_write_command_ = nullptr;
    active_read_command_ = nullptr;
    resetBandwidthState();
    if (strategy_) {
        strategy_->reset();
    }
}

bool AxiTrafficGenerator::isDone() const {
    if (!strategy_) {
        return true; // No strategy means we're done
    }
    return strategy_->isFullyDone();
}

void AxiTrafficGenerator::generateNextCycle() {
    if (!strategy_) {
        axi_interface_->getAwChannel().setAwValid(false);
        axi_interface_->getWChannel().setWValid(false);
        axi_interface_->getArChannel().setArValid(false);
        return;
    }
    
    updateBandwidthState();
    
    // Update active write command if it exists
    if (active_write_command_) {
        // Tick the command to update its state based on ready signals
        bool write_done = active_write_command_->tick(
            axi_interface_->getAwChannel(), 
            axi_interface_->getWChannel()
        );
        
        if (write_done) {
            // Command is complete, clear it
            active_write_command_ = nullptr;
        } else {
            // Command still active, set next values
            active_write_command_->set_next_values(
                axi_interface_->getAwChannel(), 
                axi_interface_->getWChannel()
            );
        }
    }
    
    // Update active read command if it exists
    if (active_read_command_) {
        // Tick the command to update its state based on ready signals
        bool read_done = active_read_command_->tick(axi_interface_->getArChannel());
        
        if (read_done) {
            // Command is complete, clear it
            active_read_command_ = nullptr;
        } else {
            // Command still active, set next values
            active_read_command_->set_next_values(axi_interface_->getArChannel());
        }
    }
    
    // Get new commands if channels are available (respect bandwidth limits)
    if (!active_write_command_ && !isWriteBandwidthExceeded()) {
        auto write_cmd = strategy_->getNextWriteCommand(*axi_interface_);
        if (write_cmd) {
            active_write_command_ = write_cmd;
            active_write_command_->set_next_values(
                axi_interface_->getAwChannel(), 
                axi_interface_->getWChannel()
            );
        }
    }
    
    if (!active_read_command_ && !isReadBandwidthExceeded()) {
        auto read_cmd = strategy_->getNextReadCommand(*axi_interface_);
        if (read_cmd) {
            active_read_command_ = read_cmd;
            active_read_command_->set_next_values(axi_interface_->getArChannel());
        }
    }
    
    // If no active write command, clear write channels
    if (!active_write_command_) {
        axi_interface_->getAwChannel().setAwValid(false);
        axi_interface_->getWChannel().setWValid(false);
    }
    
    // If no active read command, clear read channel
    if (!active_read_command_) {
        axi_interface_->getArChannel().setArValid(false);
    }
}

void AxiTrafficGenerator::updateResponses(bool force_readys_high) {
    if (!strategy_) {
        return;
    }
    
    if (force_readys_high) {
        axi_interface_->getBChannel().setBReady(true);
        axi_interface_->getRChannel().setRReady(true);
    } else {

    }
    
    // Process responses from the AXI interface
    strategy_->processResponses(*axi_interface_);
}

std::unique_ptr<AxiTrafficStrategy> AxiTrafficGenerator::createStrategy(AxiGenerationMode mode) {
    switch (mode) {
        case AxiGenerationMode::RANDOM:
            return std::make_unique<AxiRandomStrategy>();
        case AxiGenerationMode::FILE_STREAM:
            // return std::make_unique<AxiFileStrategy>();
            return nullptr;
        default:
            return nullptr;
    }
}

bool AxiTrafficGenerator::setMode(AxiGenerationMode mode) {
    current_mode_ = mode;
    strategy_ = createStrategy(mode);
    
    if (!strategy_) {
        std::cerr << "Error: Failed to create strategy for mode" << std::endl;
        return false;
    }
    
    write_bandwidth_bytes_per_cycle_ = 0.0;
    read_bandwidth_bytes_per_cycle_ = 0.0;
    resetBandwidthState();
    
    if (mode == AxiGenerationMode::RANDOM) {
        auto* random_strategy = dynamic_cast<AxiRandomStrategy*>(strategy_.get());
        if (random_strategy) {
            random_strategy->setNsuList(nsu_list_);
        }
    }
    
    configureVerification();
    
    return true;
}

bool AxiTrafficGenerator::setMode(const AxiRandomStrategy::Config& config) {
    current_mode_ = AxiGenerationMode::RANDOM;
    strategy_ = createStrategy(AxiGenerationMode::RANDOM);
    
    if (!strategy_) {
        std::cerr << "Error: Failed to create random strategy" << std::endl;
        return false;
    }
    
    auto* random_strategy = dynamic_cast<AxiRandomStrategy*>(strategy_.get());
    if (random_strategy) {
        random_strategy->configure(config);
        random_strategy->setNsuList(nsu_list_);
        configureVerification();
        return true;
    }
    
    return false;
}

// bool AxiTrafficGenerator::setMode(const AxiFileStrategy::Config& config) {
//     current_mode_ = AxiGenerationMode::FILE_STREAM;
//     strategy_ = createStrategy(AxiGenerationMode::FILE_STREAM);
    
//     if (!strategy_) {
//         std::cerr << "Error: Failed to create file stream strategy" << std::endl;
//         return false;
//     }
    
//     // auto* file_strategy = dynamic_cast<AxiFileStrategy*>(strategy_.get());
//     // if (file_strategy) {
//     //     file_strategy->configure(config);
//     //     // Configure verification if enabled
//     //     configureVerification();
//     //     return true;
//     // }
    
//     return false;
// }

std::string AxiTrafficGenerator::getModeName() const {
    if (strategy_) {
        return strategy_->getModeName();
    }
    return "unknown";
}

void AxiTrafficGenerator::setNsuList(const std::vector<NsuInfo>& nsu_list) {
    nsu_list_ = nsu_list;

    if (current_mode_ == AxiGenerationMode::RANDOM) {
        auto* random_strategy = dynamic_cast<AxiRandomStrategy*>(strategy_.get());
        if (random_strategy) {
            random_strategy->setNsuList(nsu_list_);
        }
    }
}

std::string AxiTrafficGenerator::getStrategyConfig() const {
    if (strategy_) {
        return strategy_->getConfigString();
    }
    return "";
}

void AxiTrafficGenerator::configureVerification() {
    if (strategy_) {
        strategy_->setReadWriteVerification(enable_verification_);
    }
}

std::tuple<uint64_t, uint64_t> AxiTrafficGenerator::reportStatistics() const {
    if (!strategy_) {
        return std::make_tuple(0, 0);
    }
    
    uint64_t comparisons = strategy_->getReadWriteComparisons();
    uint64_t mismatches = strategy_->getReadWriteMismatches();
    uint64_t matches = comparisons - mismatches;
    
    return std::make_tuple(matches, mismatches);
}

void AxiTrafficGenerator::updateBandwidthState() {
    if (write_bandwidth_bytes_per_cycle_ > 0.0) {
        write_bandwidth_budget_bytes_ += write_bandwidth_bytes_per_cycle_;
        const AxiWChannel& w_channel = axi_interface_->getWChannel();
        if (w_channel.getWValid() && w_channel.getWReady()) {
            write_bandwidth_budget_bytes_ -= static_cast<double>(w_channel.getWDataWidthBytes());
        }
    }
    if (read_bandwidth_bytes_per_cycle_ > 0.0) {
        read_bandwidth_budget_bytes_ += read_bandwidth_bytes_per_cycle_;
        const AxiRChannel& r_channel = axi_interface_->getRChannel();
        if (r_channel.getRValid() && r_channel.getRReady()) {
            read_bandwidth_budget_bytes_ -= static_cast<double>(r_channel.getRDataWidthBytes());
        }
    }
}

void AxiTrafficGenerator::resetBandwidthState() {
    write_bandwidth_budget_bytes_ = 0.0;
    read_bandwidth_budget_bytes_ = 0.0;
}

bool AxiTrafficGenerator::isWriteBandwidthExceeded() const {
    return write_bandwidth_bytes_per_cycle_ > 0.0 && write_bandwidth_budget_bytes_ < 0.0;
}

bool AxiTrafficGenerator::isReadBandwidthExceeded() const {
    return read_bandwidth_bytes_per_cycle_ > 0.0 && read_bandwidth_budget_bytes_ < 0.0;
}

void AxiTrafficGenerator::setBandwidthLimits(double max_write_bandwidth_mbps,
                                             double max_read_bandwidth_mbps,
                                             double clock_period_ns) {
    double seconds_per_cycle = (clock_period_ns > 0.0) ? (clock_period_ns * 1e-9) : 0.0;
    write_bandwidth_bytes_per_cycle_ = (max_write_bandwidth_mbps > 0.0)
        ? (max_write_bandwidth_mbps * 1e6 * seconds_per_cycle)
        : 0.0;
    read_bandwidth_bytes_per_cycle_ = (max_read_bandwidth_mbps > 0.0)
        ? (max_read_bandwidth_mbps * 1e6 * seconds_per_cycle)
        : 0.0;
    resetBandwidthState();
}

