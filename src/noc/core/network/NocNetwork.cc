/*
 * Copyright (c) 2017 ARM Limited
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

// copied and modifid from src/mem/ruby/network/Network.cc
 #include "noc/core/network/NocNetwork.hh"

 #include "base/logging.hh"
 #include "mem/ruby/common/MachineID.hh"
 #include "noc/core/network/NocBasicLink.hh"
 #include "mem/ruby/system/RubySystem.hh"
 #include "noc/core/network/NocSystem.hh"
 #include "sim/serialize.hh"
 #include "noc/core/interface/NocInterface.hh"
 #include <iostream>
 #include <algorithm>

namespace gem5
{

namespace noc
{

uint32_t NocNetwork::m_virtual_networks;
uint32_t NocNetwork::m_control_msg_size;
uint32_t NocNetwork::m_data_msg_size;

NocNetwork::NocNetwork(const Params &p)
    : ClockedObject(p)
{
    // std::cout<<"In NocNetwork constructor \n"<<std::endl;
    m_virtual_networks = p.number_of_virtual_networks;
    m_control_msg_size = p.control_msg_size;

    fatal_if(p.data_msg_size > p.noc_system->getBlockSizeBytes(),
             "%s: data message size > cache line size", name());
    m_data_msg_size = p.data_msg_size + m_control_msg_size;

    m_noc_system = p.noc_system;
    m_noc_system->registerNocNetwork(this);

    // Populate localNodeVersions with the version of each MachineType in
    // this network. This will be used to compute a global to local ID.
    // Do this by looking at the ext_node for each ext_link. There is one
    // ext_node per ext_link and it points to an AbstractController.
    // For RubySystems with one network global and local ID are the same.
    std::unordered_map<gem5::ruby::MachineType, std::vector<gem5::ruby::NodeID>> localNodeVersions;
    for (auto &it : params().ext_links) {
        NocInterface *cntrl = it->params().ext_node;
        auto &versions = localNodeVersions[cntrl->getType()];
        if (std::find(versions.begin(), versions.end(), cntrl->getVersion()) == versions.end()) {
            versions.push_back(cntrl->getVersion());
        }
        params().noc_system->registerMachineID(cntrl->getMachineID(), this);
    }

    // Compute a local ID for each MachineType using the same order as SLICC
    gem5::ruby::NodeID local_node_id = 0;
    for (int i = 0; i < MachineType_base_level(gem5::ruby::MachineType_NUM); ++i) {
        gem5::ruby::MachineType mach = static_cast<gem5::ruby::MachineType>(i);
        if (localNodeVersions.count(mach)) {
            for (auto &ver : localNodeVersions.at(mach)) {
                // Get the global ID Ruby will pass around
                gem5::ruby::NodeID global_node_id = MachineType_base_number(mach) + ver;
                globalToLocalMap.emplace(global_node_id, local_node_id);
                ++local_node_id;
            }
        }
    }

    // Total nodes/controllers in network is equal to the local node count
    // Must make sure this is called after the State Machine constructors
    m_nodes = local_node_id;

    assert(m_nodes != 0);
    assert(m_virtual_networks != 0);

    m_topology_ptr = new NocTopology(m_nodes, p.routers.size(),
                                  m_virtual_networks,
                                  p.ext_links, p.int_links,
                                  m_noc_system);

    // Allocate to and from queues
    // Queues that are getting messages from protocol
    m_toNetQueues.resize(m_nodes);

    // Queues that are feeding the protocol
    m_fromNetQueues.resize(m_nodes);

    m_ordered.resize(m_virtual_networks);
    m_vnet_type_names.resize(m_virtual_networks);

    for (int i = 0; i < m_virtual_networks; i++) {
        m_ordered[i] = false;
    }

    // Initialize the controller's network pointers
    for (std::vector<NocBasicExtLink*>::const_iterator i = p.ext_links.begin();
         i != p.ext_links.end(); ++i) {
        NocBasicExtLink *ext_link = (*i);
        NocInterface *abs_cntrl = ext_link->params().ext_node;
        abs_cntrl->initNocNetworkPtr(this);
        const AddrRangeList &ranges = abs_cntrl->getAddrRanges();
        if (!ranges.empty()) {
            gem5::ruby::MachineID mid = abs_cntrl->getMachineID();
            AddrMapNode addr_map_node = {
                .id = mid.getNum(),
                .ranges = ranges
            };
            addrMap.emplace(mid.getType(), addr_map_node);
        }
    }

    for (auto &it : dynamic_cast<NocNetwork *>(this)->params().ext_links) {
        it->params().ext_node->initNetQueues();
    }
}

NocNetwork::~NocNetwork()
 {
    for (int node = 0; node < m_nodes; node++) {

        // Delete the Message Buffers
        for (auto& it : m_toNetQueues[node]) {
            delete it;
        }

        for (auto& it : m_fromNetQueues[node]) {
            delete it;
        }
    }

    delete m_topology_ptr;
 }

uint32_t
NocNetwork::MessageSizeType_to_int(AxiMsgSizeType size_type)
{
    switch(size_type) {
        case AxiMsgSizeType::AR:
            return sizeof(aximmRWAddr);
        case AxiMsgSizeType::AW:
            return sizeof(aximmRWAddr);
        case AxiMsgSizeType::W:
            return sizeof(aximmRWData);
        case AxiMsgSizeType::R:
            return sizeof(aximmRWData);
        case AxiMsgSizeType::B:
            return sizeof(aximmWResp);
        default:
            panic("Invalid range for type MessageSizeType");
            break;
    }
}

void
NocNetwork::checkNetworkAllocation(gem5::ruby::NodeID local_id, bool ordered,
                                         int network_num,
                                         std::string vnet_type)
 {
    fatal_if(local_id >= m_nodes, "Node ID is out of range");
    fatal_if(network_num >= m_virtual_networks, "Network id is out of range");

    if (ordered) {
        m_ordered[network_num] = true;
    }

    m_vnet_type_names[network_num] = vnet_type;
 }


void
NocNetwork::setToNetQueue(gem5::ruby::NodeID global_id, bool ordered, int network_num,
                                  std::string vnet_type, MessageBuffer *b)
 {
    // gem5::ruby::NodeID local_id = getLocalNodeID(global_id);
    gem5::ruby::NodeID local_id = global_id;
    checkNetworkAllocation(local_id, ordered, network_num, vnet_type);
    DPRINTF(RubyQueue, "setToNetQueue, local_id: %d, network_num: %d\n", local_id, network_num);

    while (m_toNetQueues[local_id].size() <= network_num) {
        m_toNetQueues[local_id].push_back(nullptr);
    }
    m_toNetQueues[local_id][network_num] = b;
 }

void
NocNetwork::setFromNetQueue(gem5::ruby::NodeID global_id, bool ordered, int network_num,
                                   std::string vnet_type, MessageBuffer *b)
{
    gem5::ruby::NodeID local_id = global_id;
    checkNetworkAllocation(local_id, ordered, network_num, vnet_type);
    DPRINTF(RubyQueue, "setFromNetQueue, local_id: %d, network_num: %d\n", local_id, network_num);

    while (m_fromNetQueues[local_id].size() <= network_num) {
        m_fromNetQueues[local_id].push_back(nullptr);
    }
    m_fromNetQueues[local_id][network_num] = b;
}

// NodeID
// NocNetwork::addressToNodeID(Addr addr, MachineType mtype)
// {
//     // Look through the address maps for entries with matching machine
//     // type to get the responsible node for this address.
//     const auto &matching_ranges = addrMap.equal_range(mtype);
//     for (auto it = matching_ranges.first; it != matching_ranges.second; it++) {
//         AddrMapNode &node = it->second;
//         auto &ranges = node.ranges;
//         for (AddrRange &range: ranges) {
//             if (range.contains(addr)) {
//                 return node.id;
//             }
//         }
//     }
//     return m_ruby_system->MachineType_base_count(mtype);
// }

gem5::ruby::NodeID
NocNetwork::getLocalNodeID(gem5::ruby::NodeID global_id) const
{
    assert(globalToLocalMap.count(global_id));
    return globalToLocalMap.at(global_id);
}

bool
NocNetwork::getRandomization() const
{
    return m_noc_system->getRandomization();
}

bool
NocNetwork::getWarmupEnabled() const
{
    return m_noc_system->getWarmupEnabled();
}

int
NocNetwork::MachineType_base_number(const gem5::ruby::MachineType& obj)
{
    return m_noc_system->MachineType_base_number(obj);
}

void
NocNetwork::serialize(CheckpointOut &cp) const
{
    ClockedObject::serialize(cp);
}

void
NocNetwork::unserialize(CheckpointIn &cp)
{
    ClockedObject::unserialize(cp);
}

} // namespace noc
} // namespace gem5
