#include "noc/endpoints/memory/ddr/DdrPacketDmaNode.hh"

#include "base/logging.hh"
#include "debug/NocPacketFlow.hh"
#include "debug/NocTiming.hh"
#include "noc/lib/AxisPacketUtils.hh"
#include "sim/cur_tick.hh"

#include <algorithm>
#include <fstream>
#include <array>
#include <iomanip>
#include <iostream>
#include <random>

namespace gem5
{
namespace noc
{

namespace
{

void
writeLe16(std::vector<uint8_t>& bytes, size_t off, uint16_t value)
{
    bytes.at(off) = static_cast<uint8_t>(value & 0xff);
    bytes.at(off + 1) = static_cast<uint8_t>((value >> 8) & 0xff);
}

void
writeLe32(std::vector<uint8_t>& bytes, size_t off, uint32_t value)
{
    for (size_t i = 0; i < 4; ++i) {
        bytes.at(off + i) = static_cast<uint8_t>((value >> (8 * i)) & 0xff);
    }
}

void
writeLe32(std::array<uint8_t, 64>& bytes, size_t off, uint32_t value)
{
    for (size_t i = 0; i < 4; ++i) {
        bytes.at(off + i) = static_cast<uint8_t>((value >> (8 * i)) & 0xff);
    }
}

void
writeLe64(std::vector<uint8_t>& bytes, size_t off, uint64_t value)
{
    for (size_t i = 0; i < 8; ++i) {
        bytes.at(off + i) = static_cast<uint8_t>((value >> (8 * i)) & 0xff);
    }
}

uint16_t
readLe16(const std::vector<uint8_t>& bytes, size_t off)
{
    return static_cast<uint16_t>(bytes.at(off)) |
           (static_cast<uint16_t>(bytes.at(off + 1)) << 8);
}

uint32_t
readLe32(const std::vector<uint8_t>& bytes, size_t off)
{
    uint32_t value = 0;
    for (size_t i = 0; i < 4; ++i) {
        value |= static_cast<uint32_t>(bytes.at(off + i)) << (8 * i);
    }
    return value;
}

uint32_t
readLe32(const std::array<uint8_t, 64>& bytes, size_t off)
{
    uint32_t value = 0;
    for (size_t i = 0; i < 4; ++i) {
        value |= static_cast<uint32_t>(bytes.at(off + i)) << (8 * i);
    }
    return value;
}

uint64_t
readLe64(const std::vector<uint8_t>& bytes, size_t off)
{
    uint64_t value = 0;
    for (size_t i = 0; i < 8; ++i) {
        value |= static_cast<uint64_t>(bytes.at(off + i)) << (8 * i);
    }
    return value;
}

uint64_t
prefixStrobe(size_t bytes)
{
    if (bytes >= 64) {
        return 0xffffffffffffffffULL;
    }
    return bytes == 0 ? 0 : ((1ULL << bytes) - 1ULL);
}

uint32_t
firstActiveLane(const aximmRWData& w)
{
    for (uint32_t lane = 0; lane < 64; lane += 4) {
        if (((w.wstrb >> lane) & 0xf) != 0) {
            return lane;
        }
    }
    return 0;
}

uint32_t
activeWordLanes(const aximmRWData& w)
{
    uint32_t count = 0;
    for (uint32_t lane = 0; lane < 64; lane += 4) {
        if (((w.wstrb >> lane) & 0xf) != 0) {
            ++count;
        }
    }
    return count;
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

uint32_t
ceilDiv(uint32_t value, uint32_t divisor)
{
    return (value + divisor - 1) / divisor;
}

void
prependPrefix(std::vector<uint8_t>& packet, uint32_t prefixBytes,
              uint32_t prefixValue)
{
    if (prefixBytes == 0) {
        return;
    }
    std::vector<uint8_t> prefixed;
    prefixed.reserve(prefixBytes + packet.size());
    for (uint32_t i = 0; i < prefixBytes; ++i) {
        prefixed.push_back(static_cast<uint8_t>((prefixValue >> (8 * i)) & 0xff));
    }
    prefixed.insert(prefixed.end(), packet.begin(), packet.end());
    packet = std::move(prefixed);
}

} // anonymous namespace

DdrPacketDmaNode::DdrPacketDmaNode(const Params& p)
    : NocNode(p),
      m_axisOut(p.data_width, p.tid_width, p.tdest_width),
      m_descriptorBase(p.descriptor_base),
      m_packetBase(p.packet_base),
      m_controlBase(p.control_base),
      m_packetStride(p.packet_stride),
      m_packetCount(p.packet_count),
      m_maxReadBurstBeats(p.max_read_burst_beats),
      m_maxOutstandingReads(p.max_outstanding_reads),
      m_descriptorPrefetchDepth(p.descriptor_prefetch_depth),
      m_packetPrefetchDepth(p.packet_prefetch_depth),
      m_startDelayCycles(p.start_delay_cycles),
      m_postPreloadReadDelayCycles(p.post_preload_read_delay_cycles),
      m_packetGapCycles(p.packet_gap_cycles),
      m_descriptorFlags(p.descriptor_flags),
      m_dataWidth(p.data_width),
      m_tidWidth(p.tid_width),
      m_tdestWidth(p.tdest_width),
      m_tuserWidth(p.tuser_width),
      m_axiId(p.axi_id),
      m_tid(p.tid),
      m_tdest(p.tdest),
      m_tuser(p.tuser),
      m_preloadDdr(p.preload_ddr),
      m_preloadDescriptors(p.preload_descriptors),
      m_preloadPackets(p.preload_packets),
      m_functionalPreloadPackets(p.functional_preload_packets),
      m_waitForControlStart(p.wait_for_control_start),
      m_printSummary(p.print_summary),
      m_stopOnEoc(p.stop_on_eoc),
      m_metricsOutputPath(p.metrics_output_path)
{
    maxPorts = 3;
    m_portAssigned.resize(maxPorts, false);
    m_aximmOut.rReady = true;
    m_aximmOut.bReady = true;
    m_axisOut.data.tvalid = false;
    m_axisIn.tready = true;
    m_ctrlOut.awReady = true;
    m_ctrlOut.wReady = true;
    m_ctrlOut.arReady = true;
    m_ctrlOut.r.valid = false;
    m_ctrlOut.b.valid = false;
    m_startDelayRemaining = m_startDelayCycles;
    m_postPreloadReadDelayRemaining = m_postPreloadReadDelayCycles;
    m_started = !m_waitForControlStart;

    fatal_if(m_dataWidth != 512,
             "DdrPacketDmaNode currently expects 512-bit AXIS data width");
    fatal_if(m_axiId >= 4,
             "DdrPacketDmaNode AXI ID %u exceeds mmNocSlaveUnit support",
             m_axiId);
    fatal_if(m_packetStride < 64,
             "DdrPacketDmaNode packet_stride must be at least 64 bytes");
    fatal_if(m_maxReadBurstBeats == 0 || m_maxReadBurstBeats > 256,
             "DdrPacketDmaNode max_read_burst_beats must be in [1, 256]");
    fatal_if(m_maxOutstandingReads == 0 || m_maxOutstandingReads > 256,
             "DdrPacketDmaNode max_outstanding_reads must be in [1, 256]");
    fatal_if(m_descriptorPrefetchDepth == 0,
             "DdrPacketDmaNode descriptor_prefetch_depth must be non-zero");
    fatal_if(m_packetPrefetchDepth == 0,
             "DdrPacketDmaNode packet_prefetch_depth must be non-zero");

    if (p.preload_memory) {
        m_preloadMemory =
            dynamic_cast<FunctionalMemoryEndpoint*>(p.preload_memory);
        fatal_if(!m_preloadMemory,
                 "DdrPacketDmaNode preload_memory must implement "
                 "FunctionalMemoryEndpoint");
    }
    fatal_if(m_functionalPreloadPackets && !m_preloadMemory,
             "DdrPacketDmaNode functional_preload_packets requires "
             "preload_memory");

    buildExpectedPackets(p);
    m_packetStates.resize(m_expectedDescriptors.size());
    if (m_preloadDdr) {
        buildPreloadWrites();
    }
}

bool
DdrPacketDmaNode::tick(int clockDomain)
{
    if (!clockDomains.empty() &&
        std::find(clockDomains.begin(), clockDomains.end(), clockDomain) ==
            clockDomains.end()) {
        return false;
    }

    if (m_started && m_functionalPreloadPackets &&
        !m_functionalPacketsPreloaded) {
        performFunctionalPacketPreload();
    }

    consumeHandshakes();
    consumeControlPort();
    if (m_startDelayRemaining > 0) {
        --m_startDelayRemaining;
        clearAxiRequestOutputs();
        driveControlPort();
        m_aximmOut.rReady = true;
        m_aximmOut.bReady = true;
        m_axisOut.data.tvalid = false;
        return true;
    }
    if (m_packetGapRemaining > 0) {
        --m_packetGapRemaining;
        clearAxiRequestOutputs();
        driveControlPort();
        m_aximmOut.rReady = true;
        m_aximmOut.bReady = true;
        m_axisOut.data.tvalid = false;
        return true;
    }
    driveNextOutputs();
    driveControlPort();
    return true;
}

bool
DdrPacketDmaNode::done()
{
    const bool finished = dmaTransferFinished() &&
        !m_axisOut.data.tvalid && !m_hasActiveOp && !m_hasPendingReadOp &&
        m_inflightReads.empty() && m_axisBeats.empty();
    if (finished) {
        printSummary();
    }
    return finished;
}

void
DdrPacketDmaNode::update(int portID, State* inputNocInterfaceState)
{
    if (portID == 0) {
        auto* s = dynamic_cast<aximmSlaveState*>(inputNocInterfaceState);
        fatal_if(!s, "DdrPacketDmaNode port 0 expected aximmSlaveState");
        m_aximmIn = *s;
        return;
    }
    if (portID == 1) {
        auto* s = dynamic_cast<axisSlaveState*>(inputNocInterfaceState);
        fatal_if(!s, "DdrPacketDmaNode port 1 expected axisSlaveState");
        m_axisIn = *s;
        return;
    }
    if (portID == 2) {
        auto* s = dynamic_cast<aximmMasterState*>(inputNocInterfaceState);
        fatal_if(!s, "DdrPacketDmaNode port 2 expected aximmMasterState");
        m_ctrlIn = *s;
        return;
    }
    panic("DdrPacketDmaNode::update invalid portID %d", portID);
}

State*
DdrPacketDmaNode::getCurrentState(int portID)
{
    if (portID == 0) {
        return &m_aximmOut;
    }
    if (portID == 1) {
        return &m_axisOut;
    }
    if (portID == 2) {
        return &m_ctrlOut;
    }
    panic("DdrPacketDmaNode::getCurrentState invalid portID %d", portID);
    return nullptr;
}

int
DdrPacketDmaNode::assignPort(const std::string& endpointName)
{
    for (int i = 0; i < maxPorts; ++i) {
        if (static_cast<size_t>(i) < portEndpointNames.size() &&
            endpointName == portEndpointNames[i] && !m_portAssigned[i]) {
            m_portAssigned[i] = true;
            return i;
        }
    }
    panic("DdrPacketDmaNode::assignPort invalid endpointName: %s",
          endpointName.c_str());
    return -1;
}

void
DdrPacketDmaNode::buildExpectedPackets(const Params& p)
{
    const auto profile = axis_packet::parseProfile(p.profile);
    const auto payloadSizes = axis_packet::parsePayloadSizes(p.payload_sizes);
    const uint32_t srcIp =
        axis_packet::parseIpv4Address(p.src_ip, 0xc0a80164u);
    const uint32_t dstIp =
        axis_packet::parseIpv4Address(p.dst_ip, 0x08080808u);
    uint32_t minPayload = p.min_payload_bytes;
    uint32_t maxPayload = p.max_payload_bytes;
    if (maxPayload < minPayload) {
        std::swap(maxPayload, minPayload);
    }

    std::mt19937 rng(p.seed);
    std::uniform_int_distribution<uint32_t> payloadDist(minPayload, maxPayload);
    m_expectedPackets.reserve(m_packetCount);
    m_expectedDescriptors.reserve(m_packetCount);

    for (uint32_t i = 0; i < m_packetCount; ++i) {
        const uint32_t payloadBytes = payloadSizes.empty() ?
            payloadDist(rng) : payloadSizes[i % payloadSizes.size()];
        auto packet = axis_packet::buildIpv4Packet(
            profile, i, std::max<uint32_t>(1, p.flow_count), payloadBytes,
            srcIp, dstIp, p.src_port, p.dst_port,
            p.corrupt_ipv4_checksum, p.corrupt_l4_checksum);
        prependPrefix(packet, p.prefix_bytes, p.prefix_value);
        fatal_if(packet.size() > m_packetStride,
                 "DdrPacketDmaNode packet %u is %zu bytes but stride is %u",
                 i, packet.size(), m_packetStride);

        Descriptor desc;
        desc.packetAddr = m_packetBase + static_cast<uint64_t>(i) * m_packetStride;
        desc.packetLen = packet.size();
        desc.tdest = static_cast<uint16_t>(m_tdest);
        desc.tid = static_cast<uint16_t>(m_tid);
        desc.tuser = static_cast<uint16_t>(m_tuser);
        desc.flags = m_descriptorFlags;
        if (m_stopOnEoc && i == m_packetCount - 1) {
            desc.flags |= DescFlagEndOfChain;
        }
        m_expectedDescriptors.push_back(desc);
        m_expectedPackets.push_back(std::move(packet));
    }
}

void
DdrPacketDmaNode::buildPreloadWrites()
{
    for (uint32_t i = 0; i < m_packetCount; ++i) {
        if (m_preloadDescriptors) {
            enqueueWrite(m_descriptorBase + static_cast<uint64_t>(i) * DescriptorStride,
                         serializeDescriptor(m_expectedDescriptors[i]));
        }
        if (m_preloadPackets) {
            if (!m_functionalPreloadPackets) {
                enqueueWrite(m_expectedDescriptors[i].packetAddr,
                             m_expectedPackets[i]);
            }
        }
    }
}

void
DdrPacketDmaNode::performFunctionalPacketPreload()
{
    if (m_functionalPacketsPreloaded || !m_preloadPackets) {
        m_functionalPacketsPreloaded = true;
        return;
    }

    const uint32_t count =
        std::min<uint32_t>(m_packetCount, m_expectedPackets.size());
    for (uint32_t i = 0; i < count; ++i) {
        functionalPreloadWrite(m_expectedDescriptors[i].packetAddr,
                               m_expectedPackets[i]);
    }
    m_functionalPacketsPreloaded = true;
}

void
DdrPacketDmaNode::functionalPreloadWrite(
    uint64_t addr, const std::vector<uint8_t>& bytes)
{
    fatal_if(!m_preloadMemory,
             "DdrPacketDmaNode functional packet preload has no memory");
    m_preloadMemory->functionalWrite(addr, bytes.data(), bytes.size());
}

std::vector<uint8_t>
DdrPacketDmaNode::serializeDescriptor(const Descriptor& desc) const
{
    std::vector<uint8_t> bytes(DescriptorBytes, 0);
    writeLe64(bytes, 0, desc.packetAddr);
    writeLe32(bytes, 8, desc.packetLen);
    writeLe16(bytes, 12, desc.tdest);
    writeLe16(bytes, 14, desc.tid);
    writeLe16(bytes, 16, desc.tuser);
    writeLe16(bytes, 18, desc.flags);
    return bytes;
}

DdrPacketDmaNode::Descriptor
DdrPacketDmaNode::parseDescriptor(const std::vector<uint8_t>& bytes) const
{
    fatal_if(bytes.size() < DescriptorBytes,
             "DdrPacketDmaNode descriptor read returned too few bytes");
    Descriptor desc;
    desc.packetAddr = readLe64(bytes, 0);
    desc.packetLen = readLe32(bytes, 8);
    desc.tdest = readLe16(bytes, 12);
    desc.tid = readLe16(bytes, 14);
    desc.tuser = readLe16(bytes, 16);
    desc.flags = readLe16(bytes, 18);
    if ((desc.flags & DescFlagValid) == 0) {
        fatal("DdrPacketDmaNode descriptor missing VALID flag");
    }
    fatal_if(desc.packetLen == 0,
             "DdrPacketDmaNode descriptor packet length is zero");
    fatal_if(desc.packetLen > m_packetStride,
             "DdrPacketDmaNode descriptor packet length %u exceeds stride %u",
             desc.packetLen, m_packetStride);
    return desc;
}

void
DdrPacketDmaNode::enqueueWrite(uint64_t addr, const std::vector<uint8_t>& bytes)
{
    for (size_t off = 0; off < bytes.size(); off += BeatBytes) {
        const size_t n = std::min<size_t>(BeatBytes, bytes.size() - off);
        AxiOp op;
        op.kind = AxiKind::Write;
        op.addr = addr + off;
        op.validBytes = n;
        op.bytes.resize(n);
        std::copy(bytes.begin() + off, bytes.begin() + off + n,
                  op.bytes.begin());
        m_preloadWrites.push_back(std::move(op));
    }
}

void
DdrPacketDmaNode::consumeHandshakes()
{
    const bool awFire = m_aximmOut.aw.valid && m_aximmIn.awReady;
    const bool wFire = m_aximmOut.w.valid && m_aximmIn.wReady;
    const bool arFire = m_aximmOut.ar.valid && m_aximmIn.arReady;
    const bool bFire = m_aximmOut.bReady && m_aximmIn.b.valid;
    const bool rFire = m_aximmOut.rReady && m_aximmIn.r.valid;
    const bool axisFire = m_axisOut.data.tvalid && m_axisIn.tready;

    if (m_started && !dmaTransferFinished()) {
        ++m_inflightSampleCycles;
        m_inflightReadOccupancySum += m_inflightReads.size();
        if (m_hasPendingReadOp) {
            ++m_pendingReadValidCycles;
        }
        if (m_aximmOut.ar.valid) {
            ++m_arValidCycles;
            if (m_aximmIn.arReady) {
                ++m_arReadyValidCycles;
            } else {
                ++m_arValidNotReadyCycles;
            }
        }
        if (m_aximmIn.r.valid) {
            ++m_rValidCycles;
            if (m_aximmOut.rReady) {
                ++m_rReadyValidCycles;
            } else {
                ++m_rValidNotReadyCycles;
            }
        } else if (!m_inflightReads.empty()) {
            ++m_rIdleInflightCycles;
        }
        if (m_axisOut.data.tvalid) {
            ++m_axisValidCycles;
            if (m_axisIn.tready) {
                ++m_axisReadyValidCycles;
            } else {
                ++m_axisValidNotReadyCycles;
            }
        }
    }

    if (m_hasActiveOp && m_activeOp.kind == AxiKind::Write) {
        m_awAccepted = m_awAccepted || awFire;
        m_wAccepted = m_wAccepted || wFire;
        if (bFire) {
            fatal_if(m_aximmIn.b.resp != AximmResp::OKAY,
                     "DdrPacketDmaNode preload write got AXI response error");
            m_hasActiveOp = false;
            m_awAccepted = false;
            m_wAccepted = false;
        }
    }

    if (m_hasPendingReadOp && arFire) {
        m_pendingReadOp.issueTick = curTick();
        m_inflightReads.push_back(m_pendingReadOp);
        ++m_readsIssued;
        if (m_pendingReadOp.kind == AxiKind::ReadDescriptor) {
            ++m_descriptorReadTransactionsIssued;
            m_descriptorReadRequestBytesIssued += m_pendingReadOp.validBytes;
        } else if (m_pendingReadOp.kind == AxiKind::ReadPacket) {
            ++m_packetReadTransactionsIssued;
            m_packetReadRequestBytesIssued += m_pendingReadOp.validBytes;
        }
        m_maxInflightReadsObserved =
            std::max<uint64_t>(m_maxInflightReadsObserved,
                               m_inflightReads.size());
        if (!m_sawFirstDdrReadRequest) {
            m_firstDdrReadRequestTick = curTick();
            m_sawFirstDdrReadRequest = true;
        }
        m_hasPendingReadOp = false;
    }

    if (rFire) {
        fatal_if(m_inflightReads.empty(),
                 "DdrPacketDmaNode got AXI read data with no in-flight read");
        AxiOp& op = m_inflightReads.front();
        fatal_if(m_aximmIn.r.resp != AximmResp::OKAY,
                 "DdrPacketDmaNode read got AXI response error");
        fatal_if(op.packetIndex >= m_packetStates.size(),
                 "DdrPacketDmaNode read returned for invalid packet %u",
                 op.packetIndex);
        fatal_if(op.kind == AxiKind::ReadDescriptor &&
                 op.packetIndex + op.descriptorCount > m_packetStates.size(),
                 "DdrPacketDmaNode descriptor read returned for invalid range %u..%u",
                 op.packetIndex, op.packetIndex + op.descriptorCount);
        PacketState& pkt = m_packetStates[op.packetIndex];
        std::vector<uint8_t>& dst =
            op.kind == AxiKind::ReadDescriptor
                ? op.bytes
                : pkt.packetReadBuffer;
        fatal_if(op.bytesTransferred >= op.validBytes,
                 "DdrPacketDmaNode received more read bytes than requested");
        const uint32_t remaining = op.validBytes - op.bytesTransferred;
        const uint32_t n = std::min<uint32_t>(remaining,
                                              m_aximmIn.r.data.size());
        dst.insert(dst.end(), m_aximmIn.r.data.begin(),
                   m_aximmIn.r.data.begin() + n);
        op.bytesTransferred += n;
        if (op.kind != AxiKind::ReadDescriptor) {
            m_totalDdrBytesRead += n;
        }
        if (m_aximmIn.r.last) {
            m_lastDdrReadCompletionTick = curTick();
            m_readLatencyTicks.push_back(
                static_cast<uint64_t>(curTick() - op.issueTick));
            fatal_if(op.bytesTransferred != op.validBytes,
                     "DdrPacketDmaNode read burst ended after %u bytes, expected %u",
                     op.bytesTransferred, op.validBytes);
            completeReadOp(op);
            m_inflightReads.pop_front();
        }
    }

    if (axisFire) {
        DPRINTF(NocPacketFlow,
                "DdrPacketDmaNode axis beat fire pkt=%u beat=%u tdest=%u tid=%u "
                "tkeep=%#llx tlast=%d bytes=%u\n",
                m_packetIndex, m_axisBeatIndex, m_axisOut.data.tdest,
                m_axisOut.data.tid,
                static_cast<unsigned long long>(m_axisOut.data.tkeep),
                m_axisOut.data.tlast,
                m_axisOut.data.getTotalByteSize());
        if (!m_sawAxisBeat) {
            m_firstAxisTick = curTick();
            m_sawAxisBeat = true;
        }
        m_lastAxisTick = curTick();
        ++m_beatsEmitted;
        m_bytesEmitted += m_axisOut.data.getTotalByteSize();
        ++m_axisBeatIndex;
        if (m_axisBeatIndex >= m_axisBeats.size()) {
            ++m_packetIndex;
            ++m_packetsCompleted;
            if (dmaTransferFinished()) {
                m_doneStatus = true;
                m_dmaDoneTick = curTick();
            }
            m_axisBeatIndex = 0;
            m_axisBeats.clear();
            if (m_packetIndex > 0 && m_packetIndex - 1 < m_packetStates.size()) {
                PacketState& pkt = m_packetStates[m_packetIndex - 1];
                pkt.descReadBuffer.clear();
                pkt.packetReadBuffer.clear();
            }
            m_packetGapRemaining = m_packetGapCycles;
        }
    }
}

void
DdrPacketDmaNode::driveNextOutputs()
{
    clearAxiRequestOutputs();
    m_aximmOut.rReady = true;
    m_aximmOut.bReady = true;

    if (m_hasActiveOp || !m_preloadWrites.empty()) {
        if (!m_hasActiveOp) {
            startNextAxiOp();
        }
        if (m_hasActiveOp) {
            driveWriteOp(m_activeOp);
        }
        return;
    }

    if (m_postPreloadReadDelayArmed) {
        if (m_postPreloadReadDelayRemaining > 0) {
            --m_postPreloadReadDelayRemaining;
            return;
        }
        m_postPreloadReadDelayArmed = false;
    }

    const bool axisBlocked = m_axisOut.data.tvalid && !m_axisIn.tready;
    if (!axisBlocked) {
        m_axisOut.data.tvalid = false;

        if (m_axisBeatIndex < m_axisBeats.size()) {
            m_axisOut.data = m_axisBeats[m_axisBeatIndex];
        } else if (packetComplete()) {
            preparePacketAxisBeats();
            if (!m_axisBeats.empty()) {
                m_axisOut.data = m_axisBeats[0];
            }
        } else if (m_started && m_packetIndex < m_packetCount) {
            ++m_axisWaitPacketCycles;
        }
    }

    if (!m_hasPendingReadOp) {
        if (readCreditAvailable()) {
            AxiOp op;
            if (buildNextReadOp(op)) {
                m_pendingReadOp = std::move(op);
                m_hasPendingReadOp = true;
            }
        } else if (hasSchedulableReadCandidate()) {
            ++m_readIssueStallInflightFullCycles;
        }
    }

    if (m_hasPendingReadOp) {
        driveReadOp(m_pendingReadOp);
    }
}

bool
DdrPacketDmaNode::readCreditAvailable() const
{
    const uint32_t pending = m_hasPendingReadOp ? 1 : 0;
    return (m_inflightReads.size() + pending) < m_maxOutstandingReads;
}

bool
DdrPacketDmaNode::hasSchedulableReadCandidate() const
{
    if (!m_started || m_packetIndex >= m_packetCount) {
        return false;
    }
    const uint32_t packetEnd =
        std::min<uint32_t>(m_packetCount,
                           m_packetIndex + m_packetPrefetchDepth);
    for (uint32_t i = m_packetIndex; i < packetEnd; ++i) {
        const PacketState& pkt = m_packetStates[i];
        if (pkt.descriptorDone &&
            pkt.packetReadIssuedBytes < pkt.desc.packetLen) {
            return true;
        }
    }

    if (m_nextDescriptorIndex >= m_packetCount) {
        return false;
    }

    const uint32_t descriptorWindowEnd =
        std::min<uint32_t>(m_packetCount,
                           m_packetIndex + m_descriptorPrefetchDepth);
    if (m_nextDescriptorIndex >= descriptorWindowEnd) {
        return false;
    }

    const uint32_t availableDescriptors =
        descriptorWindowEnd - m_nextDescriptorIndex;
    const bool descriptorBatchReady =
        availableDescriptors >= m_maxReadBurstBeats;
    const bool descriptorNeededSoon = m_nextDescriptorIndex < packetEnd;
    const bool descriptorAtEnd = descriptorWindowEnd == m_packetCount;
    return descriptorBatchReady || descriptorNeededSoon || descriptorAtEnd;
}

bool
DdrPacketDmaNode::buildNextReadOp(AxiOp& op)
{
    if (!m_started || m_packetIndex >= m_packetCount) {
        return false;
    }

    const uint32_t packetEnd =
        std::min<uint32_t>(m_packetCount,
                           m_packetIndex + m_packetPrefetchDepth);
    for (uint32_t i = m_packetIndex; i < packetEnd; ++i) {
        PacketState& pkt = m_packetStates[i];
        if (!pkt.descriptorDone ||
            pkt.packetReadIssuedBytes >= pkt.desc.packetLen) {
            continue;
        }
        const uint32_t remaining =
            pkt.desc.packetLen - pkt.packetReadIssuedBytes;
        const uint32_t maxBytes = m_maxReadBurstBeats * BeatBytes;
        op = {};
        op.kind = AxiKind::ReadPacket;
        op.packetIndex = i;
        op.addr = pkt.desc.packetAddr + pkt.packetReadIssuedBytes;
        op.validBytes = std::min<uint32_t>(maxBytes, remaining);
        pkt.packetReadIssuedBytes += op.validBytes;
        return true;
    }

    if (m_nextDescriptorIndex < m_packetCount) {
        const uint32_t descriptorWindowEnd =
            std::min<uint32_t>(m_packetCount,
                               m_packetIndex + m_descriptorPrefetchDepth);
        if (m_nextDescriptorIndex >= descriptorWindowEnd) {
            return false;
        }
        const uint32_t availableDescriptors =
            descriptorWindowEnd - m_nextDescriptorIndex;
        const bool descriptorBatchReady =
            availableDescriptors >= m_maxReadBurstBeats;
        const bool descriptorNeededSoon = m_nextDescriptorIndex < packetEnd;
        const bool descriptorAtEnd = descriptorWindowEnd == m_packetCount;
        if (!descriptorBatchReady && !descriptorNeededSoon && !descriptorAtEnd) {
            return false;
        }
        const uint32_t descriptorCount =
            std::min<uint32_t>(m_maxReadBurstBeats,
                               availableDescriptors);
        op = {};
        op.kind = AxiKind::ReadDescriptor;
        op.packetIndex = m_nextDescriptorIndex;
        op.descriptorCount = descriptorCount;
        op.addr = m_descriptorBase +
            static_cast<uint64_t>(m_nextDescriptorIndex) * DescriptorStride;
        op.validBytes = descriptorCount * DescriptorStride;
        op.bytes.reserve(op.validBytes);
        for (uint32_t i = 0; i < descriptorCount; ++i) {
            const uint32_t packetIndex = m_nextDescriptorIndex + i;
            PacketState& pkt = m_packetStates[packetIndex];
            fatal_if(pkt.descriptorIssued,
                     "DdrPacketDmaNode tried to issue descriptor %u twice",
                     packetIndex);
            pkt.descriptorIssued = true;
        }
        m_nextDescriptorIndex += descriptorCount;
        return true;
    }

    return false;
}

void
DdrPacketDmaNode::consumeControlPort()
{
    const bool awFire = m_ctrlOut.awReady && m_ctrlIn.aw.valid;
    const bool wFire = m_ctrlOut.wReady && m_ctrlIn.w.valid;
    const bool arFire = m_ctrlOut.arReady && m_ctrlIn.ar.valid;
    const bool bFire = m_ctrlOut.b.valid && m_ctrlIn.bReady;
    const bool rFire = m_ctrlOut.r.valid && m_ctrlIn.rReady;

    if (bFire) {
        m_ctrlOut.b.valid = false;
    }
    if (rFire) {
        m_ctrlOut.r.valid = false;
    }

    if (awFire) {
        m_ctrlAw = m_ctrlIn.aw;
        m_ctrlHaveAw = true;
        DPRINTF(NocPacketFlow,
                "DdrPacketDmaNode ctrl AW recv addr=%#llx id=%u size=%u len=%u\n",
                static_cast<unsigned long long>(m_ctrlAw.addr), m_ctrlAw.id,
                m_ctrlAw.size, m_ctrlAw.len);
    }
    if (wFire) {
        m_ctrlW = m_ctrlIn.w;
        m_ctrlHaveW = true;
        DPRINTF(NocPacketFlow,
                "DdrPacketDmaNode ctrl W recv id=%u strb=%#llx last=%d\n",
                m_ctrlW.id,
                static_cast<unsigned long long>(m_ctrlW.wstrb),
                m_ctrlW.last);
    }

    if (m_ctrlHaveAw && m_ctrlHaveW && !m_ctrlOut.b.valid) {
        // MMIO/control writes may arrive with the exact byte address in AWADDR
        // while WDATA/WSTRB are still positioned on a 64B internal beat lane.
        // When a single 32-bit word lane is active, use AWADDR as-is and only
        // use the lane to extract the payload/strobe.
        if (m_ctrlAw.len == 0 && activeWordLanes(m_ctrlW) == 1) {
            const uint32_t lane = firstActiveLane(m_ctrlW);
            const uint64_t laneStrobe = (m_ctrlW.wstrb >> lane) & 0xf;
            if (laneStrobe != 0) {
                const uint32_t value = readLe32(m_ctrlW.data, lane);
                DPRINTF(NocPacketFlow,
                        "DdrPacketDmaNode ctrl exact write aw_addr=%#llx lane=%u strobe=%#llx value=%#x\n",
                        static_cast<unsigned long long>(m_ctrlAw.addr),
                        lane,
                        static_cast<unsigned long long>(laneStrobe),
                        value);
                writeControlReg(m_ctrlAw.addr,
                                value, laneStrobe);
            }
        } else {
            for (uint32_t lane = 0; lane < 64; lane += 4) {
                const uint64_t laneStrobe = (m_ctrlW.wstrb >> lane) & 0xf;
                if (laneStrobe != 0) {
                    DPRINTF(NocPacketFlow,
                            "DdrPacketDmaNode ctrl wide write aw_addr=%#llx lane=%u eff_addr=%#llx strobe=%#llx value=%#x\n",
                            static_cast<unsigned long long>(m_ctrlAw.addr),
                            lane,
                            static_cast<unsigned long long>(m_ctrlAw.addr + lane),
                            static_cast<unsigned long long>(laneStrobe),
                            readLe32(m_ctrlW.data, lane));
                    writeControlReg(m_ctrlAw.addr + lane,
                                    readLe32(m_ctrlW.data, lane), laneStrobe);
                }
            }
        }
        m_ctrlOut.b = {};
        m_ctrlOut.b.id = m_ctrlAw.id;
        m_ctrlOut.b.resp = AximmResp::OKAY;
        m_ctrlOut.b.valid = true;
        m_ctrlHaveAw = false;
        m_ctrlHaveW = false;
    }

    if (arFire && !m_ctrlOut.r.valid) {
        m_ctrlOut.r = {};
        m_ctrlOut.r.cmd = AximmCommand::READ;
        m_ctrlOut.r.id = m_ctrlIn.ar.id;
        m_ctrlOut.r.resp = AximmResp::OKAY;
        m_ctrlOut.r.last = true;
        m_ctrlOut.r.valid = true;
        m_ctrlOut.r.data.fill(0);
        for (uint32_t lane = 0; lane < 64; lane += 4) {
            writeLe32(m_ctrlOut.r.data, lane,
                      readControlReg(m_ctrlIn.ar.addr + lane));
        }
    }
}

void
DdrPacketDmaNode::driveControlPort()
{
    m_ctrlOut.awReady = !m_ctrlHaveAw && !m_ctrlOut.b.valid;
    m_ctrlOut.wReady = !m_ctrlHaveW && !m_ctrlOut.b.valid;
    m_ctrlOut.arReady = !m_ctrlOut.r.valid;
}

void
DdrPacketDmaNode::writeControlReg(uint64_t addr, uint32_t data, uint64_t wstrb)
{
    if ((wstrb & 0xf) == 0) {
        return;
    }

    DPRINTF(NocPacketFlow,
            "DdrPacketDmaNode writeControlReg addr=%#llx offset=%#llx data=%#x wstrb=%#llx\n",
            static_cast<unsigned long long>(addr),
            static_cast<unsigned long long>(controlOffset(addr)),
            data,
            static_cast<unsigned long long>(wstrb));

    switch (controlOffset(addr)) {
      case 0x00:
        if ((data & ControlClearStatus) != 0) {
            clearStatus();
        }
        if ((data & ControlStart) != 0) {
            startDma();
        }
        break;
      case 0x08:
        m_descriptorBase = (m_descriptorBase & 0xffffffff00000000ULL) | data;
        break;
      case 0x0c:
        m_descriptorBase = (m_descriptorBase & 0x00000000ffffffffULL) |
            (static_cast<uint64_t>(data) << 32);
        break;
      case 0x10:
        fatal_if(data > m_expectedDescriptors.size(),
                 "DdrPacketDmaNode control packet_count %u exceeds generated descriptor count %zu",
                 data, m_expectedDescriptors.size());
        m_packetCount = data;
        break;
      case 0x14:
        fatal_if(data == 0 || data > 256,
                 "DdrPacketDmaNode control max_read_burst_beats must be in [1, 256]");
        m_maxReadBurstBeats = data;
        break;
      case 0x20:
        fatal_if(data == 0 || data > 256,
                 "DdrPacketDmaNode control max_outstanding_reads must be in [1, 256]");
        m_maxOutstandingReads = data;
        break;
      default:
        break;
    }
}

uint32_t
DdrPacketDmaNode::readControlReg(uint64_t addr) const
{
    switch (controlOffset(addr)) {
      case 0x00:
        return 0;
      case 0x04: {
        uint32_t status = 0;
        if (m_started && !dmaTransferFinished()) {
            status |= StatusBusy;
        }
        if (m_doneStatus || dmaTransferFinished()) {
            status |= StatusDone;
        }
        if (m_errorStatus) {
            status |= StatusError;
        }
        if (m_eocSeen) {
            status |= StatusEocSeen;
        }
        return status;
      }
      case 0x08:
        return static_cast<uint32_t>(m_descriptorBase & 0xffffffffULL);
      case 0x0c:
        return static_cast<uint32_t>(m_descriptorBase >> 32);
      case 0x10:
        return m_packetCount;
      case 0x14:
        return m_maxReadBurstBeats;
      case 0x18:
        return static_cast<uint32_t>(m_packetsCompleted);
      case 0x1c:
        return m_errorCode;
      case 0x20:
        return m_maxOutstandingReads;
      default:
        return 0;
    }
}

uint64_t
DdrPacketDmaNode::controlOffset(uint64_t addr) const
{
    if (addr >= m_controlBase) {
        return addr - m_controlBase;
    }
    return addr;
}

void
DdrPacketDmaNode::clearStatus()
{
    m_doneStatus = false;
    m_errorStatus = false;
    m_errorCode = 0;
    m_eocSeen = false;
}

void
DdrPacketDmaNode::startDma()
{
    fatal_if(m_packetCount > m_expectedDescriptors.size(),
             "DdrPacketDmaNode cannot start: packet_count %u exceeds generated descriptor count %zu",
             m_packetCount, m_expectedDescriptors.size());

    clearStatus();
    m_started = true;
    if (m_functionalPreloadPackets && !m_functionalPacketsPreloaded) {
        performFunctionalPacketPreload();
    }
    m_dmaLaunchTick = curTick();
    m_sawDmaLaunch = true;
    m_packetIndex = 0;
    m_nextDescriptorIndex = 0;
    m_axisBeatIndex = 0;
    m_beatsEmitted = 0;
    m_bytesEmitted = 0;
    m_descriptorsRead = 0;
    m_packetsCompleted = 0;
    m_descriptorErrors = 0;
    m_totalDdrBytesRead = 0;
    m_readsIssued = 0;
    m_maxInflightReadsObserved = 0;
    m_descriptorReadsCompleted = 0;
    m_packetReadsCompleted = 0;
    m_descriptorReadTransactionsIssued = 0;
    m_packetReadTransactionsIssued = 0;
    m_descriptorReadTransactionsCompleted = 0;
    m_packetReadTransactionsCompleted = 0;
    m_descriptorReadRequestBytesIssued = 0;
    m_packetReadRequestBytesIssued = 0;
    m_arValidCycles = 0;
    m_arReadyValidCycles = 0;
    m_arValidNotReadyCycles = 0;
    m_rValidCycles = 0;
    m_rReadyValidCycles = 0;
    m_rValidNotReadyCycles = 0;
    m_rIdleInflightCycles = 0;
    m_axisValidCycles = 0;
    m_axisReadyValidCycles = 0;
    m_axisValidNotReadyCycles = 0;
    m_inflightSampleCycles = 0;
    m_inflightReadOccupancySum = 0;
    m_pendingReadValidCycles = 0;
    m_readIssueStallInflightFullCycles = 0;
    m_axisWaitPacketCycles = 0;
    m_packetStates.assign(m_expectedDescriptors.size(), PacketState());
    m_inflightReads.clear();
    m_hasPendingReadOp = false;
    m_axisBeats.clear();
    m_sawAxisBeat = false;
    m_firstDdrReadRequestTick = 0;
    m_lastDdrReadCompletionTick = 0;
    m_dmaDoneTick = 0;
    m_sawFirstDdrReadRequest = false;
    m_readLatencyTicks.clear();
    m_reportedSummary = false;
    m_postPreloadReadDelayRemaining = m_postPreloadReadDelayCycles;
    m_postPreloadReadDelayArmed = true;
    m_packetGapRemaining = 0;
}

bool
DdrPacketDmaNode::dmaTransferFinished() const
{
    return m_started && m_packetIndex >= m_packetCount;
}

bool
DdrPacketDmaNode::startNextAxiOp()
{
    if (!m_preloadWrites.empty()) {
        m_activeOp = std::move(m_preloadWrites.front());
        m_preloadWrites.pop_front();
        m_hasActiveOp = true;
        return true;
    }
    return false;
}

void
DdrPacketDmaNode::driveWriteOp(const AxiOp& op)
{
    if (!m_awAccepted) {
        m_aximmOut.aw.valid = true;
        m_aximmOut.aw.cmd = AximmCommand::WRITE;
        m_aximmOut.aw.id = m_axiId;
        m_aximmOut.aw.addr = op.addr;
        m_aximmOut.aw.len = 0;
        m_aximmOut.aw.size = 6;
        m_aximmOut.aw.burst = BurstType::INCR;
    }

    // tileNSU_HBM currently expects AW to be observed before the matching W
    // beat. Keep the preload path conservative so DDR initialization is
    // deterministic.
    if (m_awAccepted && !m_wAccepted) {
        m_aximmOut.w.valid = true;
        m_aximmOut.w.cmd = AximmCommand::WRITE;
        m_aximmOut.w.id = m_axiId;
        m_aximmOut.w.last = true;
        m_aximmOut.w.wstrb = prefixStrobe(op.validBytes);
        m_aximmOut.w.data.fill(0);
        std::copy(op.bytes.begin(), op.bytes.end(), m_aximmOut.w.data.begin());
    }
}

void
DdrPacketDmaNode::driveReadOp(const AxiOp& op)
{
    const uint32_t beats = ceilDiv(op.validBytes, BeatBytes);
    m_aximmOut.ar.valid = true;
    m_aximmOut.ar.cmd = AximmCommand::READ;
    m_aximmOut.ar.id = m_axiId;
    m_aximmOut.ar.addr = op.addr;
    m_aximmOut.ar.len = beats - 1;
    m_aximmOut.ar.size = 6;
    m_aximmOut.ar.burst = BurstType::INCR;
}

void
DdrPacketDmaNode::completeReadOp(const AxiOp& op)
{
    if (op.kind == AxiKind::ReadDescriptor) {
        fatal_if(op.descriptorCount == 0,
                 "DdrPacketDmaNode descriptor read completed with zero descriptors");
        fatal_if(op.bytes.size() < op.descriptorCount * DescriptorStride,
                 "DdrPacketDmaNode descriptor block read returned too few bytes");
        for (uint32_t i = 0; i < op.descriptorCount; ++i) {
            const uint32_t packetIndex = op.packetIndex + i;
            PacketState& pkt = m_packetStates[packetIndex];
            const size_t slotOffset = static_cast<size_t>(i) * DescriptorStride;
            pkt.descReadBuffer.assign(
                op.bytes.begin() + slotOffset,
                op.bytes.begin() + slotOffset + DescriptorBytes);
            const Descriptor desc = parseDescriptor(pkt.descReadBuffer);
            const Descriptor& expected = m_expectedDescriptors[packetIndex];
            fatal_if(desc.packetAddr != expected.packetAddr ||
                     desc.packetLen != expected.packetLen,
                     "DdrPacketDmaNode descriptor mismatch for packet %u",
                     packetIndex);
            pkt.desc = desc;
            pkt.descriptorDone = true;
            ++m_descriptorsRead;
            ++m_descriptorReadsCompleted;
            if ((desc.flags & DescFlagEndOfChain) != 0) {
                m_eocSeen = true;
            }
            fatal_if((desc.flags & DescFlagDrop) != 0,
                     "DdrPacketDmaNode descriptor DROP flag is parsed but not supported yet");
        }
        ++m_descriptorReadTransactionsCompleted;
        m_totalDdrBytesRead += op.descriptorCount * DescriptorBytes;
        return;
    }

    if (op.kind == AxiKind::ReadPacket) {
        PacketState& pkt = m_packetStates[op.packetIndex];
        fatal_if(!pkt.descriptorDone,
                 "DdrPacketDmaNode packet payload completed before descriptor %u",
                 op.packetIndex);
        fatal_if(pkt.packetReadBuffer.size() > pkt.desc.packetLen,
                 "DdrPacketDmaNode packet %u read too many bytes",
                 op.packetIndex);
        ++m_packetReadsCompleted;
        ++m_packetReadTransactionsCompleted;
        return;
    }

    panic("DdrPacketDmaNode completeReadOp invalid kind");
}

void
DdrPacketDmaNode::clearAxiRequestOutputs()
{
    m_aximmOut.ar.valid = false;
    m_aximmOut.aw.valid = false;
    m_aximmOut.w.valid = false;
}

bool
DdrPacketDmaNode::packetComplete() const
{
    if (m_packetIndex >= m_packetCount ||
        m_packetIndex >= m_packetStates.size()) {
        return false;
    }
    const PacketState& pkt = m_packetStates[m_packetIndex];
    return pkt.descriptorDone &&
           pkt.packetReadBuffer.size() >= pkt.desc.packetLen;
}

void
DdrPacketDmaNode::preparePacketAxisBeats()
{
    fatal_if(m_packetIndex >= m_packetCount,
             "DdrPacketDmaNode tried to prepare packet after completion");
    PacketState& pkt = m_packetStates[m_packetIndex];
    fatal_if(!pkt.descriptorDone,
             "DdrPacketDmaNode tried to emit packet %u before descriptor read",
             m_packetIndex);
    const Descriptor desc = pkt.desc;
    fatal_if(pkt.packetReadBuffer.size() < desc.packetLen,
             "DdrPacketDmaNode tried to emit packet %u before payload read",
             m_packetIndex);
    std::vector<uint8_t> packet(
        pkt.packetReadBuffer.begin(),
        pkt.packetReadBuffer.begin() + desc.packetLen);
    fatal_if(packet != m_expectedPackets[m_packetIndex],
             "DdrPacketDmaNode packet bytes read from DDR do not match expected packet %u",
             m_packetIndex);
    m_axisBeats = axis_packet::packetToAxisBeats(
        packet, m_dataWidth, m_tidWidth, m_tdestWidth,
        desc.tid, desc.tdest, desc.tuser);
    m_axisBeatIndex = 0;
    DPRINTF(NocPacketFlow,
            "DdrPacketDmaNode prepared packet %u len=%u beats=%zu tdest=%u tid=%u tuser=%u\n",
            m_packetIndex, desc.packetLen, m_axisBeats.size(),
            desc.tdest, desc.tid, desc.tuser);
}

void
DdrPacketDmaNode::printSummary()
{
    if (!m_printSummary || m_reportedSummary) {
        return;
    }
    m_reportedSummary = true;
    std::cout << "[DdrPacketDmaNode] packets=" << m_packetIndex
              << " completed=" << m_packetsCompleted
              << " descriptors=" << m_descriptorsRead
              << " beats=" << m_beatsEmitted
              << " bytes=" << m_bytesEmitted
              << " max_read_burst_beats=" << m_maxReadBurstBeats
              << " max_outstanding_reads=" << m_maxOutstandingReads
              << " reads_issued=" << m_readsIssued
              << " desc_read_tx_issued=" << m_descriptorReadTransactionsIssued
              << " packet_read_tx_issued=" << m_packetReadTransactionsIssued
              << " max_inflight_reads_observed=" << m_maxInflightReadsObserved
              << " avg_inflight_reads="
              << (m_inflightSampleCycles == 0 ? 0.0 :
                  static_cast<double>(m_inflightReadOccupancySum) /
                  static_cast<double>(m_inflightSampleCycles))
              << " start_delay_cycles=" << m_startDelayCycles
              << " post_preload_read_delay_cycles="
              << m_postPreloadReadDelayCycles
              << " packet_gap_cycles=" << m_packetGapCycles
              << " eoc_seen=" << (m_eocSeen ? 1 : 0)
              << " descriptor_errors=" << m_descriptorErrors
              << " preload=" << (m_preloadDdr ? 1 : 0) << "\n";
    if (m_sawAxisBeat) {
        const int clockMHz = getPortClockDomain(1);
        const double cycles = spanCycles(m_firstAxisTick, m_lastAxisTick,
                                         clockMHz);
        const double bytesPerCycle = cycles > 0.0 ?
            static_cast<double>(m_bytesEmitted) / cycles : 0.0;
        const double gbps = bytesPerCycle * 8.0 *
            static_cast<double>(clockMHz) / 1000.0;
        std::cout << "[DdrPacketDmaNode] axis_output_window"
                  << " first_tick=" << m_firstAxisTick
                  << " last_tick=" << m_lastAxisTick
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
DdrPacketDmaNode::emitMetricsFragment() const
{
    if (m_metricsOutputPath.empty()) {
        return;
    }
    std::ofstream out(m_metricsOutputPath, std::ios::trunc);
    if (!out.is_open()) {
        warn("DdrPacketDmaNode could not open metrics fragment %s",
             m_metricsOutputPath.c_str());
        return;
    }
    out << "{\n";
    out << "  \"type\": \"ddr_packet_dma\",\n";
    out << "  \"packet_count\": " << m_packetCount << ",\n";
    out << "  \"packets_completed\": " << m_packetsCompleted << ",\n";
    out << "  \"descriptors_read\": " << m_descriptorsRead << ",\n";
    out << "  \"reads_issued\": " << m_readsIssued << ",\n";
    out << "  \"max_inflight_reads_observed\": "
        << m_maxInflightReadsObserved << ",\n";
    out << "  \"descriptor_reads_completed\": "
        << m_descriptorReadsCompleted << ",\n";
    out << "  \"packet_reads_completed\": "
        << m_packetReadsCompleted << ",\n";
    out << "  \"descriptor_read_transactions_issued\": "
        << m_descriptorReadTransactionsIssued << ",\n";
    out << "  \"packet_read_transactions_issued\": "
        << m_packetReadTransactionsIssued << ",\n";
    out << "  \"descriptor_read_transactions_completed\": "
        << m_descriptorReadTransactionsCompleted << ",\n";
    out << "  \"packet_read_transactions_completed\": "
        << m_packetReadTransactionsCompleted << ",\n";
    out << "  \"descriptor_read_request_bytes_issued\": "
        << m_descriptorReadRequestBytesIssued << ",\n";
    out << "  \"packet_read_request_bytes_issued\": "
        << m_packetReadRequestBytesIssued << ",\n";
    out << "  \"ar_valid_cycles\": " << m_arValidCycles << ",\n";
    out << "  \"ar_ready_valid_cycles\": " << m_arReadyValidCycles << ",\n";
    out << "  \"ar_valid_not_ready_cycles\": " << m_arValidNotReadyCycles << ",\n";
    out << "  \"r_valid_cycles\": " << m_rValidCycles << ",\n";
    out << "  \"r_ready_valid_cycles\": " << m_rReadyValidCycles << ",\n";
    out << "  \"r_valid_not_ready_cycles\": " << m_rValidNotReadyCycles << ",\n";
    out << "  \"r_idle_inflight_cycles\": " << m_rIdleInflightCycles << ",\n";
    out << "  \"axis_valid_cycles\": " << m_axisValidCycles << ",\n";
    out << "  \"axis_ready_valid_cycles\": " << m_axisReadyValidCycles << ",\n";
    out << "  \"axis_valid_not_ready_cycles\": "
        << m_axisValidNotReadyCycles << ",\n";
    out << "  \"inflight_sample_cycles\": " << m_inflightSampleCycles << ",\n";
    out << "  \"inflight_read_occupancy_sum\": "
        << m_inflightReadOccupancySum << ",\n";
    out << "  \"avg_inflight_reads\": "
        << (m_inflightSampleCycles == 0 ? 0.0 :
            static_cast<double>(m_inflightReadOccupancySum) /
            static_cast<double>(m_inflightSampleCycles)) << ",\n";
    out << "  \"pending_read_valid_cycles\": "
        << m_pendingReadValidCycles << ",\n";
    out << "  \"read_issue_stall_inflight_full_cycles\": "
        << m_readIssueStallInflightFullCycles << ",\n";
    out << "  \"axis_wait_packet_cycles\": "
        << m_axisWaitPacketCycles << ",\n";
    out << "  \"post_preload_read_delay_cycles\": "
        << m_postPreloadReadDelayCycles << ",\n";
    out << "  \"beats_emitted\": " << m_beatsEmitted << ",\n";
    out << "  \"axis_bytes_emitted\": " << m_bytesEmitted << ",\n";
    out << "  \"total_ddr_bytes_read\": " << m_totalDdrBytesRead << ",\n";
    out << "  \"saw_dma_launch\": " << (m_sawDmaLaunch ? "true" : "false") << ",\n";
    out << "  \"saw_first_ddr_read_request\": "
        << (m_sawFirstDdrReadRequest ? "true" : "false") << ",\n";
    out << "  \"saw_axis_beat\": " << (m_sawAxisBeat ? "true" : "false") << ",\n";
    out << "  \"dma_launch_tick\": " << m_dmaLaunchTick << ",\n";
    out << "  \"first_ddr_read_request_tick\": " << m_firstDdrReadRequestTick << ",\n";
    out << "  \"last_ddr_read_completion_tick\": " << m_lastDdrReadCompletionTick << ",\n";
    out << "  \"first_axis_beat_tick\": " << m_firstAxisTick << ",\n";
    out << "  \"last_axis_beat_tick\": " << m_lastAxisTick << ",\n";
    out << "  \"dma_done_tick\": " << m_dmaDoneTick << ",\n";
    out << "  \"operation_window_start_reason\": \""
        << (m_sawDmaLaunch ? "dma_launch_accepted" :
            (m_sawFirstDdrReadRequest ? "first_ddr_read_request" : "")) << "\",\n";
    out << "  \"axis_stream_window_start_reason\": \""
        << (m_sawAxisBeat ? "first_dma_axis_beat" : "") << "\",\n";
    out << "  \"read_latency_ticks\": [";
    for (size_t i = 0; i < m_readLatencyTicks.size(); ++i) {
        if (i != 0) {
            out << ", ";
        }
        out << m_readLatencyTicks[i];
    }
    out << "]\n";
    out << "}\n";
}

} // namespace noc
} // namespace gem5
