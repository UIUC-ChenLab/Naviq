#ifndef __AXI_TYPES_HH
#define __AXI_TYPES_HH

#include <cmath>
#include <cstdint>
#include <string>
#include <iostream>
#include <variant>
#include <vector>
#include <array>

#include "base/types.hh"


namespace gem5
{
namespace noc
{

/******************************/
/********* general AXI ********/
/******************************/

struct State {
    virtual ~State() = default;
    virtual std::unique_ptr<State> clone() const = 0;

    int32_t getDebugId() const { return debugId; }
    void setDebugId(int32_t id) { debugId = id; }
    bool hasDebugId() const { return debugId >= 0; }

  private:
    int32_t debugId = -1;
};

enum class AxiMsgSizeType{
    AR,
    AW,
    R,
    W,
    B,
    DEFAULT
};

using AxiDataBeat = std::array<uint8_t, 64>; // each beat up to 512-bit


/******************************/
/*********   AXI-S  **********/
/******************************/

struct axisData {
    // --- Configurable widths --- //
    uint32_t DATA_WIDTH = 512;
    uint32_t DATA_WIDTH_BITS = 9;
    uint32_t DST_ID_WIDTH = 4;
    uint32_t ID_WIDTH = 6;

    // --- Signals --- //
    std::vector<uint8_t> tdata;  // size = DATA_WIDTH / 8
    uint32_t tid = 0;            // width = ID_WIDTH
    uint32_t tdest = 0;          // width = DST_ID_WIDTH
    uint64_t tkeep = 0xFFFFFFFFFFFFFFFF; // dynamic masking (only use lower DATA_WIDTH/8 bits)
    uint32_t tuser = 0;
    bool     tlast = false;
    bool     tvalid = false;

    // --- Constructors --- //
    // Width is endpoint-configured.  The model stores up to 64 TKEEP bits,
    // covering endpoint data widths up to 512 bits.
    axisData(
        uint32_t data_width = 512,
        uint32_t id_width   = 6,
        uint32_t dest_width = 4
    ) :
        DATA_WIDTH(data_width),
        DATA_WIDTH_BITS(std::log2(data_width)),
        DST_ID_WIDTH(dest_width),
        ID_WIDTH(id_width)
    {
        // allocate TDATA based on runtime width
        tdata.resize(DATA_WIDTH / 8, 0);
    }

    axisData(
        const std::vector<uint8_t>& data,
        uint32_t data_width = 512,
        uint32_t id_width   = 6,
        uint32_t dest_width = 4,
        uint32_t tid = 0,
        uint32_t tdest = 0,
        bool last = false,
        bool valid = true
    ) :
        DATA_WIDTH(data_width),
        DATA_WIDTH_BITS(std::log2(data_width)),
        DST_ID_WIDTH(dest_width),
        ID_WIDTH(id_width),
        tdata(data),
        tid(tid),
        tdest(tdest),
        tlast(last),
        tvalid(valid)
    {
        if (tdata.size() != DATA_WIDTH / 8)
            tdata.resize(DATA_WIDTH / 8, 0);
    }

    // --- Functions --- //
    uint16_t getTotalByteSize() const {
        // One TKEEP bit represents one valid TDATA byte.  Sparse masks are
        // legal: this returns their population count, not a contiguous length.
        uint16_t active_bytes = 0;
        uint64_t mask = (DATA_WIDTH >= 64) ? 0xFFFFFFFFFFFFFFFFULL
                                        : ((1ULL << (DATA_WIDTH / 8)) - 1);

        uint64_t effective_tkeep = tkeep & mask;
        for (int i = 0; i < (DATA_WIDTH / 8); ++i) {
            if (effective_tkeep & (1ULL << i))
                ++active_bytes;
        }

        return active_bytes;
    }
};


struct axisSlaveState : public State {
    bool tready = true;

    std::unique_ptr<State> clone() const override {
        return std::unique_ptr<State>(new axisSlaveState(*this));
    }
};

struct axisMasterState : public State {
    axisData data{};

