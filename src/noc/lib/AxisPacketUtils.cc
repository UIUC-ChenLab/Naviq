#include "noc/lib/AxisPacketUtils.hh"

#include "base/logging.hh"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <random>
#include <sstream>
#include <utility>

namespace gem5
{
namespace noc
{
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
l4Checksum(const std::vector<uint8_t>& packet, size_t l4Off, size_t l4Len,
           uint8_t protocol)
{
    uint32_t sum = 0;
    sum += readBe16(packet, 12);
    sum += readBe16(packet, 14);
    sum += readBe16(packet, 16);
    sum += readBe16(packet, 18);
    sum += protocol;
    sum += static_cast<uint16_t>(l4Len);
    sum = onesAddBytes(sum, packet.data() + l4Off, l4Len);
    const uint16_t result = onesFinalize(sum);
    return result == 0 ? 0xffffu : result;
}

uint64_t
prefixKeep(size_t validBytes)
{
    if (validBytes >= 64) {
        return 0xffffffffffffffffULL;
    }
    if (validBytes == 0) {
        return 0;
    }
    return (1ULL << validBytes) - 1ULL;
}

} // anonymous namespace

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
        fatal_if(idx != token.size() || value > 65535,
                 "Invalid payload size token '%s'", token);
        sizes.push_back(static_cast<uint32_t>(value));
    }
    return sizes;
}

std::vector<uint8_t>
buildIpv4Packet(Profile profile, uint32_t packetIndex, uint32_t flowCount,
                uint32_t payloadBytes, uint32_t srcIp, uint32_t dstIp,
                uint16_t srcPort, uint16_t dstPort,
                bool corruptIpv4Checksum, bool corruptL4Checksum)
{
    const bool tcp = profile == Profile::Ipv4Tcp ||
        (profile == Profile::MixedTcpUdp && (packetIndex & 1));
    const uint8_t protocol = tcp ? 6 : 17;
    const size_t ipHdrLen = 20;
    const size_t l4HdrLen = tcp ? 20 : 8;
    const size_t totalLen = ipHdrLen + l4HdrLen + payloadBytes;
    fatal_if(totalLen > 65535, "Axis packet total length exceeds IPv4 max");

    const uint32_t flow = flowCount == 0 ? 0 : (packetIndex % flowCount);
    const uint32_t flowSrcIp = srcIp + flow;
    const uint32_t flowDstIp = dstIp + flow;
    const uint16_t flowSrcPort = static_cast<uint16_t>(srcPort + flow);
    const uint16_t flowDstPort = static_cast<uint16_t>(dstPort + flow);

    std::vector<uint8_t> bytes(totalLen, 0);
    bytes[0] = 0x45;
    bytes[1] = 0;
    writeBe16(bytes, 2, static_cast<uint16_t>(totalLen));
    writeBe16(bytes, 4, static_cast<uint16_t>(0x1000u + packetIndex));
    writeBe16(bytes, 6, 0x4000);
    bytes[8] = 64;
    bytes[9] = protocol;
    writeBe16(bytes, 10, 0);
    writeBe32(bytes, 12, flowSrcIp);
    writeBe32(bytes, 16, flowDstIp);

    const size_t l4 = ipHdrLen;
    writeBe16(bytes, l4, flowSrcPort);
    writeBe16(bytes, l4 + 2, flowDstPort);
    if (tcp) {
        writeBe32(bytes, l4 + 4, 0x01000000u + packetIndex);
        writeBe32(bytes, l4 + 8, 0x02000000u + packetIndex);
        bytes[l4 + 12] = 0x50;
        bytes[l4 + 13] = 0x18;
        writeBe16(bytes, l4 + 14, 0x4000);
        writeBe16(bytes, l4 + 16, 0);
        writeBe16(bytes, l4 + 18, 0);
    } else {
        writeBe16(bytes, l4 + 4, static_cast<uint16_t>(l4HdrLen + payloadBytes));
        writeBe16(bytes, l4 + 6, 0);
    }

    for (size_t i = 0; i < payloadBytes; ++i) {
        bytes[ipHdrLen + l4HdrLen + i] =
            static_cast<uint8_t>(0xa0u + packetIndex + i);
    }

    writeBe16(bytes, 10, internetChecksum(bytes.data(), ipHdrLen));
    if (tcp) {
        writeBe16(bytes, l4 + 16, l4Checksum(bytes, l4, l4HdrLen + payloadBytes,
                                             protocol));
    } else {
        writeBe16(bytes, l4 + 6, l4Checksum(bytes, l4, l4HdrLen + payloadBytes,
                                            protocol));
    }
    if (corruptIpv4Checksum) {
        writeBe16(bytes, 10, readBe16(bytes, 10) ^ 0xffffu);
    }
    if (corruptL4Checksum) {
        const size_t checksumOff = tcp ? (l4 + 16) : (l4 + 6);
        writeBe16(bytes, checksumOff, readBe16(bytes, checksumOff) ^ 0xffffu);
    }
    return bytes;
}

