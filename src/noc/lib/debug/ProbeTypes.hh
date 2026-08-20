#ifndef __NOC_TEST_PROBE_TYPES_HH__
#define __NOC_TEST_PROBE_TYPES_HH__

#include <array>
#include <cstdint>

namespace gem5 {
namespace noc {

/** Polymorphic root for NocInterface / NocProbe beat snapshots (not a Ruby State). */
struct ProbeData
{
    virtual ~ProbeData() = default;

    int32_t debugId = -1;
    int32_t getDebugId() const { return debugId; }
    void setDebugId(int32_t id) { debugId = id; }
    bool hasDebugId() const { return debugId >= 0; }
};

/** AXIS beat signals copied from tile + NI states at NocInterface snooper hooks. */
struct NocInterfaceAxisBeatData : ProbeData
{
    bool tvalid = false;
    /** Ready from the slave/link side toward the master beat (per-cycle handshake). */
    bool tready = false;
    bool tlast = false;
    uint64_t tkeep = 0;
    uint32_t tid = 0;
    uint32_t tdest = 0;
    uint8_t tuser = 0;
    std::array<uint8_t, 16> tdata_prefix{};

    bool ni_tready = false;
    bool cdc_enqueue_ready = false;
    bool node_input_tready = false;
};

/**
 * AXI-MM signals grouped by channel (aximm.<ch>.<signal> field IDs in NocProbe).
 * Master-driven payload uses tvalid; complementary ready uses tready on each channel.
 */
struct NocInterfaceAximmBeatData : ProbeData
{
    bool cdc_enqueue_ready = false;

    struct Ar
    {
        uint64_t addr = 0;
        uint32_t id = 0;
        uint8_t len = 0;
        uint8_t size = 0;
        uint8_t burst = 0;
        bool lock = false;
        uint8_t cache = 0;
        uint8_t prot = 0;
        uint8_t qos = 0;
        uint8_t region = 0;
        uint8_t user = 0;
        bool tvalid = false;
        bool tready = false;
    } ar;

    struct Aw
    {
        uint64_t addr = 0;
        uint32_t id = 0;
        uint8_t len = 0;
        uint8_t size = 0;
        uint8_t burst = 0;
        bool lock = false;
        uint8_t cache = 0;
        uint8_t prot = 0;
        uint8_t qos = 0;
        uint8_t region = 0;
        uint8_t user = 0;
        bool tvalid = false;
        bool tready = false;
    } aw;

    struct W
    {
        uint32_t id = 0;
        uint8_t resp = 0;
        bool last = false;
        uint8_t user = 0;
        bool tvalid = false;
        bool tready = false;
        uint64_t wstrb = 0;
        std::array<uint8_t, 64> data{};
    } w;

    struct R
    {
        uint32_t id = 0;
        uint8_t resp = 0;
        bool last = false;
        uint8_t user = 0;
        bool tvalid = false;
        bool tready = false;
        uint64_t wstrb = 0;
        std::array<uint8_t, 64> data{};
    } r;

    struct B
    {
        uint32_t id = 0;
        uint8_t resp = 0;
        uint8_t user = 0;
        bool tvalid = false;
        bool tready = false;
    } b;
};

} // namespace noc
} // namespace gem5

#endif
