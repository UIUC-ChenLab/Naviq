#include "noc/endpoints/rtl/SmartNicRtlNodes.hh"

namespace gem5
{
namespace noc
{

PacketRateLimiterRtlNode::PacketRateLimiterRtlNode(const Params &p)
    : AxisRtlStreamNode(p, "PacketRateLimiterRtlNode")
{
}

PacketRateLimiterRtlNode::~PacketRateLimiterRtlNode() = default;

PacketRateLimiterThrottleRtlNode::PacketRateLimiterThrottleRtlNode(const Params &p)
    : AxisRtlStreamNode(p, "PacketRateLimiterThrottleRtlNode")
{
}

PacketRateLimiterThrottleRtlNode::~PacketRateLimiterThrottleRtlNode() = default;

TelemetryRtlNode::TelemetryRtlNode(const Params &p)
    : AxisRtlStreamNode(p, "TelemetryRtlNode")
{
}

TelemetryRtlNode::~TelemetryRtlNode() = default;

ChecksumRtlNode::ChecksumRtlNode(const Params &p)
    : AxisRtlStreamNode(p, "ChecksumRtlNode")
{
}

ChecksumRtlNode::~ChecksumRtlNode() = default;

SegmentationOffloadRtlNode::SegmentationOffloadRtlNode(const Params &p)
    : AxisRtlStreamNode(p, "SegmentationOffloadRtlNode")
{
}

SegmentationOffloadRtlNode::~SegmentationOffloadRtlNode() = default;

OverloadedNatRtlNode::OverloadedNatRtlNode(const Params &p)
    : AxisRtlStreamNode(p, "OverloadedNatRtlNode")
{
}

OverloadedNatRtlNode::~OverloadedNatRtlNode() = default;

#define DEFINE_PPE_BASE_NODE(ClassName) \
ClassName::ClassName(const Params &p) \
    : AxisRtlStreamNode(p, #ClassName) \
{ \
} \
ClassName::~ClassName() = default;

DEFINE_PPE_BASE_NODE(PacketProcessingEngineBaseNoneRtlNode)
DEFINE_PPE_BASE_NODE(PacketProcessingEngineBaseTelemetryRtlNode)
DEFINE_PPE_BASE_NODE(PacketProcessingEngineBaseSegmentationRtlNode)
DEFINE_PPE_BASE_NODE(PacketProcessingEngineBaseChecksumRtlNode)
DEFINE_PPE_BASE_NODE(PacketProcessingEngineBaseNatRtlNode)

#undef DEFINE_PPE_BASE_NODE

PacketProcessingEngineBaseFlowPrefixRtlNode::PacketProcessingEngineBaseFlowPrefixRtlNode(
    const Params &p)
    : AxisRtlStreamControlNode(p, "PacketProcessingEngineBaseFlowPrefixRtlNode")
{
}

PacketProcessingEngineBaseFlowPrefixRtlNode::~PacketProcessingEngineBaseFlowPrefixRtlNode() =
    default;

PacketProcessingEngineBaseFiveTupleHashRtlNode::PacketProcessingEngineBaseFiveTupleHashRtlNode(
    const Params &p)
    : AxisRtlStreamControlNode(p, "PacketProcessingEngineBaseFiveTupleHashRtlNode")
{
}

PacketProcessingEngineBaseFiveTupleHashRtlNode::
    ~PacketProcessingEngineBaseFiveTupleHashRtlNode() = default;

#define DEFINE_PPE_2X_NODE(ClassName) \
ClassName::ClassName(const Params &p) \
    : AxisRtlStreamNode2x(p, #ClassName) \
{ \
} \
ClassName::~ClassName() = default;

DEFINE_PPE_2X_NODE(PacketProcessingEngine2xNoneRtlNode)
DEFINE_PPE_2X_NODE(PacketProcessingEngine2xTelemetryRtlNode)
DEFINE_PPE_2X_NODE(PacketProcessingEngine2xSegmentationRtlNode)
DEFINE_PPE_2X_NODE(PacketProcessingEngine2xChecksumRtlNode)
DEFINE_PPE_2X_NODE(PacketProcessingEngine2xNatRtlNode)
DEFINE_PPE_2X_NODE(PacketProcessingEngine2xFlowPrefixRtlNode)
DEFINE_PPE_2X_NODE(PacketProcessingEngine2xFiveTupleHashRtlNode)

#undef DEFINE_PPE_2X_NODE

} // namespace noc
} // namespace gem5
