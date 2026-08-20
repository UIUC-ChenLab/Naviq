#ifndef __AXIS_RTL_STREAM_NODE_2X_HH__
#define __AXIS_RTL_STREAM_NODE_2X_HH__

#include <algorithm>
#include <cstdint>
#include <memory>

#include "axis.hpp"
#include "base/logging.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/endpoints/NocNode.hh"
#include "verilated.h"

namespace gem5
{
namespace noc
{

template <typename RootT, typename ParamsT, typename WrapperTraits,
          uint32_t MaxUserBits>
class AxisRtlStreamNode2x : public NocNode
{
  public:
    explicit AxisRtlStreamNode2x(const ParamsT &p, const char* nodeName)
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
          m_ingressState{{}, {}},
          m_egressState{
              axisMasterState(p.data_width, p.id_width, p.dest_width),
              axisMasterState(p.data_width, p.id_width, p.dest_width)},
          m_ingressInput{
              axisMasterState(p.data_width, p.id_width, p.dest_width),
              axisMasterState(p.data_width, p.id_width, p.dest_width)},
          m_egressReadyInput{{}, {}},
          m_dut(std::make_unique<RootT>()),
          m_ingressBinding0(nullptr),
          m_ingressBinding1(nullptr),
          m_egressBinding0(nullptr),
          m_egressBinding1(nullptr)
    {
        panic_if(m_dataWidthBits > kMaxDataBits,
                 "%s only supports up to %u-bit data", m_nodeName, kMaxDataBits);
        panic_if(m_idWidth > kMaxIdBits,
                 "%s only supports up to %u-bit TID", m_nodeName, kMaxIdBits);
        panic_if(m_destWidth > kMaxDestBits,
                 "%s only supports up to %u-bit TDEST", m_nodeName, kMaxDestBits);
        panic_if(m_userWidth > MaxUserBits,
                 "%s only supports up to %u-bit TUSER", m_nodeName, MaxUserBits);

        maxPorts = 4;
        for (auto& state : m_ingressState) {
            state.tready = false;
        }
        for (auto& state : m_egressState) {
            state.data.tvalid = false;
        }
        for (auto& state : m_egressReadyInput) {
            state.tready = false;
        }

        m_ingressBinding0.r = m_dut.get();
        m_ingressBinding1.r = m_dut.get();
        m_egressBinding0.r = m_dut.get();
        m_egressBinding1.r = m_dut.get();
        clearAxisView(m_ingressBinding0.view());
        clearAxisView(m_ingressBinding1.view());
        clearAxisView(m_egressBinding0.view());
        clearAxisView(m_egressBinding1.view());

        WrapperTraits::clock(*m_dut) = 0;
        WrapperTraits::resetn(*m_dut) = 0;
        driveIdleInputs();
        m_dut->eval();
    }

    ~AxisRtlStreamNode2x() override = default;

    bool done() override
    {
        if (!m_resetComplete || m_expectedPackets == 0) {
            return false;
        }
        return m_packetsForwarded >= m_expectedPackets &&
            !m_egressState[0].data.tvalid && !m_egressState[1].data.tvalid;
    }

    bool tick(int clockDomain) override
    {
        if (!clockDomains.empty() && clockDomain != clockDomains[0]) {
            return false;
        }

        for (int i = 0; i < 2; ++i) {
            const bool handshakeOut =
                m_egressState[i].data.tvalid && m_egressReadyInput[i].tready;
            if (handshakeOut && m_egressState[i].data.tlast) {
                ++m_packetsForwarded;
            }
        }

        if (m_resetCountdown > 0) {
            --m_resetCountdown;
            driveIdleInputs();
            WrapperTraits::resetn(*m_dut) = 0;
            rawTick();
            captureIngressReady();
            clearAxisView(m_egressBinding0.view());
            clearAxisView(m_egressBinding1.view());
            m_egressState[0].data.tvalid = false;
            m_egressState[1].data.tvalid = false;
            m_ingressState[0].tready = false;
            m_ingressState[1].tready = false;
            if (m_resetCountdown == 0) {
                m_resetComplete = true;
            }
            return true;
        }

        WrapperTraits::resetn(*m_dut) = 1;
        driveIngressFromState();
        driveEgressReadyFromState();
        WrapperTraits::driveSideInputs(*m_dut, m_activeCycles);
        rawTick();
        ++m_activeCycles;
        captureIngressReady();
        captureEgressState();
        return true;
    }

    void update(int portID, State* inputNocInterfaceState) override
    {
        if (portID == 0 || portID == 1) {
            auto* axisMaster = dynamic_cast<axisMasterState*>(inputNocInterfaceState);
            if (!axisMaster) {
                panic("%s::update expected axisMasterState on port %d",
                      m_nodeName, portID);
            }
            m_ingressInput[portID] = *axisMaster;
            return;
        }

        if (portID == 2 || portID == 3) {
            auto* axisSlave = dynamic_cast<axisSlaveState*>(inputNocInterfaceState);
            if (!axisSlave) {
                panic("%s::update expected axisSlaveState on port %d",
                      m_nodeName, portID);
            }
            m_egressReadyInput[portID - 2] = *axisSlave;
            return;
        }

        panic("%s::update invalid portID %d", m_nodeName, portID);
    }

    State* getCurrentState(int portID) override
    {
        if (portID == 0 || portID == 1) {
            return &m_ingressState[portID];
        }
        if (portID == 2 || portID == 3) {
            return &m_egressState[portID - 2];
        }
        panic("%s::getCurrentState invalid portID %d", m_nodeName, portID);
        return nullptr;
    }

