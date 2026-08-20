from m5.params import *
from m5.proxy import *
from m5.objects import NocNode


class _AxisStreamRtlParams(NocNode):
    abstract = True
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(4, "Cycles to hold the RTL model in reset")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    limiter_enabled = Param.Bool(False, "Enable controlled AXIS backpressure for limiter experiments")
    limiter_config_name = Param.String("none", "Human-readable limiter configuration name")
    limiter_rate_setting = Param.String("period1_allow1", "Limiter rate setting label")
    limiter_scope = Param.String("empty_or_not_applicable", "Limiter metric/configuration scope")
    limiter_backpressure_period = Param.UInt32(1, "Controlled AXIS backpressure period")
    limiter_backpressure_allow = Param.UInt32(1, "Ready/valid slots allowed per backpressure period")


class PacketRateLimiterRtlNode(_AxisStreamRtlParams):
    type = "PacketRateLimiterRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketRateLimiterRtlNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(4, "Cycles to hold the RTL model in reset")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    limiter_enabled = Param.Bool(False, "Enable controlled AXIS backpressure for limiter experiments")
    limiter_config_name = Param.String("none", "Human-readable limiter configuration name")
    limiter_rate_setting = Param.String("period1_allow1", "Limiter rate setting label")
    limiter_scope = Param.String("empty_or_not_applicable", "Limiter metric/configuration scope")
    limiter_backpressure_period = Param.UInt32(1, "Controlled AXIS backpressure period")
    limiter_backpressure_allow = Param.UInt32(1, "Ready/valid slots allowed per backpressure period")


class PacketRateLimiterThrottleRtlNode(_AxisStreamRtlParams):
    type = "PacketRateLimiterThrottleRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketRateLimiterThrottleRtlNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(4, "Cycles to hold the RTL model in reset")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    limiter_enabled = Param.Bool(False, "Enable controlled AXIS backpressure for limiter experiments")
    limiter_config_name = Param.String("none", "Human-readable limiter configuration name")
    limiter_rate_setting = Param.String("period1_allow1", "Limiter rate setting label")
    limiter_scope = Param.String("empty_or_not_applicable", "Limiter metric/configuration scope")
    limiter_backpressure_period = Param.UInt32(1, "Controlled AXIS backpressure period")
    limiter_backpressure_allow = Param.UInt32(1, "Ready/valid slots allowed per backpressure period")


class TelemetryRtlNode(_AxisStreamRtlParams):
    type = "TelemetryRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::TelemetryRtlNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(4, "Cycles to hold the RTL model in reset")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    limiter_enabled = Param.Bool(False, "Enable controlled AXIS backpressure for limiter experiments")
    limiter_config_name = Param.String("none", "Human-readable limiter configuration name")
    limiter_rate_setting = Param.String("period1_allow1", "Limiter rate setting label")
    limiter_scope = Param.String("empty_or_not_applicable", "Limiter metric/configuration scope")
    limiter_backpressure_period = Param.UInt32(1, "Controlled AXIS backpressure period")
    limiter_backpressure_allow = Param.UInt32(1, "Ready/valid slots allowed per backpressure period")


class ChecksumRtlNode(_AxisStreamRtlParams):
    type = "ChecksumRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::ChecksumRtlNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(4, "Cycles to hold the RTL model in reset")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    limiter_enabled = Param.Bool(False, "Enable controlled AXIS backpressure for limiter experiments")
    limiter_config_name = Param.String("none", "Human-readable limiter configuration name")
    limiter_rate_setting = Param.String("period1_allow1", "Limiter rate setting label")
    limiter_scope = Param.String("empty_or_not_applicable", "Limiter metric/configuration scope")
    limiter_backpressure_period = Param.UInt32(1, "Controlled AXIS backpressure period")
    limiter_backpressure_allow = Param.UInt32(1, "Ready/valid slots allowed per backpressure period")


class SegmentationOffloadRtlNode(_AxisStreamRtlParams):
    type = "SegmentationOffloadRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::SegmentationOffloadRtlNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(4, "Cycles to hold the RTL model in reset")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    limiter_enabled = Param.Bool(False, "Enable controlled AXIS backpressure for limiter experiments")
    limiter_config_name = Param.String("none", "Human-readable limiter configuration name")
    limiter_rate_setting = Param.String("period1_allow1", "Limiter rate setting label")
    limiter_scope = Param.String("empty_or_not_applicable", "Limiter metric/configuration scope")
    limiter_backpressure_period = Param.UInt32(1, "Controlled AXIS backpressure period")
    limiter_backpressure_allow = Param.UInt32(1, "Ready/valid slots allowed per backpressure period")


class OverloadedNatRtlNode(_AxisStreamRtlParams):
    type = "OverloadedNatRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::OverloadedNatRtlNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(4, "Cycles to hold the RTL model in reset")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    limiter_enabled = Param.Bool(False, "Enable controlled AXIS backpressure for limiter experiments")
    limiter_config_name = Param.String("none", "Human-readable limiter configuration name")
    limiter_rate_setting = Param.String("period1_allow1", "Limiter rate setting label")
    limiter_scope = Param.String("empty_or_not_applicable", "Limiter metric/configuration scope")
    limiter_backpressure_period = Param.UInt32(1, "Controlled AXIS backpressure period")
    limiter_backpressure_allow = Param.UInt32(1, "Ready/valid slots allowed per backpressure period")


class _PacketProcessingEngineParams(NocNode):
    abstract = True
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngineBaseNoneRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngineBaseNoneRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngineBaseNoneRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngineBaseTelemetryRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngineBaseTelemetryRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngineBaseTelemetryRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngineBaseSegmentationRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngineBaseSegmentationRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngineBaseSegmentationRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngineBaseChecksumRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngineBaseChecksumRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngineBaseChecksumRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngineBaseNatRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngineBaseNatRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngineBaseNatRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngineBaseFlowPrefixRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngineBaseFlowPrefixRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngineBaseFlowPrefixRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngineBaseFiveTupleHashRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngineBaseFiveTupleHashRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngineBaseFiveTupleHashRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngine2xNoneRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngine2xNoneRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngine2xNoneRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngine2xTelemetryRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngine2xTelemetryRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngine2xTelemetryRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngine2xSegmentationRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngine2xSegmentationRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngine2xSegmentationRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngine2xChecksumRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngine2xChecksumRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngine2xChecksumRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngine2xNatRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngine2xNatRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngine2xNatRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngine2xFlowPrefixRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngine2xFlowPrefixRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngine2xFlowPrefixRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")


class PacketProcessingEngine2xFiveTupleHashRtlNode(_PacketProcessingEngineParams):
    type = "PacketProcessingEngine2xFiveTupleHashRtlNode"
    cxx_header = "noc/endpoints/rtl/SmartNicRtlNodes.hh"
    cxx_class = "gem5::noc::PacketProcessingEngine2xFiveTupleHashRtlNode"
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(16, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "How many TLAST packets should drain")
    reset_cycles = Param.UInt32(8, "Cycles to hold the RTL model in reset")
