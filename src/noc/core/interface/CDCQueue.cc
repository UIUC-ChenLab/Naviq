#include "noc/core/interface/CDCQueue.hh"

#include "base/cprintf.hh"
#include "base/trace.hh"
#include "debug/NocCDC.hh"
#include "sim/core.hh"
#include "sim/serialize.hh"

namespace gem5 {
namespace noc {

namespace {

template <typename T, std::size_t N>
static void
serializeStdArray(CheckpointOut &cp, const char *name,
                  const std::array<T, N> &arr)
{
    ::gem5::arrayParamOut(cp, name, arr.data(), N);
}

template <typename T, std::size_t N>
static void
unserializeStdArray(CheckpointIn &cp, const char *name, std::array<T, N> &arr)
{
    ::gem5::arrayParamIn(cp, name, arr.data(), N);
}

static void
serialize_axisData(CheckpointOut &cp, const axisData &d)
{
    ::gem5::paramOut(cp, "DATA_WIDTH", d.DATA_WIDTH);
    ::gem5::paramOut(cp, "DST_ID_WIDTH", d.DST_ID_WIDTH);
    ::gem5::paramOut(cp, "ID_WIDTH", d.ID_WIDTH);
    ::gem5::arrayParamOut(cp, "tdata", d.tdata);
    ::gem5::paramOut(cp, "tid", d.tid);
    ::gem5::paramOut(cp, "tdest", d.tdest);
    ::gem5::paramOut(cp, "tkeep", d.tkeep);
    ::gem5::paramOut(cp, "tuser", (uint64_t)d.tuser);
    ::gem5::paramOut(cp, "tlast", d.tlast);
    ::gem5::paramOut(cp, "tvalid", d.tvalid);
}

static axisData
unserialize_axisData(CheckpointIn &cp)
{
    uint32_t data_width = 512, id_width = 6, dest_width = 4;
    ::gem5::paramIn(cp, "DATA_WIDTH", data_width);
    ::gem5::paramIn(cp, "ID_WIDTH", id_width);
    ::gem5::paramIn(cp, "DST_ID_WIDTH", dest_width);
    axisData d(data_width, id_width, dest_width);
    ::gem5::arrayParamIn(cp, "tdata", d.tdata);
    ::gem5::paramIn(cp, "tid", d.tid);
    ::gem5::paramIn(cp, "tdest", d.tdest);
    ::gem5::paramIn(cp, "tkeep", d.tkeep);
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "tuser", tmp);
    d.tuser = (uint8_t)tmp;
    ::gem5::paramIn(cp, "tlast", d.tlast);
    ::gem5::paramIn(cp, "tvalid", d.tvalid);
    return d;
}

static void
serialize_aximmRWAddr(CheckpointOut &cp, const aximmRWAddr &a)
{
    ::gem5::paramOut(cp, "cmd", (int)a.cmd);
    ::gem5::paramOut(cp, "id", a.id);
    ::gem5::paramOut(cp, "addr", a.addr);
    ::gem5::paramOut(cp, "len", (uint64_t)a.len);
    ::gem5::paramOut(cp, "size", (uint64_t)a.size);
    ::gem5::paramOut(cp, "burst", (int)a.burst);
    ::gem5::paramOut(cp, "lock", a.lock);
    ::gem5::paramOut(cp, "cache", (uint64_t)a.cache);
    ::gem5::paramOut(cp, "prot", (uint64_t)a.prot);
    ::gem5::paramOut(cp, "qos", (uint64_t)a.qos);
    ::gem5::paramOut(cp, "region", (uint64_t)a.region);
    ::gem5::paramOut(cp, "user", (uint64_t)a.user);
    ::gem5::paramOut(cp, "valid", a.valid);
}

static aximmRWAddr
unserialize_aximmRWAddr(CheckpointIn &cp)
{
    aximmRWAddr a;
    int cmd = 0, burst = 0;
    ::gem5::paramIn(cp, "cmd", cmd);
    ::gem5::paramIn(cp, "burst", burst);
    a.cmd = (AximmCommand)cmd;
    a.burst = (BurstType)burst;
    ::gem5::paramIn(cp, "id", a.id);
    ::gem5::paramIn(cp, "addr", a.addr);
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "len", tmp); a.len = (uint8_t)tmp;
    ::gem5::paramIn(cp, "size", tmp); a.size = (uint8_t)tmp;
    ::gem5::paramIn(cp, "lock", a.lock);
    ::gem5::paramIn(cp, "cache", tmp); a.cache = (uint8_t)tmp;
    ::gem5::paramIn(cp, "prot", tmp); a.prot = (uint8_t)tmp;
    ::gem5::paramIn(cp, "qos", tmp); a.qos = (uint8_t)tmp;
    ::gem5::paramIn(cp, "region", tmp); a.region = (uint8_t)tmp;
    ::gem5::paramIn(cp, "user", tmp); a.user = (uint8_t)tmp;
    ::gem5::paramIn(cp, "valid", a.valid);
    return a;
}

static void
serialize_aximmRWData(CheckpointOut &cp, const aximmRWData &d)
{
    ::gem5::paramOut(cp, "cmd", (int)d.cmd);
    ::gem5::paramOut(cp, "id", d.id);
    ::gem5::paramOut(cp, "resp", (int)d.resp);
    ::gem5::paramOut(cp, "last", d.last);
    ::gem5::paramOut(cp, "user", (uint64_t)d.user);
    ::gem5::paramOut(cp, "valid", d.valid);
    ::gem5::paramOut(cp, "ready", d.ready);
    serializeStdArray(cp, "data", d.data);
    ::gem5::paramOut(cp, "wstrb", d.wstrb);
}

static aximmRWData
unserialize_aximmRWData(CheckpointIn &cp)
{
    aximmRWData d;
    int cmd = 0, resp = 0;
    ::gem5::paramIn(cp, "cmd", cmd);
    ::gem5::paramIn(cp, "resp", resp);
    d.cmd = (AximmCommand)cmd;
    d.resp = (AximmResp)resp;
    ::gem5::paramIn(cp, "id", d.id);
    ::gem5::paramIn(cp, "last", d.last);
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "user", tmp); d.user = (uint8_t)tmp;
    ::gem5::paramIn(cp, "valid", d.valid);
    ::gem5::paramIn(cp, "ready", d.ready);
    unserializeStdArray(cp, "data", d.data);
    ::gem5::paramIn(cp, "wstrb", d.wstrb);
    return d;
}

