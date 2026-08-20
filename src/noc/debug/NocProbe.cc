#include "noc/debug/NocProbe.hh"

#include "base/logging.hh"
#include "sim/sim_exit.hh"

#include "mem/ruby/network/garnet/flit.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/lib/debug/ProbeTypes.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "noc/core/network/NocStreamMsg.hh"

#include <algorithm>
#include <cctype>
#include <functional>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <string_view>
#include <type_traits>
#include <unordered_map>
#include <vector>

#include "sim/core.hh" // sim_clock::Frequency

namespace gem5
{
namespace noc
{

namespace
{

/** Strip ASCII whitespace so JSON / CLI typos do not break registry lookup. */
void
trimSnoopFieldId(std::string& s)
{
    const auto not_space = [](unsigned char c) { return !std::isspace(c); };
    s.erase(s.begin(), std::find_if(s.begin(), s.end(), not_space));
    s.erase(std::find_if(s.rbegin(), s.rend(), not_space).base(), s.end());
}

std::string_view
extractMiddleToken(const std::string& hookPoint, const char* probeName,
                   const char* paramLabel)
{
    const std::string_view hook(hookPoint);
    const size_t firstDot = hook.find('.');
    const size_t secondDot = (firstDot == std::string_view::npos)
        ? std::string_view::npos
        : hook.find('.', firstDot + 1);

    if (firstDot == std::string_view::npos || secondDot == std::string_view::npos ||
        secondDot <= firstDot + 1) {
        fatal("NocProbe %s: %s must match '*.*.*', got '%s'",
              probeName, paramLabel, hookPoint);
    }

    return hook.substr(firstDot + 1, secondDot - firstDot - 1);
}

bool
middleTokenOk(std::string_view middle)
{
    return middle == "flit" || middle == "msg" || middle == "state" ||
           middle == "node" || middle == "cdc" || middle == "net";
}

/** What `onHookEvent(..., item)` passes for this hook id (comparator pairing). */
enum class ComparatorHookItemKind : uint8_t
{
    Flit,
    Message,
    State,
    ProbeData,
};


static constexpr const char* kNocIfProbeFromNode = "noc_if.state.node_side";
static constexpr const char* kNocIfProbeFromNoc = "noc_if.state.noc_side";

ComparatorHookItemKind
comparatorHookItemKind(const std::string& hookPoint, const char* probeName,
                         const char* paramLabel)
{
    if (hookPoint == kNocIfProbeFromNode || hookPoint == kNocIfProbeFromNoc) {
        return ComparatorHookItemKind::ProbeData;
    }
    // NocInterface: only this `*.node.*` hook carries a message; others are State.
    if (hookPoint == "noc_if.node.to_cdc") {
        return ComparatorHookItemKind::Message;
    }

    const std::string_view mid =
        extractMiddleToken(hookPoint, probeName, paramLabel);
    if (mid == "flit") {
        return ComparatorHookItemKind::Flit;
    }
    if (mid == "msg") {
        return ComparatorHookItemKind::Message;
    }
    if (mid == "state" || mid == "cdc" || mid == "net") {
        return ComparatorHookItemKind::State;
    }
    if (mid == "node") {
        fatal("NocProbe %s: %s unsupported hook_id '%s' (middle token 'node' is "
              "only valid for noc_if.node.to_cdc).",
              probeName, paramLabel, hookPoint);
    }
    fatal("NocProbe %s: %s cannot classify comparator hook item kind for '%s'.",
          probeName, paramLabel, hookPoint);
}

void
appendDebugIdPool(std::deque<int>& pool, int startId, size_t count)
{
    for (size_t i = 0; i < count; ++i) {
        pool.push_back(startId + static_cast<int>(i));
    }
}

} // namespace

namespace
{

/**
 * Comparator hook1 id matching for flit/msg taps: choose how to read ids at hook1.
 * Derived from hook_id only (probe_id is a user label only).
 *  - Message hooks: collectNetworkPayloadDebugIds (axisPayload, AXI-MM msg, etc.)
 *  - Flit hooks: forEachHook1FlitStyleDebugId (flit id, then msg id, then payload)
 */
static std::optional<NocProbe::LatencyHook1IdSource>
inferLatencyHook1IdSourceFromHook(const std::string& hookPoint1,
                                  const char* probeName)
{
    if (hookPoint1 == "noc_if.node.to_cdc") {
        return NocProbe::LatencyHook1IdSource::AxisPayloadDebugIds;
    }
    const std::string_view mid =
        extractMiddleToken(hookPoint1, probeName, "hook_id_1");
    if (mid == "msg") {
        return NocProbe::LatencyHook1IdSource::AxisPayloadDebugIds;
    }
    if (mid == "flit") {
        return NocProbe::LatencyHook1IdSource::FlitDebugId;
    }
    return std::nullopt;
}

static bool
tryExtractAxisPayload(const NocMessage* msg, axisPayload& out)
{
    if (!msg) return false;
    const auto* s = dynamic_cast<const NocStreamMsg*>(msg);
    if (!s) return false;
    // Only NETWORK-mode stream messages carry axisPayload in getData().
    Payload pl;
    try {
        pl = s->getData();
    } catch (...) {
        return false;
    }
    if (auto* ap = std::get_if<axisPayload>(&pl)) {
        out = *ap; // copy-out to avoid dangling pointers
        return true;
    }
    return false;
}

/** AXI-S (axisPayload::debugIds) or AXI-MM (NocMemoryMsg::network probe ids). */
static void
collectNetworkPayloadDebugIds(const NocMessage* msg, std::vector<int32_t>& out)
{
    out.clear();
    if (!msg) {
        return;
    }
    // Tile-facing (BUFFER-mode) stream messages may carry per-beat contributing
    // ids via NocMessage::debugIds (e.g., depacketized AXI-S beats).
    if (msg->hasDebugIds()) {
        out = msg->getDebugIds();
        return;
    }
    axisPayload ap{};
    if (tryExtractAxisPayload(msg, ap)) {
        out = ap.debugIds;
        return;
    }
    if (const auto* mm = dynamic_cast<const NocMemoryMsg*>(msg)) {
        out = mm->getNetworkProbeDebugIds();
    }
}

/**
 * Comparator hook1 for `*.flit.*` (and message items): correlation id may be on
 * the flit, on the shared message (see flit.cc sync), or only in payload /
 * getDebugIds(). Try those in order so router0→router1 latency still matches.
 */
template <typename T, typename Fn>
void
forEachHook1FlitStyleDebugId(T* item, Fn&& fn)
{
    if (!item) {
        return;
    }
    if constexpr (std::is_same_v<T, NocProbe::FlitType>) {
        if (item->hasDebugId()) {
            fn(item->getDebugId());
            return;
        }
        const auto& mp = item->get_msg_ptr();
        if (mp && mp->hasDebugId()) {
            fn(mp->getDebugId());
            return;
        }
        std::vector<int32_t> ids;
        collectNetworkPayloadDebugIds(mp.get(), ids);
        for (int32_t id : ids) {
            fn(static_cast<int>(id));
        }
        return;
    }
    if constexpr (std::is_same_v<T, NocMessage>) {
        if (item->hasDebugId()) {
            fn(item->getDebugId());
            return;
        }
        std::vector<int32_t> ids;
        collectNetworkPayloadDebugIds(item, ids);
        for (int32_t id : ids) {
            fn(static_cast<int>(id));
        }
    }
}
} // anonymous namespace

namespace
{
struct SnooperFieldHandler
{
    std::function<std::string(void*, const std::string&)> fmt;
};

static std::string
fmtBool01(bool v)
{
    return v ? "1" : "0";
}

template <typename T>
static std::string
fmtDec(T v)
{
    std::ostringstream os;
    os << v;
    return os.str();
}

template <typename T>
static std::string
fmtHex(T v)
{
    std::ostringstream os;
    os << "0x" << std::hex << std::nouppercase << v;
    return os.str();
}

static std::string
fmtPrefix16Arr(const std::array<uint8_t, 16>& bytes)
{
    std::ostringstream os;
    os << "0x" << std::hex << std::setfill('0');
    for (size_t i = 0; i < bytes.size(); ++i) {
        os << std::setw(2) << static_cast<unsigned>(bytes[i]);
    }
    return os.str();
}

static std::string_view
shortenPathLike(std::string_view s)
{
    // Trim common prefix to keep snooper prints short.
    constexpr std::string_view pfx = "system.";
    if (s.rfind(pfx, 0) == 0) {
        s.remove_prefix(pfx.size());
    }
    return s;
}

static inline uint64_t
popcount_u64(uint64_t x)
{
    return static_cast<uint64_t>(__builtin_popcountll(static_cast<unsigned long long>(x)));
}

static std::optional<uint64_t>
trySnooperProbeBytes(void* item)
{
    if (!item) {
        return std::nullopt;
    }
    const auto* pd = static_cast<const ProbeData*>(item);
    if (const auto* ax = dynamic_cast<const NocInterfaceAxisBeatData*>(pd)) {
        const uint64_t mask = 0xFFFFFFFFFFFFFFFFULL;
        const uint64_t masked_keep = ax->tkeep & mask;
        return popcount_u64(masked_keep);
    }
    if (const auto* am = dynamic_cast<const NocInterfaceAximmBeatData*>(pd)) {
        if (am->w.tvalid)
            return popcount_u64(am->w.wstrb);
        const bool use_aw = am->aw.tvalid;
        const bool use_ar = am->ar.tvalid;
        if (use_aw || use_ar) {
            const uint8_t len = use_aw ? am->aw.len : am->ar.len;
            const uint8_t size = use_aw ? am->aw.size : am->ar.size;
            return static_cast<uint64_t>(
                (static_cast<uint16_t>(len) + 1) * (1ULL << size));
        }
        if (am->r.tvalid)
            return 64;
        return std::nullopt;
    }
    return std::nullopt;
}

/**
 * Bytes moved on this beat only when the relevant channel completes a handshake
 * (valid&&ready). Used for end-of-run average throughput; differs from
 * trySnooperProbeBytes which reflects payload sizing even without ready.
 */
static std::optional<uint64_t>
trySnooperTransferredBytes(void* item)
{
    if (!item) {
        return std::nullopt;
    }
    const auto* pd = static_cast<const ProbeData*>(item);
    if (const auto* ax = dynamic_cast<const NocInterfaceAxisBeatData*>(pd)) {
        if (!ax->tvalid || !ax->tready) {
            return std::nullopt;
        }
        const uint64_t mask = 0xFFFFFFFFFFFFFFFFULL;
        const uint64_t masked_keep = ax->tkeep & mask;
        return popcount_u64(masked_keep);
    }
    if (const auto* am = dynamic_cast<const NocInterfaceAximmBeatData*>(pd)) {
        if (am->w.tvalid && am->w.tready) {
            return popcount_u64(am->w.wstrb);
        }
        const bool use_aw = am->aw.tvalid && am->aw.tready;
        const bool use_ar = am->ar.tvalid && am->ar.tready;
        if (use_aw || use_ar) {
            const uint8_t len = use_aw ? am->aw.len : am->ar.len;
            const uint8_t size = use_aw ? am->aw.size : am->ar.size;
            return static_cast<uint64_t>(
                (static_cast<uint16_t>(len) + 1) * (1ULL << size));
        }
        if (am->r.tvalid && am->r.tready) {
            return 64;
        }
        return std::nullopt;
    }
    return std::nullopt;
}

template <typename Fn>
static std::string
snoopAxisBeat(void* p, Fn&& fn)
{
    const auto* b = dynamic_cast<const NocInterfaceAxisBeatData*>(
        static_cast<const ProbeData*>(p));
    return b ? fn(*b) : std::string("NA");
}

template <typename Fn>
static std::string
snoopAximmBeat(void* p, Fn&& fn)
{
    const auto* d = dynamic_cast<const NocInterfaceAximmBeatData*>(
        static_cast<const ProbeData*>(p));
    return d ? fn(*d) : std::string("NA");
}

static const std::unordered_map<std::string, SnooperFieldHandler>&
snooperFieldRegistry() {
    static const std::unordered_map<std::string, SnooperFieldHandler> reg = {
        {"axis.tvalid", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtBool01(b.tvalid);
            });
        }}},
        {"axis.tready", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtBool01(b.tready);
            });
        }}},
        {"axis.ni_tready", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtBool01(b.ni_tready);
            });
        }}},
        {"axis.cdc_enqueue_ready", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtBool01(b.cdc_enqueue_ready);
            });
        }}},
        {"axis.tlast", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtBool01(b.tlast);
            });
        }}},
        {"axis.tid", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtDec(b.tid);
            });
        }}},
        {"axis.tdest", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtDec(b.tdest);
            });
        }}},
        {"axis.tkeep", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtHex(b.tkeep);
            });
        }}},
        {"axis.tuser", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtDec(static_cast<unsigned>(b.tuser));
            });
        }}},
        {"axis.nbytes_valid", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtDec(static_cast<unsigned>(popcount_u64(b.tkeep)));
            });
        }}},
        {"axis.tdata[0:15]", {[](void* p, const std::string&) {
            return snoopAxisBeat(p, [&](const NocInterfaceAxisBeatData& b) {
                return fmtPrefix16Arr(b.tdata_prefix);
            });
        }}},
        {"state.debug_id", {[](void* p, const std::string&) {
            const auto* pd = static_cast<const ProbeData*>(p);
            return pd->hasDebugId() ? fmtDec(pd->getDebugId()) : std::string("NA");
        }}},
        {"cdc.enqueue_ready", {[](void* p, const std::string&) {
            const auto* pd = static_cast<const ProbeData*>(p);
            if (const auto* b = dynamic_cast<const NocInterfaceAxisBeatData*>(pd))
                return fmtBool01(b->cdc_enqueue_ready);
            if (const auto* d = dynamic_cast<const NocInterfaceAximmBeatData*>(pd))
                return fmtBool01(d->cdc_enqueue_ready);
            return std::string("NA");
        }}},
        {"aximm.ar.addr", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtHex(d.ar.addr);
            });
        }}},
        {"aximm.ar.len", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(static_cast<unsigned>(d.ar.len));
            });
        }}},
        {"aximm.ar.size", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(static_cast<unsigned>(d.ar.size));
            });
        }}},
        {"aximm.ar.burst", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(static_cast<int>(d.ar.burst));
            });
        }}},
        {"aximm.ar.id", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(d.ar.id);
            });
        }}},
        {"aximm.ar.valid", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.ar.tvalid);
            });
        }}},
        {"aximm.ar.ready", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.ar.tready);
            });
        }}},
        {"aximm.aw.addr", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtHex(d.aw.addr);
            });
        }}},
        {"aximm.aw.len", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(static_cast<unsigned>(d.aw.len));
            });
        }}},
        {"aximm.aw.size", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(static_cast<unsigned>(d.aw.size));
            });
        }}},
        {"aximm.aw.burst", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(static_cast<int>(d.aw.burst));
            });
        }}},
        {"aximm.aw.id", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(d.aw.id);
            });
        }}},
        {"aximm.aw.valid", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.aw.tvalid);
            });
        }}},
        {"aximm.aw.ready", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.aw.tready);
            });
        }}},
        {"aximm.w.last", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.w.last);
            });
        }}},
        {"aximm.w.strb", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtHex(d.w.wstrb);
            });
        }}},
        {"aximm.w.valid", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.w.tvalid);
            });
        }}},
        {"aximm.w.ready", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.w.tready);
            });
        }}},
        {"aximm.r.ready", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.r.tready);
            });
        }}},
        {"aximm.r.valid", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.r.tvalid);
            });
        }}},
        {"aximm.b.ready", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.b.tready);
            });
        }}},
        {"aximm.b.valid", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtBool01(d.b.tvalid);
            });
        }}},
        {"aximm.b.resp", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                return fmtDec(static_cast<int>(d.b.resp));
            });
        }}},
        {"aximm.beat_bytes", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                const bool aw = d.aw.tvalid;
                const uint8_t len = aw ? d.aw.len : d.ar.len;
                const uint8_t size = aw ? d.aw.size : d.ar.size;
                const uint16_t beat =
                    static_cast<uint16_t>((static_cast<uint16_t>(len) + 1) *
                                          (1U << size));
                return fmtDec(static_cast<unsigned>(beat));
            });
        }}},
        {"aximm.total_bytes", {[](void* p, const std::string&) {
            return snoopAximmBeat(p, [&](const NocInterfaceAximmBeatData& d) {
                const bool aw = d.aw.tvalid;
                const uint8_t len = aw ? d.aw.len : d.ar.len;
                const uint8_t size = aw ? d.aw.size : d.ar.size;
                const uint32_t total =
                    (static_cast<uint32_t>(len) + 1U) *
                    static_cast<uint32_t>(1U << size);
                return fmtDec(total);
            });
        }}},
    };
    return reg;
}
} // anonymous namespace

