#pragma once

#include "AximmMemorySmoke.h"
#include "AximmMemorySmoke___024root.h"
#include "AximmMemorySmoke_verilator_mappings.h"
#include "noc/endpoints/rtl/AximmRtlSlaveNode.hh"
#include "params/AximmMemorySmokeRtlNode.hh"

namespace gem5::noc
{

struct AximmMemorySmokeRtlNodeWrapperTraits
{
    using AxiTraits = AximmMemorySmoke_verilator::Axi_AximmMemorySmoke__DOT__u_nsuTraits;

    static auto &clock(AximmMemorySmoke &dut) { return dut.rootp->clk; }
    static auto &resetn(AximmMemorySmoke &dut) { return dut.rootp->resetn; }
};

class AximmMemorySmokeRtlNode : public AximmRtlSlaveNode<
    AximmMemorySmoke, AximmMemorySmokeRtlNodeParams, AximmMemorySmokeRtlNodeWrapperTraits>
{
  public:
    using Params = AximmMemorySmokeRtlNodeParams;

    explicit AximmMemorySmokeRtlNode(const Params &p)
        : AximmRtlSlaveNode(p, "AximmMemorySmokeRtlNode")
    {}
};

} // namespace gem5::noc