static void
serialize_aximmWResp(CheckpointOut &cp, const aximmWResp &r)
{
    ::gem5::paramOut(cp, "id", r.id);
    ::gem5::paramOut(cp, "resp", (int)r.resp);
    ::gem5::paramOut(cp, "user", (uint64_t)r.user);
    ::gem5::paramOut(cp, "valid", r.valid);
}

static aximmWResp
unserialize_aximmWResp(CheckpointIn &cp)
{
    aximmWResp r;
    ::gem5::paramIn(cp, "id", r.id);
    int resp = 0;
    ::gem5::paramIn(cp, "resp", resp);
    r.resp = (AximmResp)resp;
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "user", tmp); r.user = (uint8_t)tmp;
    ::gem5::paramIn(cp, "valid", r.valid);
    return r;
}

static void
serialize_state(CheckpointOut &cp, const State *s)
{
    panic_if(!s, "CDCQueue serialize_state got null State");
    if (auto a = dynamic_cast<const axisSlaveState*>(s)) {
        ::gem5::paramOut(cp, "kind", std::string("axisSlaveState"));
        ::gem5::paramOut(cp, "tready", a->tready);
        return;
    }
    if (auto a = dynamic_cast<const axisMasterState*>(s)) {
        ::gem5::paramOut(cp, "kind", std::string("axisMasterState"));
        Serializable::ScopedCheckpointSection sec(cp, "axisData");
        serialize_axisData(cp, a->data);
        ::gem5::paramOut(cp, "ni_tready", a->ni_tready);
        ::gem5::paramOut(cp, "cdc_enqueue_ready", a->cdc_enqueue_ready);
        ::gem5::paramOut(cp, "node_input_tready", a->node_input_tready);
        return;
    }
    if (auto a = dynamic_cast<const aximmSlaveState*>(s)) {
        ::gem5::paramOut(cp, "kind", std::string("aximmSlaveState"));
        ::gem5::paramOut(cp, "arReady", a->arReady);
        ::gem5::paramOut(cp, "awReady", a->awReady);
        ::gem5::paramOut(cp, "wReady", a->wReady);
        Serializable::ScopedCheckpointSection sec1(cp, "r");
        serialize_aximmRWData(cp, a->r);
        Serializable::ScopedCheckpointSection sec2(cp, "b");
        serialize_aximmWResp(cp, a->b);
        return;
    }
    if (auto a = dynamic_cast<const aximmMasterState*>(s)) {
        ::gem5::paramOut(cp, "kind", std::string("aximmMasterState"));
        ::gem5::paramOut(cp, "rReady", a->rReady);
        ::gem5::paramOut(cp, "bReady", a->bReady);
        Serializable::ScopedCheckpointSection sec1(cp, "ar");
        serialize_aximmRWAddr(cp, a->ar);
        Serializable::ScopedCheckpointSection sec2(cp, "aw");
        serialize_aximmRWAddr(cp, a->aw);
        Serializable::ScopedCheckpointSection sec3(cp, "w");
        serialize_aximmRWData(cp, a->w);
        return;
    }
    panic("CDCQueue serialize_state: unsupported State type");
}

