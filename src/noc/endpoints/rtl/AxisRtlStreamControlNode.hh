#ifndef __AXIS_RTL_STREAM_CONTROL_NODE_HH__
#define __AXIS_RTL_STREAM_CONTROL_NODE_HH__

#include <algorithm>
#include <cstdint>
#include <memory>

#include "axis.hpp"
#include "base/logging.hh"
#include "debug/NocPacketFlow.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/endpoints/NocNode.hh"
#include "verilated.h"

namespace gem5
{
namespace noc
{

template <typename RootT, typename ParamsT, typename WrapperTraits,
          uint32_t MaxUserBits>
class AxisRtlStreamControlNode : public NocNode
{
  public:
    explicit AxisRtlStreamControlNode(const ParamsT &p, const char* nodeName)
        : NocNode(p),
          m_nodeName(nodeName),
          m_expectedPackets(p.expected_packets),
          m_resetCycles(p.reset_cycles),
          m_dataWidthBits(p.data_width),
          m_idWidth(p.id_width),
          m_destWidth(p.dest_width),
          m_userWidth(p.user_width),
          m_dataBytes(p.data_width / 8),
          m_resetCountdown(p.reset_cycles),
          m_packetsForwarded(0),
          m_activeCycles(0),
          m_resetComplete(false),
          m_ingressState(),
          m_egressState(p.data_width, p.id_width, p.dest_width),
          m_ingressInput(p.data_width, p.id_width, p.dest_width),
          m_egressReadyInput(),
          m_ctrlState(),
          m_ctrlInput(),
          m_dut(std::make_unique<RootT>()),
          m_ingressBinding(nullptr),
          m_egressBinding(nullptr)
    {
        panic_if(m_dataWidthBits > kMaxDataBits,
                 "%s only supports up to %u-bit data", m_nodeName, kMaxDataBits);
        panic_if(m_idWidth > kMaxIdBits,
                 "%s only supports up to %u-bit TID", m_nodeName, kMaxIdBits);
        panic_if(m_destWidth > kMaxDestBits,
                 "%s only supports up to %u-bit TDEST", m_nodeName, kMaxDestBits);
        panic_if(m_userWidth > MaxUserBits,
                 "%s only supports up to %u-bit TUSER", m_nodeName, MaxUserBits);

        maxPorts = 3;
        m_ingressState.tready = false;
        m_egressState.data.tvalid = false;
        m_egressReadyInput.tready = false;
        m_ctrlState.awReady = false;
        m_ctrlState.wReady = false;
        m_ctrlState.arReady = false;
        m_ctrlState.b.valid = false;
        m_ctrlState.r.valid = false;

        m_ingressBinding.r = m_dut.get();
        m_egressBinding.r = m_dut.get();
        clearAxisView(m_ingressBinding.view());
        clearAxisView(m_egressBinding.view());

        WrapperTraits::clock(*m_dut) = 0;
        WrapperTraits::resetn(*m_dut) = 0;
        driveIdleInputs();
        m_dut->eval();
    }

    ~AxisRtlStreamControlNode() override = default;

    bool done() override
    {
        if (!m_resetComplete) {
            return false;
        }
        if (m_expectedPackets == 0) {
            const bool ctrlIdle =
                !m_haveWriteAddr && !m_haveWriteData && !m_haveReadAddr &&
                !m_writeAddrIssued && !m_writeDataIssued && !m_readAddrIssued &&
                !m_ctrlState.b.valid && !m_ctrlState.r.valid;
            return ctrlIdle;
        }
        return m_packetsForwarded >= m_expectedPackets && !m_egressState.data.tvalid;
    }

