/*
 * Copyright (c) 2008 Princeton University
 * Copyright (c) 2016 Georgia Institute of Technology
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

 // copioed and modified from mem/ruby/network/garnet/GarnetLink.hh

 #ifndef __NOCGARNETLINK_HH__
 #define __NOCGARNETLINK_HH__

 #include <iostream>
 #include <string>
 #include <vector>

 #include "noc/core/network/NocBasicLink.hh"
 #include "mem/ruby/network/garnet/CreditLink.hh"
 #include "mem/ruby/network/garnet/NetworkBridge.hh"
 #include "mem/ruby/network/garnet/NetworkLink.hh"
 #include "mem/ruby/network/garnet/CommonTypes.hh"
 #include "params/NocGarnetExtLink.hh"
 #include "params/NocGarnetIntLink.hh"
 #include "noc/lib/network/NocMessage.hh"
 #include "sim/serialize.hh"

 namespace gem5
 {
 namespace noc
 {

 namespace garnet
 {


 class NocGarnetIntLink : public NocBasicIntLink
 {
   public:

     typedef NocGarnetIntLinkParams Params;
     NocGarnetIntLink(const Params &p);

     void init();

     void print(std::ostream& out) const;

     void serialize(CheckpointOut &cp) const override;
     void unserialize(CheckpointIn &cp) override;

     friend class NocGarnetNetwork;

   protected:
     gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo>* m_network_link;
     gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo>* m_credit_link;

     bool srcBridgeEn;
     bool dstBridgeEn;

     bool srcSerdesEn;
     bool dstSerdesEn;

     bool srcCdcEn;
     bool dstCdcEn;

     gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo>* srcNetBridge;
     gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo>* dstNetBridge;

     gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo>* srcCredBridge;
     gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo>* dstCredBridge;
 };

 inline std::ostream&
 operator<<(std::ostream& out, const NocGarnetIntLink& obj)
 {
     obj.print(out);
     out << std::flush;
     return out;
 }

 class NocGarnetExtLink : public NocBasicExtLink
 {
   public:
     typedef NocGarnetExtLinkParams Params;
     NocGarnetExtLink(const Params &p);

     void init();

     void print(std::ostream& out) const;

     void serialize(CheckpointOut &cp) const override;
     void unserialize(CheckpointIn &cp) override;

     friend class NocGarnetNetwork;

   protected:
     bool extBridgeEn;
     bool intBridgeEn;

     bool extSerdesEn;
     bool intSerdesEn;

     bool extCdcEn;
     bool intCdcEn;

     gem5::ruby::garnet::NetworkLink<NocMessage, NocRouteInfo>* m_network_links[2];
     gem5::ruby::garnet::CreditLink<NocMessage, NocRouteInfo>* m_credit_links[2];

     gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo>* extNetBridge[2];
     gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo>* intNetBridge[2];

     gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo>* extCredBridge[2];
     gem5::ruby::garnet::NetworkBridge<NocMessage, NocRouteInfo>* intCredBridge[2];

 };

 inline std::ostream&
 operator<<(std::ostream& out, const NocGarnetExtLink& obj)
 {
     obj.print(out);
     out << std::flush;
     return out;
 }

 } // namespace garnet
 } // namespace noc
 } // namespace gem5

 #endif //__MEM_RUBY_NETWORK_GARNET_0_GARNETLINK_HH__