NocProbe::NocProbe(const Params &p)
    : SimObject(p),
      nocSystem(p.noc_system),
      probeId(p.probe_id),
      probeMode(p.probe_mode),
      comparatorOp(p.comparator_op),
      hookPoint0(p.hook_id_0),
      hookPoint1(p.hook_id_1),
      enabled(p.enabled),
      pathMatchTrace(p.path_match_trace),
      latencyHook1IdSource(std::nullopt),
      snoopFields(p.snoop_fields)
{
    if (probeMode != "snooper" && probeMode != "comparator") {
        fatal("NocProbe %s: probe_mode must be \"snooper\" or \"comparator\", got \"%s\"",
              name(), probeMode);
    }
    if (enabled && probeMode == "snooper") {
        if (hookPoint0 != kNocIfProbeFromNode && hookPoint0 != kNocIfProbeFromNoc) {
            fatal("NocProbe %s: probe_mode=snooper requires hook_id_0 to be "
                  "noc_if.state.node_side or noc_if.state.noc_side (got '%s').",
                  name(), hookPoint0);
        }
        if (!hookPoint1.empty() && hookPoint1 != kNocIfProbeFromNode &&
            hookPoint1 != kNocIfProbeFromNoc) {
            fatal("NocProbe %s: probe_mode=snooper requires hook_id_1 to be "
                  "noc_if.state.node_side or noc_if.state.noc_side (got '%s').",
                  name(), hookPoint1);
        }
    }
    if (probeMode == "comparator") {
        if (comparatorOp != "latency" && comparatorOp != "path_match") {
            fatal("NocProbe %s: comparator_op must be \"latency\" or \"path_match\", got \"%s\"",
                  name(), comparatorOp);
        }
    }

    if (enabled && probeMode == "comparator" &&
        (comparatorOp == "latency" || comparatorOp == "path_match") &&
        !hookPoint1.empty()) {
        latencyHook1IdSource =
            inferLatencyHook1IdSourceFromHook(hookPoint1, name().c_str());
    }

    if (enabled) {
        if (!hookPoint0.empty()) {
            const std::string_view m =
                extractMiddleToken(hookPoint0, name().c_str(), "hook_id_0");
            if (!middleTokenOk(m)) {
                fatal("NocProbe %s: unsupported hook_id_0 middle token '%s' in '%s'; "
                      "expected one of {flit,msg,state,node,cdc,net}",
                      name(), std::string(m).c_str(), hookPoint0);
            }
        }

        if (!hookPoint1.empty()) {
            const std::string_view m =
                extractMiddleToken(hookPoint1, name().c_str(), "hook_id_1");
            if (!middleTokenOk(m)) {
                fatal("NocProbe %s: unsupported hook_id_1 middle token '%s' in '%s'; "
                      "expected one of {flit,msg,state,node,cdc,net}",
                      name(), std::string(m).c_str(), hookPoint1);
            }
        }

        if (probeMode == "comparator" && !hookPoint0.empty() &&
            !hookPoint1.empty()) {
            const ComparatorHookItemKind k0 = comparatorHookItemKind(
                hookPoint0, name().c_str(), "hook_id_0");
            const ComparatorHookItemKind k1 = comparatorHookItemKind(
                hookPoint1, name().c_str(), "hook_id_1");
            if (k0 != k1) {
                fatal("NocProbe %s: comparator mode requires hook_id_0 and hook_id_1 "
                      "to observe the same item type (flit+flit, msg+msg, "
                      "state+state, or probe snapshot+probe snapshot). Got '%s' vs '%s'.",
                      name(), hookPoint0, hookPoint1);
            }
        }
    }

    if (enabled && (!hookPoint0.empty() || !hookPoint1.empty())) {
        appendDebugIdPool(debugIds, nextDebugId, kInitialDebugPoolSize);
        nextDebugId += static_cast<int>(kInitialDebugPoolSize);
    }
}

