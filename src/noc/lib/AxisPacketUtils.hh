#ifndef __NOC_AXIS_PACKET_UTILS_HH__
#define __NOC_AXIS_PACKET_UTILS_HH__

#include "noc/lib/axi/AXITypes.hh"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace gem5
{
namespace noc
{
namespace axis_packet
{

enum class Profile
{
    Ipv4Udp,
    Ipv4Tcp,
    MixedTcpUdp,
};

Profile parseProfile(const std::string& profile);

uint32_t parseIpv4Address(const std::string& text, uint32_t fallback);
std::string ipv4ToString(uint32_t ip);
std::vector<uint32_t> parsePayloadSizes(const std::string& text);

std::vector<uint8_t> buildIpv4Packet(
    Profile profile,
    uint32_t packetIndex,
    uint32_t flowCount,
    uint32_t payloadBytes,
    uint32_t srcIp,
    uint32_t dstIp,
    uint16_t srcPort,
    uint16_t dstPort,
    bool corruptIpv4Checksum = false,
    bool corruptL4Checksum = false);

std::vector<axisData> packetToAxisBeats(
    const std::vector<uint8_t>& packet,
    uint32_t dataWidth,
    uint32_t idWidth,
    uint32_t destWidth,
    uint32_t tid,
    uint32_t tdest,
    uint32_t tuser);

std::vector<axisData> buildAxisPacketStream(
    Profile profile,
    uint32_t maxPackets,
    uint32_t flowCount,
    uint32_t minPayloadBytes,
    uint32_t maxPayloadBytes,
    uint32_t seed,
    uint32_t dataWidth,
    uint32_t idWidth,
    uint32_t destWidth,
    uint32_t tid,
    uint32_t tdest,
    uint32_t tuser,
    uint32_t srcIp,
    uint32_t dstIp,
    uint16_t srcPort,
    uint16_t dstPort,
    bool corruptIpv4Checksum = false,
    bool corruptL4Checksum = false,
    uint32_t prefixBytes = 0,
    uint32_t prefixValue = 0);

std::vector<axisData> buildAxisPacketStream(
    Profile profile,
    uint32_t maxPackets,
    uint32_t flowCount,
    const std::vector<uint32_t>& payloadSizes,
    uint32_t dataWidth,
    uint32_t idWidth,
    uint32_t destWidth,
    uint32_t tid,
    uint32_t tdest,
    uint32_t tuser,
    uint32_t srcIp,
    uint32_t dstIp,
    uint16_t srcPort,
    uint16_t dstPort,
    bool corruptIpv4Checksum = false,
    bool corruptL4Checksum = false,
    uint32_t prefixBytes = 0,
    uint32_t prefixValue = 0);

bool validateIpv4Packet(
    const std::vector<uint8_t>& packet,
    std::string& reason,
    bool validateIpv4Checksum = true,
    bool validateL4Checksum = true);

} // namespace axis_packet
} // namespace noc
} // namespace gem5

#endif // __NOC_AXIS_PACKET_UTILS_HH__
