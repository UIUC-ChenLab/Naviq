#ifndef AXIS_PACKET_UTILS_H
#define AXIS_PACKET_UTILS_H

#include <cstdint>
#include <string>
#include <vector>

namespace axis_packet
{

struct AxisBeat
{
    std::vector<uint8_t> tdata;
    uint64_t tkeep = 0;
    uint64_t tid = 0;
    uint64_t tdest = 0;
    uint32_t tuser = 0;
    bool tlast = false;
    bool tvalid = false;

    AxisBeat() = default;
    AxisBeat(uint32_t data_width, uint64_t tid_value, uint64_t tdest_value,
             uint32_t tuser_value, bool last, bool valid);

    uint32_t validByteCount() const;
};

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
    uint32_t packet_index,
    uint32_t flow_count,
    uint32_t payload_bytes,
    uint32_t src_ip,
    uint32_t dst_ip,
    uint16_t src_port,
    uint16_t dst_port,
    bool corrupt_ipv4_checksum = false,
    bool corrupt_l4_checksum = false);

std::vector<uint8_t> prependEthernetHeader(
    const std::vector<uint8_t>& payload,
    uint64_t src_mac,
    uint64_t dst_mac,
    uint16_t ether_type = 0x0800);

std::vector<AxisBeat> packetToAxisBeats(
    const std::vector<uint8_t>& packet,
    uint32_t data_width,
    uint32_t id_width,
    uint32_t dest_width,
    uint32_t tid,
    uint32_t tdest,
    uint32_t tuser);

std::vector<AxisBeat> buildAxisPacketStream(
    Profile profile,
    uint32_t max_packets,
    uint32_t flow_count,
    uint32_t min_payload_bytes,
    uint32_t max_payload_bytes,
    uint32_t seed,
    uint32_t data_width,
    uint32_t id_width,
    uint32_t dest_width,
    uint32_t tid,
    uint32_t tdest,
    uint32_t tuser,
    uint32_t src_ip,
    uint32_t dst_ip,
    uint16_t src_port,
    uint16_t dst_port,
    bool corrupt_ipv4_checksum = false,
    bool corrupt_l4_checksum = false,
    uint32_t prefix_bytes = 0,
    uint32_t prefix_value = 0,
    bool include_ethernet = false,
    uint64_t src_mac = 0x020000000001ULL,
    uint64_t dst_mac = 0x020000000002ULL,
    uint16_t ether_type = 0x0800);

std::vector<AxisBeat> buildAxisPacketStream(
    Profile profile,
    uint32_t max_packets,
    uint32_t flow_count,
    const std::vector<uint32_t>& payload_sizes,
    uint32_t data_width,
    uint32_t id_width,
    uint32_t dest_width,
    uint32_t tid,
    uint32_t tdest,
    uint32_t tuser,
    uint32_t src_ip,
    uint32_t dst_ip,
    uint16_t src_port,
    uint16_t dst_port,
    bool corrupt_ipv4_checksum = false,
    bool corrupt_l4_checksum = false,
    uint32_t prefix_bytes = 0,
    uint32_t prefix_value = 0,
    bool include_ethernet = false,
    uint64_t src_mac = 0x020000000001ULL,
    uint64_t dst_mac = 0x020000000002ULL,
    uint16_t ether_type = 0x0800);

bool validateIpv4Packet(
    const std::vector<uint8_t>& packet,
    std::string& reason,
    bool validate_ipv4_checksum = true,
    bool validate_l4_checksum = true);

} // namespace axis_packet

#endif // AXIS_PACKET_UTILS_H
