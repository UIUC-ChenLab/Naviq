/*
 * Copyright (c) 2020 Advanced Micro Devices, Inc.
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


#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "noc/lib/network/NocMessage.hh"
#include "base/str.hh"
#include "sim/serialize.hh"
#include <type_traits>

namespace gem5
{

namespace ruby
{

namespace garnet
{

template class flitBuffer<Message, RouteInfo>;
template class flitBuffer<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;

template <typename T_Msg, typename T_RouteInfo>
flitBuffer<T_Msg, T_RouteInfo>::flitBuffer()
{
    max_size = INFINITE_;
    size = 0;
}

template <typename T_Msg, typename T_RouteInfo>
flitBuffer<T_Msg, T_RouteInfo>::flitBuffer(int maximum_size)
{
    max_size = maximum_size;
    size = 0;
}

template <typename T_Msg, typename T_RouteInfo>
bool
flitBuffer<T_Msg, T_RouteInfo>::isEmpty()
{
    // return (m_buffer.size() == 0);
    return size == 0;
}

template <typename T_Msg, typename T_RouteInfo>
bool
flitBuffer<T_Msg, T_RouteInfo>::isReady(Tick curTime)
{
    // if (m_buffer.size() != 0 ) {
    if (size != 0 ) {
        flit<T_Msg, T_RouteInfo> *t_flit = peekTopFlit();
        if (t_flit->get_time() <= curTime)
            return true;
    }
    return false;
}

template <typename T_Msg, typename T_RouteInfo>
void
flitBuffer<T_Msg, T_RouteInfo>::print(std::ostream& out) const
{
    // out << "[flitBuffer: " << m_buffer.size() << "] " << std::endl;
    out << "[flitBuffer: " << size << "] " << std::endl;
}

template <typename T_Msg, typename T_RouteInfo>
bool
flitBuffer<T_Msg, T_RouteInfo>::isFull()
{
    // return (m_buffer.size() >= max_size);
    return (size >= max_size);
}

template <typename T_Msg, typename T_RouteInfo>
void
flitBuffer<T_Msg, T_RouteInfo>::setMaxSize(int maximum)
{
    max_size = maximum;
}

template <typename T_Msg, typename T_RouteInfo>
bool
flitBuffer<T_Msg, T_RouteInfo>::functionalRead(Packet *pkt, WriteMask &mask)
{
    bool read = false;
    // for (unsigned int i = 0; i < m_buffer.size(); ++i) {
    for (unsigned int i = 0; i < size; ++i) {
        if (m_buffer[i]->functionalRead(pkt, mask)) {
            read = true;
        }
    }

    return read;
}

template <typename T_Msg, typename T_RouteInfo>
uint32_t
flitBuffer<T_Msg, T_RouteInfo>::functionalWrite(Packet *pkt)
{
    uint32_t num_functional_writes = 0;

    // for (unsigned int i = 0; i < m_buffer.size(); ++i) {
    for (unsigned int i = 0; i < size; ++i) {
        if (m_buffer[i]->functionalWrite(pkt)) {
            num_functional_writes++;
        }
    }

    return num_functional_writes;
}

template <typename T_Msg, typename T_RouteInfo>
void
flitBuffer<T_Msg, T_RouteInfo>::serializeForNocNetworkCheckpoint(
    CheckpointOut &cp) const
{
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        paramOut(cp, "fb_max_size", max_size);
        paramOut(cp, "fb_size", size);
        for (int i = 0; i < size; i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("fb_flit_%d", i).c_str());
            m_buffer[i]->serializeForNocNetworkCheckpoint(cp);
        }
    } else {
        panic("serializeForNocNetworkCheckpoint used on non-Noc buffer");
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
flitBuffer<T_Msg, T_RouteInfo>::unserializeForNocNetworkCheckpoint(
    CheckpointIn &cp)
{
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        while (size > 0) {
            flit<T_Msg, T_RouteInfo> *old = getTopFlit();
            delete old;
        }
        paramIn(cp, "fb_max_size", max_size);
        int n = 0;
        paramIn(cp, "fb_size", n);
        for (int i = 0; i < n; i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, csprintf("fb_flit_%d", i).c_str());
            flit<T_Msg, T_RouteInfo> *f =
                flit<T_Msg, T_RouteInfo>::unserializeForNocNetworkCheckpoint(cp);
            insert(f);
        }
    } else {
        panic("unserializeForNocNetworkCheckpoint used on non-Noc buffer");
    }
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