static std::unique_ptr<State>
unserialize_state(CheckpointIn &cp)
{
    std::string kind;
    ::gem5::paramIn(cp, "kind", kind);
    if (kind == "axisSlaveState") {
        auto s = std::make_unique<axisSlaveState>();
        ::gem5::paramIn(cp, "tready", s->tready);
        return s;
    }
    if (kind == "axisMasterState") {
        Serializable::ScopedCheckpointSection sec(cp, "axisData");
        axisData d = unserialize_axisData(cp);
        auto s = std::make_unique<axisMasterState>(d.DATA_WIDTH, d.ID_WIDTH, d.DST_ID_WIDTH);
        s->data = std::move(d);
        if (!::gem5::optParamIn(cp, "ni_tready", s->ni_tready, false)) {
            s->ni_tready = false;
        }
        if (!::gem5::optParamIn(cp, "cdc_enqueue_ready", s->cdc_enqueue_ready, false)) {
            s->cdc_enqueue_ready = false;
        }
        if (!::gem5::optParamIn(cp, "node_input_tready", s->node_input_tready, false)) {
            s->node_input_tready = false;
        }
        return s;
    }
    if (kind == "aximmSlaveState") {
        auto s = std::make_unique<aximmSlaveState>();
        ::gem5::paramIn(cp, "arReady", s->arReady);
        ::gem5::paramIn(cp, "awReady", s->awReady);
        ::gem5::paramIn(cp, "wReady", s->wReady);
        { Serializable::ScopedCheckpointSection sec(cp, "r"); s->r = unserialize_aximmRWData(cp); }
        { Serializable::ScopedCheckpointSection sec(cp, "b"); s->b = unserialize_aximmWResp(cp); }
        return s;
    }
    if (kind == "aximmMasterState") {
        auto s = std::make_unique<aximmMasterState>();
        ::gem5::paramIn(cp, "rReady", s->rReady);
        ::gem5::paramIn(cp, "bReady", s->bReady);
        { Serializable::ScopedCheckpointSection sec(cp, "ar"); s->ar = unserialize_aximmRWAddr(cp); }
        { Serializable::ScopedCheckpointSection sec(cp, "aw"); s->aw = unserialize_aximmRWAddr(cp); }
        { Serializable::ScopedCheckpointSection sec(cp, "w"); s->w = unserialize_aximmRWData(cp); }
        return s;
    }
    panic("CDCQueue unserialize_state: bad kind '%s'", kind);
}

/** CDCQueue is not a SimObject; use dprintf_flag with a synthetic context name. */
#define NOC_CDC_DPRINTF(when, fmt, ...)                                        \
    do {                                                                       \
        if (GEM5_UNLIKELY(TRACING_ON && ::gem5::debug::NocCDC)) {              \
            const std::string ctx =                                            \
                dbg ? csprintf("ni%u:%s:%s", (unsigned)dbg_ni,                 \
                               dbg_endpoint.c_str(), dbg_channel.c_str())      \
                    : std::string("cdc:unlabeled");                            \
            ::gem5::trace::getDebugLogger()->dprintf_flag(                     \
                (when), ctx, "NocCDC", (fmt), ##__VA_ARGS__);                  \
        }                                                                      \
    } while (0)

} // namespace

