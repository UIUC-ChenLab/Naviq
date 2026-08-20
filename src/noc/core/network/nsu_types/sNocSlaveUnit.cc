#include "noc/core/network/nsu_types/sNocSlaveUnit.hh"

#include "noc/core/network/nsu_types/AxisDepacketizer.hh"
#include "noc/core/network/NocMessageBuffer.hh"
#include "base/logging.hh"
#include "base/str.hh"
#include "sim/eventq.hh"
#include "debug/NocTiming.hh"
#include "debug/NocDebugVerbose.hh"
#include <algorithm>
#include <bit>
#include "noc/core/network/NocStreamMsg.hh"
#include <memory>
#include "sim/serialize.hh"
#include <iomanip>


namespace gem5 {
namespace noc {
namespace garnet {

namespace
{

static std::string
findSecWithKey(CheckpointIn &cp, const std::string &obj, const char *key)
{
    if (cp.entryExists(obj, key)) {
        return obj;
    }
    const std::string inp0 = obj + ".ni_inp_0";
    if (cp.entryExists(inp0, key)) {
        return inp0;
    }
    for (int j = 0; j < 64; j++) {
        const std::string sec = obj + ".ni_inp_0.fb_flit_" +
            std::to_string(j) + ".flt_route_net_dest";
        if (cp.entryExists(sec, key)) {
            return sec;
        }
    }
    return "";
}

template <typename T>
static void
paramInSecString(CheckpointIn &cp, const std::string &sec,
    const char *name, T &v)
{
    std::string s;
    fatal_if(!cp.find(sec, name, s),
        "Can't unserialize '%s:%s'", sec, name);
    fatal_if(!ParseParam<T>::parse(s, v),
        "sNocSlaveUnit: bad value for %s", name);
}

static void
arrayParamInSecU8(CheckpointIn &cp, const std::string &sec,
    const char *name, uint8_t *data, size_t n)
{
    std::string s;
    fatal_if(!cp.find(sec, name, s),
        "Can't unserialize '%s:%s'", sec, name);
    std::vector<std::string> tok;
    tokenize(tok, s, ' ');
    fatal_if(tok.size() != n,
        "sNocSlaveUnit: %s token count %zu expected %zu", name, tok.size(), n);
    for (size_t i = 0; i < n; i++) {
        fatal_if(!to_number(tok[i], data[i]),
            "sNocSlaveUnit: parse %s[%zu]", name, i);
    }
}

} // namespace

namespace
{

} // namespace

sNocSlaveUnit::sNocSlaveUnit(const Params &p) : NocSlaveUnit(p)
{
    S_DATA_WIDTH = p.data_width;
}

void
sNocSlaveUnit::serialize(CheckpointOut &cp) const
{
    NocSlaveUnit::serialize(cp);
    ::gem5::paramOut(cp, "S_DATA_WIDTH", (uint64_t)S_DATA_WIDTH);
    std::vector<int> packet_ids;
    packet_ids.reserve(depacketizeWriteDataAggregateByPacket.size());
    for (const auto& entry : depacketizeWriteDataAggregateByPacket) {
        packet_ids.push_back(entry.first);
    }
    std::sort(packet_ids.begin(), packet_ids.end());
    ::gem5::paramOut(cp, "depacketizeWriteDataAggregateByPacketSize",
                     (uint64_t)packet_ids.size());
    for (size_t i = 0; i < packet_ids.size(); ++i) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("depacketizeWriteDataAggregatePacket%u", (unsigned)i));
        const int packet_id = packet_ids[i];
        const auto& aggregate = depacketizeWriteDataAggregateByPacket.at(packet_id);
        ::gem5::paramOut(cp, "packet_id", packet_id);
        ::gem5::arrayParamOut(cp, "aggregateData", aggregate.data(),
                              aggregate.size());
    }
}

void
sNocSlaveUnit::unserialize(CheckpointIn &cp)
{
    NocSlaveUnit::unserialize(cp);
    const std::string obj = name();
    const std::string sec = findSecWithKey(cp, obj, "S_DATA_WIDTH");
    fatal_if(sec.empty(),
        "sNocSlaveUnit %s: S_DATA_WIDTH not in checkpoint", obj);
    uint64_t tmp = 0;
    paramInSecString(cp, sec, "S_DATA_WIDTH", tmp);
    S_DATA_WIDTH = (uint32_t)tmp;
    depacketizeWriteDataAggregateByPacket.clear();

    if (!cp.entryExists(sec, "depacketizeWriteDataAggregateByPacketSize")) {
        // Checkpoints written before packet-scoped AXIS reconstruction cannot
        // identify the owner of an in-progress aggregate. Start clean rather
        // than assigning those bytes to a different interleaved packet.
        warn("sNocSlaveUnit %s restoring legacy AXIS checkpoint state without "
             "packet-scoped aggregation; discarding transient partial beat",
             name());
        return;
    }

    paramInSecString(cp, sec, "depacketizeWriteDataAggregateByPacketSize", tmp);
    for (uint64_t i = 0; i < tmp; ++i) {
        const std::string packet_sec = sec + ".depacketizeWriteDataAggregatePacket" +
            std::to_string(i);
        int packet_id = 0;
        paramInSecString(cp, packet_sec, "packet_id", packet_id);
        std::array<uint8_t, 64> aggregate{};
        arrayParamInSecU8(cp, packet_sec, "aggregateData", aggregate.data(),
                          aggregate.size());
        depacketizeWriteDataAggregateByPacket.emplace(packet_id, aggregate);
    }
}


bool
sNocSlaveUnit::depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit)
{

    std::vector<uint8_t> raw_data;
    MsgPtr msg = flit->get_msg_ptr();


    //TODO actually see if its a write or read request, different processing for each
    // but how to not block the other, if they both come in on same network link?
    // if we block the read flit, it'll just keep trying the read flit

    Payload temp = flit->get_msg_ptr()->getData();
    axisPayload payload;

    if(axisPayload* p = std::get_if<axisPayload>(&temp)) {
        payload = *p;
    } else {
        panic("sNocSlaveUnit::depacketizeFlit: Unsupported payload type");
    }

    if (!depacketizeWriteDataFlit(flit)) {
        return false; //failed to depacketize write data
    }

    DPRINTF(NocTiming,"AXIS NSU %d depacketized flit %s\n",m_id, *flit);
    return true;
}


