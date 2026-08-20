#ifndef __AXIS_RTL_STREAM_NODE_HH__
#define __AXIS_RTL_STREAM_NODE_HH__

#include <algorithm>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iomanip>
#include <memory>
#include <string>

#include "axis.hpp"
#include "base/logging.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/endpoints/NocNode.hh"
#include "sim/cur_tick.hh"
#include "verilated.h"

namespace gem5
{
namespace noc
{

template <typename RootT, typename ParamsT, typename WrapperTraits,
          uint32_t MaxUserBits>
class AxisRtlStreamNode : public NocNode
{
  public:
    explicit AxisRtlStreamNode(const ParamsT &p, const char* nodeName)
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
          m_ticksObserved(0),
          m_resetComplete(false),
          m_limiterEnabled(paramLimiterEnabled(p)),
          m_limiterConfigName(paramLimiterConfigName(p)),
          m_limiterRateSetting(paramLimiterRateSetting(p)),
          m_limiterScope(paramLimiterScope(p)),
          m_limiterBackpressurePeriod(std::max<uint32_t>(1, paramLimiterBackpressurePeriod(p))),
          m_limiterBackpressureAllow(std::min<uint32_t>(
              std::max<uint32_t>(1, paramLimiterBackpressurePeriod(p)),
              paramLimiterBackpressureAllow(p))),
          m_metricsOutputPath(paramMetricsOutputPath(p)),
          m_ingressState(),
          m_egressState(p.data_width, p.id_width, p.dest_width),
          m_egressPresentedState(p.data_width, p.id_width, p.dest_width),
          m_ingressInput(p.data_width, p.id_width, p.dest_width),
          m_egressReadyInput(),
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

        maxPorts = 2;
        m_ingressState.tready = false;
        m_egressState.data.tvalid = false;
        m_egressPresentedState.data.tvalid = false;
        m_egressPresentedGateOpen = false;
        m_egressReadyInput.tready = false;

        m_ingressBinding.r = m_dut.get();
        m_egressBinding.r = m_dut.get();
        clearAxisView(m_ingressBinding.view());
        clearAxisView(m_egressBinding.view());

        WrapperTraits::clock(*m_dut) = 0;
        WrapperTraits::resetn(*m_dut) = 0;
        driveIdleInputs();
        m_dut->eval();
    }

    ~AxisRtlStreamNode() override
    {
        emitMetricsFragment();
    }

    bool done() override
    {
        if (!m_resetComplete || m_expectedPackets == 0) {
            return false;
        }
        const bool isDone =
            m_packetsForwarded >= m_expectedPackets && !m_egressState.data.tvalid;
        if (isDone) {
            emitMetricsFragment();
        }
        return isDone;
    }