    bool tick(int clockDomain) override
    {
        if (!clockDomains.empty() && clockDomain != clockDomains[0]) {
            return false;
        }
        const bool ingressHandshake =
            m_ingressInput.data.tvalid && m_ingressState.tready;
        if (ingressHandshake) {
            DPRINTF(NocPacketFlow,
                    "%s ingress beat fire tdest=%u tid=%u tkeep=%#llx tlast=%d bytes=%u\n",
                    m_nodeName, m_ingressInput.data.tdest,
                    m_ingressInput.data.tid,
                    static_cast<unsigned long long>(m_ingressInput.data.tkeep),
                    m_ingressInput.data.tlast,
                    m_ingressInput.data.getTotalByteSize());
        }
        const bool handshakeOut =
            m_egressState.data.tvalid && m_egressReadyInput.tready;
        if (handshakeOut) {
            DPRINTF(NocPacketFlow,
                    "%s egress beat fire pkt=%u tdest=%u tid=%u tkeep=%#llx tlast=%d bytes=%u\n",
                    m_nodeName, m_packetsForwarded, m_egressState.data.tdest,
                    m_egressState.data.tid,
                    static_cast<unsigned long long>(m_egressState.data.tkeep),
                    m_egressState.data.tlast,
                    m_egressState.data.getTotalByteSize());
        }
        if (handshakeOut && m_egressState.data.tlast) {
            ++m_packetsForwarded;
            DPRINTF(NocPacketFlow, "%s completed packet count=%u\n",
                    m_nodeName, m_packetsForwarded);
        }

        consumeControlNetwork();

        if (m_resetCountdown > 0) {
            --m_resetCountdown;
            WrapperTraits::resetn(*m_dut) = 0;
            driveIdleInputs();
            rawTick();
            finishControlTick();
            captureIngressReady();
            clearAxisView(m_egressBinding.view());
            m_egressState.data.tvalid = false;
            m_ingressState.tready = false;
            if (m_resetCountdown == 0) {
                m_resetComplete = true;
            }
            return true;
        }

        WrapperTraits::resetn(*m_dut) = 1;
        driveIngressFromState();
        driveEgressReadyFromState();
        driveControlInputs();
        rawTick();
        finishControlTick();
        ++m_activeCycles;
        captureIngressReady();
        captureEgressState();
        return true;
    }

    void update(int portID, State* inputNocInterfaceState) override
    {
        if (portID == 0) {
            auto* axisMaster = dynamic_cast<axisMasterState*>(inputNocInterfaceState);
            if (!axisMaster) {
                panic("%s::update expected axisMasterState on port 0", m_nodeName);
            }
            m_ingressInput = *axisMaster;
            return;
        }

        if (portID == 1) {
            auto* axisSlave = dynamic_cast<axisSlaveState*>(inputNocInterfaceState);
            if (!axisSlave) {
                panic("%s::update expected axisSlaveState on port 1", m_nodeName);
            }
            m_egressReadyInput = *axisSlave;
            return;
        }

        if (portID == 2) {
            auto* aximmMaster = dynamic_cast<aximmMasterState*>(inputNocInterfaceState);
            if (!aximmMaster) {
                panic("%s::update expected aximmMasterState on port 2", m_nodeName);
            }
            m_ctrlInput = *aximmMaster;
            if (m_ctrlInput.aw.valid || m_ctrlInput.w.valid || m_ctrlInput.ar.valid ||
                m_ctrlInput.bReady || m_ctrlInput.rReady) {
                DPRINTF(NocPacketFlow,
                        "%s ctrl update: aw_v=%d aw_addr=%#x w_v=%d w_strb=%#llx "
                        "ar_v=%d ar_addr=%#x bReady=%d rReady=%d\n",
                        m_nodeName,
                        m_ctrlInput.aw.valid, m_ctrlInput.aw.addr,
                        m_ctrlInput.w.valid,
                        static_cast<unsigned long long>(m_ctrlInput.w.wstrb),
                        m_ctrlInput.ar.valid, m_ctrlInput.ar.addr,
                        m_ctrlInput.bReady, m_ctrlInput.rReady);
            }
            return;
        }

        panic("%s::update invalid portID %d", m_nodeName, portID);
    }