    /**
     * Diagnostic snapshots for probing at NMU node hooks.
     *
     * The AXI handshake is split across structs: `axisMasterState` carries the
     * master-driven beat (`tvalid`, `tdata`, ...), while the complementary
     * `axisSlaveState::tready` lives on the NI-side state inside `NocInterface`.
     * The AXIS handler mirrors that onto the node master state each cycle via
     * `ProtocolHandler::snapshotNodeStateForToCdcProbe` so legacy comparator hooks
     * and merged `noc_if.state.node_side` snapshots can print both sides. Snooper field `cdc.enqueue_ready`
     * (or legacy `axis.cdc_enqueue_ready`) reads this.
     */
    bool ni_tready = false;
    bool cdc_enqueue_ready = false;

    /**
     * Slave-tile TREADY (axisSlaveState::tready) copied into this struct for
     * noc_if.cdc.to_node snooping: axis.tready can read the node's ready toward
     * the NI even though the hook passes axisMasterState (beat from CDC).
     */
    bool node_input_tready = false;

    /// Kept for code that needs the endpoint's configured AXIS width.
    uint32_t getDataBitWidth() const {
        return data.DATA_WIDTH;
    }

    axisMasterState(
        uint32_t data_width,
        uint32_t id_width,
        uint32_t dest_width
    ) : data(data_width, id_width, dest_width) {}

    std::unique_ptr<State> clone() const override {
        return std::unique_ptr<State>(new axisMasterState(*this));
    }
};

/******************************/
/*********   AXI-MM  **********/
/******************************/

enum class AximmCommand {
    READ,
    WRITE,
    NONE
};

enum class BurstType {
    FIXED,
    INCR,
    WRAP
    //note: the HBM controller only supports INCR and WRAP
};

enum class AximmResp{
    OKAY,
    EXOKAY,
    SLVERR,
    DECERR
};

::std::ostream&
operator<<(::std::ostream& out, const AxiMsgSizeType& obj);

std::string
MessageSizeType_to_string(const AxiMsgSizeType obj);

struct aximmRWAddr {
    AximmCommand cmd = AximmCommand::NONE; // Default command
    uint32_t id = 0;
    uint64_t addr = 0;
    uint8_t len = 0;         // Burst length - 1
    uint8_t size = 0;        // Log2(bytes per beat)
    BurstType burst = BurstType::INCR; // Default burst
    bool lock = false;
    uint8_t cache = 0;
    uint8_t prot = 0;
    uint8_t qos = 0;
    uint8_t region = 0;
    uint8_t user = 0;
    bool valid = false;
    int32_t sourceNiDebug = -1;
    uint32_t originalReadBytesDebug = 0;
    int32_t debugId = -1;
    bool finalReadChunkDebug = false;

    uint16_t getTotalByteSize() const {
        return ((len + 1) * (1 << size));
    }

    uint16_t getBeatByteSize() const {
        return (1 << size);
    }
};

struct aximmRWData {
    AximmCommand cmd = AximmCommand::NONE; // Indicate if it's R or W data
    uint32_t id = 0;
    AximmResp resp = AximmResp::OKAY; // Default response for Read data
    bool last = false;           // *** Initialize last ***
    uint8_t user = 0;
    bool valid = false;
    bool ready = false;

    std::array<uint8_t, 64> data;
    // NMU configurable 32 to 512-bit data width
    //HBM_NMU configurable from 32 to 256 bits
    // so max is 4-64 bytes
    uint64_t wstrb = 0xFFFFFFFFFFFFFFFF;

    aximmRWData(AximmCommand cmd, uint32_t id, bool last, std::array<uint8_t, 64>* data, uint64_t wstrb = 0xFFFFFFFFFFFFFFFF):
        cmd(cmd), id(id), last(last), valid(true), data(*data), wstrb(wstrb){}

    aximmRWData() {
        data.fill(0); 
    }
};

struct aximmWResp {
    uint32_t id = 0;
    AximmResp resp = AximmResp::OKAY; // Default response
    uint8_t user = 0;
    bool valid = true;
};

struct aximmSlaveState : public State {
    bool arReady = true;
    aximmRWData r{};