bool
sNocSlaveUnit::depacketizeWriteDataFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit){

    if ((S_DATA_WIDTH % 8) != 0) {
        panic("sNocSlaveUnit: S_DATA_WIDTH must be multiple of 8 bits");
    }

    auto NPPMsgBase = flit->get_msg_ptr();
    auto NPPMsg = std::dynamic_pointer_cast<NocStreamMsg>(NPPMsgBase);
    if (!NPPMsg)
        panic("Expected NocStreamMsg inside write request flit");

    const int packet_id = flit->getPacketID();
    const uint8_t flit_id = static_cast<uint8_t>(flit->get_id());
    panic_if(flit_id >= NPPMsg->getNumFlits(),
             "sNocSlaveUnit received flit %u outside packet %d length %u",
             flit_id, packet_id, NPPMsg->getNumFlits());
    const bool is_tail_flit = ((NPPMsg->getNumFlits() - 1) == flit_id);
    std::array<uint8_t, 16> flit_data =
        flit->get_msg_ptr()->getFlitData(flit_id);
    auto aggregate_it =
        depacketizeWriteDataAggregateByPacket.try_emplace(packet_id).first;
    std::array<uint8_t, 64>& payload_data = aggregate_it->second;
    if (flit_id == 0) {
        payload_data.fill(0);
    }
    Payload pl = NPPMsg->getData();
    auto* ap = std::get_if<axisPayload>(&pl);
    if (!ap) {
        panic("sNocSlaveUnit::depacketizeWriteDataFlit: Expected axisPayload in NocStreamMsg");
    }
    uint32_t src_nmu = NPPMsg->getSourceNiID();
    const int32_t fallback_dbg = NPPMsg->getDebugId();
    AxisDepacketizedFlit depacketized = depacketizeAxisPayloadFlit(
        *ap, S_DATA_WIDTH, payload_data, flit_id, NPPMsg->getNumFlits(),
        NPPMsg->containsLast(), flit_data, fallback_dbg);

    if (!sendNWriteDataMsgs(createNWriteDataMsgs(
            std::move(depacketized.payloads), src_nmu, depacketized.debugIds,
            fallback_dbg))) {
        return false;
    }
    if (is_tail_flit) {
        depacketizeWriteDataAggregateByPacket.erase(packet_id);
    }
    return true;
}

