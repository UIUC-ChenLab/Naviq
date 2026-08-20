#include "noc/core/network/nmu_types/sNocMasterUnit.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/core/network/NocGarnetNetwork.hh"

#include "debug/NocDebugVerbose.hh"

#include "sim/serialize.hh"

namespace gem5 {
namespace noc {
namespace garnet {

namespace {

template <typename T>
static void
paramInRootOrNiInp0(CheckpointIn &cp, const std::string &obj,
    const char *name, T &v)
{
    std::string s;
    if (cp.find(obj, name, s)) {
        fatal_if(!ParseParam<T>::parse(s, v),
            "sNocMasterUnit: bad value for %s", name);
        return;
    }
    const std::string niinp = obj + ".ni_inp_0";
    fatal_if(!cp.find(niinp, name, s),
        "Can't unserialize '%s:%s' (also tried %s)", obj, name, niinp);
    fatal_if(!ParseParam<T>::parse(s, v),
        "sNocMasterUnit: bad value for %s", name);
}
static void
serialize_route(CheckpointOut &cp, const NocRouteInfo &r)
{
    ::gem5::paramOut(cp, "src_ni", r.src_ni);
    ::gem5::paramOut(cp, "dest_ni", r.dest_ni);
}

static void
unserialize_route(CheckpointIn &cp, NocRouteInfo &r)
{
    ::gem5::paramIn(cp, "src_ni", r.src_ni);
    ::gem5::paramIn(cp, "dest_ni", r.dest_ni);
}

static void
serialize_msgptr_axis(CheckpointOut &cp, const MsgPtr &mp)
{
    bool valid = (bool)mp;
    ::gem5::paramOut(cp, "valid", valid);
    if (!valid)
        return;

    const auto *m = dynamic_cast<const NocStreamMsg*>(mp.get());
    fatal_if(!m, "sNocMasterUnit checkpoint only supports NocStreamMsg");

    ::gem5::paramOut(cp, "time", (uint64_t)m->getTime());
    ::gem5::paramOut(cp, "delayedTicks", (uint64_t)m->getDelayedTicks());
    ::gem5::paramOut(cp, "vnet", m->getVnet());
    ::gem5::paramOut(cp, "beatSize", (uint64_t)m->getBeatSize());
    ::gem5::paramOut(cp, "numFlits", (uint64_t)m->getNumFlits());
    ::gem5::paramOut(cp, "srcNiId", (uint64_t)m->getSourceNiID());
    ::gem5::paramOut(cp, "destNiId", (uint64_t)m->getDestNiID());
    ::gem5::paramOut(cp, "mode", (uint64_t)m->getMode());

    Payload pl = m->getData();
    auto *ap = std::get_if<axisPayload>(&pl);
    fatal_if(!ap, "sNocMasterUnit expected axisPayload inside NocStreamMsg");

    Serializable::ScopedCheckpointSection sec(cp, "axisPayload");
    ::gem5::paramOut(cp, "totalBytes", (uint64_t)ap->totalBytes);
    ::gem5::paramOut(cp, "last", ap->last);
    ::gem5::paramOut(cp, "beatsSize", (uint64_t)ap->beats.size());
    for (size_t i = 0; i < ap->beats.size(); i++) {
        Serializable::ScopedCheckpointSection sec2(cp, csprintf("b%d", (int)i));
        const axisData &d = ap->beats[i];
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
}

static MsgPtr
unserialize_msgptr_axis(CheckpointIn &cp)
{
    bool valid = false;
    ::gem5::paramIn(cp, "valid", valid);
    if (!valid)
        return MsgPtr();

    uint64_t time = 0, delayed = 0, beatSize = 0, numFlits = 0, srcNiId = 0, destNiId = 0, mode = 0;
    int vnet = -1;
    ::gem5::paramIn(cp, "time", time);
    ::gem5::paramIn(cp, "delayedTicks", delayed);
    ::gem5::paramIn(cp, "vnet", vnet);
    ::gem5::paramIn(cp, "beatSize", beatSize);
    ::gem5::paramIn(cp, "numFlits", numFlits);
    ::gem5::paramIn(cp, "srcNiId", srcNiId);
    ::gem5::paramIn(cp, "destNiId", destNiId);
    ::gem5::paramIn(cp, "mode", mode);

    axisPayload ap;
    {
        Serializable::ScopedCheckpointSection sec(cp, "axisPayload");
        uint64_t totalBytes = 0, beatsSize = 0;
        ::gem5::paramIn(cp, "totalBytes", totalBytes);
        ::gem5::paramIn(cp, "last", ap.last);
        ::gem5::paramIn(cp, "beatsSize", beatsSize);
        ap.totalBytes = (uint16_t)totalBytes;
        ap.beats.clear();
        ap.beats.reserve(beatsSize);
        for (size_t i = 0; i < beatsSize; i++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("b%d", (int)i));
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
            ::gem5::paramIn(cp, "tuser", tmp); d.tuser = (uint8_t)tmp;
            ::gem5::paramIn(cp, "tlast", d.tlast);
            ::gem5::paramIn(cp, "tvalid", d.tvalid);
            ap.beats.push_back(d);
        }
    }

    auto pl = std::make_unique<Payload>(std::move(ap));
    auto msg = std::shared_ptr<NocStreamMsg>(new NocStreamMsg((Tick)time, nullptr, std::move(pl)));
    msg->setDelayedTicks((Tick)delayed);
    msg->setVnet(vnet);
    msg->setBeatSize((uint8_t)beatSize);
    msg->setNumFlits((uint16_t)numFlits);
    msg->setSourceNiID((uint16_t)srcNiId);
    msg->setDestNiID((uint16_t)destNiId);
    msg->setMode(static_cast<NocStreamMsg::NocStreamMsgMode>(mode));
    return msg;
}
} // namespace

sNocMasterUnit::sNocMasterUnit(const Params &p) : NocMasterUnit(p), dequeueIntermediateEvent(*this)
{
    writeBuffer.setHeadReadyHandler([this](){
        this->bufferHeadReadyHandler();
    });
}

void
sNocMasterUnit::serialize(CheckpointOut &cp) const
{
    NocMasterUnit::serialize(cp);

    ::gem5::paramOut(cp, "inQueueBytes", inQueueBytes);

    ::gem5::paramOut(cp, "currValid", currNPPInfo.valid);
    ::gem5::paramOut(cp, "currFlitNum", currNPPInfo.flit_num);
    ::gem5::paramOut(cp, "currPacketId", currNPPInfo.packet_id);
    ::gem5::paramOut(cp, "currVc", currNPPInfo.vc);
    ::gem5::paramOut(cp, "currNumFlits", currNPPInfo.num_flits);
    ::gem5::paramOut(cp, "currLastFlitSize", currNPPInfo.last_flit_size_bytes);
    // Only trust oPort while a packet is in flight; otherwise it may be
    // unset or stale (must not deref for checkpoint).
    const int oport_router =
        (currNPPInfo.valid && currNPPInfo.oPort)
            ? currNPPInfo.oPort->routerID()
            : -1;
    ::gem5::paramOut(cp, "currOPortRouter", oport_router);

    bool ev_scheduled = dequeueIntermediateEvent.scheduled();
    ::gem5::paramOut(cp, "deqEvScheduled", ev_scheduled);
    Tick when = ev_scheduled ? dequeueIntermediateEvent.when() : 0;
    ::gem5::paramOut(cp, "deqEvWhen", (uint64_t)when);

    // After all scalars are written, write sub-sections.
    {
        Serializable::ScopedCheckpointSection sec(cp, "writeBuffer");
        writeBuffer.serialize(cp);
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "currRoute");
        serialize_route(cp, currNPPInfo.route);
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "currMsg");
        serialize_msgptr_axis(cp, currNPPInfo.message);
    }
}

void
sNocMasterUnit::unserialize(CheckpointIn &cp)
{
    NocMasterUnit::unserialize(cp);

    const std::string obj = name();

    // Scalars may be stored on the NI root or under the NI's ni_inp_0
    // subsection (IniFile assigns trailing paramOut lines to the last
    // opened [section] header during checkpoint generation).
    paramInRootOrNiInp0(cp, obj, "inQueueBytes", inQueueBytes);
    paramInRootOrNiInp0(cp, obj, "currValid", currNPPInfo.valid);
    paramInRootOrNiInp0(cp, obj, "currFlitNum", currNPPInfo.flit_num);
    paramInRootOrNiInp0(cp, obj, "currPacketId", currNPPInfo.packet_id);
    paramInRootOrNiInp0(cp, obj, "currVc", currNPPInfo.vc);
    paramInRootOrNiInp0(cp, obj, "currNumFlits", currNPPInfo.num_flits);
    paramInRootOrNiInp0(cp, obj, "currLastFlitSize",
        currNPPInfo.last_flit_size_bytes);
    int router_id = -1;
    paramInRootOrNiInp0(cp, obj, "currOPortRouter", router_id);
    bool ev_scheduled = false;
    uint64_t when_u = 0;
    paramInRootOrNiInp0(cp, obj, "deqEvScheduled", ev_scheduled);
    paramInRootOrNiInp0(cp, obj, "deqEvWhen", when_u);

    {
        Serializable::ScopedCheckpointSection sec(cp, "writeBuffer");
        writeBuffer.unserialize(cp, outPorts);
        writeBuffer.setHeadReadyHandler([this](){
            this->bufferHeadReadyHandler();
        });
    }

    {
        Serializable::ScopedCheckpointSection sec(cp, "currRoute");
        unserialize_route(cp, currNPPInfo.route);
    }
    {
        Serializable::ScopedCheckpointSection sec(cp, "currMsg");
        currNPPInfo.message = unserialize_msgptr_axis(cp);
    }

    currNPPInfo.oPort = nullptr;
    if (router_id >= 0) {
        for (auto *op : outPorts) {
            if (op && op->routerID() == router_id) {
                currNPPInfo.oPort = op;
                break;
            }
        }
    }
    if (ev_scheduled && currNPPInfo.valid && !dequeueIntermediateEvent.scheduled()) {
        Tick when = (Tick)when_u;
        if (when < curTick())
            when = curTick();
        schedule(dequeueIntermediateEvent, when);
    }
}


bool
sNocMasterUnit::getAxiWReady(bool upstreamValid, axisMasterState upstreamState) {
    // look at the num of valid tdata bytes via tkeep to determine if write buffer has enough space 
    const uint16_t inFlightBytes = currNPPInfo.valid
        ? static_cast<uint16_t>( (currNPPInfo.num_flits - currNPPInfo.flit_num - 1) * 16 + currNPPInfo.last_flit_size_bytes)
        : 0;
        // TODO: set data bit width at initialization beginning instead of getting it every single time 
        // TODO: is currEndPointState always ready?

    // bool current_handshake = upstreamValid && internal_w_ready; // TODO: implement this

    return (writeBuffer.getSize() +
            upstreamState.data.getTotalByteSize() +
            inFlightBytes +
            upstreamState.getDataBitWidth()/8 +
            inQueueBytes)
            <= 512;
}

void
sNocMasterUnit::bufferHeadReadyHandler() {
    // If we're already draining a packet, do not start a new one
    if (currNPPInfo.valid) {
        return;
    }
    
    std::unique_ptr<axisPayload> packet; 

    int vc = 0;
    currNPPInfo.oPort = nullptr;
    int32_t dbg_id = -1;
    packet = writeBuffer.popNextPacket(&vc, &currNPPInfo.oPort, &dbg_id);
    
    // flit per 16B of write data, +1 for any <16B left over if not divisible by 16
    // flit is 128 bits of data, npp is 256 bytes
    currNPPInfo.num_flits = (packet->totalBytes / 16) + (packet->totalBytes % 16 == 0 ? 0 : 1);
    currNPPInfo.last_flit_size_bytes = packet->totalBytes % 16 == 0 ? 16 : packet->totalBytes % 16;

    currNPPInfo.packet_id = m_net_ptr->getNextPacketID();

    // Get tdest from the first beat of the packet to determine destination
    int tdest = 0;  // default
    if (!packet->beats.empty()) {
        tdest = packet->beats[0].tdest;
    }
    
    // Look up the global destination NI from the tdest value
    NocGarnetNetwork* garnet_net = dynamic_cast<NocGarnetNetwork*>(m_net_ptr);
    int dest_ni = garnet_net ? garnet_net->getAxisDestNi(m_id, tdest) : -1;
    
    if (dest_ni < 0) {
        warn("sNocMasterUnit %d: No valid dest_ni for tdest=%d, using 0", m_id, tdest);
        dest_ni = 0;
    }
    
    // Look up the correct VC for this path - AXIS uses req_type=1 (WRITE)
    if (garnet_net) {
        currNPPInfo.vc = garnet_net->getPathVC(m_id, dest_ni, 1);  // 1 = WRITE type
    }
    
    DPRINTF(NocTiming, "AXIS NMU %d sending packet to dest_ni=%d (tdest=%d, vc=%d)\n", 
            m_id, dest_ni, tdest, currNPPInfo.vc);

    currNPPInfo.route.vnet = garnet::W_VNET;
    currNPPInfo.route.src_ni = m_id;
    currNPPInfo.route.src_router =
        currNPPInfo.oPort ? currNPPInfo.oPort->routerID() : -1;
    currNPPInfo.route.dest_ni = dest_ni;
    currNPPInfo.route.dest_router =
        m_net_ptr->get_router_id(dest_ni, garnet::W_VNET);
    currNPPInfo.route.hops_traversed = -1;

    // create a new NocStreamMsg, whose ptr will be passed along for every flit
    // Compute beat size before moving packet contents
    uint8_t beat_size_bytes = packet->beats[0].DATA_WIDTH/8;
    
    // Wrap axisPayload in the generic Payload variant and pass as unique_ptr
    auto pload = std::make_unique<Payload>(std::move(*packet));
    currNPPInfo.message = std::shared_ptr<NocStreamMsg>(
        new NocStreamMsg(clockEdge(), nullptr, std::move(pload)));
    currNPPInfo.message->setDebugId(dbg_id);

    //save vnet for receiving interface
    currNPPInfo.message->setBeatSize(beat_size_bytes);
    currNPPInfo.message->setNumFlits(currNPPInfo.num_flits);

    // set up ongoing packet state
    currNPPInfo.valid = true;
    currNPPInfo.flit_num = 0;

    // Schedule first flit injection next cycle
    schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));

    // for (int i=0; i<num_flits; i++){
    //     gem5::ruby::garnet::flit<NocMessage, NocRouteInfo> *fl = new gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>(
    //         packet_id,
    //         i, // id 0, each flit by itself
    //         vc, // virtual channel
    //         -1, // vnet
    //         route,
    //         num_flits,
    //         message,
    //         0, //change bWidth if need to serialize/deserialize
    //         oPort ? oPort->bitWidth() : 0, curTick());

    //     injectFlit(fl, -1, message, vc);
    // }
}

