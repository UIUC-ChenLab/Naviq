#include "AxisInterface.h"
#include <cstring>
#include <stdexcept>

// AxisInterface implementation
AxisInterface::AxisInterface(size_t tdata_width, size_t tid_width, size_t tdest_width, size_t tuser_width) :
    tdata_width_(tdata_width),
	tid_(tid_width, 0),
    tdest_(tdest_width, 0),
    tuser_width_(tuser_width),
	tkeep_width_(tdata_width / 8),
    tlast_(false),
    tvalid_(false),
    tready_(false),
	tdata_(std::make_shared<std::vector<uint8_t>>(tdata_width / 8, 0), tdata_width / 8, 0),
	tkeep_(std::vector<UBit>(tdata_width / 8, UBit(1, 0))),
	tuser_(std::make_shared<std::vector<uint8_t>>(tuser_width / 8, 0), tuser_width / 8, 0)
{
}

void AxisInterface::setTId(uint64_t id) {
    tid_ = id;
}

void AxisInterface::setTDest(uint64_t dest) {
    tdest_ = dest;
}

void AxisInterface::setTLast(bool last) {
    tlast_ = last;
}

void AxisInterface::setTValid(bool valid) {
    tvalid_ = valid;
}

void AxisInterface::setTReady(bool ready) {
    tready_ = ready;
}

void AxisInterface::setTData(const DataView& data) {
    tdata_ = data;
    if (tdata_.size() != tdata_width_ / 8) {
        throw std::runtime_error("tdata_ size does not match tdata_width_ (in Bytes)" + std::to_string(tdata_.size()) + " != " + std::to_string(tdata_width_ / 8));
    }
}

void AxisInterface::setTKeep(const std::vector<UBit>& keep) {
    if (keep.size() != tkeep_width_) {
        throw std::runtime_error("tkeep_ size does not match tkeep_width_" + std::to_string(keep.size()) + " != " + std::to_string(tkeep_width_));
    }
    tkeep_ = keep;
    // Ensure each UBit is 1 bit
    for (auto& bit : tkeep_) {
        if (bit.bits() != 1) {
            bit = UBit(1, bit.u64() & 1);
        }
    }
}

void AxisInterface::setTUser(const DataView& user) {
    tuser_ = user;
    if (tuser_.size() != tuser_width_ / 8) {
        throw std::runtime_error("tuser_ size does not match tuser_width_ (in Bytes)" + std::to_string(tuser_.size()) + " != " + std::to_string(tuser_width_ / 8));
    }
}

void AxisInterface::clear() {
    tid_ = 0ULL;
    tdest_ = 0ULL;
    tlast_ = false;
    tvalid_ = false;
    tready_ = false;
}