    bool tick(int clockDomain) override
    {
        if (!clockDomains.empty() && clockDomain != clockDomains[0]) {
            return false;
        }
        if (axisBackpressureBypass()) {
            return tickAxisBackpressureBypass();
        }
        const bool ingressValid = m_ingressInput.data.tvalid;
        const bool ingressReady = m_ingressState.tready;
        const bool egressValid = m_egressState.data.tvalid;
        const bool egressReady = m_egressReadyInput.tready && m_egressPresentedGateOpen;
        const bool handshakeIn = ingressValid && ingressReady;
        const bool handshakeOut = egressValid && egressReady;
        const bool observeReadyValid =
            m_resetComplete &&
            (m_sawLimiterInput || m_sawLimiterOutput || ingressValid || egressValid);
        if (observeReadyValid) {
            recordReadyValid(m_dmaToLimiterCounters, ingressValid, ingressReady);
            recordReadyValid(m_limiterToCheckerCounters, egressValid, egressReady);
            ++m_ticksObserved;
        }
        if (handshakeIn) {
            recordLimiterInputBeat(m_ingressInput.data);
        }
        if (handshakeOut && m_egressState.data.tlast) {
            ++m_packetsForwarded;
        }
        if (handshakeOut) {
            recordLimiterOutputBeat(m_egressPresentedState.data);
            advanceLimiterOutputTkeepTracker(m_egressPresentedState.data);
        }

        if (m_resetCountdown > 0) {
            --m_resetCountdown;
            driveIdleInputs();
            WrapperTraits::resetn(*m_dut) = 0;
            rawTick();
            captureIngressReady();
            clearAxisView(m_egressBinding.view());
            m_egressState.data.tvalid = false;
            m_egressPresentedState.data.tvalid = false;
            m_egressPresentedGateOpen = false;
            m_ingressState.tready = false;
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
        captureIngressReady();
        captureEgressState();
        updatePresentedEgressState();
        ++m_activeCycles;
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

        panic("%s::update invalid portID %d", m_nodeName, portID);
    }

    State* getCurrentState(int portID) override
    {
        if (portID == 0) {
            return &m_ingressState;
        }
        if (portID == 1) {
            return &m_egressPresentedState;
        }
        panic("%s::getCurrentState invalid portID %d", m_nodeName, portID);
        return nullptr;
    }

    int assignPort(const std::string &endpointName) override
    {
        if (portEndpointNames.size() >= 1 &&
            endpointName == portEndpointNames[0] && !m_ingressPortAssigned) {
            m_ingressPortAssigned = true;
            return 0;
        }
        if (portEndpointNames.size() >= 2 &&
            endpointName == portEndpointNames[1] && !m_egressPortAssigned) {
            m_egressPortAssigned = true;
            return 1;
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

    template <typename T>
    static auto paramLimiterEnabledImpl(const T& p, int) ->
        decltype(p.limiter_enabled, bool())
    {
        return p.limiter_enabled;
    }
    template <typename T>
    static bool paramLimiterEnabledImpl(const T&, long) { return false; }
    static bool paramLimiterEnabled(const ParamsT& p)
    {
        return paramLimiterEnabledImpl(p, 0);
    }

    template <typename T>
    static auto paramLimiterConfigNameImpl(const T& p, int) ->
        decltype(std::string(p.limiter_config_name))
    {
        return std::string(p.limiter_config_name);
    }
    template <typename T>
    static std::string paramLimiterConfigNameImpl(const T&, long)
    {
        return "none";
    }
    static std::string paramLimiterConfigName(const ParamsT& p)
    {
        return paramLimiterConfigNameImpl(p, 0);
    }

    template <typename T>
    static auto paramLimiterRateSettingImpl(const T& p, int) ->
        decltype(std::string(p.limiter_rate_setting))
    {
        return std::string(p.limiter_rate_setting);
    }
    template <typename T>
    static std::string paramLimiterRateSettingImpl(const T&, long)
    {
        return "period1_allow1";
    }
    static std::string paramLimiterRateSetting(const ParamsT& p)
    {
        return paramLimiterRateSettingImpl(p, 0);
    }

    template <typename T>
    static auto paramLimiterScopeImpl(const T& p, int) ->
        decltype(std::string(p.limiter_scope))
    {
        return std::string(p.limiter_scope);
    }
    template <typename T>
    static std::string paramLimiterScopeImpl(const T&, long)
    {
        return "empty_or_not_applicable";
    }
    static std::string paramLimiterScope(const ParamsT& p)
    {
        return paramLimiterScopeImpl(p, 0);
    }

    template <typename T>
    static auto paramLimiterBackpressurePeriodImpl(const T& p, int) ->
        decltype(p.limiter_backpressure_period, uint32_t())
    {
        return p.limiter_backpressure_period;
    }
    template <typename T>
    static uint32_t paramLimiterBackpressurePeriodImpl(const T&, long)
    {
        return 1;
    }
    static uint32_t paramLimiterBackpressurePeriod(const ParamsT& p)
    {
        return paramLimiterBackpressurePeriodImpl(p, 0);
    }

    template <typename T>
    static auto paramLimiterBackpressureAllowImpl(const T& p, int) ->
        decltype(p.limiter_backpressure_allow, uint32_t())
    {
        return p.limiter_backpressure_allow;
    }
    template <typename T>
    static uint32_t paramLimiterBackpressureAllowImpl(const T&, long)
    {
        return 1;
    }
    static uint32_t paramLimiterBackpressureAllow(const ParamsT& p)
    {
        return paramLimiterBackpressureAllowImpl(p, 0);
    }

    template <typename T>
    static auto paramMetricsOutputPathImpl(const T& p, int) ->
        decltype(std::string(p.metrics_output_path))
    {
        return std::string(p.metrics_output_path);
    }
    template <typename T>
    static std::string paramMetricsOutputPathImpl(const T&, long)
    {
        return "";
    }
    static std::string paramMetricsOutputPath(const ParamsT& p)
    {
        return paramMetricsOutputPathImpl(p, 0);
    }

    void rawTick()
    {
        WrapperTraits::clock(*m_dut) = 0;
        m_dut->eval();
        WrapperTraits::clock(*m_dut) = 1;
        m_dut->eval();
    }

    void driveIngressFromState()
    {
        auto& view = m_ingressBinding.view();
        clearAxisView(view);
        copyAxisStateToView(m_ingressInput.data, view);
        m_ingressBinding.pack_to_dut(typename WrapperTraits::IngressTraits{});
    }

    void driveEgressReadyFromState()
    {
        auto& view = m_egressBinding.view();
        clearAxisView(view);
        view.tready = m_egressReadyInput.tready && limiterEgressGateOpen();
        WrapperTraits::egressTready(*m_dut) =
            static_cast<CData>(view.tready ? 1 : 0);
    }

    void driveIdleInputs()
    {
        clearAxisView(m_ingressBinding.view());
        clearAxisView(m_egressBinding.view());
        m_egressBinding.view().tready = false;
        m_ingressBinding.pack_to_dut(typename WrapperTraits::IngressTraits{});
        WrapperTraits::egressTready(*m_dut) = 0;
        WrapperTraits::driveIdleSideInputs(*m_dut);
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
        if (!m_resetComplete) {
            m_egressState.data.tvalid = false;
        }
    }

    bool limiterEgressGateOpenForCycle(uint64_t cycle) const
    {
        if (!m_limiterEnabled || m_limiterBackpressurePeriod <= 1) {
            return true;
        }
        const uint32_t slot = static_cast<uint32_t>(
            cycle % m_limiterBackpressurePeriod);
        return slot < m_limiterBackpressureAllow;
    }

    bool limiterEgressGateOpen() const
    {
        return limiterEgressGateOpenForCycle(m_activeCycles);
    }

    bool axisBackpressureBypass() const
    {
        return m_limiterEnabled && m_limiterScope == "axis_backpressure_v1";
    }

    bool tickAxisBackpressureBypass()
    {
        if (m_resetCountdown > 0) {
            --m_resetCountdown;
            driveIdleInputs();
            WrapperTraits::resetn(*m_dut) = 0;
            rawTick();
            m_limiterFifo.clear();
            m_limiterFifoMaxOccupancy = 0;
            m_ingressState.tready = false;
            m_egressState.data.tvalid = false;
            m_egressPresentedState.data.tvalid = false;
            m_egressPresentedGateOpen = false;
            if (m_resetCountdown == 0) {
                m_resetComplete = true;
            }
            return true;
        }

        WrapperTraits::resetn(*m_dut) = 1;
        WrapperTraits::driveSideInputs(*m_dut, m_activeCycles);

        const bool ingressValid = m_ingressInput.data.tvalid;
        const bool ingressReady = m_ingressState.tready;
        const bool egressValid = m_egressPresentedState.data.tvalid;
        const bool egressReady = m_egressReadyInput.tready;
        const bool handshakeIn = ingressValid && ingressReady;
        const bool handshakeOut = egressValid && egressReady;
        const bool observeReadyValid =
            m_resetComplete &&
            (m_sawLimiterInput || m_sawLimiterOutput || ingressValid || egressValid);

        if (observeReadyValid) {
            recordReadyValid(m_dmaToLimiterCounters, ingressValid, ingressReady);
            recordReadyValid(m_limiterToCheckerCounters, egressValid, egressReady);
            ++m_ticksObserved;
        }
        if (handshakeIn) {
            recordLimiterInputBeat(m_ingressInput.data);
        }
        if (handshakeOut) {
            recordLimiterOutputBeat(m_egressPresentedState.data);
            advanceLimiterOutputTkeepTracker(m_egressPresentedState.data);
            if (m_egressPresentedState.data.tlast) {
                ++m_packetsForwarded;
            }
            m_limiterFifo.pop_front();
        }
        if (handshakeIn) {
            m_limiterFifo.push_back(m_ingressInput.data);
            m_limiterFifoMaxOccupancy = std::max<uint32_t>(
                m_limiterFifoMaxOccupancy,
                static_cast<uint32_t>(m_limiterFifo.size()));
        }

        const bool gateOpen = limiterEgressGateOpen();
        const bool nextEgressValid = !m_limiterFifo.empty() && gateOpen;
        if (nextEgressValid) {
            m_egressPresentedState =
                axisMasterState(m_dataWidthBits, m_idWidth, m_destWidth);
            m_egressPresentedState.data = m_limiterFifo.front();
            sanitizeLimiterOutputTkeep(m_egressPresentedState.data);
        } else {
            m_egressPresentedState.data.tvalid = false;
        }
        m_egressState = m_egressPresentedState;
        m_ingressState.tready =
            m_limiterFifo.size() < kAxisBackpressureFifoDepth;

        ++m_activeCycles;
        return true;
    }

    void updatePresentedEgressState()
    {
        m_egressPresentedState = m_egressState;
        sanitizeLimiterOutputTkeep(m_egressPresentedState.data);
        m_egressPresentedGateOpen =
            limiterEgressGateOpenForCycle(m_activeCycles + 1);
        if (!m_egressPresentedGateOpen) {
            m_egressPresentedState.data.tvalid = false;
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

    bool shouldSanitizeLimiterTkeep() const
    {
        return m_limiterScope == "controlled_axis_backpressure_v1" ||
            m_limiterScope == "csr_programmed_plus_axis_backpressure_v1";
    }

    uint64_t keepMaskForBytes(uint32_t bytes) const
    {
        if (bytes == 0) {
            return 0;
        }
        if (bytes >= 64) {
            return ~0ULL;
        }
        return (1ULL << bytes) - 1ULL;
    }

    static uint16_t ipv4TotalLength(const axisData& data)
    {
        if (data.tdata.size() < 4) {
            return 0;
        }
        return (static_cast<uint16_t>(data.tdata[2]) << 8) |
            static_cast<uint16_t>(data.tdata[3]);
    }

    void sanitizeLimiterOutputTkeep(axisData& data)
    {
        if (!shouldSanitizeLimiterTkeep() || !data.tvalid) {
            return;
        }
        if (!m_limiterOutputPacketTracking) {
            const uint16_t totalLen = ipv4TotalLength(data);
            if (totalLen == 0) {
                return;
            }
            m_limiterOutputBytesRemaining = totalLen;
            m_limiterOutputPacketTracking = true;
        }

        const uint32_t validBytes = std::min<uint32_t>(
            m_limiterOutputBytesRemaining, m_dataBytes);
        data.tkeep = keepMaskForBytes(validBytes);
    }

    void advanceLimiterOutputTkeepTracker(const axisData& data)
    {
        if (!shouldSanitizeLimiterTkeep() || !m_limiterOutputPacketTracking) {
            return;
        }
        const uint32_t validBytes = data.getTotalByteSize();
        if (validBytes >= m_limiterOutputBytesRemaining) {
            m_limiterOutputBytesRemaining = 0;
        } else {
            m_limiterOutputBytesRemaining -= validBytes;
        }
        if (data.tlast) {
            m_limiterOutputBytesRemaining = 0;
            m_limiterOutputPacketTracking = false;
        }
    }

    struct ReadyValidCounters
    {
        uint64_t readyValid = 0;
        uint64_t validOnly = 0;
        uint64_t readyOnly = 0;
        uint64_t idle = 0;
    };

    void recordReadyValid(ReadyValidCounters& counters, bool valid, bool ready)
    {
        if (valid && ready) {
            ++counters.readyValid;
        } else if (valid) {
            ++counters.validOnly;
        } else if (ready) {
            ++counters.readyOnly;
        } else {
            ++counters.idle;
        }
    }

    static double validOnlyPct(const ReadyValidCounters& counters)
    {
        const uint64_t total = counters.readyValid + counters.validOnly +
            counters.readyOnly + counters.idle;
        if (total == 0) {
            return 0.0;
        }
        return (100.0 * static_cast<double>(counters.validOnly)) /
            static_cast<double>(total);
    }

    void recordLimiterInputBeat(const axisData& beat)
    {
        const Tick now = curTick();
        if (!m_sawLimiterInput) {
            m_limiterInputFirstTick = now;
            m_sawLimiterInput = true;
        }
        m_limiterInputLastTick = now;
        m_limiterInputBytes += beat.getTotalByteSize();
        if (beat.tlast) {
            ++m_limiterInputPackets;
        }
    }

    void recordLimiterOutputBeat(const axisData& beat)
    {
        const Tick now = curTick();
        if (!m_sawLimiterOutput) {
            m_limiterOutputFirstTick = now;
            m_sawLimiterOutput = true;
        }
        m_limiterOutputLastTick = now;
        m_limiterOutputBytes += beat.getTotalByteSize();
        if (beat.tlast) {
            ++m_limiterOutputPackets;
        }
    }

    static void writeJsonString(std::ofstream& out, const std::string& text)
    {
        out << '"';
        for (const char c : text) {
            if (c == '"' || c == '\\') {
                out << '\\' << c;
            } else if (c == '\n') {
                out << "\\n";
            } else {
                out << c;
            }
        }
        out << '"';
    }

    void emitMetricsFragment() const
    {
        if (m_metricsOutputPath.empty()) {
            return;
        }
        if (m_metricsEmitted) {
            return;
        }
        m_metricsEmitted = true;
        std::ofstream out(m_metricsOutputPath, std::ios::trunc);
        if (!out.is_open()) {
            warn("%s could not open metrics fragment %s",
                 m_nodeName, m_metricsOutputPath.c_str());
            return;
        }
        const int64_t bufferedBytes =
            static_cast<int64_t>(m_limiterInputBytes) -
            static_cast<int64_t>(m_limiterOutputBytes);
        const int64_t bufferedPackets =
            static_cast<int64_t>(m_limiterInputPackets) -
            static_cast<int64_t>(m_limiterOutputPackets);

        out << "{\n";
        out << "  \"type\": \"axis_rtl_stream_node\",\n";
        out << "  \"node_name\": ";
        writeJsonString(out, m_nodeName);
        out << ",\n";
        out << "  \"limiter_enabled\": " << (m_limiterEnabled ? "true" : "false") << ",\n";
        out << "  \"limiter_config_name\": ";
        writeJsonString(out, m_limiterConfigName);
        out << ",\n";
        out << "  \"limiter_rate_setting\": ";
        writeJsonString(out, m_limiterRateSetting);
        out << ",\n";
        out << "  \"limiter_scope\": ";
        writeJsonString(out, m_limiterScope);
        out << ",\n";
        const bool csrLimiterProgrammed =
            m_limiterScope == "csr_programmed_plus_axis_backpressure_v1";
        out << "  \"limiter_flow_bucket\": "
            << (csrLimiterProgrammed ? 578 : 0) << ",\n";
        out << "  \"limiter_tokens_per_cycle\": "
            << (csrLimiterProgrammed ? 0xffffffffu : 0) << ",\n";
        out << "  \"limiter_bucket_capacity\": "
            << (csrLimiterProgrammed ? 0xffffffffu : 0) << ",\n";
        out << "  \"limiter_backpressure_period\": " << m_limiterBackpressurePeriod << ",\n";
        out << "  \"limiter_backpressure_allow\": " << m_limiterBackpressureAllow << ",\n";
        out << "  \"limiter_fifo_depth\": "
            << (axisBackpressureBypass() ? kAxisBackpressureFifoDepth : 0) << ",\n";
        out << "  \"limiter_fifo_max_occupancy\": " << m_limiterFifoMaxOccupancy << ",\n";
        out << "  \"limiter_input_bytes\": " << m_limiterInputBytes << ",\n";
        out << "  \"limiter_output_bytes\": " << m_limiterOutputBytes << ",\n";
        out << "  \"limiter_input_packets\": " << m_limiterInputPackets << ",\n";
        out << "  \"limiter_output_packets\": " << m_limiterOutputPackets << ",\n";
        out << "  \"limiter_input_first_tick\": " << m_limiterInputFirstTick << ",\n";
        out << "  \"limiter_input_last_tick\": " << m_limiterInputLastTick << ",\n";
        out << "  \"limiter_output_first_tick\": " << m_limiterOutputFirstTick << ",\n";
        out << "  \"limiter_output_last_tick\": " << m_limiterOutputLastTick << ",\n";
        out << "  \"limiter_buffered_bytes\": " << bufferedBytes << ",\n";
        out << "  \"limiter_buffered_packets\": " << bufferedPackets << ",\n";
        out << "  \"ready_valid_observed_cycles\": " << m_ticksObserved << ",\n";
        out << "  \"dma_to_limiter_ready_valid_cycles\": " << m_dmaToLimiterCounters.readyValid << ",\n";
        out << "  \"dma_to_limiter_valid_only_cycles\": " << m_dmaToLimiterCounters.validOnly << ",\n";
        out << "  \"dma_to_limiter_ready_only_cycles\": " << m_dmaToLimiterCounters.readyOnly << ",\n";
        out << "  \"dma_to_limiter_idle_cycles\": " << m_dmaToLimiterCounters.idle << ",\n";
        out << "  \"limiter_to_checker_ready_valid_cycles\": " << m_limiterToCheckerCounters.readyValid << ",\n";
        out << "  \"limiter_to_checker_valid_only_cycles\": " << m_limiterToCheckerCounters.validOnly << ",\n";
        out << "  \"limiter_to_checker_ready_only_cycles\": " << m_limiterToCheckerCounters.readyOnly << ",\n";
        out << "  \"limiter_to_checker_idle_cycles\": " << m_limiterToCheckerCounters.idle << ",\n";
        out << "  \"dma_to_limiter_valid_only_pct\": " << std::fixed << std::setprecision(6)
            << validOnlyPct(m_dmaToLimiterCounters) << ",\n";
        out << "  \"limiter_to_checker_valid_only_pct\": " << std::fixed << std::setprecision(6)
            << validOnlyPct(m_limiterToCheckerCounters) << "\n";
        out << "}\n";
    }

    const char* m_nodeName;
    bool m_ingressPortAssigned = false;
    bool m_egressPortAssigned = false;
    uint32_t m_expectedPackets;
    uint32_t m_resetCycles;
    uint32_t m_dataWidthBits;
    uint32_t m_idWidth;
    uint32_t m_destWidth;
    uint32_t m_userWidth;
    uint32_t m_dataBytes;
    static constexpr uint32_t kAxisBackpressureFifoDepth = 4;

    uint32_t m_resetCountdown;
    uint32_t m_packetsForwarded;
    uint64_t m_activeCycles;
    uint64_t m_ticksObserved;
    bool m_resetComplete;

    bool m_limiterEnabled;
    std::string m_limiterConfigName;
    std::string m_limiterRateSetting;
    std::string m_limiterScope;
    uint32_t m_limiterBackpressurePeriod;
    uint32_t m_limiterBackpressureAllow;
    std::string m_metricsOutputPath;
    mutable bool m_metricsEmitted = false;

    uint64_t m_limiterInputBytes = 0;
    uint64_t m_limiterOutputBytes = 0;
    uint64_t m_limiterInputPackets = 0;
    uint64_t m_limiterOutputPackets = 0;
    Tick m_limiterInputFirstTick = 0;
    Tick m_limiterInputLastTick = 0;
    Tick m_limiterOutputFirstTick = 0;
    Tick m_limiterOutputLastTick = 0;
    bool m_sawLimiterInput = false;
    bool m_sawLimiterOutput = false;
    ReadyValidCounters m_dmaToLimiterCounters;
    ReadyValidCounters m_limiterToCheckerCounters;
    bool m_limiterOutputPacketTracking = false;
    uint32_t m_limiterOutputBytesRemaining = 0;
    std::deque<axisData> m_limiterFifo;
    uint32_t m_limiterFifoMaxOccupancy = 0;

    axisSlaveState m_ingressState;
    axisMasterState m_egressState;
    axisMasterState m_egressPresentedState;
    bool m_egressPresentedGateOpen = false;
    axisMasterState m_ingressInput;
    axisSlaveState m_egressReadyInput;

    std::unique_ptr<RootT> m_dut;
    AxisIngressBinding m_ingressBinding;
    AxisEgressBinding m_egressBinding;
};

} // namespace noc
} // namespace gem5

#endif