void sNocMasterUnit::dequeueIntermediate() {

    if (currNPPInfo.flit_num >= currNPPInfo.num_flits) {
        return;
    }

    // Backpressure: NI output VC queue capped at kNiOutVcMaxFlits flits.
    if (niOutVcs[currNPPInfo.vc].isFull()) {
        schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));
        return;
    }

    DPRINTF(NocTiming, "AXIS NMU %d Dequeuing flit from intermediate buffer\n", m_id);
    gem5::ruby::garnet::flit<NocMessage, NocRouteInfo> *fl =
        new gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>(
            currNPPInfo.packet_id,
            currNPPInfo.flit_num,
            currNPPInfo.vc,
            W_VNET,
            currNPPInfo.route,
            currNPPInfo.num_flits,
            currNPPInfo.message,
            0,
            currNPPInfo.oPort ? currNPPInfo.oPort->bitWidth() : 0, curTick());

    DPRINTF(NocDebugVerbose,
        "[NMU niOutVc] ni=%d vc=%d vnet=%d flit_buf_size=%d "
        "flit_i=%d/%d writebuf_bytes=%u tick=%llu\n",
        m_id, currNPPInfo.vc, W_VNET,
        niOutVcs[currNPPInfo.vc].getSize(),
        currNPPInfo.flit_num, currNPPInfo.num_flits,
        (unsigned)writeBuffer.getSize(),
        (unsigned long long)curTick());

    if (!injectFlit(fl, W_VNET, currNPPInfo.message, currNPPInfo.vc)) {
        delete fl;
        schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));
        return;
    }

    if (currNPPInfo.flit_num == currNPPInfo.num_flits - 1) {
        currNPPInfo.valid = false;
        currNPPInfo.oPort = nullptr;
        writeBuffer.checkDequeueReady();
    } else {
        currNPPInfo.flit_num++;
        schedule(dequeueIntermediateEvent, clockEdge(Cycles(1)));
    }
}