void
NocProbe::printPathMatchSummary() const
{
    if (!enabled || probeMode != "comparator" ||
        comparatorOp != "path_match") {
        return;
    }

    const size_t n_unmatched = pathMatchPending.size();
    std::cout << "PathMatch " << name()
              << ": hook0_observations=" << pathMatchHook0Observations
              << " hook1_matches=" << pathMatchHook1Matches
              << " never_reached_hook1=" << n_unmatched
              << std::endl;

    if (n_unmatched == 0) {
        return;
    }

    std::vector<int> ids(pathMatchPending.begin(), pathMatchPending.end());
    // std::sort(ids.begin(), ids.end());

    const size_t cap = kPathMatchUnmatchedIdPrintMax;
    const size_t print_n = (cap == 0) ? ids.size() : std::min(ids.size(), cap);

    std::cout << "PathMatch " << name() << " unmatched_ids (" << ids.size()
              << " total";
    if (cap != 0 && ids.size() > cap) {
        std::cout << ", printing first " << cap;
    }
    std::cout << "):";

    for (size_t i = 0; i < print_n; ++i) {
        if (i % 20 == 0) {
            std::cout << "\n  ";
        } else {
            std::cout << ' ';
        }
        std::cout << ids[i];
    }
    if (ids.size() > print_n) {
        std::cout << "\n  ... (" << (ids.size() - print_n) << " more not printed)";
    }
    std::cout << std::endl;
}