    State* getCurrentState(int portID) override
    {
        if (portID == 0) {
            return &m_ingressState;
        }
        if (portID == 1) {
            return &m_egressState;
        }
        if (portID == 2) {
            return &m_ctrlState;
        }
        panic("%s::getCurrentState invalid portID %d", m_nodeName, portID);
        return nullptr;
    }

    int assignPort(const std::string &endpointName) override
    {
        if (portEndpointNames.size() >= 1 &&
            endpointName == portEndpointNames[0] && !m_ingressPortAssigned) {
            m_ingressPortAssigned = true;
            DPRINTF(NocPacketFlow, "%s assignPort ingress -> %s\n",
                    m_nodeName, endpointName);
            return 0;
        }
        if (portEndpointNames.size() >= 2 &&
            endpointName == portEndpointNames[1] && !m_egressPortAssigned) {
            m_egressPortAssigned = true;
            DPRINTF(NocPacketFlow, "%s assignPort egress -> %s\n",
                    m_nodeName, endpointName);
            return 1;
        }
        if (portEndpointNames.size() >= 3 &&
            endpointName == portEndpointNames[2] && !m_ctrlPortAssigned) {
            m_ctrlPortAssigned = true;
            DPRINTF(NocPacketFlow, "%s assignPort ctrl -> %s\n",
                    m_nodeName, endpointName);
            return 2;
        }
        panic("%s::assignPort invalid endpointName: %s",
              m_nodeName, endpointName.c_str());
        return -1;
    }

  private:
    static constexpr uint32_t kMaxDataBits = 512;
    static constexpr uint32_t kMaxKeepBits = kMaxDataBits / 8;
    static constexpr uint32_t kMaxIdBits = 16;
    static constexpr uint32_t kMaxDestBits = 12;

    using AxisIngressBinding = tb::AxisTbBinding<
        RootT,
        typename WrapperTraits::IngressTraits,
        kMaxDataBits,
        kMaxKeepBits,
        0,
        MaxUserBits,
        kMaxIdBits,
        kMaxDestBits>;
    using AxisEgressBinding = tb::AxisTbBinding<
        RootT,
        typename WrapperTraits::EgressTraits,
        kMaxDataBits,
        kMaxKeepBits,
        0,
        MaxUserBits,
        kMaxIdBits,
        kMaxDestBits>;
    using AxisView = tb::AxisInterface<
        kMaxDataBits,
        kMaxKeepBits,
        0,
        MaxUserBits,
        kMaxIdBits,
        kMaxDestBits>;

    static uint32_t
    readLe32(const std::array<uint8_t, 64>& bytes, size_t off)
    {
        uint32_t value = 0;
        for (size_t i = 0; i < 4; ++i) {
            value |= static_cast<uint32_t>(bytes.at(off + i)) << (8 * i);
        }
        return value;
    }

    static void
    writeLe32(std::array<uint8_t, 64>& bytes, size_t off, uint32_t value)
    {
        for (size_t i = 0; i < 4; ++i) {
            bytes.at(off + i) =
                static_cast<uint8_t>((value >> (8 * i)) & 0xff);
        }
    }

    static uint32_t
    firstActiveLane(const aximmRWData& w)
    {
        for (uint32_t lane = 0; lane < 64; lane += 4) {
            if (((w.wstrb >> lane) & 0xf) != 0) {
                return lane;
            }
        }
        return 0;
    }

    static uint8_t
    decodeResp(uint32_t resp)
    {
        return static_cast<uint8_t>(resp & 0x3u);
    }

    void rawTick()
    {
        WrapperTraits::clock(*m_dut) = 0;
        m_dut->eval();
        WrapperTraits::clock(*m_dut) = 1;
        m_dut->eval();
    }

    bool externalControlEnabled() const
    {
        return m_ctrlPortAssigned;
    }

