/*
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

#ifndef __NOC_NOC_NETDEST_HH__
#define __NOC_NOC_NETDEST_HH__

#include <cassert>
#include <iostream>
#include <string>
#include <vector>

#include "mem/ruby/common/Set.hh"
#include "mem/ruby/common/MachineID.hh"

#include "sim/serialize.hh"

namespace gem5
{
    namespace ruby
    {
        class Set;
    }
}

namespace gem5
{

namespace noc
{

class NocSystem;

namespace
{

inline void
nocNetDestSerializeRubySet(CheckpointOut &cp, const gem5::ruby::Set &s)
{
    int n = s.getSize();
    paramOut(cp, "ruby_set_n", n);
    std::string bits;
    if (n > 0) {
        bits.reserve((unsigned)n);
    }
    for (int j = 0; j < n; j++) {
        bits.push_back(s.elementAt(j) ? '1' : '0');
    }
    paramOut(cp, "ruby_set_bits", bits);
}

inline void
nocNetDestUnserializeRubySet(CheckpointIn &cp, gem5::ruby::Set &s)
{
    int n = 0;
    paramIn(cp, "ruby_set_n", n);
    std::string str;
    paramIn(cp, "ruby_set_bits", str);
    s.setSize(n);
    for (int j = 0; j < n && j < (int)str.size(); j++) {
        if (str[j] == '1') {
            s.add(j);
        }
    }
}

} // namespace

// NetDest specifies the network destination of a Message
class NocNetDest
{
  public:
    // Constructors
    // creates and empty set
    NocNetDest();
    NocNetDest(NocSystem *noc_system);
    explicit NocNetDest(int bit_size);

    NocNetDest& operator=(const gem5::ruby::Set& obj);

    ~NocNetDest()
    { }

    void add(gem5::ruby::MachineID newElement);
    void addNetDest(const NocNetDest& netDest);
    void setNetDest(gem5::ruby::MachineType machine, const gem5::ruby::Set& set);
    void remove(gem5::ruby::MachineID oldElement);
    void removeNetDest(const NocNetDest& netDest);
    void clear();
    void broadcast();
    void broadcast(gem5::ruby::MachineType machine);
    int count() const;
    bool isEqual(const NocNetDest& netDest) const;

    // return the logical OR of this netDest and orNetDest
    NocNetDest OR(const NocNetDest& orNetDest) const;

    // return the logical AND of this netDest and andNetDest
    NocNetDest AND(const NocNetDest& andNetDest) const;

    // Returns true if the intersection of the two netDests is non-empty
    bool intersectionIsNotEmpty(const NocNetDest& other_netDest) const;

    // Returns true if the intersection of the two netDests is empty
    bool intersectionIsEmpty(const NocNetDest& other_netDest) const;

    bool isSuperset(const NocNetDest& test) const;
    bool isSubset(const NocNetDest& test) const { return test.isSuperset(*this); }
    bool isElement(gem5::ruby::MachineID element) const;
    bool isBroadcast() const;
    bool isEmpty() const;

    // For Princeton Network
    std::vector<gem5::ruby::NodeID> getAllDest();

    gem5::ruby::MachineID smallestElement() const;
    gem5::ruby::MachineID smallestElement(gem5::ruby::MachineType machine) const;

    void resize();
    int getSize() const { return m_bits.size(); }

    // get element for a index
    gem5::ruby::NodeID elementAt(gem5::ruby::MachineID index);

    void print(std::ostream& out) const;

    void setNocSystem(NocSystem *ns) { m_noc_system = ns; resize(); }

    void
    serialize(CheckpointOut &cp) const
    {
        paramOut(cp, "noc_net_dest_n_levels", (int)m_bits.size());
        for (int i = 0; i < (int)m_bits.size(); i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, std::string("noc_net_dest_level_") + std::to_string(i));
            nocNetDestSerializeRubySet(cp, m_bits[i]);
        }
    }

    void
    unserialize(CheckpointIn &cp)
    {
        int n_levels = 0;
        paramIn(cp, "noc_net_dest_n_levels", n_levels);
        m_bits.clear();
        m_bits.resize(n_levels);
        for (int i = 0; i < n_levels; i++) {
            Serializable::ScopedCheckpointSection sec(
                cp, std::string("noc_net_dest_level_") + std::to_string(i));
            nocNetDestUnserializeRubySet(cp, m_bits[i]);
        }
    }

    int debug_id;

  private:
    // returns a value >= MachineType_base_level("this machine")
    // and < MachineType_base_level("next highest machine")
    int
    vecIndex(gem5::ruby::MachineID m) const
    {
        int vec_index = MachineType_base_level(m.type);
        assert(vec_index < m_bits.size());
        return vec_index;
    }

    gem5::ruby::NodeID bitIndex(gem5::ruby::NodeID index) const { return index; }

    std::vector<gem5::ruby::Set> m_bits;  // a vector of bit vectors - i.e. Sets

    // Needed to call MacheinType_base_count/level
    NocSystem *m_noc_system = nullptr;

    int MachineType_base_count(const gem5::ruby::MachineType& obj);
    int MachineType_base_number(const gem5::ruby::MachineType& obj);


};

inline std::ostream&
operator<<(std::ostream& out, const NocNetDest& obj)
{
    obj.print(out);
    out << std::flush;
    return out;
}

} // namespace noc
} // namespace gem5

#endif // __MEM_RUBY_COMMON_NETDEST_HH__