void
NocProbe::init() {
    SimObject::init();

    if (!enabled) {
        return;
    }

    if (hookPoint0.empty()) {
        fatal("NocProbe %s: hook_id_0 must be non-empty", name());
    }

    if (probeMode == "snooper") {
        for (auto& fid : snoopFields) {
            trimSnoopFieldId(fid);
        }
        if (!snoopFields.empty()) {
            const auto& reg = snooperFieldRegistry();
            for (const auto& fid : snoopFields) {
                if (reg.find(fid) == reg.end()) {
                    fatal("NocProbe %s: unsupported snooper field id '%s' (from snoop_fields).",
                          name(), fid);
                }
            }
        }

    } else if (probeMode == "comparator") {
        if (hookPoint1.empty()) {
            fatal("NocProbe %s: comparator mode requires non-empty hook_id_1",
                  name());
        }
    }

    if (probeMode == "comparator" && comparatorOp == "path_match") {
        registerExitCallback([this]() { printPathMatchSummary(); });
    }
    // Snooper end-of-run summary: printed from NocGarnetNetwork exit callback
    // (same path as NocTrafficMonitor) via NocSystem::printNocProbeSnoopSummariesAtExit().
}

void
NocProbe::printSnoopSummary() const
{
    if (!enabled || probeMode != "snooper") {
        return;
    }

    const std::string_view probe_label =
        !probeId.empty() ? std::string_view(probeId) : std::string_view(name());

    std::cout << "NP summary id=" << shortenPathLike(probe_label)
              << " snoop_lines=" << snoopLineCount;

    if (snoopLineCount == 0) {
        std::cout << " transferred_B=0 span_ticks=NA avg_bw_MBps=NA" << std::endl;
        return;
    }

    const Tick span_ticks = snoopLastTick - snoopFirstTick;
    std::cout << " first_t=" << snoopFirstTick << " last_t=" << snoopLastTick
              << " span_ticks=" << span_ticks;

    std::cout << " transferred_B=" << snoopTransferredBytes;

    if (span_ticks > 0 && gem5::sim_clock::Frequency > 0) {
        const double span_s =
            (double)span_ticks / (double)gem5::sim_clock::Frequency;
        const double avg_bw_MBps =
            ((double)snoopTransferredBytes / 1.0e6) / span_s;
        std::cout << std::fixed << std::setprecision(6)
                  << " avg_bw_MBps=" << avg_bw_MBps << std::defaultfloat;
    } else {
        std::cout << " avg_bw_MBps=NA";
    }
    std::cout << std::endl;
}

