#include "noc/endpoints/sink/AxisPacketCheckerSink.hh"

#include "base/logging.hh"
#include "debug/NocPacketFlow.hh"
#include "noc/lib/AxisPacketUtils.hh"
#include "sim/cur_tick.hh"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <fstream>
#include <iomanip>
#include <iostream>

namespace gem5
{
namespace noc
{

namespace
{

AxisPacketCheckerSink::CheckMode
parseCheckMode(const std::string& mode)
{
    std::string m = mode;
    std::transform(m.begin(), m.end(), m.begin(),
        [](unsigned char c) { return std::tolower(c); });
    if (m == "ipv4") {
        return AxisPacketCheckerSink::CheckMode::Ipv4;
    }
    if (m == "nat_outbound") {
        return AxisPacketCheckerSink::CheckMode::NatOutbound;
    }
    return AxisPacketCheckerSink::CheckMode::Exact;
}

uint32_t
readBe32(const std::vector<uint8_t>& bytes, size_t off)
{
    return (static_cast<uint32_t>(bytes.at(off)) << 24) |
           (static_cast<uint32_t>(bytes.at(off + 1)) << 16) |
           (static_cast<uint32_t>(bytes.at(off + 2)) << 8) |
           static_cast<uint32_t>(bytes.at(off + 3));
}

uint16_t
readBe16(const std::vector<uint8_t>& bytes, size_t off)
{
    return static_cast<uint16_t>(
        (static_cast<uint16_t>(bytes.at(off)) << 8) | bytes.at(off + 1));
}

bool
keepIsPrefix(uint64_t keep, uint32_t dataWidthBits)
{
    const uint32_t bytes = dataWidthBits / 8;
    bool seenZero = false;
    for (uint32_t i = 0; i < bytes; ++i) {
        const bool bit = (keep & (1ULL << i)) != 0;
        if (!bit) {
            seenZero = true;
        } else if (seenZero) {
            return false;
        }
    }
    return true;
}

double
spanCycles(Tick firstTick, Tick lastTick, int clockMHz)
{
    if (clockMHz <= 0) {
        return 0.0;
    }
    const double periodTicks = 1000000.0 / static_cast<double>(clockMHz);
    return ((static_cast<double>(lastTick) - static_cast<double>(firstTick)) /
            periodTicks) + 1.0;
}

} // anonymous namespace

AxisPacketCheckerSink::AxisPacketCheckerSink(const Params& p)
    : NocNode(p),
      m_masterIn(p.data_width, p.tid_width, p.tdest_width),
      m_rng(0xaced1234u),
      m_dist100(0, 99),
      m_checkMode(parseCheckMode(p.check_mode)),
      m_dataWidthBits(p.data_width),
      m_expectedPackets(p.expected_packets),
      m_readyPercent(p.ready_percent),
      m_validateIpv4Checksum(p.validate_ipv4_checksum),
      m_validateL4Checksum(p.validate_l4_checksum),
      m_printSummary(p.print_summary),
      m_metricsOutputPath(p.metrics_output_path),
      m_validationSkipBytes(p.validation_skip_bytes),
      m_checkTdest(p.check_tdest),
      m_expectedTdest(p.tdest),
      m_natPublicIp(axis_packet::parseIpv4Address(p.nat_public_ip, 0x0a000001u)),
      m_natBasePort(p.nat_base_port),
      m_natPortCount(p.nat_port_count)
{
    maxPorts = 1;
    m_currentState.tready = true;
    m_nextState = m_currentState;

    if (m_checkMode == CheckMode::Exact) {
        const auto profile = axis_packet::parseProfile(p.profile);
        const auto payloadSizes = axis_packet::parsePayloadSizes(p.payload_sizes);
        const uint32_t srcIp =
            axis_packet::parseIpv4Address(p.src_ip, 0xc0a80164u);
        const uint32_t dstIp =
            axis_packet::parseIpv4Address(p.dst_ip, 0x08080808u);
        if (!payloadSizes.empty()) {
            m_expectedStream = axis_packet::buildAxisPacketStream(
                profile,
                p.expected_packets,
                std::max<uint32_t>(1, p.flow_count),
                payloadSizes,
                p.data_width,
                p.tid_width,
                p.tdest_width,
                p.tid,
                p.tdest,
                p.tuser,
                srcIp,
                dstIp,
                p.src_port,
                p.dst_port,
                false,
                false,
                p.prefix_bytes,
                p.prefix_value);
        } else {
            m_expectedStream = axis_packet::buildAxisPacketStream(
                profile,
                p.expected_packets,
                std::max<uint32_t>(1, p.flow_count),
                p.min_payload_bytes,
                p.max_payload_bytes,
                p.seed,
                p.data_width,
                p.tid_width,
                p.tdest_width,
                p.tid,
                p.tdest,
                p.tuser,
                srcIp,
                dstIp,
                p.src_port,
                p.dst_port,
                false,
                false,
                p.prefix_bytes,
                p.prefix_value);
        }
    }
}

AxisPacketCheckerSink::~AxisPacketCheckerSink()
{
    printSummary();
}

bool
AxisPacketCheckerSink::tick(int clockDomain)
{
    if (!clockDomains.empty() && clockDomain != clockDomains[0]) {
        return false;
    }
    if (m_currentState.tready && m_masterIn.data.tvalid) {
        acceptBeat(m_masterIn.data);
    }
    m_currentState = m_nextState;
    return true;
}

bool
AxisPacketCheckerSink::done()
{
    const bool expectedDone = m_expectedPackets == 0 ||
        m_packetsReceived >= m_expectedPackets;
    if (expectedDone) {
        printSummary();
    }
    return expectedDone;
}

void
AxisPacketCheckerSink::update(int portID, State* inputNocInterfaceState)
{
    if (portID != 0) {
        panic("AxisPacketCheckerSink::update invalid portID %d", portID);
    }
    auto* axisMaster = dynamic_cast<axisMasterState*>(inputNocInterfaceState);
    if (!axisMaster) {
        panic("AxisPacketCheckerSink::update expected axisMasterState");
    }
    m_masterIn = *axisMaster;
    m_nextState.tready = m_dist100(m_rng) < static_cast<int>(m_readyPercent);
}

State*
AxisPacketCheckerSink::getCurrentState(int portID)
{
    if (portID != 0) {
        panic("AxisPacketCheckerSink::getCurrentState invalid portID %d", portID);
    }
    return &m_currentState;
}

int
AxisPacketCheckerSink::assignPort(const std::string &endpointName)
{
    if (!portEndpointNames.empty() &&
        endpointName == portEndpointNames[0] && !m_portAssigned) {
        m_portAssigned = true;
        return 0;
    }
    panic("AxisPacketCheckerSink::assignPort invalid endpointName: %s",
          endpointName.c_str());
    return -1;
}

void
AxisPacketCheckerSink::acceptBeat(const axisData& beat)
{
    DPRINTF(NocPacketFlow,
            "AxisPacketCheckerSink accept beat idx=%zu pkt=%u tdest=%u tid=%u "
            "tkeep=%#llx tlast=%d bytes=%u\n",
            m_expectedBeat, m_packetsReceived, beat.tdest, beat.tid,
            static_cast<unsigned long long>(beat.tkeep),
            beat.tlast, beat.getTotalByteSize());
    fatal_if(!keepIsPrefix(beat.tkeep, m_dataWidthBits),
             "AxisPacketCheckerSink: non-prefix TKEEP 0x%llx",
             static_cast<unsigned long long>(beat.tkeep));

    if (m_checkMode == CheckMode::Exact) {
        checkExactBeat(beat);
    } else if (m_checkTdest) {
        fatal_if(beat.tdest != m_expectedTdest,
                 "AxisPacketCheckerSink: TDEST mismatch got=%u expected=%u",
                 beat.tdest, m_expectedTdest);
    }

    const uint32_t validBytes = beat.getTotalByteSize();
    if (!m_sawBeat) {
        m_firstBeatTick = curTick();
        m_sawBeat = true;
    }
    m_lastBeatTick = curTick();
    for (uint32_t i = 0; i < validBytes; ++i) {
        fatal_if(i >= beat.tdata.size(),
                 "AxisPacketCheckerSink: beat reports more bytes than TDATA holds");
        m_packetBytes.push_back(beat.tdata[i]);
    }

    ++m_beatsReceived;
    m_bytesReceived += validBytes;

    if (beat.tlast) {
        checkPacket();
        ++m_packetsReceived;
        DPRINTF(NocPacketFlow,
                "AxisPacketCheckerSink completed packet count=%u size=%zu\n",
                m_packetsReceived, m_packetBytes.size());
        m_packetBytes.clear();
    }

}

void
AxisPacketCheckerSink::checkExactBeat(const axisData& beat)
{
    fatal_if(m_expectedBeat >= m_expectedStream.size(),
             "AxisPacketCheckerSink: received more beats than expected");
    const auto& expected = m_expectedStream[m_expectedBeat];
    fatal_if(beat.tkeep != expected.tkeep,
             "AxisPacketCheckerSink: beat %zu TKEEP mismatch got=0x%llx expected=0x%llx",
             m_expectedBeat,
             static_cast<unsigned long long>(beat.tkeep),
             static_cast<unsigned long long>(expected.tkeep));
    fatal_if(beat.tlast != expected.tlast,
             "AxisPacketCheckerSink: beat %zu TLAST mismatch", m_expectedBeat);
    fatal_if(beat.tid != expected.tid || beat.tdest != expected.tdest ||
             beat.tuser != expected.tuser,
             "AxisPacketCheckerSink: beat %zu sideband mismatch", m_expectedBeat);

    const uint32_t validBytes = expected.getTotalByteSize();
    for (uint32_t i = 0; i < validBytes; ++i) {
        fatal_if(beat.tdata[i] != expected.tdata[i],
                 "AxisPacketCheckerSink: beat %zu byte %u mismatch got=0x%02x expected=0x%02x",
                 m_expectedBeat, i, beat.tdata[i], expected.tdata[i]);
    }
    ++m_expectedBeat;
}

void
AxisPacketCheckerSink::checkPacket()
{
    std::string reason;
    fatal_if(m_validationSkipBytes > m_packetBytes.size(),
             "AxisPacketCheckerSink: validation skip %u exceeds packet size %zu",
             m_validationSkipBytes, m_packetBytes.size());

    const std::vector<uint8_t> validationBytes(
        m_packetBytes.begin() + static_cast<std::ptrdiff_t>(m_validationSkipBytes),
        m_packetBytes.end());

    fatal_if(!axis_packet::validateIpv4Packet(validationBytes, reason,
                                              m_validateIpv4Checksum,
                                              m_validateL4Checksum),
             "AxisPacketCheckerSink: invalid IPv4 packet %u: %s",
             m_packetsReceived, reason.c_str());

    if (m_checkMode == CheckMode::NatOutbound) {
        checkNatOutboundPacket();
    }
}

void
AxisPacketCheckerSink::checkNatOutboundPacket()
{
    fatal_if(m_packetBytes.size() < 24,
             "AxisPacketCheckerSink: NAT output packet too short");
    const uint32_t srcIp = readBe32(m_packetBytes, 12);
    const uint16_t srcPort = readBe16(m_packetBytes, 20);
    fatal_if(srcIp != m_natPublicIp,
             "AxisPacketCheckerSink: NAT src IP mismatch got=%s expected=%s",
             axis_packet::ipv4ToString(srcIp).c_str(),
             axis_packet::ipv4ToString(m_natPublicIp).c_str());
    fatal_if(srcPort < m_natBasePort ||
             srcPort >= static_cast<uint16_t>(m_natBasePort + m_natPortCount),
             "AxisPacketCheckerSink: NAT src port %u outside expected range [%u,%u)",
             srcPort, m_natBasePort, m_natBasePort + m_natPortCount);
}

void
AxisPacketCheckerSink::printSummary()
{
    if (!m_printSummary || m_reportedSummary) {
        return;
    }
    m_reportedSummary = true;
    std::cout << "[AxisPacketCheckerSink] packets=" << m_packetsReceived
              << " beats=" << m_beatsReceived
              << " bytes=" << m_bytesReceived
              << " expected_packets=" << m_expectedPackets << "\n";
    if (m_sawBeat) {
        const int clockMHz = getPortClockDomain(0);
        const double cycles = spanCycles(m_firstBeatTick, m_lastBeatTick,
                                         clockMHz);
        const double bytesPerCycle = cycles > 0.0 ?
            static_cast<double>(m_bytesReceived) / cycles : 0.0;
        const double gbps = bytesPerCycle * 8.0 *
            static_cast<double>(clockMHz) / 1000.0;
        std::cout << "[AxisPacketCheckerSink] axis_input_window"
                  << " first_tick=" << m_firstBeatTick
                  << " last_tick=" << m_lastBeatTick
                  << " span_cycles=" << std::fixed << std::setprecision(2)
                  << cycles
                  << " bytes_per_cycle=" << std::setprecision(3)
                  << bytesPerCycle
                  << " gbps=" << std::setprecision(3) << gbps
                  << std::defaultfloat << "\n";
    }
    emitMetricsFragment();
}

void
AxisPacketCheckerSink::emitMetricsFragment() const
{
    if (m_metricsOutputPath.empty()) {
        return;
    }
    std::ofstream out(m_metricsOutputPath, std::ios::trunc);
    if (!out.is_open()) {
        warn("AxisPacketCheckerSink could not open metrics fragment %s",
             m_metricsOutputPath.c_str());
        return;
    }
    out << "{\n";
    out << "  \"type\": \"axis_packet_checker\",\n";
    out << "  \"expected_packets\": " << m_expectedPackets << ",\n";
    out << "  \"packets_received\": " << m_packetsReceived << ",\n";
    out << "  \"beats_received\": " << m_beatsReceived << ",\n";
    out << "  \"bytes_received\": " << m_bytesReceived << ",\n";
    out << "  \"first_beat_tick\": " << m_firstBeatTick << ",\n";
    out << "  \"last_beat_tick\": " << m_lastBeatTick << ",\n";
    out << "  \"saw_beat\": " << (m_sawBeat ? "true" : "false") << ",\n";
    out << "  \"done\": "
        << ((m_expectedPackets == 0 || m_packetsReceived >= m_expectedPackets)
                ? "true" : "false")
        << "\n";
    out << "}\n";
}

} // namespace noc
} // namespace gem5