std::vector<axisData>
packetToAxisBeats(const std::vector<uint8_t>& packet, uint32_t dataWidth,
                  uint32_t idWidth, uint32_t destWidth, uint32_t tid,
                  uint32_t tdest, uint32_t tuser)
{
    fatal_if(dataWidth == 0 || dataWidth % 8 != 0,
             "AXIS data width must be a non-zero byte multiple");
    fatal_if(dataWidth > 512, "AXIS packet test nodes only support up to 512-bit data");

    const size_t bytesPerBeat = dataWidth / 8;
    std::vector<axisData> beats;
    for (size_t off = 0; off < packet.size(); off += bytesPerBeat) {
        const size_t n = std::min(bytesPerBeat, packet.size() - off);
        axisData beat(dataWidth, idWidth, destWidth);
        std::fill(beat.tdata.begin(), beat.tdata.end(), 0);
        std::copy(packet.begin() + off, packet.begin() + off + n,
                  beat.tdata.begin());
        beat.tkeep = prefixKeep(n);
        beat.tid = tid;
        beat.tdest = tdest;
        beat.tuser = tuser;
        beat.tlast = (off + n) >= packet.size();
        beat.tvalid = true;
        beats.push_back(beat);
    }
    return beats;
}

std::vector<axisData>
buildAxisPacketStream(Profile profile, uint32_t maxPackets, uint32_t flowCount,
                      uint32_t minPayloadBytes, uint32_t maxPayloadBytes,
                      uint32_t seed, uint32_t dataWidth, uint32_t idWidth,
                      uint32_t destWidth, uint32_t tid, uint32_t tdest,
                      uint32_t tuser, uint32_t srcIp, uint32_t dstIp,
                      uint16_t srcPort, uint16_t dstPort,
                      bool corruptIpv4Checksum, bool corruptL4Checksum,
                      uint32_t prefixBytes, uint32_t prefixValue)
{
    std::mt19937 rng(seed);
    if (maxPayloadBytes < minPayloadBytes) {
        std::swap(maxPayloadBytes, minPayloadBytes);
    }
    std::uniform_int_distribution<uint32_t> payloadDist(
        minPayloadBytes, maxPayloadBytes);

    std::vector<axisData> stream;
    for (uint32_t i = 0; i < maxPackets; ++i) {
        const uint32_t payloadBytes = payloadDist(rng);
        auto packet = buildIpv4Packet(profile, i, flowCount, payloadBytes,
                                      srcIp, dstIp, srcPort, dstPort,
                                      corruptIpv4Checksum,
                                      corruptL4Checksum);
        if (prefixBytes > 0) {
            std::vector<uint8_t> prefixed(prefixBytes, 0);
            for (uint32_t b = 0; b < prefixBytes; ++b) {
                prefixed[b] = static_cast<uint8_t>((prefixValue >> (8 * b)) & 0xff);
            }
            prefixed.insert(prefixed.end(), packet.begin(), packet.end());
            packet = std::move(prefixed);
        }
        auto beats = packetToAxisBeats(packet, dataWidth, idWidth, destWidth,
                                       tid, tdest, tuser);
        stream.insert(stream.end(), beats.begin(), beats.end());
    }
    return stream;
}