void
NocProbe::startup()
{
    SimObject::startup();
}

void
NocProbe::emitSnoopLineOnHook(const std::string& hookId, void* item,
                              const char* sourceComponent,
                              Tick sourceClockPeriodTicks)
{
    const Tick now = curTick();

    ++snoopLineCount;
    if (snoopFirstTick == MaxTick) {
        snoopFirstTick = now;
    }
    snoopLastTick = now;
    if (const auto xfer = trySnooperTransferredBytes(item)) {
        snoopTransferredBytes += *xfer;
    }

    const std::string_view probe_label =
        !probeId.empty() ? std::string_view(probeId) : std::string_view(name());
    std::cout << "NP id=" << shortenPathLike(probe_label) << " t=" << now;

    const auto item_bytes = trySnooperProbeBytes(item);

    const bool have_period =
        sourceClockPeriodTicks > 0 && gem5::sim_clock::Frequency > 0;
    if (have_period) {
        const double dt_ns =
            (double)sourceClockPeriodTicks * 1e9 /
            (double)gem5::sim_clock::Frequency;
        std::cout << std::fixed << std::setprecision(3) << " dt=" << dt_ns
                  << "ns";
    } else {
        std::cout << " dt=NA";
    }

    if (item_bytes) {
        std::cout << " B=" << *item_bytes;
    } else {
        std::cout << " B=NA";
    }

    if (have_period && item_bytes) {
        const double bw_MBps =
            (double)(*item_bytes) * (double)gem5::sim_clock::Frequency /
            (1.0e6 * (double)sourceClockPeriodTicks);
        std::cout << std::fixed << std::setprecision(6) << " bw_MBps="
                  << bw_MBps;
    } else {
        std::cout << " bw_MBps=NA";
    }
    std::cout << std::defaultfloat;

    std::cout << " hook=" << hookId;
    if (sourceComponent != nullptr && sourceComponent[0] != '\0') {
        std::cout << " src=" << shortenPathLike(sourceComponent);
    }

    if (!snoopFields.empty()) {
        const auto& reg = snooperFieldRegistry();
        for (const auto& fid : snoopFields) {
            const auto it = reg.find(fid);
            if (it == reg.end()) {
                std::cout << ' ' << fid << "=UNSUPPORTED";
                continue;
            }
            if (item == nullptr) {
                std::cout << ' ' << fid << "=NA";
                continue;
            }
            std::string val;
            try {
                val = it->second.fmt(item, hookId);
            } catch (...) {
                val = "ERR";
            }
            std::cout << ' ' << fid << '=' << val;
        }
    }
    std::cout << std::endl;
}

