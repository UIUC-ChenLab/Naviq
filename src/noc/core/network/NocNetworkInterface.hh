/*
* Copyright (c) 2020 Advanced Micro Devices, Inc.
* Copyright (c) 2020 Inria
* Copyright (c) 2016 Georgia Institute of Technology
* Copyright (c) 2008 Princeton University
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
#ifndef __MEM_RUBY_NETWORK_GARNET_0_NETWORKINTERFACE_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_NETWORKINTERFACE_HH__

#include <deque>
#include <iostream>
#include <vector>

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/Credit.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "noc/core/network/NocGarnetNetwork.hh"
#include "mem/ruby/network/garnet/NetworkLink.hh"
#include "noc/core/network/switch/NocOutVcState.hh"
#include "noc/lib/network/NocMessage.hh"
#include "params/NocGarnetNetworkInterface.hh"
#include "sim/serialize.hh"

#include <string>


namespace gem5
{

namespace noc
{
class NocProbe;
}

    namespace ruby {
        namespace garnet{
            template <typename T_Msg, typename T_RouteInfo>
            class flitBuffer;

            template <typename T_Msg, typename T_RouteInfo>
            class NetworkLink;

            template <typename T_Msg, typename T_RouteInfo>
            class CreditLink;

            template <typename T_Msg, typename T_RouteInfo>
            class flit;
        }
    }

namespace noc
{

class MessageBuffer;
class NocOutVcState;

namespace garnet
{

class NocGarnetNetwork;

/**
 * Clocked boundary between protocol handlers and the routed NoC.
 *
 * Protocol handlers exchange owned State objects through per-channel CDC
 * queues.  The NI turns the resulting messages into flits, applies virtual
 * channel and credit backpressure, and delivers received flits to its NMU or
 * NSU.  Ready/valid state remains stable while a CDC or VC queue is stalled.
 */
class NetworkInterface : public ClockedObject, public gem5::ruby::Consumer
{
  public:
    typedef NocGarnetNetworkInterfaceParams Params;
    /** Max flits per NI output VC; inject stalls when full (backpressure). */
    static constexpr int kNiOutVcMaxFlits = 16;
    static constexpr int kNppAssemblerMaxFlits = 7;
    NetworkInterface(const Params &p);
    ~NetworkInterface() = default;

    void addInPort(gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *in_link,
                   gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *credit_link,
                   int router_id = -1);
    void addOutPort(gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *out_link, gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *credit_link,
        gem5::ruby::SwitchID router_id, uint32_t consumerVcs);

    void dequeueCallback();
    void wakeup();
    virtual void addNode(std::vector<MessageBuffer *> &inNode,
                 std::vector<MessageBuffer *> &outNode) = 0;

    void print(std::ostream& out) const;
    int get_vnet(int vc);
    void init_net_ptr(NocGarnetNetwork *net_ptr) { m_net_ptr = net_ptr; }

    bool functionalRead(Packet *pkt, gem5::ruby::WriteMask &mask);
    uint32_t functionalWrite(Packet *);

    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;

    int findOutPortIndexForFlitQueue(
        const gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *q)
        const;

    int findInputPortIndexForCreditQueue(
        const gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *q)
        const;

    gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *
    getOutPortFlitQueueByIndex(int out_idx) const;

    gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *
    getInputPortCreditQueueByIndex(int in_idx) const;

