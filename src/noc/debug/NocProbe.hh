#ifndef __NOC_TEST_NOC_PROBE_HH__
#define __NOC_TEST_NOC_PROBE_HH__

#include <deque>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "base/types.hh"

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/core/network/NocSystem.hh"
#include "noc/lib/network/NocMessage.hh"
#include "params/NocProbe.hh"
#include "sim/sim_object.hh"

namespace gem5 { namespace ruby { namespace garnet {
template <typename T_Msg, typename T_RouteInfo> class flit;
}}}

namespace gem5
{
namespace noc
{

struct ProbeData;

/**
 * Configurable NoC probe SimObject. Optional `noc_probe` Param on Routers,
 * NetworkInterfaces, NetworkLinks, and NocInterface forwards here via onHookEvent(id).
 *
 * Hook ids (strings):
 *  - router.flit.in, router.flit.post_route, router.flit.sa_grant, router.flit.out
 *  - link.flit.enqueue
 *  - ni.msg.to_flit, ni.flit.inject, ni.flit.to_link, ni.flit.from_link, ni.flit.to_protocol
 *  - noc_if.state.to_cdc, noc_if.node.to_cdc, noc_if.cdc.to_node, noc_if.net.to_cdc,
 *    noc_if.cdc.to_net (comparator / latency taps on NocInterface only)
 *  - noc_if.state.node_side, noc_if.state.noc_side (snooper: NocInterfaceAxisBeatData /
 *    NocInterfaceAximmBeatData — node_side at end of nodeSideUpdate; noc_side from CDC
 *    peek at end of nocSideUpdate). node_side is sampled on the connected node's /
 *    tile-controller evaluation cadence (not necessarily the NocInterface Param clock).
 *    noc_side follows the NoC-side update cadence (often the configured NoC clock e.g. 1 GHz).
 *
 * In comparator mode, hook_id_0 and hook_id_1 must deliver the same item kind
 * (flit, message, State, or ProbeData): e.g. ni.flit.* with ni.flit.*, or
 * noc_if.state.to_cdc with noc_if.cdc.to_node (both State), or noc_if.state.node_side
 * with noc_if.state.noc_side (both ProbeData). For latency/path_match, hook1 flit hooks
 * try flit debug id, then message getDebugId(), then collectNetworkPayloadDebugIds.
 * Message hooks (incl. noc_if.node.to_cdc, ni.msg.*) use collectNetworkPayloadDebugIds.
 *
 * Snooper mode: only NocInterface taps — hook_id_0 / hook_id_1 must be exactly
 * noc_if.state.node_side and/or noc_if.state.noc_side (AXIS / AXIMM beat snapshots via
 * ProbeData). Other components may still hold a NocProbe Param for comparator mode.
 * Optionally lists snoop_fields (see --print-noc-probe-help). JSON hook_point_0.print_cycles
 * is parsed into Param snoop_print_cycles but is not yet applied in C++ (every matching
 * event prints).
 *
 * When the hook source passes its ClockedObject clock period (ticks per cycle), snooper
 * lines set dt to that source clock's cycle time in ns and bw_MBps to
 * B*(sim_clock::Frequency/period)/1e6 (instantaneous line rate for one beat on that clock).
 * dt is the beat clock period passed by the hook source (NocInterface clockPeriod()), not
 * the spacing between NP lines. Successive `t=` values are curTick() when the hook ran;
 * spacing differs between node_side (tile/node cadence) and noc_side (NoC cadence), and
 * neither is implied to be exactly one ni.clockPeriod() tick apart.
 */
class NocProbe : public SimObject
{
  public:
    typedef NocProbeParams Params;

    /** How comparator hook1 resolves ids (inferred from hook_id_1). */
    enum class LatencyHook1IdSource
    {
        AxisPayloadDebugIds,
        FlitDebugId,
    };

    explicit NocProbe(const Params &p);
    void init() override;
    void startup() override;