std::vector<MsgPtr>
sNocSlaveUnit::createNWriteDataMsgs(std::vector<axisData> payloads,
                                    uint32_t src_nmu,
                                    const std::vector<std::vector<int32_t>>& per_payload_debug_ids,
                                    int32_t fallback_debug_id)
{
    std::vector<MsgPtr> ret;

    for (size_t i = 0; i < payloads.size(); ++i) {
        auto mp = std::make_unique<MessagePayload>(payloads[i]);
        auto stream_msg = std::shared_ptr<NocStreamMsg>(
            new NocStreamMsg(clockEdge(), nullptr, std::move(mp)));
        stream_msg->setSourceNiID(src_nmu);
        const std::vector<int32_t> dbg_ids = (i < per_payload_debug_ids.size())
            ? per_payload_debug_ids[i]
            : std::vector<int32_t>{};
        if (!dbg_ids.empty()) {
            stream_msg->setDebugIds(dbg_ids);
            stream_msg->setDebugId(dbg_ids.front());
        } else {
            stream_msg->setDebugId(fallback_debug_id);
        }
        ret.push_back(stream_msg);
    }

    return ret;
}

bool
sNocSlaveUnit::sendNWriteDataMsgs(std::vector<MsgPtr> Msgs){

    Tick curTime = clockEdge();

    if (Msgs.size() == 0)
        return true;

    auto *wbuf = outNode_ptr[garnet::W_VNET];
    panic_if(!wbuf, "sNocSlaveUnit::sendNWriteDataMsgs: W outNode null");

    const unsigned max_sz = wbuf->getMaxSize();
    panic_if(max_sz > 0 && Msgs.size() > max_sz,
        "sNocSlaveUnit %s: sendNWriteDataMsgs needs %zu slots but W "
        "MessageBuffer max is %u (narrow S_DATA_WIDTH can emit many "
        "beats per flit; increase NocInterface buffer_size)",
        name(), Msgs.size(), max_sz);

    DPRINTF(NocDebugVerbose,
        "[NSU outNode W] ni=%d msgbuf_size=%u need_slots=%zu tick=%llu\n",
        m_id, wbuf->getSize(curTime), Msgs.size(),
        (unsigned long long)curTime);

    if (!wbuf->areNSlotsAvailable(Msgs.size(), curTime)) {
        DPRINTF(NocDebugVerbose,
            "[NSU outNode W FULL] ni=%d msgbuf_size=%u need_slots=%zu "
            "tick=%llu\n",
            m_id, wbuf->getSize(curTime), Msgs.size(),
            (unsigned long long)curTime);
        return false;
    }

    // Space is available. Enqueue messages to output buffer to tile controller.
    for (int i=0; i<Msgs.size(); i++){
        wbuf->enqueue(Msgs[i], curTime,
                    0,// cyclesToTicks(Cycles(1)),
                    m_net_ptr->getRandomization(),
                    m_net_ptr->getWarmupEnabled());
    }

    return true;

}

void
sNocSlaveUnit::print(std::ostream& out) const
{
    out << "[sNocSlaveUnit " << m_id << "]";
}

}
}
}