void
CDCQueue::setDebugContext(
    gem5::ruby::NodeID ni, std::string endpoint, std::string channel)
{
    dbg = true;
    dbg_ni = ni;
    dbg_endpoint = std::move(endpoint);
    dbg_channel = std::move(channel);
}

bool
CDCQueue::enqueue(std::unique_ptr<State> data, Tick enqueueTick) {
    if (isFull()) {
        NOC_CDC_DPRINTF(enqueueTick,
            "[CDC] ENQUEUE_DROP_FULL depth=%lu max=%d\n",
            static_cast<unsigned long>(fifo.size()), maxSize);
        return false;
    }
    const size_t depth_before = fifo.size();
    fifo.push_back({std::move(data), std::nullopt, enqueueTick, 0, false, false});
    NOC_CDC_DPRINTF(enqueueTick,
        "[CDC] ENQUEUE depth %lu->%lu (node->cdc) has_resp_info=0\n",
        static_cast<unsigned long>(depth_before),
        static_cast<unsigned long>(fifo.size()));
    return true;
}

bool
CDCQueue::enqueue(std::unique_ptr<State> data, ResponseInfo responseInfo, Tick enqueueTick) {
    if (isFull()) {
        NOC_CDC_DPRINTF(enqueueTick,
            "[CDC] ENQUEUE_DROP_FULL depth=%lu max=%d\n",
            static_cast<unsigned long>(fifo.size()), maxSize);
        return false;
    }
    const size_t depth_before = fifo.size();
    fifo.push_back({std::move(data), std::make_optional(responseInfo), enqueueTick,
                    0, false, false});
    NOC_CDC_DPRINTF(enqueueTick,
        "[CDC] ENQUEUE depth %lu->%lu (node->cdc) has_resp_info=1\n",
        static_cast<unsigned long>(depth_before),
        static_cast<unsigned long>(fifo.size()));
    return true;
}

std::unique_ptr<State>
CDCQueue::dequeue(Tick curTick) {
    if (fifo.empty()) {
        return nullptr;
    }
    FIFOEntry& entry = fifo.front();
    if (entry.dequeueTickValid && entry.dequeueTick > curTick) {
        // Intentionally no DPRINTF here: this can run every NoC tick while waiting.
        return nullptr;  // CDC delay not yet elapsed
    }
    FIFOEntry taken = std::move(fifo.front());
    fifo.pop_front();
    const Tick lat = curTick - taken.enqueueTick;
    if (taken.dequeueTickValid) {
        NOC_CDC_DPRINTF(curTick,
            "[CDC] DEQUEUE enq_tick=%llu latency_ticks=%llu depth_after=%lu "
            "min_dequeue_tick=%llu (cdc->net or cdc->node)\n",
            (unsigned long long)taken.enqueueTick, (unsigned long long)lat,
            static_cast<unsigned long>(fifo.size()),
            (unsigned long long)taken.dequeueTick);
    } else {
        NOC_CDC_DPRINTF(curTick,
            "[CDC] DEQUEUE enq_tick=%llu latency_ticks=%llu depth_after=%lu "
            "(cdc->net or cdc->node)\n",
            (unsigned long long)taken.enqueueTick, (unsigned long long)lat,
            static_cast<unsigned long>(fifo.size()));
    }
    return std::move(taken.data);
}

bool
CDCQueue::canDequeueToNoC(Tick curTick) const
{
    if (fifo.empty()) {
        return false;
    }
    const FIFOEntry& entry = fifo.front();
    if (entry.dequeueTickValid && entry.dequeueTick > curTick) {
        return false;
    }
    return true;
}

const State*
CDCQueue::peekFrontState(Tick curTick) const
{
    if (!canDequeueToNoC(curTick)) {
        return nullptr;
    }
    return fifo.front().data.get();
}

