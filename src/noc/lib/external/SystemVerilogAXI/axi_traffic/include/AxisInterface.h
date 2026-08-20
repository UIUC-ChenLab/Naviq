#ifndef AXIS_INTERFACE_H
#define AXIS_INTERFACE_H

#include <cstdint>
#include <vector>
#include "DataView.h"
#include "UBit.h"


// Class to hold AXI-Stream channel values
class AxisInterface {
public:
    // Constructor
    AxisInterface(size_t tdata_width, size_t tid_width, size_t tdest_width, size_t tuser_width);
    
    // Getter methods
    const DataView& getTData() const { return tdata_; }
    DataView& getTData() { return tdata_; }
    size_t getTDataWidth() const { return tdata_width_; }
    const std::vector<UBit>& getTKeep() const { return tkeep_; }
    std::vector<UBit>& getTKeep() { return tkeep_; }
    uint64_t getTId() const { return tid_.u64(); }
    size_t getTIdWidth() const { return tid_.bits(); }
    UBit& getTIdRef() { return tid_; }  // Get reference to UBit for direct modification
    uint64_t getTDest() const { return tdest_.u64(); }
    size_t getTDestWidth() const { return tdest_.bits(); }
    UBit& getTDestRef() { return tdest_; }  // Get reference to UBit for direct modification
    bool getTLast() const { return tlast_; }
    DataView& getTUser() { return tuser_; }
    const DataView& getTUser() const { return tuser_; }
    size_t getTUserWidth() const { return tuser_width_; }
    bool getTValid() const { return tvalid_; }
    bool getTReady() const { return tready_; }
    
    // Methods to set values
    void setTId(uint64_t id);
    void setTDest(uint64_t dest);
    void setTLast(bool last);
    void setTValid(bool valid);
    void setTReady(bool ready);
    
    // Set data (creates views or copies the views)
    void setTData(const DataView& data);
    void setTUser(const DataView& user);
    void setTKeep(const std::vector<UBit>& keep);

    // Clear all values
    void clear();

private:
    DataView tdata_;  // View into shared data for tdata
	size_t tdata_width_; // in bits
    std::vector<UBit> tkeep_;  // vector of tkeep bits (1 for each byte)
    UBit tid_;  // ID (up to 64 bits) - width stored in UBit
    UBit tdest_;  // Destination (up to 64 bits) - width stored in UBit
    bool tlast_;
    DataView tuser_;  // View into shared data for tuser
    size_t tuser_width_; // in bits
	size_t tkeep_width_; // in bits
    bool tvalid_;
    bool tready_;
};

#endif // AXIS_INTERFACE_H