std::vector<axisData>
buildAxisPacketStream(Profile profile, uint32_t maxPackets, uint32_t flowCount,
                      const std::vector<uint32_t>& payloadSizes,
                      uint32_t dataWidth, uint32_t idWidth,
                      uint32_t destWidth, uint32_t tid, uint32_t tdest,
                      uint32_t tuser, uint32_t srcIp, uint32_t dstIp,
                      uint16_t srcPort, uint16_t dstPort,
                      bool corruptIpv4Checksum, bool corruptL4Checksum,
                      uint32_t prefixBytes, uint32_t prefixValue)
{
    fatal_if(payloadSizes.empty(),
             "Payload size list must contain at least one entry");

    std::vector<axisData> stream;
    for (uint32_t i = 0; i < maxPackets; ++i) {
        auto packet = buildIpv4Packet(profile, i, flowCount,
                                      payloadSizes[i % payloadSizes.size()],
                                      srcIp, dstIp, srcPort, dstPort,
                                      corruptIpv4Checksum,
                                      corruptL4Checksum);
        if (prefixBytes > 0) {
            std::vector<uint8_t> prefixed(prefixBytes, 0);
            for (uint32_t b = 0; b < prefixBytes; ++b) {
                prefixed[b] = static_cast<uint8_t>((prefixValue >> (8 * b)) & 0xff);
            }
            prefixed.insert(prefixed.end(), packet.begin(), packet.end());
            packet = std::move(prefixed);
        }
        auto beats = packetToAxisBeats(packet, dataWidth, idWidth, destWidth,
                                       tid, tdest, tuser);
        stream.insert(stream.end(), beats.begin(), beats.end());
    }
    return stream;
}

bool
validateIpv4Packet(const std::vector<uint8_t>& packet, std::string& reason,
                   bool validateIpv4Checksum, bool validateL4Checksum)
{
    if (packet.size() < 20) {
        reason = "packet shorter than IPv4 header";
        return false;
    }
    const uint8_t version = packet[0] >> 4;
    const uint8_t ihl = packet[0] & 0x0f;
    const size_t ipHdrLen = static_cast<size_t>(ihl) * 4;
    if (version != 4 || ihl < 5) {
        reason = "invalid IPv4 version/IHL";
        return false;
    }
    if (packet.size() < ipHdrLen) {
        reason = "packet shorter than IPv4 IHL";
        return false;
    }
    const uint16_t totalLen = readBe16(packet, 2);
    if (totalLen != packet.size()) {
        reason = "IPv4 total length does not match AXIS packet bytes";
        return false;
    }
    if (validateIpv4Checksum && internetChecksum(packet.data(), ipHdrLen) != 0) {
        reason = "invalid IPv4 header checksum";
        return false;
    }

    const uint8_t protocol = packet[9];
    const size_t l4Len = packet.size() - ipHdrLen;
    if (protocol == 17) {
        if (l4Len < 8) {
            reason = "UDP packet shorter than UDP header";
            return false;
        }
        if (readBe16(packet, ipHdrLen + 4) != l4Len) {
            reason = "UDP length does not match IPv4 payload length";
            return false;
        }
        const uint16_t udpChecksum = l4Checksum(packet, ipHdrLen, l4Len, protocol);
        if (validateL4Checksum && readBe16(packet, ipHdrLen + 6) != 0 &&
            udpChecksum != 0 && udpChecksum != 0xffff) {
            reason = "invalid UDP checksum";
            return false;
        }
        return true;
    }
    if (protocol == 6) {
        if (l4Len < 20) {
            reason = "TCP packet shorter than TCP header";
            return false;
        }
        const uint8_t doff = packet[ipHdrLen + 12] >> 4;
        if (doff < 5 || l4Len < static_cast<size_t>(doff) * 4) {
            reason = "invalid TCP data offset";
            return false;
        }
        const uint16_t tcpChecksum = l4Checksum(packet, ipHdrLen, l4Len, protocol);
        if (validateL4Checksum && tcpChecksum != 0 && tcpChecksum != 0xffff) {
            reason = "invalid TCP checksum";
            return false;
        }
        return true;
    }

    reason = "unsupported IPv4 protocol";
    return false;
}

} // namespace axis_packet
} // namespace noc
} // namespace gem5