    int assignPort(const std::string &endpointName) override
    {
        for (int i = 0; i < 4; ++i) {
            if (portEndpointNames.size() > static_cast<size_t>(i) &&
                endpointName == portEndpointNames[i] && !m_portAssigned[i]) {
                m_portAssigned[i] = true;
                return i;
            }
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

    using AxisIngressBinding0 = tb::AxisTbBinding<
        RootT, typename WrapperTraits::Ingress0Traits,
        kMaxDataBits, kMaxKeepBits, 0, MaxUserBits, kMaxIdBits, kMaxDestBits>;
    using AxisIngressBinding1 = tb::AxisTbBinding<
        RootT, typename WrapperTraits::Ingress1Traits,
        kMaxDataBits, kMaxKeepBits, 0, MaxUserBits, kMaxIdBits, kMaxDestBits>;
    using AxisEgressBinding0 = tb::AxisTbBinding<
        RootT, typename WrapperTraits::Egress0Traits,
        kMaxDataBits, kMaxKeepBits, 0, MaxUserBits, kMaxIdBits, kMaxDestBits>;
    using AxisEgressBinding1 = tb::AxisTbBinding<
        RootT, typename WrapperTraits::Egress1Traits,
        kMaxDataBits, kMaxKeepBits, 0, MaxUserBits, kMaxIdBits, kMaxDestBits>;
    using AxisView = tb::AxisInterface<
        kMaxDataBits, kMaxKeepBits, 0, MaxUserBits, kMaxIdBits, kMaxDestBits>;

    void rawTick()
    {
        WrapperTraits::clock(*m_dut) = 0;
        m_dut->eval();
        WrapperTraits::clock(*m_dut) = 1;
        m_dut->eval();
    }

    void driveIngressFromState()
    {
        auto& view0 = m_ingressBinding0.view();
        auto& view1 = m_ingressBinding1.view();
        clearAxisView(view0);
        clearAxisView(view1);
        copyAxisStateToView(m_ingressInput[0].data, view0);
        copyAxisStateToView(m_ingressInput[1].data, view1);
        m_ingressBinding0.pack_to_dut(typename WrapperTraits::Ingress0Traits{});
        m_ingressBinding1.pack_to_dut(typename WrapperTraits::Ingress1Traits{});
    }

    void driveEgressReadyFromState()
    {
        auto& view0 = m_egressBinding0.view();
        auto& view1 = m_egressBinding1.view();
        clearAxisView(view0);
        clearAxisView(view1);
        view0.tready = m_egressReadyInput[0].tready;
        view1.tready = m_egressReadyInput[1].tready;
        WrapperTraits::egress0Tready(*m_dut) =
            static_cast<CData>(view0.tready ? 1 : 0);
        WrapperTraits::egress1Tready(*m_dut) =
            static_cast<CData>(view1.tready ? 1 : 0);
    }

    void driveIdleInputs()
    {
        clearAxisView(m_ingressBinding0.view());
        clearAxisView(m_ingressBinding1.view());
        clearAxisView(m_egressBinding0.view());
        clearAxisView(m_egressBinding1.view());
        m_ingressBinding0.pack_to_dut(typename WrapperTraits::Ingress0Traits{});
        m_ingressBinding1.pack_to_dut(typename WrapperTraits::Ingress1Traits{});
        WrapperTraits::egress0Tready(*m_dut) = 0;
        WrapperTraits::egress1Tready(*m_dut) = 0;
        WrapperTraits::driveIdleSideInputs(*m_dut);
    }

    void captureIngressReady()
    {
        m_ingressBinding0.unpack_from_dut(typename WrapperTraits::Ingress0Traits{});
        m_ingressBinding1.unpack_from_dut(typename WrapperTraits::Ingress1Traits{});
        m_ingressState[0].tready =
            m_ingressBinding0.view().tready && m_resetComplete;
        m_ingressState[1].tready =
            m_ingressBinding1.view().tready && m_resetComplete;
    }

    void captureEgressState()
    {
        m_egressBinding0.unpack_from_dut(typename WrapperTraits::Egress0Traits{});
        m_egressBinding1.unpack_from_dut(typename WrapperTraits::Egress1Traits{});
        copyViewToAxisState(m_egressBinding0.view(), m_egressState[0].data);
        copyViewToAxisState(m_egressBinding1.view(), m_egressState[1].data);
        if (!m_resetComplete) {
            m_egressState[0].data.tvalid = false;
            m_egressState[1].data.tvalid = false;
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
    bool m_portAssigned[4] = {false, false, false, false};
    uint32_t m_expectedPackets;
    uint32_t m_resetCycles;
    uint32_t m_dataWidthBits;
    uint32_t m_idWidth;
    uint32_t m_destWidth;
    uint32_t m_userWidth;
    uint32_t m_dataBytes;

    uint32_t m_resetCountdown;
    uint32_t m_packetsForwarded;
    uint64_t m_activeCycles;
    bool m_resetComplete;

    axisSlaveState m_ingressState[2];
    axisMasterState m_egressState[2];
    axisMasterState m_ingressInput[2];
    axisSlaveState m_egressReadyInput[2];

    std::unique_ptr<RootT> m_dut;
    AxisIngressBinding0 m_ingressBinding0;
    AxisIngressBinding1 m_ingressBinding1;
    AxisEgressBinding0 m_egressBinding0;
    AxisEgressBinding1 m_egressBinding1;
};

} // namespace noc
} // namespace gem5

#endif
