#ifndef __SMARTNIC_RTL_TRAITS_HH__
#define __SMARTNIC_RTL_TRAITS_HH__

#include "verilated.h"

#include <cstdint>

namespace gem5
{
namespace noc
{

template <typename RootT>
struct SmartNicAxisIngressTraits
{
    auto& tdata_ref(RootT& r) const { return r.s_axis_tdata; }
    auto& tkeep_ref(RootT& r) const { return r.s_axis_tkeep; }
    auto& tuser_ref(RootT& r) const { return r.s_axis_tuser; }
    auto& tid_ref(RootT& r) const { return r.s_axis_tid; }
    auto& tdest_ref(RootT& r) const { return r.s_axis_tdest; }
    auto& tlast_ref(RootT& r) const { return r.s_axis_tlast; }
    auto& tvalid_ref(RootT& r) const { return r.s_axis_tvalid; }
    auto& tready_ref(RootT& r) const { return r.s_axis_tready; }
};

template <typename RootT>
struct SmartNicAxisEgressTraits
{
    auto& tdata_ref(RootT& r) const { return r.m_axis_tdata; }
    auto& tkeep_ref(RootT& r) const { return r.m_axis_tkeep; }
    auto& tuser_ref(RootT& r) const { return r.m_axis_tuser; }
    auto& tid_ref(RootT& r) const { return r.m_axis_tid; }
    auto& tdest_ref(RootT& r) const { return r.m_axis_tdest; }
    auto& tlast_ref(RootT& r) const { return r.m_axis_tlast; }
    auto& tvalid_ref(RootT& r) const { return r.m_axis_tvalid; }
    auto& tready_ref(RootT& r) const { return r.m_axis_tready; }
};

template <typename RootT>
struct SmartNicAxis0IngressTraits
{
    auto& tdata_ref(RootT& r) const { return r.s_axis_0_tdata; }
    auto& tkeep_ref(RootT& r) const { return r.s_axis_0_tkeep; }
    auto& tuser_ref(RootT& r) const { return r.s_axis_0_tuser; }
    auto& tid_ref(RootT& r) const { return r.s_axis_0_tid; }
    auto& tdest_ref(RootT& r) const { return r.s_axis_0_tdest; }
    auto& tlast_ref(RootT& r) const { return r.s_axis_0_tlast; }
    auto& tvalid_ref(RootT& r) const { return r.s_axis_0_tvalid; }
    auto& tready_ref(RootT& r) const { return r.s_axis_0_tready; }
};

template <typename RootT>
struct SmartNicAxis1IngressTraits
{
    auto& tdata_ref(RootT& r) const { return r.s_axis_1_tdata; }
    auto& tkeep_ref(RootT& r) const { return r.s_axis_1_tkeep; }
    auto& tuser_ref(RootT& r) const { return r.s_axis_1_tuser; }
    auto& tid_ref(RootT& r) const { return r.s_axis_1_tid; }
    auto& tdest_ref(RootT& r) const { return r.s_axis_1_tdest; }
    auto& tlast_ref(RootT& r) const { return r.s_axis_1_tlast; }
    auto& tvalid_ref(RootT& r) const { return r.s_axis_1_tvalid; }
    auto& tready_ref(RootT& r) const { return r.s_axis_1_tready; }
};

template <typename RootT>
struct SmartNicAxis0EgressTraits
{
    auto& tdata_ref(RootT& r) const { return r.m_axis_0_tdata; }
    auto& tkeep_ref(RootT& r) const { return r.m_axis_0_tkeep; }
    auto& tuser_ref(RootT& r) const { return r.m_axis_0_tuser; }
    auto& tid_ref(RootT& r) const { return r.m_axis_0_tid; }
    auto& tdest_ref(RootT& r) const { return r.m_axis_0_tdest; }
    auto& tlast_ref(RootT& r) const { return r.m_axis_0_tlast; }
    auto& tvalid_ref(RootT& r) const { return r.m_axis_0_tvalid; }
    auto& tready_ref(RootT& r) const { return r.m_axis_0_tready; }
};

template <typename RootT>
struct SmartNicAxis1EgressTraits
{
    auto& tdata_ref(RootT& r) const { return r.m_axis_1_tdata; }
    auto& tkeep_ref(RootT& r) const { return r.m_axis_1_tkeep; }
    auto& tuser_ref(RootT& r) const { return r.m_axis_1_tuser; }
    auto& tid_ref(RootT& r) const { return r.m_axis_1_tid; }
    auto& tdest_ref(RootT& r) const { return r.m_axis_1_tdest; }
    auto& tlast_ref(RootT& r) const { return r.m_axis_1_tlast; }
    auto& tvalid_ref(RootT& r) const { return r.m_axis_1_tvalid; }
    auto& tready_ref(RootT& r) const { return r.m_axis_1_tready; }
};

template <typename RootT>
struct NoSideInputs
{
    static void drive(RootT&) {}
    static void drive(RootT& r, uint64_t) { drive(r); }
};

template <typename RootT>
struct AxilIdleInputs
{
    static void drive(RootT& r)
    {
        r.ctrl_aw_valid = 0;
        r.ctrl_aw_addr = 0;
        r.ctrl_aw_prot = 0;
        r.ctrl_aw_user = 0;
        r.ctrl_w_valid = 0;
        r.ctrl_w_data = 0;
        r.ctrl_w_strb = 0;
        r.ctrl_w_user = 0;
        r.ctrl_b_ready = 1;
        r.ctrl_ar_valid = 0;
        r.ctrl_ar_addr = 0;
        r.ctrl_ar_prot = 0;
        r.ctrl_ar_user = 0;
        r.ctrl_r_ready = 1;
    }
    static void drive(RootT& r, uint64_t) { drive(r); }
};

template <typename RootT>
struct PpeSteeringFlowPrefixInputs
{
    static void drive(RootT& r)
    {
        AxilIdleInputs<RootT>::drive(r);
    }

