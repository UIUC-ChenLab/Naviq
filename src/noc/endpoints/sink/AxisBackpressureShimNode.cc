#include "noc/endpoints/sink/AxisBackpressureShimNode.hh"

#include <algorithm>
#include <fstream>
#include <iomanip>

#include "base/logging.hh"
#include "sim/cur_tick.hh"

namespace gem5
{
namespace noc
{

AxisBackpressureShimNode::AxisBackpressureShimNode(const Params &p)
    : NocNode(p),
      m_expectedPackets(p.expected_packets),
      m_dataWidthBits(p.data_width),
      m_idWidth(p.id_width),
      m_destWidth(p.dest_width),
      m_fifoDepth(std::max<uint32_t>(1, p.fifo_depth)),
      m_backpressureEnabled(p.backpressure_enabled),
      m_backpressureConfigName(p.backpressure_config_name),
      m_backpressurePeriod(std::max<uint32_t>(1, p.backpressure_period)),
      m_backpressureAllow(std::min<uint32_t>(
          std::max<uint32_t>(1, p.backpressure_period),
          p.backpressure_allow)),
      m_backpressureScope(p.backpressure_scope),
      m_metricsOutputPath(p.metrics_output_path),
      m_currentSlaveState(),
      m_currentMasterState(m_dataWidthBits, m_idWidth, m_destWidth),
      m_masterIn(m_dataWidthBits, m_idWidth, m_destWidth),
      m_slaveIn(),
      m_inputStability(m_dataWidthBits, m_idWidth, m_destWidth),
      m_outputStability(m_dataWidthBits, m_idWidth, m_destWidth)
{
    maxPorts = 2;
    m_currentSlaveState.tready = true;
    m_currentMasterState.data.tvalid = false;
}

AxisBackpressureShimNode::~AxisBackpressureShimNode()
{
    emitMetricsFragment();
}

void
AxisBackpressureShimNode::update(int portID, State* inputNocInterfaceState)
{
    if (portID == 0) {
        auto* axisMaster = dynamic_cast<axisMasterState*>(inputNocInterfaceState);
        if (!axisMaster) {
            panic("AxisBackpressureShimNode::update expected axisMasterState on port 0");
        }
        m_masterIn = *axisMaster;
        return;
    }

    if (portID == 1) {
        auto* axisSlave = dynamic_cast<axisSlaveState*>(inputNocInterfaceState);
        if (!axisSlave) {
            panic("AxisBackpressureShimNode::update expected axisSlaveState on port 1");
        }
        m_slaveIn = *axisSlave;
        return;
    }

    panic("AxisBackpressureShimNode::update invalid portID %d", portID);
}

State*
AxisBackpressureShimNode::getCurrentState(int portID)
{
    if (portID == 0) {
        return &m_currentSlaveState;
    }
    if (portID == 1) {
        return &m_currentMasterState;
    }
    panic("AxisBackpressureShimNode::getCurrentState invalid portID %d", portID);
    return nullptr;
}

int
AxisBackpressureShimNode::assignPort(const std::string &endpointName)
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
    panic("AxisBackpressureShimNode::assignPort invalid endpointName: %s",
          endpointName.c_str());
    return -1;
}

bool
AxisBackpressureShimNode::patternReady() const
{
    if (!m_backpressureEnabled || m_backpressurePeriod <= 1) {
        return true;
    }
    return (m_activeCycles % m_backpressurePeriod) < m_backpressureAllow;
}

bool
AxisBackpressureShimNode::validGatedBackpressure() const
{
    return m_backpressureScope == "dma_fed_axis_valid_gated_backpressure_v1";
}

bool
AxisBackpressureShimNode::inputPatternReady() const
{
    if (!m_backpressureEnabled || m_backpressurePeriod <= 1) {
        return true;
    }
    if (validGatedBackpressure()) {
        return m_validGatedPhase < m_backpressureAllow;
    }
    return patternReady();
}

void
AxisBackpressureShimNode::advanceInputPattern(bool inputValid)
{
    if (!validGatedBackpressure() || !m_backpressureEnabled ||
        m_backpressurePeriod <= 1 || !inputValid) {
        return;
    }
    m_validGatedPhase = (m_validGatedPhase + 1) % m_backpressurePeriod;
}

bool
AxisBackpressureShimNode::tick(int clockDomain)
{
    if (!clockDomains.empty() && clockDomain != clockDomains[0]) {
        return false;
    }

    const bool outputValid = m_currentMasterState.data.tvalid;
    const bool outputReady = m_slaveIn.tready;
    const bool inputValid = m_masterIn.data.tvalid;
    const bool inputReady = m_currentSlaveState.tready;

    checkStability(m_inputStability, inputValid, inputReady,
                   m_masterIn.data, "dma_to_shim");
    checkStability(m_outputStability, outputValid, outputReady,
                   m_currentMasterState.data, "shim_to_checker");

    recordReadyValid(m_dmaToShimCounters, inputValid, inputReady);
    recordReadyValid(m_shimToCheckerCounters, outputValid, outputReady);

    const bool handshakeOut = outputValid && outputReady;
    const bool handshakeIn = inputValid && inputReady;

    if (handshakeOut) {
        ++m_shimToCheckerAcceptedBeats;
        recordOutputBeat(m_currentMasterState.data);
        if (m_currentMasterState.data.tlast) {
            ++m_outputPacketsSeen;
        }
        m_currentMasterState.data.tvalid = false;
        if (!m_fifo.empty()) {
            m_fifo.pop_front();
        }
    }

    if (handshakeIn) {
        ++m_dmaToShimAcceptedBeats;
        recordInputBeat(m_masterIn.data);
        if (m_fifo.size() >= m_fifoDepth) {
            panic("AxisBackpressureShimNode: accepted beat while FIFO full");
        }
        axisData beat = m_masterIn.data;
        beat.tvalid = true;
        m_fifo.push_back(beat);
        m_fifoMaxOccupancy = std::max<uint32_t>(
            m_fifoMaxOccupancy, static_cast<uint32_t>(m_fifo.size()));
    }

    if (!m_currentMasterState.data.tvalid && !m_fifo.empty()) {
        m_currentMasterState.data = m_fifo.front();
        m_currentMasterState.data.tvalid = true;
    }

    advanceInputPattern(inputValid);
    m_currentSlaveState.tready =
        inputPatternReady() && static_cast<uint32_t>(m_fifo.size()) < m_fifoDepth;

    ++m_activeCycles;
    return true;
}

bool
AxisBackpressureShimNode::done()
{
    const bool isDone = m_expectedPackets > 0 &&
        m_outputPacketsSeen >= m_expectedPackets &&
        m_fifo.empty() &&
        !m_currentMasterState.data.tvalid;
    if (isDone) {
        emitMetricsFragment();
    }
    return isDone;
}

void
AxisBackpressureShimNode::recordReadyValid(ReadyValidCounters& counters,
                                           bool valid, bool ready)
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

double
AxisBackpressureShimNode::validOnlyPct(const ReadyValidCounters& counters)
{
    const uint64_t total = counters.readyValid + counters.validOnly +
        counters.readyOnly + counters.idle;
    if (total == 0) {
        return 0.0;
    }
    return (100.0 * static_cast<double>(counters.validOnly)) /
        static_cast<double>(total);
}

bool
AxisBackpressureShimNode::axisEqual(const axisData& lhs, const axisData& rhs,
                                    std::string& signal) const
{
    if (lhs.tvalid != rhs.tvalid) {
        signal = "tvalid";
        return false;
    }
    if (lhs.tdata != rhs.tdata) {
        signal = "tdata";
        return false;
    }
    if (lhs.tkeep != rhs.tkeep) {
        signal = "tkeep";
        return false;
    }
    if (lhs.tlast != rhs.tlast) {
        signal = "tlast";
        return false;
    }
    if (lhs.tuser != rhs.tuser) {
        signal = "tuser";
        return false;
    }
    if (lhs.tid != rhs.tid) {
        signal = "tid";
        return false;
    }
    if (lhs.tdest != rhs.tdest) {
        signal = "tdest";
        return false;
    }
    return true;
}

void
AxisBackpressureShimNode::checkStability(StabilityTracker& tracker,
                                         bool valid, bool ready,
                                         const axisData& beat,
                                         const std::string& side)
{
    if (m_axisStabilityViolation) {
        return;
    }

    if (tracker.stalled) {
        if (!valid) {
            m_axisStabilityViolation = true;
            m_axisStabilityViolationTick = curTick();
            m_axisStabilityViolationSignal = "tvalid";
            m_axisStabilityViolationSide = side;
            return;
        }
        std::string signal;
        if (!axisEqual(beat, tracker.beat, signal)) {
            m_axisStabilityViolation = true;
            m_axisStabilityViolationTick = curTick();
            m_axisStabilityViolationSignal = signal;
            m_axisStabilityViolationSide = side;
            return;
        }
        if (ready) {
            tracker.stalled = false;
        }
        return;
    }

    if (valid && !ready) {
        tracker.beat = beat;
        tracker.stalled = true;
    }
}

void
AxisBackpressureShimNode::recordInputBeat(const axisData& beat)
{
    const Tick now = curTick();
    if (!m_sawInput) {
        m_inputFirstTick = now;
        m_sawInput = true;
    }
    m_inputLastTick = now;
    m_inputBytes += beat.getTotalByteSize();
    if (beat.tlast) {
        ++m_inputPackets;
        ++m_inputTlastCount;
    }
}

void
AxisBackpressureShimNode::recordOutputBeat(const axisData& beat)
{
    const Tick now = curTick();
    if (!m_sawOutput) {
        m_outputFirstTick = now;
        m_sawOutput = true;
    }
    m_outputLastTick = now;
    m_outputBytes += beat.getTotalByteSize();
    if (beat.tlast) {
        ++m_outputPackets;
        ++m_outputTlastCount;
    }
}

void
AxisBackpressureShimNode::writeJsonString(std::ofstream& out,
                                          const std::string& text)
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

void
AxisBackpressureShimNode::emitMetricsFragment() const
{
    if (m_metricsOutputPath.empty() || m_metricsEmitted) {
        return;
    }
    m_metricsEmitted = true;
    std::ofstream out(m_metricsOutputPath, std::ios::trunc);
    if (!out.is_open()) {
        warn("AxisBackpressureShimNode could not open metrics fragment %s",
             m_metricsOutputPath.c_str());
        return;
    }

    out << "{\n";
    out << "  \"type\": \"axis_backpressure_shim\",\n";
    out << "  \"backpressure_enabled\": "
        << (m_backpressureEnabled ? "true" : "false") << ",\n";
    out << "  \"backpressure_config_name\": ";
    writeJsonString(out, m_backpressureConfigName);
    out << ",\n";
    out << "  \"backpressure_period\": " << m_backpressurePeriod << ",\n";
    out << "  \"backpressure_allow\": " << m_backpressureAllow << ",\n";
    out << "  \"backpressure_scope\": ";
    writeJsonString(out, m_backpressureScope);
    out << ",\n";
    out << "  \"axis_stability_violation\": "
        << (m_axisStabilityViolation ? "true" : "false") << ",\n";
    out << "  \"axis_stability_violation_tick\": "
        << m_axisStabilityViolationTick << ",\n";
    out << "  \"axis_stability_violation_signal\": ";
    writeJsonString(out, m_axisStabilityViolationSignal);
    out << ",\n";
    out << "  \"axis_stability_violation_side\": ";
    writeJsonString(out, m_axisStabilityViolationSide);
    out << ",\n";
    out << "  \"dma_to_shim_ready_valid_cycles\": "
        << m_dmaToShimCounters.readyValid << ",\n";
    out << "  \"dma_to_shim_valid_only_cycles\": "
        << m_dmaToShimCounters.validOnly << ",\n";
    out << "  \"dma_to_shim_ready_only_cycles\": "
        << m_dmaToShimCounters.readyOnly << ",\n";
    out << "  \"dma_to_shim_idle_cycles\": "
        << m_dmaToShimCounters.idle << ",\n";
    out << "  \"dma_to_shim_valid_only_pct\": " << std::fixed
        << std::setprecision(6) << validOnlyPct(m_dmaToShimCounters) << ",\n";
    out << "  \"shim_to_checker_ready_valid_cycles\": "
        << m_shimToCheckerCounters.readyValid << ",\n";
    out << "  \"shim_to_checker_valid_only_cycles\": "
        << m_shimToCheckerCounters.validOnly << ",\n";
    out << "  \"shim_to_checker_ready_only_cycles\": "
        << m_shimToCheckerCounters.readyOnly << ",\n";
    out << "  \"shim_to_checker_idle_cycles\": "
        << m_shimToCheckerCounters.idle << ",\n";
    out << "  \"shim_to_checker_valid_only_pct\": " << std::fixed
        << std::setprecision(6) << validOnlyPct(m_shimToCheckerCounters) << ",\n";
    out << "  \"dma_to_shim_accepted_beats\": "
        << m_dmaToShimAcceptedBeats << ",\n";
    out << "  \"shim_to_checker_accepted_beats\": "
        << m_shimToCheckerAcceptedBeats << ",\n";
    out << "  \"shim_input_bytes\": " << m_inputBytes << ",\n";
    out << "  \"shim_output_bytes\": " << m_outputBytes << ",\n";
    out << "  \"shim_input_packets\": " << m_inputPackets << ",\n";
    out << "  \"shim_output_packets\": " << m_outputPackets << ",\n";
    out << "  \"shim_input_tlast_count\": " << m_inputTlastCount << ",\n";
    out << "  \"shim_output_tlast_count\": " << m_outputTlastCount << ",\n";
    out << "  \"shim_input_first_tick\": " << m_inputFirstTick << ",\n";
    out << "  \"shim_input_last_tick\": " << m_inputLastTick << ",\n";
    out << "  \"shim_output_first_tick\": " << m_outputFirstTick << ",\n";
    out << "  \"shim_output_last_tick\": " << m_outputLastTick << ",\n";
    out << "  \"shim_fifo_depth\": " << m_fifoDepth << ",\n";
    out << "  \"shim_fifo_max_occupancy\": " << m_fifoMaxOccupancy << "\n";
    out << "}\n";
}

} // namespace noc
} // namespace gem5
