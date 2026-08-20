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

#include "noc/core/network/NocNetDest.hh"

#include <algorithm>

#include "noc/core/network/NocSystem.hh"

namespace gem5
{

namespace noc
{

NocNetDest::NocNetDest()
{
}

NocNetDest::NocNetDest(NocSystem *noc_system)
    : m_noc_system(noc_system)
{
    static int call_count = 0;

    debug_id = call_count;
    call_count++;
    resize();
}

void
NocNetDest::add(gem5::ruby::MachineID newElement)
{
    assert(m_bits.size() > 0);
    assert(bitIndex(newElement.num) < m_bits[vecIndex(newElement)].getSize());
    m_bits[vecIndex(newElement)].add(bitIndex(newElement.num));
}

void
NocNetDest::addNetDest(const NocNetDest& NocNetDest)
{
    assert(m_bits.size() > 0);
    assert(m_bits.size() == NocNetDest.getSize());
    for (int i = 0; i < m_bits.size(); i++) {
        m_bits[i].addSet(NocNetDest.m_bits[i]);
    }
}

void
NocNetDest::setNetDest(gem5::ruby::MachineType machine, const gem5::ruby::Set& set)
{
    assert(m_noc_system != nullptr);

    // assure that there is only one set of destinations for this machine
    assert(MachineType_base_level((gem5::ruby::MachineType)(machine + 1)) -
           MachineType_base_level(machine) == 1);
    m_bits[MachineType_base_level(machine)] = set;
}

void
NocNetDest::remove(gem5::ruby::MachineID oldElement)
{
    assert(m_bits.size() > 0);
    m_bits[vecIndex(oldElement)].remove(bitIndex(oldElement.num));
}

void
NocNetDest::removeNetDest(const NocNetDest& netDest)
{
    assert(m_bits.size() > 0);
    assert(m_bits.size() == netDest.getSize());
    for (int i = 0; i < m_bits.size(); i++) {
        m_bits[i].removeSet(netDest.m_bits[i]);
    }
}

void
NocNetDest::clear()
{
    assert(m_bits.size() > 0);
    for (int i = 0; i < m_bits.size(); i++) {
        m_bits[i].clear();
    }
}

void
NocNetDest::broadcast()
{
    for (gem5::ruby::MachineType machine = gem5::ruby::MachineType_FIRST;
         machine < gem5::ruby::MachineType_NUM; ++machine) {
        broadcast(machine);
    }
}

void
NocNetDest::broadcast(gem5::ruby::MachineType machineType)
{
    assert(m_noc_system != nullptr);

    for (gem5::ruby::NodeID i = 0; i < MachineType_base_count(machineType); i++) {
        gem5::ruby::MachineID mach = {machineType, i};
        add(mach);
    }
}

//For Princeton Network
std::vector<gem5::ruby::NodeID>
NocNetDest::getAllDest()
{
    assert(m_noc_system != nullptr);
    assert(m_bits.size() > 0);

    std::vector<gem5::ruby::NodeID> dest;
    dest.clear();
    for (int i = 0; i < m_bits.size(); i++) {
        for (int j = 0; j < m_bits[i].getSize(); j++) {
            if (m_bits[i].isElement(j)) {
                int id = MachineType_base_number((gem5::ruby::MachineType)i) + j;
                dest.push_back((gem5::ruby::NodeID)id);
            }
        }
    }
    return dest;
}

int
NocNetDest::count() const
{
    assert(m_bits.size() > 0);

    int counter = 0;
    for (int i = 0; i < m_bits.size(); i++) {
        counter += m_bits[i].count();
    }
    return counter;
}

gem5::ruby::NodeID
NocNetDest::elementAt(gem5::ruby::MachineID index)
{
    assert(m_bits.size() > 0);
    return m_bits[vecIndex(index)].elementAt(bitIndex(index.num));
}

gem5::ruby::MachineID
NocNetDest::smallestElement() const
{
    assert(m_bits.size() > 0);
    assert(count() > 0);
    for (int i = 0; i < m_bits.size(); i++) {
        for (gem5::ruby::NodeID j = 0; j < m_bits[i].getSize(); j++) {
            if (m_bits[i].isElement(j)) {
                gem5::ruby::MachineID mach = {gem5::ruby::MachineType_from_base_level(i), j};
                return mach;
            }
        }
    }
    panic("No smallest element of an empty set.");
}

gem5::ruby::MachineID
NocNetDest::smallestElement(gem5::ruby::MachineType machine) const
{
    assert(m_bits.size() > 0);
    assert(m_noc_system != nullptr);

    int size = m_bits[MachineType_base_level(machine)].getSize();
    for (gem5::ruby::NodeID j = 0; j < size; j++) {
        if (m_bits[MachineType_base_level(machine)].isElement(j)) {
            gem5::ruby::MachineID mach = {machine, j};
            return mach;
        }
    }

    panic("No smallest element of given MachineType.");
}

// Returns true iff all bits are set
bool
NocNetDest::isBroadcast() const
{
    assert(m_bits.size() > 0);
    for (int i = 0; i < m_bits.size(); i++) {
        if (!m_bits[i].isBroadcast()) {
            return false;
        }
    }
    return true;
}

// Returns true iff no bits are set
bool
NocNetDest::isEmpty() const
{
    assert(m_bits.size() > 0);
    for (int i = 0; i < m_bits.size(); i++) {
        if (!m_bits[i].isEmpty()) {
            return false;
        }
    }
    return true;
}

// returns the logical OR of "this" set and orNocNetDest
NocNetDest
NocNetDest::OR(const NocNetDest& orNetDest) const
{
    assert(m_bits.size() > 0);
    assert(m_bits.size() == orNetDest.getSize());
    NocNetDest result(m_noc_system);
    for (int i = 0; i < m_bits.size(); i++) {
        result.m_bits[i] = m_bits[i].OR(orNetDest.m_bits[i]);
    }
    return result;
}

// returns the logical AND of "this" set and andNetDest
NocNetDest
NocNetDest::AND(const NocNetDest& andNetDest) const
{
    assert(m_bits.size() > 0);
    assert(m_bits.size() == andNetDest.getSize());
    NocNetDest result(m_noc_system);
    for (int i = 0; i < m_bits.size(); i++) {
        result.m_bits[i] = m_bits[i].AND(andNetDest.m_bits[i]);
    }
    return result;
}

// Returns true if the intersection of the two sets is non-empty
bool
NocNetDest::intersectionIsNotEmpty(const NocNetDest& other_netDest) const
{
    assert(m_bits.size() > 0);
    assert(m_bits.size() == other_netDest.getSize());
    for (int i = 0; i < m_bits.size(); i++) {
        if (!m_bits[i].intersectionIsEmpty(other_netDest.m_bits[i])) {
            return true;
        }
    }
    return false;
}

bool
NocNetDest::isSuperset(const NocNetDest& test) const
{
    assert(m_bits.size() > 0);
    assert(m_bits.size() == test.getSize());

    for (int i = 0; i < m_bits.size(); i++) {
        if (!m_bits[i].isSuperset(test.m_bits[i])) {
            return false;
        }
    }
    return true;
}

bool
NocNetDest::isElement(gem5::ruby::MachineID element) const
{
    assert(m_bits.size() > 0);
    return ((m_bits[vecIndex(element)])).isElement(bitIndex(element.num));
}

void
NocNetDest::resize()
{
    assert(m_noc_system != nullptr);

    m_bits.resize(MachineType_base_level(gem5::ruby::MachineType_NUM));
    assert(m_bits.size() == gem5::ruby::MachineType_NUM);

    for (int i = 0; i < m_bits.size(); i++) {
        m_bits[i].setSize(MachineType_base_count((gem5::ruby::MachineType)i));
    }
}

void
NocNetDest::print(std::ostream& out) const
{
    assert(m_bits.size() > 0);
    out << "[NocNetDest (" << m_bits.size() << ") ";

    for (int i = 0; i < m_bits.size(); i++) {
        for (int j = 0; j < m_bits[i].getSize(); j++) {
            out << (bool) m_bits[i].isElement(j) << " ";
        }
        out << " - ";
    }
    out << "]";
}

bool
NocNetDest::isEqual(const NocNetDest& n) const
{
    assert(m_bits.size() > 0);
    assert(m_bits.size() == n.m_bits.size());
    for (unsigned int i = 0; i < m_bits.size(); ++i) {
        if (!m_bits[i].isEqual(n.m_bits[i]))
            return false;
    }
    return true;
}

int
NocNetDest::MachineType_base_count(const gem5::ruby::MachineType& obj)
{
    assert(m_noc_system != nullptr);
    return m_noc_system->MachineType_base_count(obj);
}

int
NocNetDest::MachineType_base_number(const gem5::ruby::MachineType& obj)
{
    assert(m_noc_system != nullptr);
    return m_noc_system->MachineType_base_number(obj);
}

} // namespace noc
} // namespace gem5