    static void drive(RootT& r, uint64_t activeCycle)
    {
        AxilIdleInputs<RootT>::drive(r);
        r.ctrl_b_ready = 1;
        r.ctrl_r_ready = 1;

        static constexpr uint32_t flowIds[2] = {0x35u, 0xa4u};
        static constexpr uint32_t tdestValues[2] = {7u, 8u};
        const uint64_t writeIdx = activeCycle / 2;
        if ((activeCycle % 2) != 0 || writeIdx >= 2) {
            return;
        }

        r.ctrl_aw_valid = 1;
        r.ctrl_aw_addr = 0xFFFC0000u + (flowIds[writeIdx] * 4u);
        r.ctrl_aw_prot = 0;
        r.ctrl_aw_user = 0;
        r.ctrl_w_valid = 1;
        r.ctrl_w_data = tdestValues[writeIdx];
        r.ctrl_w_strb = 0xf;
        r.ctrl_w_user = 0;
    }
};

template <typename RootT>
struct PpeSteeringHashInputs
{
    static void drive(RootT& r)
    {
        AxilIdleInputs<RootT>::drive(r);
    }

    static void drive(RootT& r, uint64_t activeCycle)
    {
        AxilIdleInputs<RootT>::drive(r);
        r.ctrl_b_ready = 1;
        r.ctrl_r_ready = 1;

        static constexpr uint32_t tableEntries = 256u;
        const uint64_t writeIdx = activeCycle / 2;
        if ((activeCycle % 2) != 0 || writeIdx >= tableEntries) {
            return;
        }

        r.ctrl_aw_valid = 1;
        r.ctrl_aw_addr = 0xFFFC0000u + (static_cast<uint32_t>(writeIdx) * 4u);
        r.ctrl_aw_prot = 0;
        r.ctrl_aw_user = 0;
        r.ctrl_w_valid = 1;
        r.ctrl_w_data = 7u;
        r.ctrl_w_strb = 0xf;
        r.ctrl_w_user = 0;
    }
};

template <typename RootT>
struct AxilAximmIdleInputs
{
    static void drive(RootT& r)
    {
        AxilIdleInputs<RootT>::drive(r);
        r.dram_aw_ready = 1;
        r.dram_w_ready = 1;
        r.dram_b_valid = 0;
        r.dram_b_resp = 0;
        r.dram_b_id = 0;
        r.dram_b_user = 0;
        r.dram_ar_ready = 1;
        r.dram_r_valid = 0;
        r.dram_r_resp = 0;
        r.dram_r_last = 0;
        r.dram_r_id = 0;
        r.dram_r_user = 0;
    }
    static void drive(RootT& r, uint64_t) { drive(r); }
};

template <typename RootT>
struct PacketRateLimiterThrottleInputs
{
    static void drive(RootT& r)
    {
        AxilAximmIdleInputs<RootT>::drive(r);
    }