void
NocProbe::onHookEvent(const char* hookId, const char* sourceComponent,
                      Tick sourceClockPeriodTicks)
{
    onHookEventWithItem<NocMessage>(hookId, sourceComponent, nullptr,
                                    sourceClockPeriodTicks);
}

template <typename T>
void
NocProbe::onHookEventWithItem(const char* hookId, const char* sourceComponent,
                              T* item, Tick sourceClockPeriodTicks) {
    if (hookId == nullptr) {
        return;
    }

    if (!enabled) {
        return;
    }

    const std::string_view hid(hookId);
    bool match0 = (!hookPoint0.empty() && hid == hookPoint0);
    bool match1 = (!hookPoint1.empty() && hid == hookPoint1);

    if (match0 && match1 && sourceComponent != nullptr && sourceComponent[0] != '\0') {
        const std::string src(sourceComponent);
        if (!hookPoint0Source.empty() && hookPoint0Source == src) {
            match1 = false;
        } else if (!hookPoint1Source.empty() && hookPoint1Source == src) {
            match0 = false;
        } else if (hookPoint0Source.empty()) {
            hookPoint0Source = src;
            match1 = false;
        } else if (hookPoint1Source.empty()) {
            hookPoint1Source = src;
            match0 = false;
        }
    }


    if (!match0 && !match1) {
        return;
    }

    if (probeMode == "snooper") {
        if constexpr (!std::is_same_v<T, ProbeData>) {
            return;
        }
        emitSnoopLineOnHook(std::string(hookId), static_cast<void*>(item),
                            sourceComponent, sourceClockPeriodTicks);
        return;
    }

    if (probeMode != "comparator") {
        return;
    }

    if (comparatorOp == "latency") {
            if (match0) {
                // set the item's id and store current tick
                if (debugIds.empty()) {
                    appendDebugIdPool(debugIds, nextDebugId, kInitialDebugPoolSize);
                    nextDebugId += static_cast<int>(kInitialDebugPoolSize);
                }
                const int id = debugIds.front();
                debugIds.pop_front();
                if (item != nullptr) {
                    item->setDebugId(id);
                }
                latencyTracker[id] = curTick();
            } else if (match1) {
                auto recycleId = [&](int id) {
                    auto it = latencyTracker.find(id);
                    if (it == latencyTracker.end()) {
                        return;
                    }
                    const Tick latency_ticks = curTick() - it->second;
                    const int latency_cycles = latency_ticks / 1000;
                    std::cout << "Latency: " << latency_cycles << " cycles"
                              << std::endl;
                    debugIds.push_back(id);
                };

                if (latencyHook1IdSource) {
                    if (*latencyHook1IdSource ==
                        LatencyHook1IdSource::AxisPayloadDebugIds) {
                        const NocMessage* nm = nullptr;
                        if constexpr (std::is_same_v<T, FlitType>) {
                            if (item) {
                                nm = item->get_msg_ptr().get();
                            }
                        } else if constexpr (std::is_same_v<T, NocMessage>) {
                            nm = item;
                        }
                        std::vector<int32_t> ids;
                        collectNetworkPayloadDebugIds(nm, ids);
                        for (int32_t id : ids) {
                            recycleId(static_cast<int>(id));
                        }
                        return;
                    }

                    forEachHook1FlitStyleDebugId(item, recycleId);
                    return;
                }

                // Legacy behavior for hook1 sites that are not flit/msg taps.
                if (item != nullptr && item->hasDebugId()) {
                    recycleId(item->getDebugId());
                }
            }
        } else if (comparatorOp == "path_match") {
            if (match0) {
                if (debugIds.empty()) {
                    appendDebugIdPool(debugIds, nextDebugId, kInitialDebugPoolSize);
                    nextDebugId += static_cast<int>(kInitialDebugPoolSize);
                }
                const int id = debugIds.front();
                debugIds.pop_front();
                if (item != nullptr) {
                    item->setDebugId(id);
                }
                pathMatchPending.insert(id);
                ++pathMatchHook0Observations;
                if (pathMatchTrace) {
                    std::cout << "PathMatch trace " << name() << " hook0_assign id="
                              << id << " tick=" << curTick() << std::endl;
                }
            } else if (match1) {
                auto matchHook1Id = [&](int id) {
                    if (pathMatchPending.erase(id)) {
                        ++pathMatchHook1Matches;
                        debugIds.push_back(id);
                        if (pathMatchTrace) {
                            std::cout << "PathMatch trace " << name()
                                      << " hook1_popped id=" << id
                                      << " tick=" << curTick() << std::endl;
                        }
                    } else if (pathMatchTrace) {
                        std::cout << "PathMatch trace " << name()
                                  << " hook1_stray id=" << id
                                  << " tick=" << curTick()
                                  << " (not in pending)" << std::endl;
                    }
                };

                if (latencyHook1IdSource) {
                    if (*latencyHook1IdSource ==
                        LatencyHook1IdSource::AxisPayloadDebugIds) {
                        const NocMessage* nm = nullptr;
                        if constexpr (std::is_same_v<T, FlitType>) {
                            if (item) {
                                nm = item->get_msg_ptr().get();
                            }
                        } else if constexpr (std::is_same_v<T, NocMessage>) {
                            nm = item;
                        }
                        std::vector<int32_t> ids;
                        collectNetworkPayloadDebugIds(nm, ids);
                        for (int32_t sid : ids) {
                            matchHook1Id(static_cast<int>(sid));
                        }
                        return;
                    }

                    forEachHook1FlitStyleDebugId(item, matchHook1Id);
                    return;
                }

                if (item != nullptr && item->hasDebugId()) {
                    matchHook1Id(item->getDebugId());
                }
            }
        }
}