    void scheduleFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo> *t_flit);

    int get_router_id(int vnet)
    {
        OutputPort *oPort = getOutportForVnet(vnet);
        assert(oPort);
        return oPort->routerID();
    }

    class OutputPort
    {
      public:
          OutputPort(gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *outLink, gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *creditLink,
              int routerID)
          {
              _vnets = outLink->mVnets;
              _outFlitQueue = new gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo>();

              _outNetLink = outLink;
              _inCreditLink = creditLink;

              _routerID = routerID;
              _bitWidth = outLink->bitWidth;
              _vcRoundRobin = 0;

          }

          gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *
          outFlitQueue()
          {
              return _outFlitQueue;
          }

          gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *
          outNetLink()
          {
              return _outNetLink;
          }

          gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *
          inCreditLink()
          {
              return _inCreditLink;
          }

          int
          routerID()
          {
              return _routerID;
          }

          uint32_t bitWidth()
          {
              return _bitWidth;
          }

          bool isVnetSupported(int pVnet)
          {
              if (!_vnets.size()) {
                  return true;
              }

              for (auto &it : _vnets) {
                  if (it == pVnet) {
                      return true;
                  }
              }
              return false;

          }

          std::string
          printVnets()
          {
              std::stringstream ss;
              for (auto &it : _vnets) {
                  ss << it;
                  ss << " ";
              }
              return ss.str();
          }

          int vcRoundRobin()
          {
              return _vcRoundRobin;
          }

          void vcRoundRobin(int vc)
          {
              _vcRoundRobin = vc;
          }


      private:
          std::vector<int> _vnets;
          gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *_outFlitQueue;

          gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *_outNetLink;
          gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *_inCreditLink;

          int _vcRoundRobin; // For round robin scheduling

          int _routerID;
          uint32_t _bitWidth;
    };

    class InputPort
    {
      public:
          using NocFlit = gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>;

          InputPort(gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *inLink,
                    gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *creditLink,
                    int routerID = -1)
          {
              _vnets = inLink->mVnets;
              _outCreditQueue = new gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo>();

              _inNetLink = inLink;
              _outCreditLink = creditLink;
              _bitWidth = inLink->bitWidth;
              _routerID = routerID;
          }

          gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *
          outCreditQueue()
          {
              return _outCreditQueue;
          }

          gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *
          inNetLink()
          {
              return _inNetLink;
          }

          gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *
          outCreditLink()
          {
              return _outCreditLink;
          }

          bool isVnetSupported(int pVnet)
          {
              if (!_vnets.size()) {
                  return true;
              }

              for (auto &it : _vnets) {
                  if (it == pVnet) {
                      return true;
                  }
              }
              return false;

          }

          void sendCredit(gem5::ruby::garnet::Credit<NocMessage, NocRouteInfo> *cFlit)
          {
              _outCreditQueue->insert(cFlit);
          }

          uint32_t bitWidth()
          {
              return _bitWidth;
          }

          int routerID() const
          {
              return _routerID;
          }

          std::string
          printVnets()
          {
              std::stringstream ss;
              for (auto &it : _vnets) {
                  ss << it;
                  ss << " ";
              }
              return ss.str();
          }

          void resizeNppAssemblers(int vcs)
          {
              m_npp_assemblers.resize(vcs);
          }

          std::deque<NocFlit *> &nppAssemblerForVc(int vc)
          {
              assert(vc >= 0 && static_cast<size_t>(vc) < m_npp_assemblers.size());
              return m_npp_assemblers[vc];
          }

          std::vector<std::deque<NocFlit *>> &nppAssemblers()
          {
              return m_npp_assemblers;
          }

          int nextAssemblerVc() const
          {
              return _nextAssemblerVc;
          }

          void setNextAssemblerVc(int vc)
          {
              _nextAssemblerVc = vc;
          }

          // Queue for stalled flits
          std::vector<std::deque<NocFlit *>> m_npp_assemblers;
      private:
          std::vector<int> _vnets;
          gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo> *_outCreditQueue;
          int _nextAssemblerVc = 0;
          gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo> *_inNetLink;
          gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo> *_outCreditLink;
          uint32_t _bitWidth;
          int _routerID;
    };

  protected:
    NocGarnetNetwork *m_net_ptr;
    const gem5::ruby::NodeID m_id;
    const int m_virtual_networks;
    int m_vc_per_vnet;
    std::vector<int> m_vc_allocator;
    std::vector<OutputPort *> outPorts;
    std::vector<InputPort *> inPorts;
    int m_deadlock_threshold;
    std::vector<NocOutVcState> outVcState;

    int m_locked_assembler_input_port = -1;
    int m_locked_assembler_vc = -1;
    int m_next_assembler_input_port = 0;

    // Input Flit Buffers
    // The flit buffers which will serve the Consumer
    std::vector<gem5::ruby::garnet::flitBuffer<NocMessage, NocRouteInfo>>  niOutVcs;
    std::vector<Tick> m_ni_out_vcs_enqueue_time;

    // The Message buffers that takes messages from the protocol
    std::vector<MessageBuffer *> inNode_ptr;
    // The Message buffers that provides messages to the protocol
    std::vector<MessageBuffer *> outNode_ptr;
    // When a vc stays busy for a long time, it indicates a deadlock
    std::vector<int> vc_busy_counter;

    int nmu_latency; // in versal NoC, cycles between receiving AXI request and outputting flits, assuming no stalling

    virtual bool flitisizeMessage(MsgPtr msg_ptr, int vnet) = 0;
    virtual bool depacketizeFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* flit) = 0; // De-packetizing
    int calculateVC(int vnet);


    void scheduleOutputPort(OutputPort *oPort);
    void scheduleOutputLink();
    void checkReschedule();
    MessageBuffer *getOutNodeQueue(int vnet) const;
    void registerStallCallbackForVnet(int vnet);

    InputPort *getInportForVnet(int vnet);
    OutputPort *getOutportForVnet(int vnet);

    int MachineType_base_number(const gem5::ruby::MachineType& obj);

    bool injectFlit(gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* fl, int vnet, MsgPtr msg_ptr, int vc);

    gem5::noc::NocProbe* m_nocProbe = nullptr;
    void nocProbeEvent(const char* hookId);
    void nocProbeEvent(const char* hookId, gem5::ruby::garnet::flit<NocMessage, NocRouteInfo>* fl);
    void nocProbeEvent(const char* hookId, const MsgPtr& msg);

};

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_NETWORKINTERFACE_HH__