    void driveIngressFromState()
    {
        auto& view = m_ingressBinding.view();
        clearAxisView(view);
        copyAxisStateToView(m_ingressInput.data, view);
        if (m_ingressInput.data.tvalid) {
            DPRINTF(NocPacketFlow,
                    "%s ingress valid tdest=%u tid=%u tkeep=%#llx tlast=%d bytes=%u ready=%d\n",
                    m_nodeName, m_ingressInput.data.tdest,
                    m_ingressInput.data.tid,
                    static_cast<unsigned long long>(m_ingressInput.data.tkeep),
                    m_ingressInput.data.tlast,
                    m_ingressInput.data.getTotalByteSize(),
                    m_ingressState.tready);
        }
        m_ingressBinding.pack_to_dut(typename WrapperTraits::IngressTraits{});
    }

    void driveEgressReadyFromState()
    {
        auto& view = m_egressBinding.view();
        clearAxisView(view);
        view.tready = m_egressReadyInput.tready;
        WrapperTraits::egressTready(*m_dut) =
            static_cast<CData>(view.tready ? 1 : 0);
    }

    void driveAxisIdleInputs()
    {
        clearAxisView(m_ingressBinding.view());
        clearAxisView(m_egressBinding.view());
        m_egressBinding.view().tready = false;
        m_ingressBinding.pack_to_dut(typename WrapperTraits::IngressTraits{});
        WrapperTraits::egressTready(*m_dut) = 0;
    }

    void driveIdleInputs()
    {
        driveAxisIdleInputs();
        if (externalControlEnabled()) {
            rCtrlIdle();
        } else {
            WrapperTraits::driveIdleSideInputs(*m_dut);
        }
    }

    void driveControlInputs()
    {
        if (!externalControlEnabled()) {
            WrapperTraits::driveSideInputs(*m_dut, m_activeCycles);
            return;
        }

        rCtrlIdle();
        const uint32_t writeLane = firstActiveLane(m_writeData);
        if (m_haveWriteAddr && !m_writeAddrIssued) {
            m_dut->ctrl_aw_valid = 1;
            // m_writeAddr.addr is already the exact byte address on the
            // wide AXI-MM bus. writeLane is only for extracting the active
            // 32-bit word and nibble strobe from the wide WDATA/WSTRB beat.
            m_dut->ctrl_aw_addr = static_cast<uint32_t>(m_writeAddr.addr);
            m_dut->ctrl_aw_prot = m_writeAddr.prot;
            m_dut->ctrl_aw_user = m_writeAddr.user;
        }
        if (m_haveWriteData && !m_writeDataIssued) {
            m_dut->ctrl_w_valid = 1;
            m_dut->ctrl_w_data = readLe32(m_writeData.data, writeLane);
            m_dut->ctrl_w_strb = (m_writeData.wstrb >> writeLane) & 0xf;
            m_dut->ctrl_w_user = m_writeData.user;
        }
        if (m_haveReadAddr && !m_readAddrIssued) {
            m_dut->ctrl_ar_valid = 1;
            m_dut->ctrl_ar_addr = static_cast<uint32_t>(m_readAddr.addr);
            m_dut->ctrl_ar_prot = m_readAddr.prot;
            m_dut->ctrl_ar_user = m_readAddr.user;
        }
    }

    void rCtrlIdle()
    {
        m_dut->ctrl_aw_valid = 0;
        m_dut->ctrl_aw_addr = 0;
        m_dut->ctrl_aw_prot = 0;
        m_dut->ctrl_aw_user = 0;
        m_dut->ctrl_w_valid = 0;
        m_dut->ctrl_w_data = 0;
        m_dut->ctrl_w_strb = 0;
        m_dut->ctrl_w_user = 0;
        m_dut->ctrl_b_ready = 1;
        m_dut->ctrl_ar_valid = 0;
        m_dut->ctrl_ar_addr = 0;
        m_dut->ctrl_ar_prot = 0;
        m_dut->ctrl_ar_user = 0;
        m_dut->ctrl_r_ready = 1;
    }