std::optional<ResponseInfo>
CDCQueue::peekResponseInfo() const {
    if (fifo.empty()) return std::nullopt;
    const FIFOEntry& entry = fifo.front();
    return entry.responseInfo;
}

bool
CDCQueue::isEmpty() {
    return fifo.empty();
}

bool
CDCQueue::isFull() {
    return fifo.size() >= maxSize;
}

void
CDCQueue::serialize(CheckpointOut &cp) const
{
    ::gem5::paramOut(cp, "maxSize", maxSize);
    ::gem5::paramOut(cp, "fifo_size", (uint64_t)fifo.size());
    for (size_t i = 0; i < fifo.size(); i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("e%d", (int)i));
        const auto &e = fifo[i];
        ::gem5::paramOut(cp, "enqueueTick", e.enqueueTick);
        ::gem5::paramOut(cp, "dequeueTick", e.dequeueTick);
        ::gem5::paramOut(cp, "dequeueTickValid", e.dequeueTickValid);
        ::gem5::paramOut(cp, "sampled", e.sampled);
        ::gem5::paramOut(cp, "hasResponseInfo", e.responseInfo.has_value());
        if (e.responseInfo.has_value()) {
            const auto &ri = e.responseInfo.value();
            Serializable::ScopedCheckpointSection sec2(cp, "responseInfo");
            ::gem5::paramOut(cp, "responseEnd", ri.responseEnd);
            ::gem5::paramOut(cp, "dataValid", ri.dataValid);
            ::gem5::paramOut(cp, "type", (int)ri.type);
            ::gem5::paramOut(cp, "id", ri.id);
            ::gem5::paramOut(cp, "delay", (uint64_t)ri.delay);
            ::gem5::paramOut(cp, "src", ri.src);
            ::gem5::arrayParamOut(cp, "dataBytes", ri.dataBytes);
            ::gem5::paramOut(cp, "tlast", ri.tlast);
            ::gem5::paramOut(cp, "tdest", ri.tdest);
        }
        Serializable::ScopedCheckpointSection sec3(cp, "state");
        serialize_state(cp, e.data.get());
    }
}

void
CDCQueue::unserialize(CheckpointIn &cp)
{
    ::gem5::paramIn(cp, "maxSize", maxSize);
    uint64_t fifo_size = 0;
    ::gem5::paramIn(cp, "fifo_size", fifo_size);
    fifo.clear();
    for (size_t i = 0; i < fifo_size; i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("e%d", (int)i));
        FIFOEntry e;
        ::gem5::paramIn(cp, "enqueueTick", e.enqueueTick);
        ::gem5::paramIn(cp, "dequeueTick", e.dequeueTick);
        ::gem5::paramIn(cp, "dequeueTickValid", e.dequeueTickValid);
        ::gem5::paramIn(cp, "sampled", e.sampled);
        bool hasRi = false;
        ::gem5::paramIn(cp, "hasResponseInfo", hasRi);
        if (hasRi) {
            ResponseInfo ri;
            Serializable::ScopedCheckpointSection sec2(cp, "responseInfo");
            ::gem5::paramIn(cp, "responseEnd", ri.responseEnd);
            ::gem5::paramIn(cp, "dataValid", ri.dataValid);
            int type = 0;
            ::gem5::paramIn(cp, "type", type);
            ri.type = (ResponseInfo::Type)type;
            ::gem5::paramIn(cp, "id", ri.id);
            uint64_t delay = 0;
            ::gem5::paramIn(cp, "delay", delay);
            ri.delay = Cycles(delay);
            ::gem5::paramIn(cp, "src", ri.src);
            ::gem5::arrayParamIn(cp, "dataBytes", ri.dataBytes);
            ::gem5::paramIn(cp, "tlast", ri.tlast);
            ::gem5::paramIn(cp, "tdest", ri.tdest);
            e.responseInfo = ri;
        } else {
            e.responseInfo = std::nullopt;
        }
        {
            Serializable::ScopedCheckpointSection sec3(cp, "state");
            e.data = unserialize_state(cp);
        }
        // keep dequeue gating behavior consistent: if a dequeueTick was recorded,
        // preserve it.
        fifo.push_back(std::move(e));
    }
}

}}
