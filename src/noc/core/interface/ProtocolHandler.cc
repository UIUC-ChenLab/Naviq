#include "ProtocolHandler.hh"
#include "protocols/AXIMMHandler.hh"
#include "protocols/AXISHandler.hh"

namespace gem5 {
namespace noc {


std::unique_ptr<ProtocolHandler>
ProtocolHandler::create(const std::string &proto, const std::string &role,  Tick clock_period, const std::vector<uint32_t>& protocol_parameters) {
    if (proto == "AXIMM")
        return std::make_unique<AXIMMHandler>(role);
    if (proto == "AXIS")
        return std::make_unique<AXISHandler>(role, protocol_parameters, clock_period);
    panic("Unknown protocol %s", proto.c_str());
}

}}