    void finishControlTick()
    {
        if (!externalControlEnabled()) {
            return;
        }

        if (m_haveWriteAddr || m_haveWriteData || m_haveReadAddr ||
            m_dut->ctrl_aw_ready || m_dut->ctrl_w_ready ||
            m_dut->ctrl_b_valid || m_dut->ctrl_ar_ready ||
            m_dut->ctrl_r_valid) {
            DPRINTF(NocPacketFlow,
                    "%s ctrl tick: have_aw=%d aw_issued=%d dut_aw_ready=%d "
                    "have_w=%d w_issued=%d dut_w_ready=%d dut_b_valid=%d "
                    "have_ar=%d ar_issued=%d dut_ar_ready=%d dut_r_valid=%d\n",
                    m_nodeName,
                    m_haveWriteAddr, m_writeAddrIssued, m_dut->ctrl_aw_ready,
                    m_haveWriteData, m_writeDataIssued, m_dut->ctrl_w_ready,
                    m_dut->ctrl_b_valid,
                    m_haveReadAddr, m_readAddrIssued, m_dut->ctrl_ar_ready,
                    m_dut->ctrl_r_valid);
        }

        if (m_haveWriteAddr && !m_writeAddrIssued && m_dut->ctrl_aw_ready) {
            m_writeAddrIssued = true;
            DPRINTF(NocPacketFlow, "%s ctrl AW handshake addr=%#x id=%u\n",
                    m_nodeName, m_writeAddr.addr, m_writeAddr.id);
        }
        if (m_haveWriteData && !m_writeDataIssued && m_dut->ctrl_w_ready) {
            m_writeDataIssued = true;
            DPRINTF(NocPacketFlow, "%s ctrl W handshake strb=%#llx id=%u\n",
                    m_nodeName,
                    static_cast<unsigned long long>(m_writeData.wstrb),
                    m_writeData.id);
        }
        if (m_haveReadAddr && !m_readAddrIssued && m_dut->ctrl_ar_ready) {
            m_readAddrIssued = true;
            DPRINTF(NocPacketFlow, "%s ctrl AR handshake addr=%#x id=%u\n",
                    m_nodeName, m_readAddr.addr, m_readAddr.id);
        }

        if (m_haveWriteAddr && m_haveWriteData &&
            m_dut->ctrl_b_valid && !m_ctrlState.b.valid) {
            m_ctrlState.b = {};
            m_ctrlState.b.id = m_writeAddr.id;
            m_ctrlState.b.resp =
                static_cast<AximmResp>(decodeResp(m_dut->ctrl_b_resp));
            m_ctrlState.b.valid = true;
            DPRINTF(NocPacketFlow, "%s ctrl B captured id=%u resp=%u\n",
                    m_nodeName, m_ctrlState.b.id,
                    static_cast<unsigned>(m_ctrlState.b.resp));
            clearWriteTxn();
        }

        if (m_haveReadAddr &&
            m_dut->ctrl_r_valid && !m_ctrlState.r.valid) {
            m_ctrlState.r = {};
            m_ctrlState.r.cmd = AximmCommand::READ;
            m_ctrlState.r.id = m_readAddr.id;
            m_ctrlState.r.resp =
                static_cast<AximmResp>(decodeResp(m_dut->ctrl_r_resp));
            m_ctrlState.r.last = true;
            m_ctrlState.r.valid = true;
            m_ctrlState.r.data.fill(0);
            writeLe32(m_ctrlState.r.data, 0, m_dut->ctrl_r_data);
            DPRINTF(NocPacketFlow, "%s ctrl R captured id=%u data=%#x resp=%u\n",
                    m_nodeName, m_ctrlState.r.id, m_dut->ctrl_r_data,
                    static_cast<unsigned>(m_ctrlState.r.resp));
            clearReadTxn();
        }

        updateControlReadies();
    }