    static void drive(RootT& r, uint64_t activeCycle)
    {
        AxilAximmIdleInputs<RootT>::drive(r);

        static constexpr uint32_t maxFlows = 1024;
        static constexpr uint32_t fullRate = 0xffffffffu;
        static constexpr uint32_t fullCap = 0xffffffffu;
        static constexpr uint64_t writeHoldCycles = 8;

        // The limiter's BRAM initialization takes roughly MAX_FLOWS cycles.
        // Program every rate/capacity entry with max values so this v1
        // experiment exercises external AXI-S backpressure around the node
        // without token-bucket drops. These AXI-Lite writes are model
        // side-inputs, not NoC traffic.
        if (activeCycle >= 1200) {
            const uint64_t writeIdx = (activeCycle - 1200) / writeHoldCycles;
            const uint32_t flowBucket =
                static_cast<uint32_t>((writeIdx / 2) % maxFlows);
            const bool writeRate = (writeIdx & 1u) == 0;
            r.ctrl_aw_valid = 1;
            const uint32_t tableEntry =
                (writeRate ? flowBucket : (maxFlows + flowBucket));
            r.ctrl_aw_addr = tableEntry * 4u;
            r.ctrl_aw_prot = 0;
            r.ctrl_aw_user = 0;
            r.ctrl_w_valid = 1;
            r.ctrl_w_data = writeRate ? fullRate : fullCap;
            r.ctrl_w_strb = 0xf;
            r.ctrl_w_user = 0;
        }
    }
};

template <typename RootT>
struct OverloadedNatInitInputs
{
    static void drive(RootT& r)
    {
        AxilIdleInputs<RootT>::drive(r);
    }

    static void drive(RootT& r, uint64_t activeCycle)
    {
        AxilIdleInputs<RootT>::drive(r);
        r.ctrl_b_ready = 1;
        r.ctrl_r_ready = 1;

        // The Naviq RTL side-input shim cannot observe AXI-Lite ready, so hold
        // each idempotent NAT CSR write long enough to survive ready bubbles in
        // the wrapper/crossbar path.
        static constexpr uint64_t writeHoldCycles = 16;
        const uint64_t writeIdx = activeCycle / writeHoldCycles;
        if (writeIdx >= 4) {
            return;
        }

        static constexpr uint32_t addrs[4] = {0x00, 0x04, 0x08, 0x0c};
        static constexpr uint32_t data[4] = {
            0x0a000001u, // 10.0.0.1
            40000u,
            1000u,
            1u
        };

        r.ctrl_aw_valid = 1;
        r.ctrl_aw_addr = addrs[writeIdx];
        r.ctrl_aw_prot = 0;
        r.ctrl_aw_user = 0;
        r.ctrl_w_valid = 1;
        r.ctrl_w_data = data[writeIdx];
        r.ctrl_w_strb = 0xf;
        r.ctrl_w_user = 0;
    }
};

template <typename RootT, typename SideInputs>
struct SmartNicFlatAxisWrapperTraits
{
    using IngressTraits = SmartNicAxisIngressTraits<RootT>;
    using EgressTraits = SmartNicAxisEgressTraits<RootT>;

    static auto& clock(RootT& r) { return r.clk; }
    static auto& resetn(RootT& r) { return r.resetn; }
    static auto& egressTready(RootT& r) { return r.m_axis_tready; }
    static void driveIdleSideInputs(RootT& r) { SideInputs::drive(r); }
    static void driveSideInputs(RootT& r, uint64_t activeCycle)
    {
        SideInputs::drive(r, activeCycle);
    }
};

template <typename RootT, typename SideInputs>
struct SmartNicFlatAxis2xWrapperTraits
{
    using Ingress0Traits = SmartNicAxis0IngressTraits<RootT>;
    using Ingress1Traits = SmartNicAxis1IngressTraits<RootT>;
    using Egress0Traits = SmartNicAxis0EgressTraits<RootT>;
    using Egress1Traits = SmartNicAxis1EgressTraits<RootT>;

    static auto& clock(RootT& r) { return r.clk; }
    static auto& resetn(RootT& r) { return r.resetn; }
    static auto& egress0Tready(RootT& r) { return r.m_axis_0_tready; }
    static auto& egress1Tready(RootT& r) { return r.m_axis_1_tready; }
    static void driveIdleSideInputs(RootT& r) { SideInputs::drive(r); }
    static void driveSideInputs(RootT& r, uint64_t activeCycle)
    {
        SideInputs::drive(r, activeCycle);
    }
};

template <typename RootT, typename SideInputs>
struct SmartNicAxisClockWrapperTraits
{
    using IngressTraits = SmartNicAxisIngressTraits<RootT>;
    using EgressTraits = SmartNicAxisEgressTraits<RootT>;

    static auto& clock(RootT& r) { return r.axis_aclk; }
    static auto& resetn(RootT& r) { return r.axis_aresetn; }
    static auto& egressTready(RootT& r) { return r.m_axis_tready; }
    static void driveIdleSideInputs(RootT& r) { SideInputs::drive(r); }
    static void driveSideInputs(RootT& r, uint64_t activeCycle)
    {
        SideInputs::drive(r, activeCycle);
    }
};

} // namespace noc
} // namespace gem5

#endif
