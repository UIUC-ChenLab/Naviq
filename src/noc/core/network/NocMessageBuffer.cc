/*
 * Copyright (c) 2019-2021 ARM Limited
 * All rights reserved.
 *
 * The license below extends only to copyright in the software and shall
 * not be construed as granting a license to any other intellectual
 * property including but not limited to intellectual property relating
 * to a hardware implementation of the functionality of the software
 * licensed hereunder.  You may use the software subject to the license
 * terms below provided that you ensure that this notice is replicated
 * unmodified and in its entirety in all distributions of the software,
 * modified or unmodified, in source code or in binary form.
 *
 * Copyright (c) 1999-2008 Mark D. Hill and David A. Wood
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

 #include "noc/core/network/NocMessageBuffer.hh"

 #include <cassert>
#include <memory>
#include <sstream>
 #include <variant>

 #include "base/cprintf.hh"
 #include "base/logging.hh"
 #include "base/random.hh"
 #include "base/stl_helpers.hh"
 #include "base/str.hh"
 #include "debug/RubyQueue.hh"
 #include "noc/core/network/NocMemoryMsg.hh"
 #include "noc/lib/axi/AXITypes.hh"
#include "noc/core/network/NocStreamMsg.hh"
#include "sim/serialize.hh"

 namespace gem5
 {
    enum class MessageRandomization;

 namespace noc
 {

 using stl_helpers::operator<<;

 MessageBuffer::MessageBuffer(const Params &p)
     : SimObject(p), m_stall_map_size(0), m_max_size(p.buffer_size),
     m_max_dequeue_rate(p.max_dequeue_rate), m_dequeues_this_cy(0),
     m_time_last_time_size_checked(0),
     m_time_last_time_enqueue(0), m_time_last_time_pop(0),
     m_last_arrival_time(0), m_last_message_strict_fifo_bypassed(false),
     m_strict_fifo(p.ordered),
     m_randomization(p.randomization),
     m_allow_zero_latency(p.allow_zero_latency),
     m_routing_priority(p.routing_priority),
     ADD_STAT(m_not_avail_count, statistics::units::Count::get(),
              "Number of times this buffer did not have N slots available"),
     ADD_STAT(m_msg_count, statistics::units::Count::get(),
              "Number of messages passed the buffer"),
     ADD_STAT(m_buf_msgs, statistics::units::Rate<
                 statistics::units::Count, statistics::units::Tick>::get(),
              "Average number of messages in buffer"),
     ADD_STAT(m_stall_time, statistics::units::Tick::get(),
              "Total number of ticks messages were stalled in this buffer"),
     ADD_STAT(m_stall_count, statistics::units::Count::get(),
              "Number of times messages were stalled"),
     ADD_STAT(m_avg_stall_time, statistics::units::Rate<
                 statistics::units::Tick, statistics::units::Count>::get(),
              "Average stall ticks per message"),
     ADD_STAT(m_occupancy, statistics::units::Rate<
                 statistics::units::Ratio, statistics::units::Tick>::get(),
              "Average occupancy of buffer capacity")
 {
     m_msg_counter = 0;
     m_consumer = NULL;
     m_size_last_time_size_checked = 0;
     m_size_at_cycle_start = 0;
     m_stalled_at_cycle_start = 0;
     m_msgs_this_cycle = 0;
     m_priority_rank = 0;

     m_stall_msg_map.clear();
     m_input_link_id = 0;
     m_vnet_id = 0;

     m_buf_msgs = 0;
     m_num_msgs = 0; //actual current msg count
     m_stall_time = 0;

     m_dequeue_callback = nullptr;

     // stats
     m_not_avail_count
         .flags(statistics::nozero);

     m_msg_count
         .flags(statistics::nozero);

     m_buf_msgs
         .flags(statistics::nozero);

     m_stall_count
         .flags(statistics::nozero);

     m_avg_stall_time
         .flags(statistics::nozero | statistics::nonan);

     m_occupancy
         .flags(statistics::nozero);

     m_stall_time
         .flags(statistics::nozero);

     if (m_max_size > 0) {
         m_occupancy = m_buf_msgs / m_max_size;
     } else {
         m_occupancy = 0;
     }

     m_avg_stall_time = m_stall_time / m_msg_count;
 }

 unsigned int
 MessageBuffer::getSize(Tick curTime)
 {
     if (m_time_last_time_size_checked != curTime) {
         m_time_last_time_size_checked = curTime;
         m_size_last_time_size_checked = m_prio_heap.size();
     }

     return m_size_last_time_size_checked;
 }

 bool
 MessageBuffer::areNSlotsAvailable(unsigned int n, Tick current_time)
 {

     // fast path when message buffers have infinite size
     if (m_max_size == 0) {
         return true;
     }

     // determine the correct size for the current cycle
     // pop operations shouldn't effect the network's visible size
     // until schd cycle, but enqueue operations effect the visible
     // size immediately
     unsigned int current_size = 0;
     unsigned int current_stall_size = 0;

     if (m_time_last_time_pop < current_time) {
         // no pops this cycle - heap and stall queue size is correct
         current_size = m_prio_heap.size();
         current_stall_size = m_stall_map_size;
     } else {
         if (m_time_last_time_enqueue < current_time) {
             // no enqueues this cycle - m_size_at_cycle_start is correct
             current_size = m_size_at_cycle_start;
         } else {
             // both pops and enqueues occured this cycle - add new
             // enqueued msgs to m_size_at_cycle_start
             current_size = m_size_at_cycle_start + m_msgs_this_cycle;
         }

         // Stall queue size at start is considered
         current_stall_size = m_stalled_at_cycle_start;
     }

     // now compare the new size with our max size
     if (current_size + current_stall_size + n <= m_max_size) {
         return true;
     } else {
         DPRINTF(RubyQueue, "n: %d, current_size: %d, heap size: %d, "
                 "m_max_size: %d\n",
                 n, current_size + current_stall_size,
                 m_prio_heap.size(), m_max_size);
         m_not_avail_count++;
         return false;
     }
 }

 const NocMessage*
 MessageBuffer::peek() const
 {
     DPRINTF(RubyQueue, "Peeking at head of queue.\n");
     const NocMessage* msg_ptr = m_prio_heap.front().get();
     assert(msg_ptr);

     DPRINTF(RubyQueue, "Message: %s\n", (*msg_ptr));
     return msg_ptr;
 }

 // FIXME - move me somewhere else
 Tick
 random_time()
 {
     static Random::RandomPtr rng = Random::genRandom();
     Tick time = 1;
     time += rng->random(0, 3);  // [0...3]
     if (rng->random(0, 7) == 0) {  // 1 in 8 chance
         time += 100 + rng->random(1, 15); // 100 + [1...15]
     }
     return time;
 }

namespace noc_msg_checkpoint
{
template <typename T, std::size_t N>
void
serializeStdArray(CheckpointOut &cp, const char *name,
                  const std::array<T, N> &arr)
{
    ::gem5::arrayParamOut(cp, name, arr.data(), N);
}

template <typename T, std::size_t N>
void
unserializeStdArray(CheckpointIn &cp, const char *name, std::array<T, N> &arr)
{
    ::gem5::arrayParamIn(cp, name, arr.data(), N);
}

static void
serialize_axisData(CheckpointOut &cp, const noc::axisData &d)
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

template <typename T>
static void
paramInCheckpointSection(CheckpointIn &cp, const std::string &section,
    const std::string &key, T &v)
{
    std::string s;
    fatal_if(!cp.find(section, key, s),
        "Can't unserialize '%s:%s'", section, key);
    fatal_if(!ParseParam<T>::parse(s, v),
        "Can't parse '%s:%s' value '%s'", section, key, s);
}

static noc::axisData
unserialize_axisDataAt(CheckpointIn &cp, const std::string &sec)
{
    uint32_t data_width = 512;
    uint32_t id_width = 6;
    uint32_t dest_width = 4;
    paramInCheckpointSection(cp, sec, "DATA_WIDTH", data_width);
    paramInCheckpointSection(cp, sec, "ID_WIDTH", id_width);
    paramInCheckpointSection(cp, sec, "DST_ID_WIDTH", dest_width);

    noc::axisData d(data_width, id_width, dest_width);

    std::string tdata_str;
    fatal_if(!cp.find(sec, "tdata", tdata_str),
        "Can't unserialize '%s:tdata'", sec);
    std::vector<std::string> tokens;
    tokenize(tokens, tdata_str, ' ');
    fatal_if(tokens.size() != d.tdata.size(),
        "tdata token count mismatch in %s", sec);
    for (size_t i = 0; i < tokens.size(); i++) {
        fatal_if(!to_number(tokens[i], d.tdata[i]),
            "tdata parse error in %s", sec);
    }
    paramInCheckpointSection(cp, sec, "tid", d.tid);
    paramInCheckpointSection(cp, sec, "tdest", d.tdest);
    paramInCheckpointSection(cp, sec, "tkeep", d.tkeep);
    uint64_t tuser = 0;
    paramInCheckpointSection(cp, sec, "tuser", tuser);
    d.tuser = (uint8_t)tuser;
    paramInCheckpointSection(cp, sec, "tlast", d.tlast);
    paramInCheckpointSection(cp, sec, "tvalid", d.tvalid);
    return d;
}

static noc::axisData
unserialize_axisData(CheckpointIn &cp)
{
    return unserialize_axisDataAt(cp, Serializable::currentSection());
}

static void
serialize_aximmRWAddr(CheckpointOut &cp, const noc::aximmRWAddr &a)
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

static noc::aximmRWAddr
unserialize_aximmRWAddr(CheckpointIn &cp)
{
    noc::aximmRWAddr a;
    int cmd = (int)noc::AximmCommand::NONE;
    int burst = (int)noc::BurstType::INCR;
    ::gem5::paramIn(cp, "cmd", cmd);
    ::gem5::paramIn(cp, "burst", burst);
    a.cmd = (noc::AximmCommand)cmd;
    a.burst = (noc::BurstType)burst;
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
serialize_aximmRWData(CheckpointOut &cp, const noc::aximmRWData &d)
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

static noc::aximmRWData
unserialize_aximmRWData(CheckpointIn &cp)
{
    noc::aximmRWData d;
    int cmd = 0, resp = 0;
    ::gem5::paramIn(cp, "cmd", cmd);
    ::gem5::paramIn(cp, "resp", resp);
    d.cmd = (noc::AximmCommand)cmd;
    d.resp = (noc::AximmResp)resp;
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
serialize_aximmWResp(CheckpointOut &cp, const noc::aximmWResp &r)
{
    ::gem5::paramOut(cp, "id", r.id);
    ::gem5::paramOut(cp, "resp", (int)r.resp);
    ::gem5::paramOut(cp, "user", (uint64_t)r.user);
    ::gem5::paramOut(cp, "valid", r.valid);
}

static noc::aximmWResp
unserialize_aximmWResp(CheckpointIn &cp)
{
    noc::aximmWResp r;
    int resp = 0;
    ::gem5::paramIn(cp, "id", r.id);
    ::gem5::paramIn(cp, "resp", resp);
    r.resp = (noc::AximmResp)resp;
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "user", tmp); r.user = (uint8_t)tmp;
    ::gem5::paramIn(cp, "valid", r.valid);
    return r;
}

static void
serialize_MessagePayload(CheckpointOut &cp, const noc::MessagePayload &mp)
{
    int which = (int)mp.index();
    ::gem5::paramOut(cp, "which", which);
    if (std::holds_alternative<noc::aximmRWAddr>(mp)) {
        Serializable::ScopedCheckpointSection sec(cp, "aximmRWAddr");
        serialize_aximmRWAddr(cp, std::get<noc::aximmRWAddr>(mp));
    } else if (std::holds_alternative<noc::aximmRWData>(mp)) {
        Serializable::ScopedCheckpointSection sec(cp, "aximmRWData");
        serialize_aximmRWData(cp, std::get<noc::aximmRWData>(mp));
    } else if (std::holds_alternative<noc::aximmWResp>(mp)) {
        Serializable::ScopedCheckpointSection sec(cp, "aximmWResp");
        serialize_aximmWResp(cp, std::get<noc::aximmWResp>(mp));
    } else if (std::holds_alternative<noc::axisData>(mp)) {
        Serializable::ScopedCheckpointSection sec(cp, "axisData");
        serialize_axisData(cp, std::get<noc::axisData>(mp));
    } else {
        panic("Unsupported MessagePayload alternative");
    }
}

static noc::MessagePayload
unserialize_MessagePayload(CheckpointIn &cp)
{
    int which = 0;
    ::gem5::paramIn(cp, "which", which);
    switch (which) {
      case 0: {
        Serializable::ScopedCheckpointSection sec(cp, "aximmRWAddr");
        return unserialize_aximmRWAddr(cp);
      }
      case 1: {
        Serializable::ScopedCheckpointSection sec(cp, "aximmRWData");
        return unserialize_aximmRWData(cp);
      }
      case 2: {
        Serializable::ScopedCheckpointSection sec(cp, "aximmWResp");
        return unserialize_aximmWResp(cp);
      }
      case 3: {
        Serializable::ScopedCheckpointSection sec(cp, "axisData");
        return unserialize_axisData(cp);
      }
      default:
        panic("Bad MessagePayload index %d", which);
    }
}

static void
serialize_axisPayload(CheckpointOut &cp, const noc::axisPayload &p)
{
    ::gem5::paramOut(cp, "numBeats", p.numBeats);
    ::gem5::paramOut(cp, "totalBytes", p.totalBytes);
    ::gem5::paramOut(cp, "tid", p.tid);
    ::gem5::paramOut(cp, "last", p.last);
    ::gem5::paramOut(cp, "beats_size", (uint64_t)p.beats.size());

    for (size_t i = 0; i < p.beats.size(); i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("beat%d", (int)i));
        serialize_axisData(cp, p.beats[i]);
    }
}

static noc::axisPayload
unserialize_axisPayloadAt(CheckpointIn &cp, const std::string &axis_sec)
{
    noc::axisPayload p;
    paramInCheckpointSection(cp, axis_sec, "numBeats", p.numBeats);
    paramInCheckpointSection(cp, axis_sec, "totalBytes", p.totalBytes);
    paramInCheckpointSection(cp, axis_sec, "tid", p.tid);
    paramInCheckpointSection(cp, axis_sec, "last", p.last);
    uint64_t beats_size = 0;
    paramInCheckpointSection(cp, axis_sec, "beats_size", beats_size);
    p.beats.clear();
    p.beats.reserve(beats_size);
    for (size_t i = 0; i < beats_size; i++) {
        const std::string beat_sec =
            axis_sec + "." + csprintf("beat%d", (int)i);
        p.beats.push_back(unserialize_axisDataAt(cp, beat_sec));
    }
    return p;
}

static noc::axisPayload
unserialize_axisPayload(CheckpointIn &cp)
{
    return unserialize_axisPayloadAt(cp, Serializable::currentSection());
}

static std::string
payloadDataRootSection(CheckpointIn &cp, const std::string &cur)
{
    std::string swhich;
    if (cp.find(cur, "which", swhich)) {
        return cur;
    }
    const std::string suf = ".flt_route_net_dest.data";
    if (cur.size() >= suf.size() &&
        !cur.compare(cur.size() - suf.size(), suf.size(), suf)) {
        const std::string alt =
            cur.substr(0, cur.size() - suf.size()) + ".data";
        if (cp.find(alt, "which", swhich)) {
            return alt;
        }
    }
    return cur;
}

static noc::Payload
unserialize_PayloadAt(CheckpointIn &cp, const std::string &data_sec)
{
    int which = 0;
    paramInCheckpointSection(cp, data_sec, "which", which);
    switch (which) {
      case 0: {
        fatal("Checkpoint Payload aximm restore from relocated .data "
              "section is not implemented");
      }
      case 1: {
        const std::string axis_sec = data_sec + ".axisPayload";
        return unserialize_axisPayloadAt(cp, axis_sec);
      }
      default:
        panic("Bad Payload index %d", which);
    }
}

static void
serialize_Payload(CheckpointOut &cp, const noc::Payload &p)
{
    int which = (int)p.index();
    ::gem5::paramOut(cp, "which", which);
    if (std::holds_alternative<noc::aximmPayload>(p)) {
        Serializable::ScopedCheckpointSection sec(cp, "aximmPayload");
        const auto &arr = std::get<noc::aximmPayload>(p);
        for (size_t i = 0; i < arr.size(); i++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("beat%d", (int)i));
            serialize_aximmRWData(cp, arr[i]);
        }
    } else if (std::holds_alternative<noc::axisPayload>(p)) {
        Serializable::ScopedCheckpointSection sec(cp, "axisPayload");
        serialize_axisPayload(cp, std::get<noc::axisPayload>(p));
    } else {
        panic("Unsupported Payload alternative");
    }
}

static noc::Payload
unserialize_Payload(CheckpointIn &cp)
{
    const std::string cur = Serializable::currentSection();
    const std::string data_root = payloadDataRootSection(cp, cur);
    if (data_root != cur) {
        return unserialize_PayloadAt(cp, data_root);
    }

    int which = 0;
    ::gem5::paramIn(cp, "which", which);
    switch (which) {
      case 0: {
        Serializable::ScopedCheckpointSection sec(cp, "aximmPayload");
        noc::aximmPayload arr{};
        for (size_t i = 0; i < arr.size(); i++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("beat%d", (int)i));
            arr[i] = unserialize_aximmRWData(cp);
        }
        return arr;
      }
      case 1: {
        Serializable::ScopedCheckpointSection sec(cp, "axisPayload");
        return unserialize_axisPayload(cp);
      }
      default:
        panic("Bad Payload index %d", which);
    }
}

static void
serialize_base_fields(CheckpointOut &cp, const NocMessage &m)
{
    ::gem5::paramOut(cp, "time", m.getTime());
    ::gem5::paramOut(cp, "lastEnqueueTime", m.getLastEnqueueTime());
    ::gem5::paramOut(cp, "delayedTicks", m.getDelayedTicks());
    ::gem5::paramOut(cp, "msgCounter", m.getMsgCounter());
    ::gem5::paramOut(cp, "incomingLink", (int)m.getIncomingLink());
    ::gem5::paramOut(cp, "vnet", (int)m.getVnet());
}

static void
unserialize_base_fields(CheckpointIn &cp, NocMessage &m)
{
    Tick t = 0;
    ::gem5::paramIn(cp, "time", t);
    m.setTime(t);
    ::gem5::paramIn(cp, "lastEnqueueTime", t);
    m.setLastEnqueueTime(t);
    ::gem5::paramIn(cp, "delayedTicks", t);
    m.setDelayedTicks(t);
    uint64_t c = 0;
    ::gem5::paramIn(cp, "msgCounter", c);
    m.setMsgCounter(c);
    int tmp = 0;
    ::gem5::paramIn(cp, "incomingLink", tmp);
    m.setIncomingLink(tmp);
    ::gem5::paramIn(cp, "vnet", tmp);
    m.setVnet(tmp);
}

static void
serialize_msgptr(CheckpointOut &cp, const MsgPtr &msg)
{
    panic_if(!msg, "Attempting to serialize null MsgPtr");
    const NocMessage &m = *msg;

    if (auto mem = dynamic_cast<const NocMemoryMsg *>(msg.get())) {
        ::gem5::paramOut(cp, "kind", std::string("NocMemoryMsg"));
        serialize_base_fields(cp, m);

        ::gem5::paramOut(cp, "messageSize", (int)mem->getMessageSize());
        ::gem5::paramOut(cp, "numFlits", (uint64_t)mem->getNumFlits());
        ::gem5::paramOut(cp, "beatSize", (uint64_t)mem->getBeatSize());
        ::gem5::paramOut(cp, "burstLen", (uint64_t)mem->getBurstLen());
        ::gem5::paramOut(cp, "writeTag", (uint64_t)mem->getWriteTag());

        ::gem5::paramOut(cp, "axiRrobTag", (uint64_t)mem->getAxiRROBTag());
        ::gem5::paramOut(cp, "axiBeatId", (uint64_t)mem->getRROBBeatID());
        ::gem5::paramOut(cp, "endBeatIdx", (uint64_t)mem->getEndBeatIdx());
        ::gem5::paramOut(cp, "currentBeatIdx", (uint64_t)mem->getCurrentBeatIdx());

        ::gem5::paramOut(cp, "srcNiId", mem->getSourceNiID());
        ::gem5::paramOut(cp, "destNiId", mem->getDestNiID());
        ::gem5::paramOut(cp, "originalReadBytes",
            (uint64_t)mem->getOriginalReadBytes());
        ::gem5::paramOut(cp, "finalReadChunk", mem->isFinalReadChunk());

        auto tags = mem->getRrobTags();
        serializeStdArray(cp, "rrobTags", tags);

        {
            Serializable::ScopedCheckpointSection sec(cp, "payload");
            serialize_MessagePayload(cp, mem->getPayload());
        }
        {
            Serializable::ScopedCheckpointSection sec(cp, "data");
            serialize_Payload(cp, mem->getData());
        }
        return;
    }

    if (auto strm = dynamic_cast<const NocStreamMsg *>(msg.get())) {
        ::gem5::paramOut(cp, "kind", std::string("NocStreamMsg"));
        serialize_base_fields(cp, m);

        ::gem5::paramOut(cp, "mode", (int)strm->getMode());
        ::gem5::paramOut(cp, "messageSize", (int)strm->getMessageSize());
        ::gem5::paramOut(cp, "numFlits", (uint64_t)strm->getNumFlits());
        ::gem5::paramOut(cp, "beatSize", (uint64_t)strm->getBeatSize());

        ::gem5::paramOut(cp, "axiBeatId", (uint64_t)strm->getBeatID());
        ::gem5::paramOut(cp, "endBeatIdx", (uint64_t)strm->getEndBeatIdx());
        ::gem5::paramOut(cp, "currentBeatIdx", (uint64_t)strm->getCurrentBeatIdx());

        ::gem5::paramOut(cp, "srcNiId", strm->getSourceNiID());
        ::gem5::paramOut(cp, "destNiId", strm->getDestNiID());

        if (strm->getMode() == NocStreamMsg::NocStreamMsgMode::BUFFER) {
            Serializable::ScopedCheckpointSection sec(cp, "payload");
            serialize_MessagePayload(cp, strm->getPayload());
        } else {
            Serializable::ScopedCheckpointSection sec(cp, "data");
            serialize_Payload(cp, strm->getData());
        }
        return;
    }

    panic("Unsupported NocMessage dynamic type in MsgPtr serialize");
}

static MsgPtr
unserialize_msgptr(CheckpointIn &cp)
{
    std::string kind;
    ::gem5::paramIn(cp, "kind", kind);

    if (kind == "NocMemoryMsg") {
        int msg_size_int = 0;
        ::gem5::paramIn(cp, "messageSize", msg_size_int);
        auto msg_size = (noc::AxiMsgSizeType)msg_size_int;

        MsgPtr msg(new NocMemoryMsg(curTick(), nullptr, msg_size,
                                   noc::MessagePayload{}, noc::aximmPayload{}));
        auto mem = std::dynamic_pointer_cast<NocMemoryMsg>(msg);
        unserialize_base_fields(cp, *mem);

        uint64_t tmp = 0;
        ::gem5::paramIn(cp, "numFlits", tmp); mem->setNumFlits((uint8_t)tmp);
        ::gem5::paramIn(cp, "beatSize", tmp); mem->setBeatSize((uint8_t)tmp);
        ::gem5::paramIn(cp, "burstLen", tmp); mem->setBurstLen((uint8_t)tmp);
        ::gem5::paramIn(cp, "writeTag", tmp); mem->setWriteTag((noc::garnet::WriteTag)tmp);

        ::gem5::paramIn(cp, "axiRrobTag", tmp); mem->setAxiRROBTag((uint8_t)tmp);
        ::gem5::paramIn(cp, "axiBeatId", tmp); mem->setRROBBeatID((uint8_t)tmp);
        ::gem5::paramIn(cp, "endBeatIdx", tmp); mem->setEndBeatIdx((uint8_t)tmp);
        ::gem5::paramIn(cp, "currentBeatIdx", tmp); mem->setCurrentBeatIdx((uint8_t)tmp);

        int id = 0;
        ::gem5::paramIn(cp, "srcNiId", id); mem->setSourceNiID(id);
        ::gem5::paramIn(cp, "destNiId", id); mem->setDestNiID(id);
        tmp = 0;
        ::gem5::optParamIn(cp, "originalReadBytes", tmp, false);
        mem->setOriginalReadBytes((uint32_t)tmp);
        bool final_read_chunk = false;
        ::gem5::optParamIn(cp, "finalReadChunk", final_read_chunk, false);
        mem->setFinalReadChunk(final_read_chunk);

        std::array<uint8_t, 8> tags{};
        unserializeStdArray(cp, "rrobTags", tags);
        mem->setRrobTags(tags);

        {
            Serializable::ScopedCheckpointSection sec(cp, "payload");
            mem->setPayload(unserialize_MessagePayload(cp));
        }
        {
            Serializable::ScopedCheckpointSection sec(cp, "data");
            mem->setData(unserialize_Payload(cp));
        }
        return msg;
    }

    if (kind == "NocStreamMsg") {
        int mode_int = 0;
        ::gem5::paramIn(cp, "mode", mode_int);
        auto mode = (NocStreamMsg::NocStreamMsgMode)mode_int;

        MsgPtr msg;
        if (mode == NocStreamMsg::NocStreamMsgMode::BUFFER) {
            auto mp = std::make_unique<noc::MessagePayload>(noc::MessagePayload{});
            msg.reset(new NocStreamMsg(curTick(), nullptr, std::move(mp)));
        } else {
            auto pl = std::make_unique<noc::Payload>(noc::Payload{noc::axisPayload{}});
            msg.reset(new NocStreamMsg(curTick(), nullptr, std::move(pl)));
        }

        auto strm = std::dynamic_pointer_cast<NocStreamMsg>(msg);
        strm->setMode(mode);
        unserialize_base_fields(cp, *strm);

        uint64_t tmp = 0;
        ::gem5::paramIn(cp, "numFlits", tmp); strm->setNumFlits((uint8_t)tmp);
        ::gem5::paramIn(cp, "beatSize", tmp); strm->setBeatSize((uint8_t)tmp);
        ::gem5::paramIn(cp, "axiBeatId", tmp); strm->setBeatID((uint8_t)tmp);
        ::gem5::paramIn(cp, "endBeatIdx", tmp); strm->setEndBeatIdx((uint8_t)tmp);
        ::gem5::paramIn(cp, "currentBeatIdx", tmp); strm->setCurrentBeatIdx((uint8_t)tmp);

        int id = 0;
        ::gem5::paramIn(cp, "srcNiId", id); strm->setSourceNiID(id);
        ::gem5::paramIn(cp, "destNiId", id); strm->setDestNiID(id);

        if (mode == NocStreamMsg::NocStreamMsgMode::BUFFER) {
            Serializable::ScopedCheckpointSection sec(cp, "payload");
            strm->setPayload(unserialize_MessagePayload(cp));
        } else {
            Serializable::ScopedCheckpointSection sec(cp, "data");
            strm->setData(unserialize_Payload(cp));
        }
        return msg;
    }

    panic("Unsupported serialized MsgPtr kind '%s'", kind);
}

} // namespace noc_msg_checkpoint

void
serializeNocMsgPtr(CheckpointOut &cp, const MsgPtr &msg)
{
    noc_msg_checkpoint::serialize_msgptr(cp, msg);
}

MsgPtr
unserializeNocMsgPtr(CheckpointIn &cp)
{
    return noc_msg_checkpoint::unserialize_msgptr(cp);
}

void
serializeNocMsgPtrOptional(CheckpointOut &cp, const MsgPtr &msg)
{
    bool valid = (bool)msg;
    ::gem5::paramOut(cp, "msgValid", valid);
    if (valid)
        noc_msg_checkpoint::serialize_msgptr(cp, msg);
}

MsgPtr
unserializeNocMsgPtrOptional(CheckpointIn &cp)
{
    bool valid = false;
    ::gem5::paramIn(cp, "msgValid", valid);
    if (!valid)
        return MsgPtr();
    return noc_msg_checkpoint::unserialize_msgptr(cp);
}

 void
 MessageBuffer::enqueue(MsgPtr message, Tick current_time, Tick delta,
                        bool ruby_is_random, bool ruby_warmup,
                        bool bypassStrictFIFO)
 {
     // record current time incase we have a pop that also adjusts my size
     if (m_time_last_time_enqueue < current_time) {
         m_msgs_this_cycle = 0;  // first msg this cycle
         m_time_last_time_enqueue = current_time;
     }

     m_msg_counter++;
     m_msgs_this_cycle++;

     // Calculate the arrival time of the message, that is, the first
     // cycle the message can be dequeued.
     panic_if((delta == 0) && !m_allow_zero_latency,
            "Delta equals zero and allow_zero_latency is false during enqueue");
     Tick arrival_time = 0;

     // random delays are inserted if the RubySystem level randomization flag
     // is turned on and this buffer allows it
     if ((m_randomization == gem5::MessageRandomization::disabled) ||
         ((m_randomization == gem5::MessageRandomization::ruby_system) &&
           !ruby_is_random)) {
         // No randomization
         arrival_time = current_time + delta;
     } else {
         // Randomization - ignore delta
         if (m_strict_fifo) {
             if (m_last_arrival_time < current_time) {
                 m_last_arrival_time = current_time;
             }
             arrival_time = m_last_arrival_time + random_time();
         } else {
             arrival_time = current_time + random_time();
         }
     }

     // TODO: THIS CAUSES A FAILURE : ARRIVAL TIME WAS LESS THAN LAST ARRIVAL TIME
     // Check the arrival time
     assert(arrival_time >= current_time);
     if (m_strict_fifo &&
         !(bypassStrictFIFO || m_last_message_strict_fifo_bypassed)) {
         if (arrival_time < m_last_arrival_time) {
             panic("FIFO ordering violated: %s name: %s current time: %d "
                   "delta: %d arrival_time: %d last arrival_time: %d\n",
                   *this, name(), current_time, delta, arrival_time,
                   m_last_arrival_time);
         }
     }

     // If running a cache trace, don't worry about the last arrival checks
     if (!ruby_warmup) {
         m_last_arrival_time = arrival_time;
     }

     m_last_message_strict_fifo_bypassed = bypassStrictFIFO;

     // compute the delay cycles and set enqueue time
     NocMessage* msg_ptr = message.get();
     assert(msg_ptr != NULL);

     assert(current_time >= msg_ptr->getLastEnqueueTime() &&
            "ensure we aren't dequeued early");

     msg_ptr->updateDelayedTicks(current_time);
    //  msg_ptr->setLastEnqueueTime(current_time);
     msg_ptr->setLastEnqueueTime(arrival_time);
     msg_ptr->setMsgCounter(m_msg_counter);

     // Insert the message into the priority heap
     m_prio_heap.push_back(message);
     push_heap(m_prio_heap.begin(), m_prio_heap.end(), std::greater<MsgPtr>());
     // Increment the number of messages statistic
     m_buf_msgs++;
     m_num_msgs++; //actual current msg count

     assert((m_max_size == 0) ||
            ((m_prio_heap.size() + m_stall_map_size) <= m_max_size));

     DPRINTF(RubyQueue, "Enqueue arrival_time: %lld, Message: %s\n",
             arrival_time, *(message.get()));

     // Schedule the wakeup
     assert(m_consumer != NULL);
     m_consumer->scheduleEventAbsolute(arrival_time);
     m_consumer->storeEventInfo(m_vnet_id);
 }

 Tick
 MessageBuffer::dequeue(Tick current_time, bool decrement_messages)
 {
     DPRINTF(RubyQueue, "Popping\n");
     assert(isReady(current_time));

     // get MsgPtr of the message about to be dequeued
     MsgPtr message = m_prio_heap.front();

     // get the delay cycles
     message->updateDelayedTicks(current_time);
     Tick delay = message->getDelayedTicks();

     // record previous size and time so the current buffer size isn't
     // adjusted until schd cycle
     if (m_time_last_time_pop < current_time) {
         m_size_at_cycle_start = m_prio_heap.size();
         m_stalled_at_cycle_start = m_stall_map_size;
         m_time_last_time_pop = current_time;
         m_dequeues_this_cy = 0;
     }
     ++m_dequeues_this_cy;

     pop_heap(m_prio_heap.begin(), m_prio_heap.end(), std::greater<MsgPtr>());
     m_prio_heap.pop_back();
     if (decrement_messages) {
         // Record how much time is passed since the message was enqueued
         m_stall_time += curTick() - message->getLastEnqueueTime();
         m_msg_count++;

         // If the message will be removed from the queue, decrement the
         // number of message in the queue.
         m_buf_msgs--; //stat avg
         m_num_msgs--; //actual current msg count
     }

     // if a dequeue callback was requested, call it now
     if (m_dequeue_callback) {
         m_dequeue_callback();
     }

     return delay;
 }

 void
 MessageBuffer::registerDequeueCallback(std::function<void()> callback)
 {
     m_dequeue_callback = callback;
 }

 void
 MessageBuffer::unregisterDequeueCallback()
 {
     m_dequeue_callback = nullptr;
 }

 void
 MessageBuffer::clear()
 {
     m_prio_heap.clear();

     m_msg_counter = 0;
     m_time_last_time_enqueue = 0;
     m_time_last_time_pop = 0;
     m_size_at_cycle_start = 0;
     m_stalled_at_cycle_start = 0;
     m_msgs_this_cycle = 0;
 }

void
MessageBuffer::serialize(CheckpointOut &cp) const
{
    // Bookkeeping state (does not include pointers / callbacks).
    SERIALIZE_SCALAR(m_num_msgs);
    SERIALIZE_SCALAR(m_stall_map_size);
    SERIALIZE_SCALAR(m_dequeues_this_cy);
    SERIALIZE_SCALAR(m_time_last_time_size_checked);
    SERIALIZE_SCALAR(m_size_last_time_size_checked);
    SERIALIZE_SCALAR(m_time_last_time_enqueue);
    SERIALIZE_SCALAR(m_time_last_time_pop);
    SERIALIZE_SCALAR(m_last_arrival_time);
    SERIALIZE_SCALAR(m_size_at_cycle_start);
    SERIALIZE_SCALAR(m_stalled_at_cycle_start);
    SERIALIZE_SCALAR(m_msgs_this_cycle);
    SERIALIZE_SCALAR(m_msg_counter);
    SERIALIZE_SCALAR(m_priority_rank);
    SERIALIZE_SCALAR(m_last_message_strict_fifo_bypassed);
    SERIALIZE_SCALAR(m_input_link_id);
    SERIALIZE_SCALAR(m_vnet_id);

    // IMPORTANT: Write all scalar keys for this SimObject section before
    // creating any sub-sections. The checkpoint format is INI-like and does
    // not "return" to the parent section automatically after writing a
    // sub-section header.
    const uint64_t prio_size = m_prio_heap.size();
    const uint64_t stall_keys = m_stall_msg_map.size();
    const uint64_t def_keys = m_deferred_msg_map.size();
    ::gem5::paramOut(cp, "prio_heap_size", prio_size);
    ::gem5::paramOut(cp, "stall_keys", stall_keys);
    ::gem5::paramOut(cp, "deferred_keys", def_keys);

    // Main heap.
    for (size_t i = 0; i < m_prio_heap.size(); i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("prio%d", (int)i));
        noc_msg_checkpoint::serialize_msgptr(cp, m_prio_heap[i]);
    }

    // Stall map.
    size_t k = 0;
    for (const auto &it : m_stall_msg_map) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("stall%d", (int)k));
        ::gem5::paramOut(cp, "addr", (uint64_t)it.first);
        ::gem5::paramOut(cp, "list_size", (uint64_t)it.second.size());
        size_t j = 0;
        for (const auto &msg : it.second) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("m%d", (int)j));
            noc_msg_checkpoint::serialize_msgptr(cp, msg);
            j++;
        }
        k++;
    }

    // Deferred map.
    k = 0;
    for (const auto &it : m_deferred_msg_map) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("deferred%d", (int)k));
        ::gem5::paramOut(cp, "addr", (uint64_t)it.first);
        ::gem5::paramOut(cp, "vec_size", (uint64_t)it.second.size());
        for (size_t j = 0; j < it.second.size(); j++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("m%d", (int)j));
            noc_msg_checkpoint::serialize_msgptr(cp, it.second[j]);
        }
        k++;
    }
}

void
MessageBuffer::unserialize(CheckpointIn &cp)
{
    // Scalars.
    UNSERIALIZE_SCALAR(m_num_msgs);
    UNSERIALIZE_SCALAR(m_stall_map_size);
    UNSERIALIZE_SCALAR(m_dequeues_this_cy);
    UNSERIALIZE_SCALAR(m_time_last_time_size_checked);
    UNSERIALIZE_SCALAR(m_size_last_time_size_checked);
    UNSERIALIZE_SCALAR(m_time_last_time_enqueue);
    UNSERIALIZE_SCALAR(m_time_last_time_pop);
    UNSERIALIZE_SCALAR(m_last_arrival_time);
    UNSERIALIZE_SCALAR(m_size_at_cycle_start);
    UNSERIALIZE_SCALAR(m_stalled_at_cycle_start);
    UNSERIALIZE_SCALAR(m_msgs_this_cycle);
    UNSERIALIZE_SCALAR(m_msg_counter);
    UNSERIALIZE_SCALAR(m_priority_rank);
    UNSERIALIZE_SCALAR(m_last_message_strict_fifo_bypassed);
    UNSERIALIZE_SCALAR(m_input_link_id);
    UNSERIALIZE_SCALAR(m_vnet_id);

    // Containers.
    m_prio_heap.clear();
    uint64_t prio_size = 0;
    ::gem5::paramIn(cp, "prio_heap_size", prio_size);
    m_prio_heap.reserve(prio_size);
    for (size_t i = 0; i < prio_size; i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("prio%d", (int)i));
        m_prio_heap.push_back(noc_msg_checkpoint::unserialize_msgptr(cp));
    }
    std::make_heap(m_prio_heap.begin(), m_prio_heap.end(), std::greater<MsgPtr>());

    m_stall_msg_map.clear();
    uint64_t stall_keys = 0;
    ::gem5::paramIn(cp, "stall_keys", stall_keys);
    int recomputed_stall_size = 0;
    for (size_t i = 0; i < stall_keys; i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("stall%d", (int)i));
        uint64_t addr_u = 0;
        ::gem5::paramIn(cp, "addr", addr_u);
        uint64_t list_size = 0;
        ::gem5::paramIn(cp, "list_size", list_size);
        auto &lst = m_stall_msg_map[(Addr)addr_u];
        for (size_t j = 0; j < list_size; j++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("m%d", (int)j));
            lst.push_back(noc_msg_checkpoint::unserialize_msgptr(cp));
        }
        recomputed_stall_size += lst.size();
    }
    // Prefer recomputed size to avoid stale bookkeeping.
    m_stall_map_size = recomputed_stall_size;

    m_deferred_msg_map.clear();
    uint64_t def_keys = 0;
    ::gem5::paramIn(cp, "deferred_keys", def_keys);
    for (size_t i = 0; i < def_keys; i++) {
        Serializable::ScopedCheckpointSection sec(cp, csprintf("deferred%d", (int)i));
        uint64_t addr_u = 0;
        ::gem5::paramIn(cp, "addr", addr_u);
        uint64_t vec_size = 0;
        ::gem5::paramIn(cp, "vec_size", vec_size);
        auto &vec = m_deferred_msg_map[(Addr)addr_u];
        vec.clear();
        vec.reserve(vec_size);
        for (size_t j = 0; j < vec_size; j++) {
            Serializable::ScopedCheckpointSection sec2(cp, csprintf("m%d", (int)j));
            vec.push_back(noc_msg_checkpoint::unserialize_msgptr(cp));
        }
    }

    // The consumer pointer/callback is not checkpointed; wiring must restore it.
    m_dequeue_callback = nullptr;
}

 void
 MessageBuffer::recycle(Tick current_time, Tick recycle_latency)
 {
     DPRINTF(RubyQueue, "Recycling.\n");
     assert(isReady(current_time));
     MsgPtr node = m_prio_heap.front();
     pop_heap(m_prio_heap.begin(), m_prio_heap.end(), std::greater<MsgPtr>());

     Tick future_time = current_time + recycle_latency;
     node->setLastEnqueueTime(future_time);

     m_prio_heap.back() = node;
     push_heap(m_prio_heap.begin(), m_prio_heap.end(), std::greater<MsgPtr>());
     m_consumer->scheduleEventAbsolute(future_time);
 }

 void
 MessageBuffer::reanalyzeList(std::list<MsgPtr> &lt, Tick schdTick)
 {
     while (!lt.empty()) {
         MsgPtr m = lt.front();
         assert(m->getLastEnqueueTime() <= schdTick);

         m_prio_heap.push_back(m);
         push_heap(m_prio_heap.begin(), m_prio_heap.end(),
                   std::greater<MsgPtr>());

         m_consumer->scheduleEventAbsolute(schdTick);

         DPRINTF(RubyQueue, "Requeue arrival_time: %lld, Message: %s\n",
             schdTick, *(m.get()));

         lt.pop_front();
     }
 }

 void
 MessageBuffer::reanalyzeMessages(Addr addr, Tick current_time)
 {
     DPRINTF(RubyQueue, "ReanalyzeMessages %#x\n", addr);
     assert(m_stall_msg_map.count(addr) > 0);

     //
     // Put all stalled messages associated with this address back on the
     // prio heap.  The reanalyzeList call will make sure the consumer is
     // scheduled for the current cycle so that the previously stalled messages
     // will be observed before any younger messages that may arrive this cycle
     //
     m_stall_map_size -= m_stall_msg_map[addr].size();
     assert(m_stall_map_size >= 0);
     reanalyzeList(m_stall_msg_map[addr], current_time);
     m_stall_msg_map.erase(addr);
 }

 void
 MessageBuffer::reanalyzeAllMessages(Tick current_time)
 {
     DPRINTF(RubyQueue, "ReanalyzeAllMessages\n");

     //
     // Put all stalled messages associated with this address back on the
     // prio heap.  The reanalyzeList call will make sure the consumer is
     // scheduled for the current cycle so that the previously stalled messages
     // will be observed before any younger messages that may arrive this cycle.
     //
     for (StallMsgMapType::iterator map_iter = m_stall_msg_map.begin();
          map_iter != m_stall_msg_map.end(); ++map_iter) {
         m_stall_map_size -= map_iter->second.size();
         assert(m_stall_map_size >= 0);
         reanalyzeList(map_iter->second, current_time);
     }
     m_stall_msg_map.clear();
 }

 void
 MessageBuffer::stallMessage(Addr addr, Tick current_time)
 {
     DPRINTF(RubyQueue, "Stalling due to %#x\n", addr);
     assert(isReady(current_time));
     MsgPtr message = m_prio_heap.front();

     // Since the message will just be moved to stall map, indicate that the
     // buffer should not decrement the m_buf_msgs statistic
     dequeue(current_time, false);

     //
     // Note: no event is scheduled to analyze the map at a later time.
     // Instead the controller is responsible to call reanalyzeMessages when
     // these addresses change state.
     //
     (m_stall_msg_map[addr]).push_back(message);
     m_stall_map_size++;
     m_stall_count++;
 }

 bool
 MessageBuffer::hasStalledMsg(Addr addr) const
 {
     return (m_stall_msg_map.count(addr) != 0);
 }

 void
 MessageBuffer::deferEnqueueingMessage(Addr addr, MsgPtr message)
 {
     DPRINTF(RubyQueue, "Deferring enqueueing message: %s, Address %#x\n",
             *(message.get()), addr);
     (m_deferred_msg_map[addr]).push_back(message);
 }

 void
 MessageBuffer::enqueueDeferredMessages(Addr addr, Tick curTime, Tick delay,
                                        bool ruby_is_random, bool ruby_warmup)
 {
     assert(!isDeferredMsgMapEmpty(addr));
     std::vector<MsgPtr>& msg_vec = m_deferred_msg_map[addr];
     assert(msg_vec.size() > 0);

     // enqueue all deferred messages associated with this address
     for (MsgPtr m : msg_vec) {
         enqueue(m, curTime, delay, ruby_is_random, ruby_warmup);
     }

     msg_vec.clear();
     m_deferred_msg_map.erase(addr);
 }

 bool
 MessageBuffer::isDeferredMsgMapEmpty(Addr addr) const
 {
     return m_deferred_msg_map.count(addr) == 0;
 }

 void
 MessageBuffer::print(std::ostream& out) const
 {
     ccprintf(out, "[MessageBuffer: ");
     if (m_consumer != NULL) {
         ccprintf(out, " consumer-yes ");
     }

     std::vector<MsgPtr> copy(m_prio_heap);
     std::sort_heap(copy.begin(), copy.end(), std::greater<MsgPtr>());
     ccprintf(out, "%s] %s", copy, name());
 }

 bool
 MessageBuffer::isReady(Tick current_time) const
 {
     assert(m_time_last_time_pop <= current_time);
     bool can_dequeue = (m_max_dequeue_rate == 0) ||
                        (m_time_last_time_pop < current_time) ||
                        (m_dequeues_this_cy < m_max_dequeue_rate);
     bool is_ready = (m_prio_heap.size() > 0) &&
                    (m_prio_heap.front()->getLastEnqueueTime() <= current_time);
     if (!can_dequeue && is_ready) {
         // Make sure the Consumer executes next cycle to dequeue the ready msg
         m_consumer->scheduleEvent(Cycles(1));
     }
     return can_dequeue && is_ready;
 }

 Tick
 MessageBuffer::readyTime() const
 {
     if (m_prio_heap.empty())
         return MaxTick;
     else
         return m_prio_heap.front()->getLastEnqueueTime();
 }

 uint32_t
 MessageBuffer::functionalAccess(Packet *pkt, bool is_read, gem5::ruby::WriteMask *mask)
 {
     DPRINTF(RubyQueue, "functional %s for %#x\n",
             is_read ? "read" : "write", pkt->getAddr());

     uint32_t num_functional_accesses = 0;

     // Check the priority heap and write any messages that may
     // correspond to the address in the packet.
     for (unsigned int i = 0; i < m_prio_heap.size(); ++i) {
         NocMessage *msg = m_prio_heap[i].get();
         if (is_read && !mask && msg->functionalRead(pkt))
             return 1;
         else if (is_read && mask && msg->functionalRead(pkt, *mask))
             num_functional_accesses++;
         else if (!is_read && msg->functionalWrite(pkt))
             num_functional_accesses++;
     }

     // Check the stall queue and write any messages that may
     // correspond to the address in the packet.
     for (StallMsgMapType::iterator map_iter = m_stall_msg_map.begin();
          map_iter != m_stall_msg_map.end();
          ++map_iter) {

         for (std::list<MsgPtr>::iterator it = (map_iter->second).begin();
             it != (map_iter->second).end(); ++it) {

             NocMessage *msg = (*it).get();
             if (is_read && !mask && msg->functionalRead(pkt))
                 return 1;
             else if (is_read && mask && msg->functionalRead(pkt, *mask))
                 num_functional_accesses++;
             else if (!is_read && msg->functionalWrite(pkt))
                 num_functional_accesses++;
         }
     }

     return num_functional_accesses;
 }

 } // namespace ruby
 } // namespace gem5