    void consumeControlNetwork()
    {
        if (!externalControlEnabled()) {
            return;
        }

        const bool bFire = m_ctrlState.b.valid && m_ctrlInput.bReady;
        const bool rFire = m_ctrlState.r.valid && m_ctrlInput.rReady;
        const bool awFire = m_ctrlState.awReady && m_ctrlInput.aw.valid;
        const bool wFire = m_ctrlState.wReady && m_ctrlInput.w.valid;
        const bool arFire = m_ctrlState.arReady && m_ctrlInput.ar.valid;

        if (bFire) {
            m_ctrlState.b.valid = false;
        }
        if (rFire) {
            m_ctrlState.r.valid = false;
        }
        if (awFire) {
            m_writeAddr = m_ctrlInput.aw;
            m_haveWriteAddr = true;
            m_writeAddrIssued = false;
            DPRINTF(NocPacketFlow, "%s ctrl AW recv addr=%#x id=%u size=%u len=%u\n",
                    m_nodeName, m_writeAddr.addr, m_writeAddr.id,
                    m_writeAddr.size, m_writeAddr.len);
        }
        if (wFire) {
            m_writeData = m_ctrlInput.w;
            m_haveWriteData = true;
            m_writeDataIssued = false;
            DPRINTF(NocPacketFlow, "%s ctrl W recv id=%u strb=%#llx last=%d\n",
                    m_nodeName, m_writeData.id,
                    static_cast<unsigned long long>(m_writeData.wstrb),
                    m_writeData.last);
        }
        if (arFire) {
            m_readAddr = m_ctrlInput.ar;
            m_haveReadAddr = true;
            m_readAddrIssued = false;
            DPRINTF(NocPacketFlow, "%s ctrl AR recv addr=%#x id=%u size=%u len=%u\n",
                    m_nodeName, m_readAddr.addr, m_readAddr.id,
                    m_readAddr.size, m_readAddr.len);
        }

        updateControlReadies();
    }

    void updateControlReadies()
    {
        if (!externalControlEnabled()) {
            m_ctrlState.awReady = false;
            m_ctrlState.wReady = false;
            m_ctrlState.arReady = false;
            return;
        }

        const bool writeRespPending = m_ctrlState.b.valid;
        const bool readBusy = m_haveReadAddr || m_ctrlState.r.valid;

        // AXI-Lite write address and write data channels are independent.
        // Accept either half of the write first, then keep the other side
        // ready until the pair is complete.
        m_ctrlState.awReady =
            !readBusy && !writeRespPending && !m_haveWriteAddr;
        m_ctrlState.wReady =
            !readBusy && !writeRespPending && !m_haveWriteData;
        m_ctrlState.arReady =
            !readBusy && !writeRespPending &&
            !m_haveWriteAddr && !m_haveWriteData;
    }

    void clearWriteTxn()
    {
        m_haveWriteAddr = false;
        m_haveWriteData = false;
        m_writeAddrIssued = false;
        m_writeDataIssued = false;
    }

    void clearReadTxn()
    {
        m_haveReadAddr = false;
        m_readAddrIssued = false;
    }

    void captureIngressReady()
    {
        m_ingressBinding.unpack_from_dut(typename WrapperTraits::IngressTraits{});
        m_ingressState.tready = m_ingressBinding.view().tready && m_resetComplete;
    }

    void captureEgressState()
    {
        m_egressBinding.unpack_from_dut(typename WrapperTraits::EgressTraits{});
        copyViewToAxisState(m_egressBinding.view(), m_egressState.data);
        if (m_egressState.data.tvalid) {
            DPRINTF(NocPacketFlow,
                    "%s egress valid tdest=%u tid=%u tkeep=%#llx tlast=%d bytes=%u ready=%d\n",
                    m_nodeName, m_egressState.data.tdest,
                    m_egressState.data.tid,
                    static_cast<unsigned long long>(m_egressState.data.tkeep),
                    m_egressState.data.tlast,
                    m_egressState.data.getTotalByteSize(),
                    m_egressReadyInput.tready);
        }
        if (!m_resetComplete) {
            m_egressState.data.tvalid = false;
        }
    }

