#ifndef __INTERFACE_TYPES_HH
#define __INTERFACE_TYPES_HH

#include <memory>
#include <variant>
#include <optional>

#include "noc/lib/axi/AXITypes.hh"
#include "noc/lib/network/NocMessage.hh"
#include "noc/core/network/NocMessageBuffer.hh"
#include "noc/lib/interface/ResponseInfo.hh"
#include "noc/core/interface/CDCQueue.hh"

namespace gem5
{
namespace noc
{

struct ChannelDesc {
    std::string                 name;               // AR, AW, R, etc.
    int                         vnet;               // garnet::R_VNET, etc.
    std::string                 vnet_type;          // from pov of master
    int                         dir;                // 1=in 0=out if connected to a NMU
    MessageBuffer*              queue = nullptr;    // assigned at setup
    std::shared_ptr<CDCQueue>   cdcQueue = nullptr; // assigned at setup
};


struct MessageParams {
    int delay = 0;
    MsgPtr msg = nullptr;
    // std::variant<aximmRWData, aximmRWAddr, aximmWResp, MessagePayload>* data = nullptr; // used for traffic monitor stuff i guess
    // std::optional<std::variant<aximmRWData, aximmRWAddr, aximmWResp, MessagePayload>> data;
    std::optional<std::variant<aximmRWAddr, axisData>> data;
    // Protocol-agnostic data for this message (e.g., per-beat valid bytes)
    std::vector<uint8_t> beatBytes;
};

struct StreamObservation
{
    bool valid = false;
    bool ready = false;
    std::optional<bool> last;
    std::optional<uint64_t> dest;
    // Payload fingerprint for stability checking while stalled.
    // Handlers should include all signals that must remain stable while valid && !ready.
    std::vector<uint8_t> payload;
};

} // namespace noc
} // namespace gem5

#endif