    bool isEnabled() const { return enabled; }
    const std::string &getProbeId() const { return probeId; }
    const std::string &getProbeMode() const { return probeMode; }
    /** Same as getProbeMode() ("snooper" or "comparator"). */
    const std::string &getMode() const { return probeMode; }
    const std::string &getComparatorOp() const { return comparatorOp; }
    const std::string &getHookPoint0() const { return hookPoint0; }
    const std::string &getHookPoint1() const { return hookPoint1; }
    /** True if hook_point_1 was set to a non-empty id. */
    bool hasHookPoint1() const { return !hookPoint1.empty(); }
    NocSystem *getNocSystem() const { return nocSystem; }

    using FlitType = gem5::ruby::garnet::flit<gem5::noc::NocMessage,
                                              gem5::noc::garnet::NocRouteInfo>;

    /** Hook sites pass a stable string id (e.g. "ni.flit.from_link"). */
    void onHookEvent(const char* hookId,
                     const char* sourceComponent = nullptr,
                     Tick sourceClockPeriodTicks = 0);

    /** Hook sites may also provide the active flit. */
    void onHookEvent(const char* hookId, FlitType* fl,
                     const char* sourceComponent = nullptr,
                     Tick sourceClockPeriodTicks = 0);

    /** Hook sites may provide the active Ruby message. */
    void onHookEvent(const char* hookId, const MsgPtr& msg,
                     const char* sourceComponent = nullptr,
                     Tick sourceClockPeriodTicks = 0);

    /** Hook sites may provide the active AXI/CDC state. */
    void onHookEvent(const char* hookId, State* st,
                     const char* sourceComponent = nullptr,
                     Tick sourceClockPeriodTicks = 0);

    /** NocInterface snooper/comparator taps on merged beat snapshots (AXIS / AXIMM). */
    void onHookEvent(const char* hookId, ProbeData* pd,
                     const char* sourceComponent = nullptr,
                     Tick sourceClockPeriodTicks = 0);

    /** Comparator and snooper both consume hook callbacks. */
    bool needsHookEvents() const
    {
        return enabled && (probeMode == "comparator" || probeMode == "snooper");
    }

    /**
     * Snooper only: print cumulative transferred bytes and average BW (first→last
     * snoop tick). Invoked from NocSystem::printNocProbeSnoopSummariesAtExit().
     */
    void printSnoopSummary() const;

  private:
    template <typename T>
    void onHookEventWithItem(const char* hookId, const char* sourceComponent,
                             T* item, Tick sourceClockPeriodTicks);

    void emitSnoopLineOnHook(const std::string& hookId, void* item,
                             const char* sourceComponent,
                             Tick sourceClockPeriodTicks);

    /** Called from registerExitCallback when comparator_op is path_match. */
    void printPathMatchSummary() const;

    NocSystem *nocSystem;
    std::string probeId;
    std::string probeMode;
    std::string comparatorOp;
    std::string hookPoint0;
    std::string hookPoint1;
    bool enabled;
    /** Verbose path_match: print hook0 assign / hook1 pop per id. */
    bool pathMatchTrace = false;

    /**
     * When probe_mode=comparator and comparator_op is latency or path_match, and
     * hook_id_1 is a flit or message hook, hook1 id matching uses:
     *  - `*.msg.*` and `noc_if.node.to_cdc`: collectNetworkPayloadDebugIds
     *  - `*.flit.*`: flit debug id, else message debug id, else payload ids
     */
    std::optional<LatencyHook1IdSource> latencyHook1IdSource;

    constexpr static size_t kInitialDebugPoolSize = 512;

    std::deque<int> debugIds;
    int nextDebugId = 0;

    std::unordered_map<int, Tick> latencyTracker;

    /** cap for listing unmatched ids at exit; 0 = no limit. */
    constexpr static size_t kPathMatchUnmatchedIdPrintMax = 2000;

    /** path_match: ids assigned at hook0 not yet seen at hook1 */
    std::unordered_set<int> pathMatchPending;
    uint64_t pathMatchHook0Observations = 0;
    uint64_t pathMatchHook1Matches = 0;

    mutable std::string hookPoint0Source;
    mutable std::string hookPoint1Source;

    // --- Snooper mode state ---
    std::vector<std::string> snoopFields;

    Tick snoopFirstTick = MaxTick;
    Tick snoopLastTick = 0;
    uint64_t snoopTransferredBytes = 0;
    uint64_t snoopLineCount = 0;
};

} // namespace noc
} // namespace gem5

#endif // __NOC_TEST_NOC_PROBE_HH__
