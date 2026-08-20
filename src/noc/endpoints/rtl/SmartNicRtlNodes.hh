#ifndef __SMARTNIC_RTL_NODES_HH__
#define __SMARTNIC_RTL_NODES_HH__

#include "checksum_wrapper.h"
#include "noc/endpoints/rtl/AxisRtlStreamControlNode.hh"
#include "noc/endpoints/rtl/AxisRtlStreamNode2x.hh"
#include "noc/endpoints/rtl/AxisRtlStreamNode.hh"
#include "noc/endpoints/rtl/SmartNicRtlTraits.hh"
#include "overloaded_nat_wrapper.h"
#include "packet_rate_limiter_wrapper.h"
#include "params/PacketProcessingEngine2xChecksumRtlNode.hh"
#include "params/PacketProcessingEngine2xFiveTupleHashRtlNode.hh"
#include "params/PacketProcessingEngine2xFlowPrefixRtlNode.hh"
#include "params/PacketProcessingEngine2xNatRtlNode.hh"
#include "params/PacketProcessingEngine2xNoneRtlNode.hh"
#include "params/PacketProcessingEngine2xSegmentationRtlNode.hh"
#include "params/PacketProcessingEngine2xTelemetryRtlNode.hh"
#include "params/PacketProcessingEngineBaseChecksumRtlNode.hh"
#include "params/PacketProcessingEngineBaseFiveTupleHashRtlNode.hh"
#include "params/PacketProcessingEngineBaseFlowPrefixRtlNode.hh"
#include "params/PacketProcessingEngineBaseNatRtlNode.hh"
#include "params/PacketProcessingEngineBaseNoneRtlNode.hh"
#include "params/PacketProcessingEngineBaseSegmentationRtlNode.hh"
#include "params/PacketProcessingEngineBaseTelemetryRtlNode.hh"
#include "params/ChecksumRtlNode.hh"
#include "params/OverloadedNatRtlNode.hh"
#include "params/PacketRateLimiterRtlNode.hh"
#include "params/PacketRateLimiterThrottleRtlNode.hh"
#include "params/SegmentationOffloadRtlNode.hh"
#include "params/TelemetryRtlNode.hh"
#include "ppe_2x_checksum_wrapper.h"
#include "ppe_2x_five_tuple_hash_wrapper.h"
#include "ppe_2x_flow_prefix_wrapper.h"
#include "ppe_2x_nat_wrapper.h"
#include "ppe_2x_none_wrapper.h"
#include "ppe_2x_segmentation_wrapper.h"
#include "ppe_2x_telemetry_wrapper.h"
#include "ppe_base_checksum_wrapper.h"
#include "ppe_base_five_tuple_hash_wrapper.h"
#include "ppe_base_flow_prefix_wrapper.h"
#include "ppe_base_nat_wrapper.h"
#include "ppe_base_none_wrapper.h"
#include "ppe_base_segmentation_wrapper.h"
#include "ppe_base_telemetry_wrapper.h"
#include "segmentation_offload_wrapper.h"
#include "telemetry_wrapper.h"