bool
sNocMasterUnit::flitisizeMessage(MsgPtr msg_ptr, int vnet) {
    // Convert a high-level message into flits for transmission
    // Implement flit creation and enqueue into the appropriate VC

    //save vnet for receiving interface
    msg_ptr->setVnet(vnet);

    auto strm_msg_ptr = dynamic_cast<NocStreamMsg*>(msg_ptr.get());
    if (!strm_msg_ptr) {
        panic("Failed to cast MsgPtr to NocStreamMsg");
    }

    axisData data;

    MessagePayload p = strm_msg_ptr->getPayload();

    if(auto* temp = std::get_if<axisData>(&p)) {
        data = *temp;
    } else {
        panic("sNocMasterUnit::flitisizeMessage: Unsupported payload type");
    }

    OutputPort *oPort = getOutportForVnet(vnet);
    assert(oPort);

    int vc = 0;
    // int cmd_int = 1; // TODO: CHECK IF THIS IS RIGHT
    // TODO: make sure to check 64 outstanding writes
    writeBuffer.add(data, oPort, vc, msg_ptr->getDebugId());
    inQueueBytes -= data.getTotalByteSize();

    m_ni_out_vcs_enqueue_time[vc] = curTick();
    outVcState[vc].setState(gem5::ruby::garnet::ACTIVE_, curTick());
    DPRINTF(NocTiming, "AXIS NMU %d Queued data to be sent out\n", m_id);

    return true;

}


void
sNocMasterUnit::print(std::ostream& out) const
{
    out << "[AXIS NocMasterUnit " << m_id << "]";
}

}
}
}