    bool awReady = true;   // Ready to accept write address (slave drives AWREADY)
    bool wReady = true;    // Ready to accept write data (slave drives WREADY)
    aximmWResp b{};     // Write response (slave drives BRESP)

    std::unique_ptr<State> clone() const override {
        return std::unique_ptr<State>(new aximmSlaveState(*this));
    }
};

struct aximmMasterState : public State {
    aximmRWAddr ar{};
    bool rReady = false;

    aximmRWAddr aw{};   // Write address channel payload (master drives AWVALID, AWADDR, etc.)
    aximmRWData w{};    // Write data channel payload (master drives WVALID, WDATA, WSTRB, WLAST, etc.)
    bool bReady = false;    // Ready to accept write response (master drives BREADY)

    /** Filled by AXIMMHandler::snapshotNodeStateForToCdcProbe (CDC has slot this cycle). */
    bool cdc_enqueue_ready = false;

    std::unique_ptr<State> clone() const override {
        return std::unique_ptr<State>(new aximmMasterState(*this));
    }
};

// esentially a vector of n axisDatas that add up to 256 bytes (size of one NPP)
// with some other metadata that makes coding easier
struct axisPayload {
    static constexpr uint32_t NPP_MAX_SIZE = 256; // in bytes

    int numBeats = 0; // how many axisData objects make up the 256 bytes
    std::vector<axisData> beats;
    // Debug correlation ids aligned 1:1 with `beats`.
    // Intended for probing/latency measurement when multiple beats are packed
    // into one NPP.
    std::vector<int32_t> debugIds;
    int totalBytes = 0; // running sum of valid bytes
    int tid = -1;        // shared tid of all the beats. guaranteed to be the same // TODO: was never set
    int last = 0;      // contains the last byte of data of this transaction

    axisPayload() : numBeats(0), totalBytes(0), tid(-1), last(0) {}

    // constructor with a vector of beats
    axisPayload(const std::vector<axisData>& incomingBeats) : numBeats(0), totalBytes(0) {
        for (const auto& beat : incomingBeats) {
            int newBytes = beat.getTotalByteSize(); // how many bytes are in this beat
            // if(totalBytes + newBytes > NPP_MAX_SIZE) panic("axisPayload multi-beat initialization overflow (>256 bytes)");
            beats.push_back(beat);
            debugIds.push_back(-1);
            numBeats++;
            totalBytes += newBytes;
        }
    }

    // constructor with a single beat
    axisPayload(const axisData& incomingBeat) : numBeats(0), totalBytes(0) {
        int newBytes = incomingBeat.getTotalByteSize(); // how many bytes are in this beat
        // if(totalBytes + newBytes > NPP_MAX_SIZE) panic("axisPayload single-beat initialization overflow (>256 bytes)");
        beats.push_back(incomingBeat);
        debugIds.push_back(-1);
        numBeats++;
        totalBytes += newBytes;
    }

    // check if it can take

    // append to beats
    void add(const axisData& incomingBeat, int32_t dbgId = -1) {
        int newBytes = incomingBeat.getTotalByteSize(); // how many bytes are in this beat
        // if(totalBytes + newBytes > NPP_MAX_SIZE) panic("axisPayload add beat overflow (>256 bytes)"); // TODO: add back this panic
        beats.push_back(incomingBeat);
        debugIds.push_back(dbgId);
        numBeats++;
        totalBytes += newBytes;
    }

};

using MessagePayload = std::variant<aximmRWAddr, aximmRWData, aximmWResp, axisData>; //TODO take out aximmRWData, rename to something that makes more sense
// using aximmPayload = std::array<aximmRWData, 16>; // max 16 beats in a burst
using aximmPayload = std::array<aximmRWData, 4>; // max 16 beats in a burst

static constexpr uint8_t NPP_BEAT_SIZE = 64;
using Payload = std::variant<aximmPayload, axisPayload>;

using CDCPayload = std::variant<Payload, MessagePayload>;

} // namespace noc
} // namespace gem5


#endif
