#ifndef AXIS_TRAFFIC_STRATEGY_H
#define AXIS_TRAFFIC_STRATEGY_H

#include "DataView.h"
#include "AxisInterface.h"
#include "UBit.h"
#include <vector>
#include <string>
#include <cstdint>
#include <memory>

// Abstract base class for traffic generation strategies
// Each mode (random, file stream, pcap replay) implements this interface
class AxisTrafficStrategy {
public:
    virtual ~AxisTrafficStrategy() = default;
    
    // Get current interface values without modifying state
    // This should return the same values on repeated calls unless tick() has been called
    void setInterfaceValues(
        AxisInterface& channel
    );
    
    // Update internal state to the next state based on tready from channel
    // channel: the AxisInterface to read tready from and calculate widths from
    // This should update the internal state to the next state based on tready from channel
    virtual void tick(AxisInterface& channel);
    
    // Calculate the next values for the strategy
    virtual void calculateNextValues(AxisInterface& channel) = 0;
    
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

    // Initialize buffers based on interface widths
    // Should be called once when interface is available
    void initializeBuffers(AxisInterface& channel);

protected:
    // Current interface state (for getInterfaceValues)
    // Derived classes should update these in tick() based on tready
    bool current_tvalid_;
    bool current_tlast_;
    uint64_t current_tid_;
    uint64_t current_tdest_;
    std::shared_ptr<std::vector<uint8_t>> current_tdata_buffer_;
    DataView current_tdata_;
    std::vector<UBit> current_tkeep_;
    std::shared_ptr<std::vector<uint8_t>> current_tuser_buffer_;
    DataView current_tuser_;


    bool next_tvalid_;
    bool next_tlast_;
    uint64_t next_tid_;
    uint64_t next_tdest_;
    std::shared_ptr<std::vector<uint8_t>> next_tdata_buffer_;
    DataView next_tdata_;
    std::vector<UBit> next_tkeep_;
    std::shared_ptr<std::vector<uint8_t>> next_tuser_buffer_;
    DataView next_tuser_;
    
    // Constructor - initializes common state
    AxisTrafficStrategy();
    
    // Helper to reset common state (call from derived reset())
    void resetCommonState();
};

#endif // AXIS_TRAFFIC_STRATEGY_H

