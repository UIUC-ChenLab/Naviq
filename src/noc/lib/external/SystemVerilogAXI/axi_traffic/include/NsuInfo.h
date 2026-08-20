#ifndef NSU_INFO_H
#define NSU_INFO_H

#include <cstdint>

// NSU (NOC Slave Unit) descriptor: min AXI address and address space size in bytes
// Required for random strategy; all addresses are generated within the specified NSUs
// For AXIS, id is the NSU ID
struct NsuInfo {
    uint64_t min_addr = 0;
    uint64_t address_space = 0;  // Size in bytes; valid range is [min_addr, min_addr + address_space - 1]
    uint64_t id; // NSU ID for AXIS only

    NsuInfo(uint64_t min_addr, uint64_t address_space) {
        this->min_addr = min_addr;
        this->address_space = address_space;
    }

    NsuInfo(uint64_t id) {
        this->id = id;
    }
};

#endif // NSU_INFO_H
