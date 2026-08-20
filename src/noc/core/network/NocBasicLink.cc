/*
 * Copyright (c) 2011 Advanced Micro Devices, Inc.
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

 #include "noc/core/network/NocBasicLink.hh"

 namespace gem5
 {

 namespace noc
 {

 NocBasicLink::NocBasicLink(const Params &p)
     : SimObject(p)
 {
     m_latency = p.latency;
     m_bandwidth_factor = p.bandwidth_factor;
     m_weight = p.weight;
     mVnets = p.supported_vnets;
     m_id = p.link_id;
 }

 void
 NocBasicLink::init()
 {
 }

 void
 NocBasicLink::print(std::ostream& out) const
 {
     out << name();
 }

 void
 NocBasicLink::serialize(CheckpointOut &cp) const
 {
     SimObject::serialize(cp);
     uint64_t lat = (uint64_t)m_latency;
     paramOut(cp, "m_latency", lat);
     SERIALIZE_SCALAR(m_bandwidth_factor);
     SERIALIZE_SCALAR(m_weight);
     SERIALIZE_SCALAR(m_id);
     SERIALIZE_CONTAINER(mVnets);
 }

 void
 NocBasicLink::unserialize(CheckpointIn &cp)
 {
     SimObject::unserialize(cp);
     uint64_t lat = 0;
     paramIn(cp, "m_latency", lat);
     m_latency = Cycles(lat);
     UNSERIALIZE_SCALAR(m_bandwidth_factor);
     UNSERIALIZE_SCALAR(m_weight);
     UNSERIALIZE_SCALAR(m_id);
     UNSERIALIZE_CONTAINER(mVnets);
 }

 NocBasicExtLink::NocBasicExtLink(const Params &p)
     : NocBasicLink(p)
 {
 }

 void
 NocBasicExtLink::serialize(CheckpointOut &cp) const
 {
     NocBasicLink::serialize(cp);
 }

 void
 NocBasicExtLink::unserialize(CheckpointIn &cp)
 {
     NocBasicLink::unserialize(cp);
 }

 NocBasicIntLink::NocBasicIntLink(const Params &p)
     : NocBasicLink(p)
 {
 }

 void
 NocBasicIntLink::serialize(CheckpointOut &cp) const
 {
     NocBasicLink::serialize(cp);
 }

 void
 NocBasicIntLink::unserialize(CheckpointIn &cp)
 {
     NocBasicLink::unserialize(cp);
 }

 } // namespace noc
 } // namespace gem5
