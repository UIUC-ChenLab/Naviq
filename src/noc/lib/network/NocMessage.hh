/*
 * Copyright (c) 2021 ARM Limited
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

 #ifndef __NOC_MESSAGE_HH__
 #define __NOC_MESSAGE_HH__

 #include <iostream>
 #include <memory>
 #include <stack>

 #include "mem/packet.hh"
 #include "noc/core/network/NocNetDest.hh"
 #include "noc/lib/axi/AXITypes.hh"
 #include "mem/ruby/common/WriteMask.hh"
 #include "mem/ruby/protocol/MessageSizeType.hh"

 namespace gem5
 {

 namespace noc
 {

namespace garnet{using WriteTag = uint8_t;}
 class NocMessage;
 typedef std::shared_ptr<NocMessage> MsgPtr;

 class NocMessage
 {
   public:
     NocMessage(Tick curTime, const NocSystem *ns):
         //: m_block_size(block_size),
           m_time(curTime),
           m_LastEnqueueTime(curTime),
           m_DelayedTicks(0), m_msg_counter(0)
     { }

     NocMessage(const NocMessage &other) = default;

     virtual ~NocMessage() { }

     virtual MsgPtr clone() const = 0;
     virtual void print(std::ostream& out) const = 0;
     virtual NocSystem* getNocSystem() = 0;

     virtual uint8_t getNumFlits() const = 0;
     virtual void setNumFlits(uint8_t num_flits) = 0;
     virtual void setPayload(MessagePayload payload) = 0;
     virtual MessagePayload getPayload() const = 0;

    //  // aximm specific
    //  virtual void setWriteTag(garnet::WriteTag tag) = 0;
    //  virtual garnet::WriteTag getWriteTag() const = 0;
    //  virtual uint8_t getRROBTag(uint8_t idx) const = 0;
    //  virtual void setRROBTag(uint8_t idx, uint8_t id) = 0;
    //  virtual uint8_t getAxiRROBTag() const = 0;
    //  virtual void setAxiRROBTag(uint8_t id) = 0;
    //  virtual uint8_t getRROBBeatID() const = 0;
    //  virtual uint8_t getStartBeatIdx() = 0;
    //  virtual uint8_t getEndBeatIdx() const = 0;
    //  virtual void setRROBBeatID(uint8_t id) = 0;
    //  //end

     virtual void setSourceNiID(int id) = 0;
     virtual int getSourceNiID() const = 0;

     virtual std::array<uint8_t, 16> getFlitData(uint8_t flit_id) = 0;
     virtual  void setBeatSize(uint8_t beat_size) = 0;
     virtual uint8_t getBeatSize() const = 0;
    //  virtual void setBurstLen(uint8_t burst_len) = 0;
    //  virtual uint8_t getRespAXIID() = 0;
     virtual void setData(Payload payload) = 0;
     virtual Payload getData() const = 0;

     int32_t getDebugId() const { return debugId; }
     void setDebugId(int32_t id) { debugId = id; }
     bool hasDebugId() const { return debugId >= 0; }

     /**
      * Optional per-message list of contributing debug ids.
      *
      * This is used when one emitted beat corresponds to multiple source beats
      * (e.g., AXI-S depacketization where an output beat spans multiple packed
      * beats). When present, it should be interpreted as the set of debug ids
      * that contributed bytes to this message payload.
      */
     const std::vector<int32_t>& getDebugIds() const { return debugIds; }
     void setDebugIds(std::vector<int32_t> ids) { debugIds = std::move(ids); }
     bool hasDebugIds() const { return !debugIds.empty(); }
 
     uint64_t getFlitStrobe(uint8_t flit_id) const {
         uint8_t beat_size = (1 << this->getBeatSize());
 
         // Prefer strobe from AXI-MM payload beats, mirroring getFlitData behavior
         Payload payload_data = this->getData();
         if (auto *p = std::get_if<aximmPayload>(&payload_data)) {
             if (beat_size >= 64) {
                 uint8_t beat_idx = (flit_id * 16) / beat_size;
                 if (beat_idx < (*p).size() && (*p)[beat_idx].valid) {
                     uint8_t flits_per_beat = beat_size / 16;
                     uint8_t section = flit_id % flits_per_beat;
                     // Extract 16-bit strobe for this 16B section
                     return ((*p)[beat_idx].wstrb >> (section * 16)) & 0xFFFF;
                 }
             } else if (flit_id < (*p).size() && (*p)[flit_id].valid) {
                 return (*p)[flit_id].wstrb;
             }
         }
 
         // single-beat strobe from message payload if available
         MessagePayload mp = this->getPayload();
         if (std::holds_alternative<aximmRWData>(mp)) {
             const aximmRWData& d = std::get<aximmRWData>(mp);
             if (d.valid) {
                 return d.wstrb;
             }
         }
         return 0; // No valid strobe found
     }

  private:
     int32_t debugId = -1;
     std::vector<int32_t> debugIds;

  public:

    //  virtual void appendData(aximmRWData beat) = 0;
    //  virtual void resizeRequest(uint8_t newSize) = 0;




     virtual const gem5::noc::AxiMsgSizeType& getMessageSize() const
     { panic("MessageSizeType() called on wrong message!"); }
     virtual gem5::noc::AxiMsgSizeType& getMessageSize()
     { panic("MessageSizeType() called on wrong message!"); }

     /**
      * The two functions below are used for reading / writing the message
      * functionally. The methods return true if the address in the packet
      * matches the address / address range in the message. Each message
      * class that can be potentially searched for the address needs to
      * implement these methods.
      */
     virtual bool functionalRead(Packet *pkt)
     { panic("functionalRead(Packet) not implemented"); }
     virtual bool functionalRead(Packet *pkt, gem5::ruby::WriteMask &mask)
     { panic("functionalRead(Packet,WriteMask) not implemented"); }
     virtual bool functionalWrite(Packet *pkt)
     { panic("functionalWrite(Packet) not implemented"); }

     //! Update the delay this message has experienced so far.
     void updateDelayedTicks(Tick curTime)
     {
         assert(m_LastEnqueueTime <= curTime);
         Tick delta = curTime - m_LastEnqueueTime;
         m_DelayedTicks += delta;
     }
     Tick getDelayedTicks() const {return m_DelayedTicks;}

     void setLastEnqueueTime(const Tick& time) { m_LastEnqueueTime = time; }
     Tick getLastEnqueueTime() const {return m_LastEnqueueTime;}

     Tick getTime() const { return m_time; }
     void setTime(Tick t) { m_time = t; }
     void setDelayedTicks(Tick t) { m_DelayedTicks = t; }
     void setMsgCounter(uint64_t c) { m_msg_counter = c; }
     uint64_t getMsgCounter() const { return m_msg_counter; }

     // Functions related to network traversal
     virtual const NocNetDest& getDestination() const
     { panic("getDestination() called on wrong message!"); }
     virtual NocNetDest& getDestination()
     { panic("getDestination() called on wrong message!"); }

     int getIncomingLink() const { return incoming_link; }
     void setIncomingLink(int link) { incoming_link = link; }
     int getVnet() const { return vnet; }
     void setVnet(int net) { vnet = net; }

   protected:
    //  int m_block_size = 0;

   private:
     Tick m_time;
     Tick m_LastEnqueueTime; // my last enqueue time
     Tick m_DelayedTicks; // my delayed cycles
     uint64_t m_msg_counter; // FIXME, should this be a 64-bit value?

     // Variables for required network traversal
     int incoming_link;
     int vnet;
 };

 inline bool
 operator>(const MsgPtr &lhs, const MsgPtr &rhs)
 {
     const NocMessage *l = lhs.get();
     const NocMessage *r = rhs.get();

     if (l->getLastEnqueueTime() == r->getLastEnqueueTime()) {
         return l->getMsgCounter() > r->getMsgCounter();
     }
     return l->getLastEnqueueTime() > r->getLastEnqueueTime();
 }

 inline std::ostream&
 operator<<(std::ostream& out, const NocMessage& obj)
 {
     obj.print(out);
     out << std::flush;
     return out;
 }

 } // namespace noc
 } // namespace gem5

 #endif // __NOC_MESSAGE_HH__
