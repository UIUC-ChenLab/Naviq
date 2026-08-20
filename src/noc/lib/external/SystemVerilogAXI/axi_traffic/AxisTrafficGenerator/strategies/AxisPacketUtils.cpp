#include "AxisPacketUtils.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <random>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace axis_packet
{

namespace
{

std::string
upper(std::string s)
{
    std::transform(s.begin(), s.end(), s.begin(),
        [](unsigned char c) { return std::toupper(c); });
    return s;
}

void
writeBe16(std::vector<uint8_t>& bytes, size_t off, uint16_t value)
{
    bytes.at(off) = static_cast<uint8_t>((value >> 8) & 0xff);
    bytes.at(off + 1) = static_cast<uint8_t>(value & 0xff);
}

void
writeBe32(std::vector<uint8_t>& bytes, size_t off, uint32_t value)
{
    bytes.at(off) = static_cast<uint8_t>((value >> 24) & 0xff);
    bytes.at(off + 1) = static_cast<uint8_t>((value >> 16) & 0xff);
    bytes.at(off + 2) = static_cast<uint8_t>((value >> 8) & 0xff);
    bytes.at(off + 3) = static_cast<uint8_t>(value & 0xff);
}

uint16_t
readBe16(const std::vector<uint8_t>& bytes, size_t off)
{
    return static_cast<uint16_t>(
        (static_cast<uint16_t>(bytes.at(off)) << 8) | bytes.at(off + 1));
}

uint32_t
onesAddBytes(uint32_t sum, const uint8_t* data, size_t len)
{
    for (size_t i = 0; i + 1 < len; i += 2) {
        sum += (static_cast<uint32_t>(data[i]) << 8) | data[i + 1];
    }
    if (len & 1) {
        sum += static_cast<uint32_t>(data[len - 1]) << 8;
    }
    return sum;
}

uint16_t
onesFinalize(uint32_t sum)
{
    while (sum >> 16) {
        sum = (sum & 0xffffu) + (sum >> 16);
    }
    return static_cast<uint16_t>(~sum & 0xffffu);
}

uint16_t
internetChecksum(const uint8_t* data, size_t len)
{
    return onesFinalize(onesAddBytes(0, data, len));
}

uint16_t
l4Checksum(const std::vector<uint8_t>& packet, size_t l4_off, size_t l4_len,
           uint8_t protocol)
{
    uint32_t sum = 0;
    sum += readBe16(packet, 12);
    sum += readBe16(packet, 14);
    sum += readBe16(packet, 16);
    sum += readBe16(packet, 18);
    sum += protocol;
    sum += static_cast<uint16_t>(l4_len);
    sum = onesAddBytes(sum, packet.data() + l4_off, l4_len);
    const uint16_t result = onesFinalize(sum);
    return result == 0 ? 0xffffu : result;
}

uint64_t
prefixKeep(size_t valid_bytes)
{
    if (valid_bytes >= 64) {
        return 0xffffffffffffffffULL;
    }
    if (valid_bytes == 0) {
        return 0;
    }
    return (1ULL << valid_bytes) - 1ULL;
}

void
appendMac(std::vector<uint8_t>& bytes, uint64_t mac)
{
    for (int shift = 40; shift >= 0; shift -= 8) {
        bytes.push_back(static_cast<uint8_t>((mac >> shift) & 0xff));
    }
}

void
prependPrefix(std::vector<uint8_t>& packet, uint32_t prefix_bytes,
              uint32_t prefix_value)
{
    if (prefix_bytes == 0) {
        return;
    }

    std::vector<uint8_t> prefixed(prefix_bytes, 0);
    for (uint32_t b = 0; b < prefix_bytes; ++b) {
        prefixed[b] = static_cast<uint8_t>((prefix_value >> (8 * b)) & 0xff);
    }
    prefixed.insert(prefixed.end(), packet.begin(), packet.end());
    packet = std::move(prefixed);
}

} // anonymous namespace

AxisBeat::AxisBeat(uint32_t data_width, uint64_t tid_value,
                   uint64_t tdest_value, uint32_t tuser_value, bool last,
                   bool valid)
    : tdata(data_width / 8, 0),
      tid(tid_value),
      tdest(tdest_value),
      tuser(tuser_value),
      tlast(last),
      tvalid(valid)
{
}

uint32_t
AxisBeat::validByteCount() const
{
    uint32_t active_bytes = 0;
    const size_t bytes = std::min<size_t>(tdata.size(), 64);
    for (size_t i = 0; i < bytes; ++i) {
        if (tkeep & (1ULL << i)) {
            ++active_bytes;
        }
    }
    return active_bytes;
}

Profile
parseProfile(const std::string& profile)
{
    const std::string p = upper(profile);
    if (p == "IPV4_TCP") {
        return Profile::Ipv4Tcp;
    }
    if (p == "MIXED_TCP_UDP") {
        return Profile::MixedTcpUdp;
    }
    return Profile::Ipv4Udp;
}

uint32_t
parseIpv4Address(const std::string& text, uint32_t fallback)
{
    unsigned a = 0, b = 0, c = 0, d = 0;
    if (std::sscanf(text.c_str(), "%u.%u.%u.%u", &a, &b, &c, &d) == 4 &&
        a <= 255 && b <= 255 && c <= 255 && d <= 255) {
        return (a << 24) | (b << 16) | (c << 8) | d;
    }

    if (!text.empty()) {
        try {
            size_t idx = 0;
            unsigned long value = std::stoul(text, &idx, 0);
            if (idx == text.size() && value <= 0xffffffffUL) {
                return static_cast<uint32_t>(value);
            }
        } catch (...) {
        }
    }
    return fallback;
}

std::string
ipv4ToString(uint32_t ip)
{
    std::ostringstream os;
    os << ((ip >> 24) & 0xff) << '.'
       << ((ip >> 16) & 0xff) << '.'
       << ((ip >> 8) & 0xff) << '.'
       << (ip & 0xff);
    return os.str();
}

std::vector<uint32_t>
parsePayloadSizes(const std::string& text)
{
    std::vector<uint32_t> sizes;
    std::stringstream ss(text);
    std::string token;
    while (std::getline(ss, token, ',')) {
        token.erase(std::remove_if(token.begin(), token.end(),
                    [](unsigned char c) { return std::isspace(c); }),
                    token.end());
        if (token.empty()) {
            continue;
        }
        size_t idx = 0;
        const unsigned long value = std::stoul(token, &idx, 0);
        if (idx != token.size() || value > 65535) {
            throw std::invalid_argument("Invalid payload size token '" + token + "'");
        }
        sizes.push_back(static_cast<uint32_t>(value));
    }
    return sizes;
}

std::vector<uint8_t>
buildIpv4Packet(Profile profile, uint32_t packet_index, uint32_t flow_count,
                uint32_t payload_bytes, uint32_t src_ip, uint32_t dst_ip,
                uint16_t src_port, uint16_t dst_port,
                bool corrupt_ipv4_checksum, bool corrupt_l4_checksum)
{
    const bool tcp = profile == Profile::Ipv4Tcp ||
        (profile == Profile::MixedTcpUdp && (packet_index & 1));
    const uint8_t protocol = tcp ? 6 : 17;
    const size_t ip_hdr_len = 20;
    const size_t l4_hdr_len = tcp ? 20 : 8;
    const size_t total_len = ip_hdr_len + l4_hdr_len + payload_bytes;
    if (total_len > 65535) {
        throw std::invalid_argument("Axis packet total length exceeds IPv4 max");
    }

    const uint32_t flow = flow_count == 0 ? 0 : (packet_index % flow_count);
    const uint32_t flow_src_ip = src_ip + flow;
    const uint32_t flow_dst_ip = dst_ip + flow;
    const uint16_t flow_src_port = static_cast<uint16_t>(src_port + flow);
    const uint16_t flow_dst_port = static_cast<uint16_t>(dst_port + flow);

    std::vector<uint8_t> bytes(total_len, 0);
    bytes[0] = 0x45;
    bytes[1] = 0;
    writeBe16(bytes, 2, static_cast<uint16_t>(total_len));
    writeBe16(bytes, 4, static_cast<uint16_t>(0x1000u + packet_index));
    writeBe16(bytes, 6, 0x4000);
    bytes[8] = 64;
    bytes[9] = protocol;
    writeBe16(bytes, 10, 0);
    writeBe32(bytes, 12, flow_src_ip);
    writeBe32(bytes, 16, flow_dst_ip);

    const size_t l4 = ip_hdr_len;
    writeBe16(bytes, l4, flow_src_port);
    writeBe16(bytes, l4 + 2, flow_dst_port);
    if (tcp) {
        writeBe32(bytes, l4 + 4, 0x01000000u + packet_index);
        writeBe32(bytes, l4 + 8, 0x02000000u + packet_index);
        bytes[l4 + 12] = 0x50;
        bytes[l4 + 13] = 0x18;
        writeBe16(bytes, l4 + 14, 0x4000);
        writeBe16(bytes, l4 + 16, 0);
        writeBe16(bytes, l4 + 18, 0);
    } else {
        writeBe16(bytes, l4 + 4, static_cast<uint16_t>(l4_hdr_len + payload_bytes));
        writeBe16(bytes, l4 + 6, 0);
    }

    for (size_t i = 0; i < payload_bytes; ++i) {
        bytes[ip_hdr_len + l4_hdr_len + i] =
            static_cast<uint8_t>(0xa0u + packet_index + i);
    }

    writeBe16(bytes, 10, internetChecksum(bytes.data(), ip_hdr_len));
    if (tcp) {
        writeBe16(bytes, l4 + 16,
                  l4Checksum(bytes, l4, l4_hdr_len + payload_bytes, protocol));
    } else {
        writeBe16(bytes, l4 + 6,
                  l4Checksum(bytes, l4, l4_hdr_len + payload_bytes, protocol));
    }
    if (corrupt_ipv4_checksum) {
        writeBe16(bytes, 10, readBe16(bytes, 10) ^ 0xffffu);
    }
    if (corrupt_l4_checksum) {
        const size_t checksum_off = tcp ? (l4 + 16) : (l4 + 6);
        writeBe16(bytes, checksum_off, readBe16(bytes, checksum_off) ^ 0xffffu);
    }
    return bytes;
}

std::vector<uint8_t>
prependEthernetHeader(const std::vector<uint8_t>& payload, uint64_t src_mac,
                      uint64_t dst_mac, uint16_t ether_type)
{
    std::vector<uint8_t> frame;
    frame.reserve(14 + payload.size());
    appendMac(frame, dst_mac);
    appendMac(frame, src_mac);
    frame.push_back(static_cast<uint8_t>((ether_type >> 8) & 0xff));
    frame.push_back(static_cast<uint8_t>(ether_type & 0xff));
    frame.insert(frame.end(), payload.begin(), payload.end());
    return frame;
}

std::vector<AxisBeat>
packetToAxisBeats(const std::vector<uint8_t>& packet, uint32_t data_width,
                  uint32_t id_width, uint32_t dest_width, uint32_t tid,
                  uint32_t tdest, uint32_t tuser)
{
    (void)id_width;
    (void)dest_width;

    if (data_width == 0 || data_width % 8 != 0) {
        throw std::invalid_argument("AXIS data width must be a non-zero byte multiple");
    }
    if (data_width > 512) {
        throw std::invalid_argument("AXIS packet test nodes only support up to 512-bit data");
    }

    const size_t bytes_per_beat = data_width / 8;
    std::vector<AxisBeat> beats;
    for (size_t off = 0; off < packet.size(); off += bytes_per_beat) {
        const size_t n = std::min(bytes_per_beat, packet.size() - off);
        AxisBeat beat(data_width, tid, tdest, tuser,
                      (off + n) >= packet.size(), true);
        std::copy(packet.begin() + off, packet.begin() + off + n,
                  beat.tdata.begin());
        beat.tkeep = prefixKeep(n);
        beats.push_back(beat);
    }
    return beats;
}

std::vector<AxisBeat>
buildAxisPacketStream(Profile profile, uint32_t max_packets, uint32_t flow_count,
                      uint32_t min_payload_bytes, uint32_t max_payload_bytes,
                      uint32_t seed, uint32_t data_width, uint32_t id_width,
                      uint32_t dest_width, uint32_t tid, uint32_t tdest,
                      uint32_t tuser, uint32_t src_ip, uint32_t dst_ip,
                      uint16_t src_port, uint16_t dst_port,
                      bool corrupt_ipv4_checksum, bool corrupt_l4_checksum,
                      uint32_t prefix_bytes, uint32_t prefix_value,
                      bool include_ethernet, uint64_t src_mac,
                      uint64_t dst_mac, uint16_t ether_type)
{
    std::mt19937 rng(seed);
    if (max_payload_bytes < min_payload_bytes) {
        std::swap(max_payload_bytes, min_payload_bytes);
    }
    std::uniform_int_distribution<uint32_t> payload_dist(
        min_payload_bytes, max_payload_bytes);

    std::vector<AxisBeat> stream;
    for (uint32_t i = 0; i < max_packets; ++i) {
        const uint32_t payload_bytes = payload_dist(rng);
        auto packet = buildIpv4Packet(profile, i, flow_count, payload_bytes,
                                      src_ip, dst_ip, src_port, dst_port,
                                      corrupt_ipv4_checksum,
                                      corrupt_l4_checksum);
        if (include_ethernet) {
            packet = prependEthernetHeader(packet, src_mac, dst_mac, ether_type);
        }
        prependPrefix(packet, prefix_bytes, prefix_value);

        auto beats = packetToAxisBeats(packet, data_width, id_width, dest_width,
                                       tid, tdest, tuser);
        stream.insert(stream.end(), beats.begin(), beats.end());
    }
    return stream;
}

std::vector<AxisBeat>
buildAxisPacketStream(Profile profile, uint32_t max_packets, uint32_t flow_count,
                      const std::vector<uint32_t>& payload_sizes,
                      uint32_t data_width, uint32_t id_width,
                      uint32_t dest_width, uint32_t tid, uint32_t tdest,
                      uint32_t tuser, uint32_t src_ip, uint32_t dst_ip,
                      uint16_t src_port, uint16_t dst_port,
                      bool corrupt_ipv4_checksum, bool corrupt_l4_checksum,
                      uint32_t prefix_bytes, uint32_t prefix_value,
                      bool include_ethernet, uint64_t src_mac,
                      uint64_t dst_mac, uint16_t ether_type)
{
    if (payload_sizes.empty()) {
        throw std::invalid_argument("Payload size list must contain at least one entry");
    }

    std::vector<AxisBeat> stream;
    for (uint32_t i = 0; i < max_packets; ++i) {
        auto packet = buildIpv4Packet(profile, i, flow_count,
                                      payload_sizes[i % payload_sizes.size()],
                                      src_ip, dst_ip, src_port, dst_port,
                                      corrupt_ipv4_checksum,
                                      corrupt_l4_checksum);
        if (include_ethernet) {
            packet = prependEthernetHeader(packet, src_mac, dst_mac, ether_type);
        }
        prependPrefix(packet, prefix_bytes, prefix_value);

        auto beats = packetToAxisBeats(packet, data_width, id_width, dest_width,
                                       tid, tdest, tuser);
        stream.insert(stream.end(), beats.begin(), beats.end());
    }
    return stream;
}

bool
validateIpv4Packet(const std::vector<uint8_t>& packet, std::string& reason,
                   bool validate_ipv4_checksum, bool validate_l4_checksum)
{
    if (packet.size() < 20) {
        reason = "packet shorter than IPv4 header";
        return false;
    }
    const uint8_t version = packet[0] >> 4;
    const uint8_t ihl = packet[0] & 0x0f;
    const size_t ip_hdr_len = static_cast<size_t>(ihl) * 4;
    if (version != 4 || ihl < 5) {
        reason = "invalid IPv4 version/IHL";
        return false;
    }
    if (packet.size() < ip_hdr_len) {
        reason = "packet shorter than IPv4 IHL";
        return false;
    }
    const uint16_t total_len = readBe16(packet, 2);
    if (total_len != packet.size()) {
        reason = "IPv4 total length does not match AXIS packet bytes";
        return false;
    }
    if (validate_ipv4_checksum && internetChecksum(packet.data(), ip_hdr_len) != 0) {
        reason = "invalid IPv4 header checksum";
        return false;
    }

    const uint8_t protocol = packet[9];
    const size_t l4_len = packet.size() - ip_hdr_len;
    if (protocol == 17) {
        if (l4_len < 8) {
            reason = "UDP packet shorter than UDP header";
            return false;
        }
        if (readBe16(packet, ip_hdr_len + 4) != l4_len) {
            reason = "UDP length does not match IPv4 payload length";
            return false;
        }
        const uint16_t udp_checksum = l4Checksum(packet, ip_hdr_len, l4_len, protocol);
        if (validate_l4_checksum && readBe16(packet, ip_hdr_len + 6) != 0 &&
            udp_checksum != 0 && udp_checksum != 0xffff) {
            reason = "invalid UDP checksum";
            return false;
        }
        return true;
    }
    if (protocol == 6) {
        if (l4_len < 20) {
            reason = "TCP packet shorter than TCP header";
            return false;
        }
        const uint8_t doff = packet[ip_hdr_len + 12] >> 4;
        if (doff < 5 || l4_len < static_cast<size_t>(doff) * 4) {
            reason = "invalid TCP data offset";
            return false;
        }
        const uint16_t tcp_checksum = l4Checksum(packet, ip_hdr_len, l4_len, protocol);
        if (validate_l4_checksum && tcp_checksum != 0 && tcp_checksum != 0xffff) {
            reason = "invalid TCP checksum";
            return false;
        }
        return true;
    }

    reason = "unsupported IPv4 protocol";
    return false;
}

} // namespace axis_packet
