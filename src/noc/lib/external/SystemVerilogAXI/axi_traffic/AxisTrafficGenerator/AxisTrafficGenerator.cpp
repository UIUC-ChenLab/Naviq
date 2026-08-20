#include "AxisTrafficGenerator.h"
#include <memory>

AxisTrafficGenerator::AxisTrafficGenerator(
    std::shared_ptr<AxisInterface> interface
) : interface_(interface),
    current_mode_(AxisGenerationMode::RANDOM)
{
    // Default to random mode
    setMode(AxisGenerationMode::RANDOM);
    reset();
}

AxisTrafficGenerator::~AxisTrafficGenerator() {
}

std::unique_ptr<AxisTrafficStrategy> AxisTrafficGenerator::createStrategy(AxisGenerationMode mode) {
    switch (mode) {
        case AxisGenerationMode::RANDOM:
            return std::make_unique<AxisRandomStrategy>();
        case AxisGenerationMode::PCAP_REPLAY:
            return std::make_unique<AxisPcapStrategy>();
        case AxisGenerationMode::PACKET:
            return std::make_unique<AxisPacketStrategy>();
        default:
            return nullptr;
    }
}

bool AxisTrafficGenerator::setMode(AxisGenerationMode mode) {
    current_mode_ = mode;
    strategy_ = createStrategy(mode);
    
    if (!strategy_) {
        std::cerr << "Error: Failed to create strategy for mode" << std::endl;
        return false;
    }
    
    // Initialize buffers based on interface widths
    strategy_->initializeBuffers(*interface_);
    
    return true;
}


bool AxisTrafficGenerator::setMode(const AxisRandomStrategy::Config& config) {
    current_mode_ = AxisGenerationMode::RANDOM;
    strategy_ = createStrategy(AxisGenerationMode::RANDOM);
    
    if (!strategy_) {
        std::cerr << "Error: Failed to create random strategy" << std::endl;
        return false;
    }
    
    auto* random_strategy = dynamic_cast<AxisRandomStrategy*>(strategy_.get());
    if (random_strategy) {
        random_strategy->configure(config);
        // Initialize buffers based on interface widths
        strategy_->initializeBuffers(*interface_);
        return true;
    }
    
    return false;
}

bool AxisTrafficGenerator::setMode(const AxisPcapStrategy::Config& config) {
    current_mode_ = AxisGenerationMode::PCAP_REPLAY;
    strategy_ = createStrategy(AxisGenerationMode::PCAP_REPLAY);
    
    if (!strategy_) {
        std::cerr << "Error: Failed to create PCAP replay strategy" << std::endl;
        return false;
    }
    
    auto* pcap_strategy = dynamic_cast<AxisPcapStrategy*>(strategy_.get());
    if (pcap_strategy) {
        pcap_strategy->configure(config);
        // Initialize buffers based on interface widths
        strategy_->initializeBuffers(*interface_);
        return true;
    }
    
    return false;
}

bool AxisTrafficGenerator::setMode(const AxisPacketStrategy::Config& config) {
    current_mode_ = AxisGenerationMode::PACKET;
    strategy_ = createStrategy(AxisGenerationMode::PACKET);

    if (!strategy_) {
        std::cerr << "Error: Failed to create packet strategy" << std::endl;
        return false;
    }

    auto* packet_strategy = dynamic_cast<AxisPacketStrategy*>(strategy_.get());
    if (packet_strategy) {
        packet_strategy->configure(config);
        strategy_->initializeBuffers(*interface_);
        return true;
    }

    return false;
}

void AxisTrafficGenerator::reset() {
    if (strategy_) {
        strategy_->reset();
    }
}

bool AxisTrafficGenerator::isDone() const {
    if (!strategy_) {
        return true; // No strategy means we're done
    }
    return !strategy_->hasMoreData();
}

void AxisTrafficGenerator::update() {
    strategy_->calculateNextValues(*interface_);
    strategy_->setInterfaceValues(*interface_);
}

void AxisTrafficGenerator::tick() {
    strategy_->tick(*interface_);
    strategy_->setInterfaceValues(*interface_);
}

void AxisTrafficGenerator::setInterfaceValues() {
    strategy_->setInterfaceValues(*interface_);
}

void AxisTrafficGenerator::calculateNextValues() {
    strategy_->calculateNextValues(*interface_);
}

std::string AxisTrafficGenerator::getModeName() const {
    if (strategy_) {
        return strategy_->getModeName();
    }
    return "unknown";
}

std::string AxisTrafficGenerator::getStrategyConfig() const {
    if (strategy_) {
        return strategy_->getConfigString();
    }
    return "";
}
