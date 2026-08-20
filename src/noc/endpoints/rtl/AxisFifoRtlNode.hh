#ifndef __AXIS_FIFO_RTL_NODE_HH__
#define __AXIS_FIFO_RTL_NODE_HH__

#include "axis_fifo_wrapper.h"
#include "noc/endpoints/rtl/AxisRtlStreamNode.hh"
#include "noc/endpoints/rtl/SmartNicRtlTraits.hh"
#include "params/AxisFifoRtlNode.hh"

namespace gem5
{
namespace noc
{

using AxisFifoWrapperTraits =
    SmartNicAxisClockWrapperTraits<axis_fifo_wrapper, NoSideInputs<axis_fifo_wrapper>>;

class AxisFifoRtlNode : public AxisRtlStreamNode<
    axis_fifo_wrapper,
    AxisFifoRtlNodeParams,
    AxisFifoWrapperTraits,
    1>
{
  public:
    typedef AxisFifoRtlNodeParams Params;
    explicit AxisFifoRtlNode(const Params &p);
    ~AxisFifoRtlNode() override;
};

} // namespace noc
} // namespace gem5

#endif
