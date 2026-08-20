#include "noc/endpoints/rtl/AxisFifoRtlNode.hh"

namespace gem5
{
namespace noc
{

AxisFifoRtlNode::AxisFifoRtlNode(const Params &p)
    : AxisRtlStreamNode(p, "AxisFifoRtlNode")
{
}

AxisFifoRtlNode::~AxisFifoRtlNode() = default;

} // namespace noc
} // namespace gem5