template void NocProbe::onHookEventWithItem<NocMessage>(
    const char*, const char*, NocMessage*, Tick);
template void NocProbe::onHookEventWithItem<NocProbe::FlitType>(
    const char*, const char*, NocProbe::FlitType*, Tick);
template void NocProbe::onHookEventWithItem<State>(
    const char*, const char*, State*, Tick);
template void NocProbe::onHookEventWithItem<ProbeData>(
    const char*, const char*, ProbeData*, Tick);

void
NocProbe::onHookEvent(const char* hookId, FlitType* fl,
                      const char* sourceComponent, Tick sourceClockPeriodTicks)
{
    onHookEventWithItem(hookId, sourceComponent, fl, sourceClockPeriodTicks);
}

void
NocProbe::onHookEvent(const char* hookId, const MsgPtr& msg,
                      const char* sourceComponent, Tick sourceClockPeriodTicks)
{
    onHookEventWithItem(hookId, sourceComponent, msg.get(),
                        sourceClockPeriodTicks);
}

void
NocProbe::onHookEvent(const char* hookId, State* st,
                      const char* sourceComponent, Tick sourceClockPeriodTicks)
{
    onHookEventWithItem(hookId, sourceComponent, st, sourceClockPeriodTicks);
}

void
NocProbe::onHookEvent(const char* hookId, ProbeData* pd,
                      const char* sourceComponent, Tick sourceClockPeriodTicks)
{
    onHookEventWithItem(hookId, sourceComponent, pd, sourceClockPeriodTicks);
}


} // namespace noc
} // namespace gem5
