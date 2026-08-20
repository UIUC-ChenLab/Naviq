#ifndef AXIS_TRAFFIC_GENERATOR_H
#define AXIS_TRAFFIC_GENERATOR_H

#include <cstring>
#include <algorithm>
#include <fstream>
#include <sstream>
#include <string>
#include <cstdint>
#include <iostream>
#include <vector>
#include <memory>
#include "UBit.h"
#include "DataView.h"
#include "AxisInterface.h"
#include "AxisTrafficStrategy.h"
#include "AxisRandomStrategy.h"
#include "AxisPcapStrategy.h"
#include "AxisPacketStrategy.h"

// Generation modes
enum class AxisGenerationMode {
    RANDOM,
    PCAP_REPLAY,
    PACKET
};

// C++ class for AXIS traffic generation
// Can be used standalone in C++ testbenches or via DPI wrapper for Verilog
class AxisTrafficGenerator {
public:
    AxisTrafficGenerator(
        std::shared_ptr<AxisInterface> interface
    );
    
    ~AxisTrafficGenerator();
    
    // Set the generation mode
    // mode: the generation mode to use
    // Returns true on success, false on error
    bool setMode(AxisGenerationMode mode);
    
    // Set mode to RANDOM with configuration struct
    // config: AxisRandomStrategy configuration
    // Returns true on success, false on error
    bool setMode(const AxisRandomStrategy::Config& config);
    
    // Set mode to PCAP_REPLAY with configuration struct
    // config: AxisPcapStrategy configuration
    // Returns true on success, false on error
    bool setMode(const AxisPcapStrategy::Config& config);

    // Set mode to PACKET with configuration struct.
    bool setMode(const AxisPacketStrategy::Config& config);
    
    // Reset the generator
    void reset();
    
    // Check if the generator is done (no more data to generate)
    // Returns true if done, false if more data is available
    bool isDone() const;
    
    // Set the interface values
    void update();

    // Tick the generator
    void tick();
    
    // Get current configuration
    size_t getTDataWidth() const { return interface_->getTDataWidth(); }
    size_t getTdestWidth() const { return interface_->getTDestWidth(); }
    size_t getTidWidth() const { return interface_->getTIdWidth(); }
    size_t getTuserWidth() const { return interface_->getTUserWidth(); }
    size_t getKeepWidth() const { return interface_->getTKeep().size(); }
    AxisGenerationMode getCurrentMode() const { return current_mode_; }
    std::string getModeName() const;
    std::string getStrategyConfig() const;

private:
    std::shared_ptr<AxisInterface> interface_; // Shared pointer to the AxisInterface
    
    AxisGenerationMode current_mode_;
    std::unique_ptr<AxisTrafficStrategy> strategy_;
    
    // Helper function to create strategy based on mode
    std::unique_ptr<AxisTrafficStrategy> createStrategy(AxisGenerationMode mode);

    // Calculate the next values for the strategy
    void calculateNextValues();
    void setInterfaceValues();
};

#endif // AXIS_TRAFFIC_GENERATOR_H