    void clearAxisView(AxisView& view)
    {
        view = AxisView{};
    }

    uint32_t userMask() const
    {
        if (m_userWidth == 0) {
            return 0;
        }
        if (m_userWidth >= 32) {
            return ~0u;
        }
        return (1u << m_userWidth) - 1u;
    }

    void copyAxisStateToView(const axisData& data, AxisView& view)
    {
        const size_t maxBytes =
            std::min<size_t>(m_dataBytes, view.tdata.size() * sizeof(uint32_t));
        for (size_t i = 0; i < maxBytes; ++i) {
            const size_t wordIdx = i / 4;
            const size_t byteOff = i % 4;
            view.tdata[wordIdx] &= ~(0xFFu << (byteOff * 8));
            view.tdata[wordIdx] |=
                static_cast<uint32_t>(data.tdata[i]) << (byteOff * 8);
        }

        view.tkeep.fill(0u);
        if (view.tkeep.size() > 0) {
            view.tkeep[0] = static_cast<uint32_t>(data.tkeep & 0xFFFFFFFFu);
        }
        if (view.tkeep.size() > 1) {
            view.tkeep[1] =
                static_cast<uint32_t>((data.tkeep >> 32) & 0xFFFFFFFFu);
        }

        if (m_userWidth > 0) {
            view.tuser[0] = data.tuser & userMask();
        }
        view.tid[0] = data.tid;
        view.tdest[0] = data.tdest;
        view.tlast = data.tlast;
        view.tvalid = data.tvalid;
    }

    void copyViewToAxisState(const AxisView& view, axisData& data)
    {
        std::fill(data.tdata.begin(), data.tdata.end(), 0);
        for (size_t i = 0; i < m_dataBytes; ++i) {
            const size_t wordIdx = i / 4;
            const size_t byteOff = i % 4;
            data.tdata[i] =
                static_cast<uint8_t>((view.tdata[wordIdx] >> (byteOff * 8)) & 0xFFu);
        }

        uint64_t keep = 0;
        if (view.tkeep.size() > 0) {
            keep |= static_cast<uint64_t>(view.tkeep[0]);
        }
        if (view.tkeep.size() > 1) {
            keep |= static_cast<uint64_t>(view.tkeep[1]) << 32;
        }

        data.tkeep = keep;
        data.tuser = view.tuser[0] & userMask();
        data.tid = view.tid[0];
        data.tdest = view.tdest[0];
        data.tlast = view.tlast;
        data.tvalid = view.tvalid;
    }

    const char* m_nodeName;
    const uint32_t m_expectedPackets;
    const uint32_t m_resetCycles;
    const uint32_t m_dataWidthBits;
    const uint32_t m_idWidth;
    const uint32_t m_destWidth;
    const uint32_t m_userWidth;
    const uint32_t m_dataBytes;

    uint32_t m_resetCountdown;
    uint32_t m_packetsForwarded;
    uint64_t m_activeCycles;
    bool m_resetComplete;

    axisSlaveState m_ingressState;
    axisMasterState m_egressState;
    axisMasterState m_ingressInput;
    axisSlaveState m_egressReadyInput;

    aximmSlaveState m_ctrlState;
    aximmMasterState m_ctrlInput;
    aximmRWAddr m_writeAddr;
    aximmRWData m_writeData;
    aximmRWAddr m_readAddr;
    bool m_haveWriteAddr = false;
    bool m_haveWriteData = false;
    bool m_haveReadAddr = false;
    bool m_writeAddrIssued = false;
    bool m_writeDataIssued = false;
    bool m_readAddrIssued = false;

    std::unique_ptr<RootT> m_dut;
    AxisIngressBinding m_ingressBinding;
    AxisEgressBinding m_egressBinding;
    bool m_ingressPortAssigned = false;
    bool m_egressPortAssigned = false;
    bool m_ctrlPortAssigned = false;
};

} // namespace noc
} // namespace gem5

#endif
