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


 #include "noc/core/network/switch/NocOutVcState.hh"

 #include "mem/ruby/system/RubySystem.hh"
 #include "sim/serialize.hh"

 namespace gem5
 {

 namespace noc
 {

 namespace garnet
 {

 NocOutVcState::NocOutVcState(int id, NocGarnetNetwork *network_ptr, uint32_t consumerVcs, Nps_Type nps_type)
     : m_time(0)
 {
     m_id = id;
     m_nps_type = nps_type;
     m_vc_state = gem5::ruby::garnet::IDLE_;

    if (network_ptr) {
        m_max_credit_count =
            network_ptr->get_effective_physical_vc_buffer_depth(
                id, consumerVcs, m_nps_type);
    } else {
        switch(m_nps_type) {
            case Nps_Type::VNOC: m_max_credit_count = 5; break;
            case Nps_Type::HNOC: m_max_credit_count = 7; break;
            case Nps_Type::NCRB: m_max_credit_count = 7; break;
            case Nps_Type::RPTR: m_max_credit_count = 1; break;
            case Nps_Type::NIDB: m_max_credit_count = 7; break;
            default: m_max_credit_count = 5; break;
        }
    }

     m_credit_count = m_max_credit_count;
     assert(m_credit_count >= 1);
 }

 void
 NocOutVcState::increment_credit()
 {
     m_credit_count++;
     assert(m_credit_count <= m_max_credit_count);
 }

 void
 NocOutVcState::decrement_credit()
 {
     m_credit_count--;
     assert(m_credit_count >= 0);
 }

 void
 NocOutVcState::serialize(CheckpointOut &cp) const
 {
     SERIALIZE_SCALAR(m_id);
     paramOutNpsType(cp, "novs_nps_type", m_nps_type);
     SERIALIZE_SCALAR(m_time);
     int st = (int)m_vc_state;
     paramOut(cp, "novs_vc_state", st);
     SERIALIZE_SCALAR(m_credit_count);
     SERIALIZE_SCALAR(m_max_credit_count);
 }

 void
 NocOutVcState::unserialize(CheckpointIn &cp)
 {
     UNSERIALIZE_SCALAR(m_id);
     paramInNpsType(cp, "novs_nps_type", m_nps_type);
     UNSERIALIZE_SCALAR(m_time);
     int st = 0;
     paramIn(cp, "novs_vc_state", st);
     m_vc_state = (gem5::ruby::garnet::VC_state_type)st;
     UNSERIALIZE_SCALAR(m_credit_count);
     UNSERIALIZE_SCALAR(m_max_credit_count);
 }

 } // namespace garnet
 } // namespace noc
 } // namespace gem5