namespace gem5
{
namespace noc
{

using PacketRateLimiterWrapperTraits = SmartNicFlatAxisWrapperTraits<
    packet_rate_limiter_wrapper,
    AxilAximmIdleInputs<packet_rate_limiter_wrapper>>;
using PacketRateLimiterThrottleWrapperTraits = SmartNicFlatAxisWrapperTraits<
    packet_rate_limiter_wrapper,
    PacketRateLimiterThrottleInputs<packet_rate_limiter_wrapper>>;
using TelemetryWrapperTraits = SmartNicFlatAxisWrapperTraits<
    telemetry_wrapper,
    AxilIdleInputs<telemetry_wrapper>>;
using ChecksumWrapperTraits = SmartNicFlatAxisWrapperTraits<
    checksum_wrapper,
    NoSideInputs<checksum_wrapper>>;
using SegmentationOffloadWrapperTraits = SmartNicFlatAxisWrapperTraits<
    segmentation_offload_wrapper,
    AxilIdleInputs<segmentation_offload_wrapper>>;
using OverloadedNatWrapperTraits = SmartNicFlatAxisWrapperTraits<
    overloaded_nat_wrapper,
    OverloadedNatInitInputs<overloaded_nat_wrapper>>;

using PpeBaseNoneWrapperTraits = SmartNicFlatAxisWrapperTraits<
    ppe_base_none_wrapper, AxilIdleInputs<ppe_base_none_wrapper>>;
using PpeBaseTelemetryWrapperTraits = SmartNicFlatAxisWrapperTraits<
    ppe_base_telemetry_wrapper, AxilIdleInputs<ppe_base_telemetry_wrapper>>;
using PpeBaseSegmentationWrapperTraits = SmartNicFlatAxisWrapperTraits<
    ppe_base_segmentation_wrapper, AxilIdleInputs<ppe_base_segmentation_wrapper>>;
using PpeBaseChecksumWrapperTraits = SmartNicFlatAxisWrapperTraits<
    ppe_base_checksum_wrapper, AxilIdleInputs<ppe_base_checksum_wrapper>>;
using PpeBaseNatWrapperTraits = SmartNicFlatAxisWrapperTraits<
    ppe_base_nat_wrapper, OverloadedNatInitInputs<ppe_base_nat_wrapper>>;
using PpeBaseFlowPrefixWrapperTraits = SmartNicFlatAxisWrapperTraits<
    ppe_base_flow_prefix_wrapper, PpeSteeringFlowPrefixInputs<ppe_base_flow_prefix_wrapper>>;
using PpeBaseFiveTupleHashWrapperTraits = SmartNicFlatAxisWrapperTraits<
    ppe_base_five_tuple_hash_wrapper, PpeSteeringHashInputs<ppe_base_five_tuple_hash_wrapper>>;

using Ppe2xNoneWrapperTraits = SmartNicFlatAxis2xWrapperTraits<
    ppe_2x_none_wrapper, AxilIdleInputs<ppe_2x_none_wrapper>>;
using Ppe2xTelemetryWrapperTraits = SmartNicFlatAxis2xWrapperTraits<
    ppe_2x_telemetry_wrapper, AxilIdleInputs<ppe_2x_telemetry_wrapper>>;
using Ppe2xSegmentationWrapperTraits = SmartNicFlatAxis2xWrapperTraits<
    ppe_2x_segmentation_wrapper, AxilIdleInputs<ppe_2x_segmentation_wrapper>>;
using Ppe2xChecksumWrapperTraits = SmartNicFlatAxis2xWrapperTraits<
    ppe_2x_checksum_wrapper, AxilIdleInputs<ppe_2x_checksum_wrapper>>;
using Ppe2xNatWrapperTraits = SmartNicFlatAxis2xWrapperTraits<
    ppe_2x_nat_wrapper, OverloadedNatInitInputs<ppe_2x_nat_wrapper>>;
using Ppe2xFlowPrefixWrapperTraits = SmartNicFlatAxis2xWrapperTraits<
    ppe_2x_flow_prefix_wrapper, PpeSteeringFlowPrefixInputs<ppe_2x_flow_prefix_wrapper>>;
using Ppe2xFiveTupleHashWrapperTraits = SmartNicFlatAxis2xWrapperTraits<
    ppe_2x_five_tuple_hash_wrapper, PpeSteeringHashInputs<ppe_2x_five_tuple_hash_wrapper>>;

class PacketRateLimiterRtlNode : public AxisRtlStreamNode<
    packet_rate_limiter_wrapper,
    PacketRateLimiterRtlNodeParams,
    PacketRateLimiterWrapperTraits,
    16>
{
  public:
    typedef PacketRateLimiterRtlNodeParams Params;
    explicit PacketRateLimiterRtlNode(const Params &p);
    ~PacketRateLimiterRtlNode() override;
};

class PacketRateLimiterThrottleRtlNode : public AxisRtlStreamNode<
    packet_rate_limiter_wrapper,
    PacketRateLimiterThrottleRtlNodeParams,
    PacketRateLimiterThrottleWrapperTraits,
    16>
{
  public:
    typedef PacketRateLimiterThrottleRtlNodeParams Params;
    explicit PacketRateLimiterThrottleRtlNode(const Params &p);
    ~PacketRateLimiterThrottleRtlNode() override;
};

class TelemetryRtlNode : public AxisRtlStreamNode<
    telemetry_wrapper,
    TelemetryRtlNodeParams,
    TelemetryWrapperTraits,
    16>
{
  public:
    typedef TelemetryRtlNodeParams Params;
    explicit TelemetryRtlNode(const Params &p);
    ~TelemetryRtlNode() override;
};

class ChecksumRtlNode : public AxisRtlStreamNode<
    checksum_wrapper,
    ChecksumRtlNodeParams,
    ChecksumWrapperTraits,
    16>
{
  public:
    typedef ChecksumRtlNodeParams Params;
    explicit ChecksumRtlNode(const Params &p);
    ~ChecksumRtlNode() override;
};

class SegmentationOffloadRtlNode : public AxisRtlStreamNode<
    segmentation_offload_wrapper,
    SegmentationOffloadRtlNodeParams,
    SegmentationOffloadWrapperTraits,
    16>
{
  public:
    typedef SegmentationOffloadRtlNodeParams Params;
    explicit SegmentationOffloadRtlNode(const Params &p);
    ~SegmentationOffloadRtlNode() override;
};

class OverloadedNatRtlNode : public AxisRtlStreamNode<
    overloaded_nat_wrapper,
    OverloadedNatRtlNodeParams,
    OverloadedNatWrapperTraits,
    16>
{
  public:
    typedef OverloadedNatRtlNodeParams Params;
    explicit OverloadedNatRtlNode(const Params &p);
    ~OverloadedNatRtlNode() override;
};

#define DECL_PPE_BASE_NODE(ClassName, WrapperT, ParamsT, TraitsT) \
class ClassName : public AxisRtlStreamNode<WrapperT, ParamsT, TraitsT, 16> \
{ \
  public: \
    typedef ParamsT Params; \
    explicit ClassName(const Params &p); \
    ~ClassName() override; \
};

DECL_PPE_BASE_NODE(PacketProcessingEngineBaseNoneRtlNode,
    ppe_base_none_wrapper, PacketProcessingEngineBaseNoneRtlNodeParams,
    PpeBaseNoneWrapperTraits)
DECL_PPE_BASE_NODE(PacketProcessingEngineBaseTelemetryRtlNode,
    ppe_base_telemetry_wrapper, PacketProcessingEngineBaseTelemetryRtlNodeParams,
    PpeBaseTelemetryWrapperTraits)
DECL_PPE_BASE_NODE(PacketProcessingEngineBaseSegmentationRtlNode,
    ppe_base_segmentation_wrapper, PacketProcessingEngineBaseSegmentationRtlNodeParams,
    PpeBaseSegmentationWrapperTraits)
DECL_PPE_BASE_NODE(PacketProcessingEngineBaseChecksumRtlNode,
    ppe_base_checksum_wrapper, PacketProcessingEngineBaseChecksumRtlNodeParams,
    PpeBaseChecksumWrapperTraits)
DECL_PPE_BASE_NODE(PacketProcessingEngineBaseNatRtlNode,
    ppe_base_nat_wrapper, PacketProcessingEngineBaseNatRtlNodeParams,
    PpeBaseNatWrapperTraits)

#undef DECL_PPE_BASE_NODE

class PacketProcessingEngineBaseFlowPrefixRtlNode : public AxisRtlStreamControlNode<
    ppe_base_flow_prefix_wrapper,
    PacketProcessingEngineBaseFlowPrefixRtlNodeParams,
    PpeBaseFlowPrefixWrapperTraits,
    16>
{
  public:
    typedef PacketProcessingEngineBaseFlowPrefixRtlNodeParams Params;
    explicit PacketProcessingEngineBaseFlowPrefixRtlNode(const Params &p);
    ~PacketProcessingEngineBaseFlowPrefixRtlNode() override;
};

class PacketProcessingEngineBaseFiveTupleHashRtlNode : public AxisRtlStreamControlNode<
    ppe_base_five_tuple_hash_wrapper,
    PacketProcessingEngineBaseFiveTupleHashRtlNodeParams,
    PpeBaseFiveTupleHashWrapperTraits,
    16>
{
  public:
    typedef PacketProcessingEngineBaseFiveTupleHashRtlNodeParams Params;
    explicit PacketProcessingEngineBaseFiveTupleHashRtlNode(const Params &p);
    ~PacketProcessingEngineBaseFiveTupleHashRtlNode() override;
};

#define DECL_PPE_2X_NODE(ClassName, WrapperT, ParamsT, TraitsT) \
class ClassName : public AxisRtlStreamNode2x<WrapperT, ParamsT, TraitsT, 16> \
{ \
  public: \
    typedef ParamsT Params; \
    explicit ClassName(const Params &p); \
    ~ClassName() override; \
};

DECL_PPE_2X_NODE(PacketProcessingEngine2xNoneRtlNode,
    ppe_2x_none_wrapper, PacketProcessingEngine2xNoneRtlNodeParams,
    Ppe2xNoneWrapperTraits)
DECL_PPE_2X_NODE(PacketProcessingEngine2xTelemetryRtlNode,
    ppe_2x_telemetry_wrapper, PacketProcessingEngine2xTelemetryRtlNodeParams,
    Ppe2xTelemetryWrapperTraits)
DECL_PPE_2X_NODE(PacketProcessingEngine2xSegmentationRtlNode,
    ppe_2x_segmentation_wrapper, PacketProcessingEngine2xSegmentationRtlNodeParams,
    Ppe2xSegmentationWrapperTraits)
DECL_PPE_2X_NODE(PacketProcessingEngine2xChecksumRtlNode,
    ppe_2x_checksum_wrapper, PacketProcessingEngine2xChecksumRtlNodeParams,
    Ppe2xChecksumWrapperTraits)
DECL_PPE_2X_NODE(PacketProcessingEngine2xNatRtlNode,
    ppe_2x_nat_wrapper, PacketProcessingEngine2xNatRtlNodeParams,
    Ppe2xNatWrapperTraits)
DECL_PPE_2X_NODE(PacketProcessingEngine2xFlowPrefixRtlNode,
    ppe_2x_flow_prefix_wrapper, PacketProcessingEngine2xFlowPrefixRtlNodeParams,
    Ppe2xFlowPrefixWrapperTraits)
DECL_PPE_2X_NODE(PacketProcessingEngine2xFiveTupleHashRtlNode,
    ppe_2x_five_tuple_hash_wrapper, PacketProcessingEngine2xFiveTupleHashRtlNodeParams,
    Ppe2xFiveTupleHashWrapperTraits)

#undef DECL_PPE_2X_NODE

} // namespace noc
} // namespace gem5

#endif
