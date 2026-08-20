// copied and modified from src/mem/ruby/network/Topology.cc

#include "noc/topology/NocTopology.hh"
#include <cassert>

#include "base/trace.hh"
#include "debug/RubyNetwork.hh"
#include "noc/core/network/NocNetDest.hh"
#include "noc/core/network/NocBasicLink.hh"
#include "noc/core/network/NocNetwork.hh"
#include "mem/ruby/slicc_interface/AbstractController.hh"
#include "mem/ruby/system/RubySystem.hh"
#include "noc/core/interface/NocInterface.hh"

#include <sstream>  // For basic string parsing
#include <vector>
#include <string>
#include <unordered_map>
#include <set>

namespace gem5
{

namespace noc
{

const int INFINITE_LATENCY = 10000; // Yes, this is a big hack

// Note: In this file, we use the first 2*m_nodes SwitchIDs to
// represent the input and output endpoint links.  These really are
// not 'switches', as they will not have a Switch object allocated for
// them. The first m_nodes SwitchIDs are the links into the network,
// the second m_nodes set of SwitchIDs represent the the output queues
// of the network.

NocTopology::NocTopology(uint32_t num_nodes, uint32_t num_routers,
                   uint32_t num_vnets,
                   const std::vector<NocBasicExtLink *> &ext_links,
                   const std::vector<NocBasicIntLink *> &int_links,
                   NocSystem *noc_system)
    : m_nodes(noc_system->MachineType_base_number(gem5::ruby::MachineType_NUM)),
      m_number_of_switches(num_routers), m_vnets(num_vnets),
      m_ext_link_vector(ext_links), m_int_link_vector(int_links),
      m_noc_system(noc_system)
{
    // Total nodes/controllers in network
    assert(m_nodes > 1);

    // analyze both the internal and external links, create data structures.
    // The python created external links are bi-directional,
    // and the python created internal links are uni-directional.
    // The networks and topology utilize uni-directional links.
    // Thus each external link is converted to two calls to addLink,
    // one for each direction.
    //
    // External Links
    for (std::vector<NocBasicExtLink*>::const_iterator i = ext_links.begin();
         i != ext_links.end(); ++i) {
        NocBasicExtLink *ext_link = (*i);
        NocInterface *abs_cntrl = ext_link->params().ext_node;
        gem5::ruby::BasicRouter *router = ext_link->params().int_node;

        int machine_base_idx =
            noc_system->MachineType_base_number(abs_cntrl->getType());
        int ext_idx1 = machine_base_idx + abs_cntrl->getVersion();
        int ext_idx2 = ext_idx1 + m_nodes;
        int int_idx = router->params().router_id + 2*m_nodes;

        // create the internal uni-directional links in both directions
        // ext to int
        addLink(ext_idx1, int_idx, ext_link);
        // int to ext
        addLink(int_idx, ext_idx2, ext_link);
    }

    // Internal Links
    for (std::vector<NocBasicIntLink*>::const_iterator i = int_links.begin();
         i != int_links.end(); ++i) {
        NocBasicIntLink *int_link = (*i);
        gem5::ruby::BasicRouter *router_src = int_link->params().src_node;
        gem5::ruby::BasicRouter *router_dst = int_link->params().dst_node;

        gem5::ruby::PortDirection src_outport = int_link->params().src_outport;
        gem5::ruby::PortDirection dst_inport = int_link->params().dst_inport;

        // Store the IntLink pointers for later
        // m_int_link_vector.push_back(int_link);

        int src = router_src->params().router_id + 2*m_nodes;
        int dst = router_dst->params().router_id + 2*m_nodes;

        // create the internal uni-directional link from src to dst
        addLink(src, dst, int_link, src_outport, dst_inport);
    }
}

void
NocTopology::createLinks(NocNetwork *net)
{
    // Find maximum switchID
    gem5::ruby::SwitchID max_switch_id = 0;
    for (LinkMap::const_iterator i = m_link_map.begin();
         i != m_link_map.end(); ++i) {
        std::pair<gem5::ruby::SwitchID, gem5::ruby::SwitchID> src_dest = (*i).first;
        max_switch_id = std::max(max_switch_id, src_dest.first);
        max_switch_id = std::max(max_switch_id, src_dest.second);
    }

    // Initialize weight, latency, and inter switched vectors
    int num_switches = max_switch_id+1;
    Matrix topology_weights(m_vnets,
            std::vector<std::vector<int>>(num_switches,
            std::vector<int>(num_switches, INFINITE_LATENCY)));
    Matrix component_latencies(num_switches,
            std::vector<std::vector<int>>(num_switches,
            std::vector<int>(m_vnets, -1)));
    Matrix component_inter_switches(num_switches,
            std::vector<std::vector<int>>(num_switches,
            std::vector<int>(m_vnets, 0)));

    // Set identity weights to zero
    for (int i = 0; i < topology_weights[0].size(); i++) {
        for (int v = 0; v < m_vnets; v++) {
            topology_weights[v][i][i] = 0;
        }
    }

    // Fill in the topology weights and bandwidth multipliers
    for (auto link_group : m_link_map) {
        std::pair<int, int> src_dest = link_group.first;
        std::vector<bool> vnet_done(m_vnets, 0);
        int src = src_dest.first;
        int dst = src_dest.second;

        // Iterate over all links for this source and destination
        std::vector<LinkEntry> link_entries = link_group.second;
        for (int l = 0; l < link_entries.size(); l++) {
            NocBasicLink* link = link_entries[l].link;
            if (link->mVnets.size() == 0) {
                for (int v = 0; v < m_vnets; v++) {
                    // Two links connecting same src and destination
                    // cannot carry same vnets.
                    fatal_if(vnet_done[v], "Two links connecting same src"
                    " and destination cannot support same vnets");

                    component_latencies[src][dst][v] = link->m_latency;
                    topology_weights[v][src][dst] = link->m_weight;
                    vnet_done[v] = true;
                }
            } else {
                for (int v = 0; v < link->mVnets.size(); v++) {
                    int vnet = link->mVnets[v];
                    fatal_if(vnet >= m_vnets, "Not enough virtual networks "
                             "(setting latency and weight for vnet %d)", vnet);
                    // Two links connecting same src and destination
                    // cannot carry same vnets.
                    fatal_if(vnet_done[vnet], "Two links connecting same src"
                    " and destination cannot support same vnets");

                    component_latencies[src][dst][vnet] = link->m_latency;
                    topology_weights[vnet][src][dst] = link->m_weight;
                    vnet_done[vnet] = true;
                }
            }
        }
    }

    // Walk topology and hookup the links
    Matrix dist = shortest_path(topology_weights, component_latencies,
                                component_inter_switches);

    for (int i = 0; i < topology_weights[0].size(); i++) {
        for (int j = 0; j < topology_weights[0][i].size(); j++) {
            std::vector<NocNetDest> routingMap;
            routingMap.resize(m_vnets, m_noc_system);

            // Not all sources and destinations are connected
            // by direct links. We only construct the links
            // which have been configured in topology.
            bool realLink = false;

            for (int v = 0; v < m_vnets; v++) {
                int weight = topology_weights[v][i][j];
                if (weight > 0 && weight != INFINITE_LATENCY) {
                    realLink = true;
                    routingMap[v] =
                        shortest_path_to_node(i, j, topology_weights, dist, v);
                }
            }
            // Make one link for each set of vnets between
            // a given source and destination. We do not
            // want to create one link for each vnet.
            if (realLink) {
                makeLink(net, i, j, routingMap);
            }
        }
    }
}


bool parseRoutingJSON(const std::string& json_str, std::vector<std::vector<int>>& out_table) {
    out_table.clear();
    if (json_str.empty() || json_str == "[]") return true;

    // Very basic parser for "[[int,int,int,int],[int,int,int,int]]"
    // Assumes no whitespace, no nested complexity other than list of lists of ints
    if (json_str.length() < 4 || json_str.substr(0,2) != "[[" || json_str.substr(json_str.length()-2, 2) != "]]") {
        warn("JSON Parsing: Invalid outer brackets"); return false;
    }

    std::string content = json_str.substr(1, json_str.length() - 2); // Remove outer []

    std::stringstream ss_outer(content);
    std::string segment;

    while(std::getline(ss_outer, segment, ']')) {
        size_t start = segment.find('[');
        if (start == std::string::npos) {
            // Check for trailing comma or whitespace issues if segment isn't just " ,"
             std::string temp = segment;
             temp.erase(std::remove(temp.begin(), temp.end(), ' '), temp.end());
             temp.erase(std::remove(temp.begin(), temp.end(), ','), temp.end());
             if (!temp.empty()) continue; // Skip potentially malformed parts after valid ']'
             else continue; // Skip empty segments between valid lists
        }
        std::string inner_list_str = segment.substr(start + 1);
        if (inner_list_str.empty()) continue; // Skip empty inner lists "[[]...]"

        std::vector<int> row;
        std::stringstream ss_inner(inner_list_str);
        std::string num_str;
        while(std::getline(ss_inner, num_str, ',')) {
            try {
                // Remove leading/trailing whitespace just in case
                num_str.erase(0, num_str.find_first_not_of(" \t\n\r\f\v"));
                num_str.erase(num_str.find_last_not_of(" \t\n\r\f\v") + 1);
                if (!num_str.empty()) {
                    row.push_back(std::stoi(num_str));
                }
            } catch (const std::exception& e) {
                warn("JSON Parsing: Error converting '%s' to int: %s", num_str, e.what());
                return false; // Indicate failure
            }
        }
        // Check if the row size is correct (e.g., 4 elements)
        if (!row.empty()) {
            if (row.size() != 4) {
                 warn("JSON Parsing: Row has %d elements, expected 4.", row.size());
                 return false;
            }
            out_table.push_back(row);
        }
    }
    return true;
}

void
NocTopology::createCustomLinks(NocNetwork *net,
    const std::string& custom_routing_table_json)
{
    std::vector<std::vector<int>> custom_routing_table_raw;
    if (!parseRoutingJSON(custom_routing_table_json, custom_routing_table_raw)) {
        fatal("Failed to parse custom routing table JSON string:\n%s", custom_routing_table_json);
   }

    std::unordered_map<int, std::vector<gem5::noc::garnet::NocRouteMapKey>> routes_by_link_id;
    for (const auto& routing_touple : custom_routing_table_raw) {
        // Format: [link_id, src_node_id, final_dest_node_id, vc_int]

        gem5::noc::garnet::NocRouteMapKey key{routing_touple[1], routing_touple[2], routing_touple[3]};
        routes_by_link_id[routing_touple[0]].push_back(key);
    }

    for (const auto* ext_link_obj : net->params().ext_links){
        NocBasicExtLink *ext_link = const_cast<NocBasicExtLink*>(ext_link_obj);
        NocInterface *abs_cntrl = ext_link->params().ext_node;
        gem5::ruby::BasicRouter *router = ext_link->params().int_node;
        int link_id = ext_link->params().link_id;
        int controller_id = abs_cntrl->getVersion();
        int router_id = router->params().router_id;
        // DPRINTF(RubyNetwork, "Controller: %s\n", abs_cntrl);
        net->makeNocExtInLink(controller_id, router_id, ext_link);
        net->makeNocExtOutLink(router_id, controller_id, ext_link, routes_by_link_id[link_id]);
    }

    // Internal Links
    for (const auto* int_link_obj : net->params().int_links){
        NocBasicIntLink *int_link = const_cast<NocBasicIntLink*>(int_link_obj);
        gem5::ruby::BasicRouter *router_src = int_link->params().src_node;
        gem5::ruby::BasicRouter *router_dst = int_link->params().dst_node;
        int link_id = int_link->params().link_id;
        int src_router_id = router_src->params().router_id;
        int dst_router_id = router_dst->params().router_id;

        net->makeNocInternalLink(src_router_id, dst_router_id, int_link,
            routes_by_link_id[link_id], int_link->params().src_outport,
            int_link->params().dst_inport);
    }
}

void
NocTopology::addLink(gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest, NocBasicLink* link,
    gem5::ruby::PortDirection src_outport_dirn,
    gem5::ruby::PortDirection dst_inport_dirn)
{
    assert(src <= m_number_of_switches+m_nodes+m_nodes);
    assert(dest <= m_number_of_switches+m_nodes+m_nodes);

    std::pair<int, int> src_dest_pair;
    src_dest_pair.first = src;
    src_dest_pair.second = dest;
    LinkEntry link_entry;

    link_entry.link = link;
    link_entry.src_outport_dirn = src_outport_dirn;
    link_entry.dst_inport_dirn  = dst_inport_dirn;

    auto lit = m_link_map.find(src_dest_pair);
    if (lit != m_link_map.end()) {
        // HeteroGarnet allows multiple links between
        // same source-destination pair supporting
        // different vnets. If there is a link already
        // between a given pair of source and destination
        // add this new link to it.
        lit->second.push_back(link_entry);
    } else {
        std::vector<LinkEntry> links;
        links.push_back(link_entry);
        m_link_map[src_dest_pair] = links;
    }
}

void
NocTopology::makeLink(NocNetwork *net, gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest,
                   std::vector<NocNetDest>& routing_table_entry)
{
    // Make sure we're not trying to connect two end-point nodes
    // directly together
    assert(src >= 2 * m_nodes || dest >= 2 * m_nodes);

    std::pair<int, int> src_dest;
    LinkEntry link_entry;

    if (src < m_nodes) {
        src_dest.first = src;
        src_dest.second = dest;
        std::vector<LinkEntry> links = m_link_map[src_dest];
        for (int l = 0; l < links.size(); l++) {
            link_entry = links[l];
            NocBasicLink *link = link_entry.link;
            net->makeExtInLink(src, dest - (2 * m_nodes), link);

        }
    } else if (dest < 2*m_nodes) {
        assert(dest >= m_nodes);
        gem5::ruby::NodeID node = dest - m_nodes;
        src_dest.first = src;
        src_dest.second = dest;
        std::vector<LinkEntry> links = m_link_map[src_dest];
        for (int l = 0; l < links.size(); l++) {
            link_entry = links[l];
            std::vector<NocNetDest> linkRoute;
            linkRoute.resize(m_vnets, m_noc_system);
            NocBasicLink *link = link_entry.link;
            if (link->mVnets.size() == 0) {
                net->makeExtOutLink(src - (2 * m_nodes), node, link,
                                 routing_table_entry);
            } else {
                for (int v = 0; v< link->mVnets.size(); v++) {
                    int vnet = link->mVnets[v];
                    linkRoute[vnet] = routing_table_entry[vnet];
                }
                net->makeExtOutLink(src - (2 * m_nodes), node, link,
                                linkRoute);
            }
        }
    } else {
        assert((src >= 2 * m_nodes) && (dest >= 2 * m_nodes));
        src_dest.first = src;
        src_dest.second = dest;
        std::vector<LinkEntry> links = m_link_map[src_dest];
        for (int l = 0; l < links.size(); l++) {
            link_entry = links[l];
            std::vector<NocNetDest> linkRoute;
            linkRoute.resize(m_vnets, m_noc_system);
            NocBasicLink *link = link_entry.link;
            if (link->mVnets.size() == 0) {
                net->makeInternalLink(src - (2 * m_nodes),
                              dest - (2 * m_nodes), link, routing_table_entry,
                              link_entry.src_outport_dirn,
                              link_entry.dst_inport_dirn);
            } else {
                for (int v = 0; v< link->mVnets.size(); v++) {
                    int vnet = link->mVnets[v];
                    linkRoute[vnet] = routing_table_entry[vnet];
                }
                net->makeInternalLink(src - (2 * m_nodes),
                              dest - (2 * m_nodes), link, linkRoute,
                              link_entry.src_outport_dirn,
                              link_entry.dst_inport_dirn);
            }
        }
    }
}

// void
// NocTopology::makeCustomLink(NocNetwork *net, gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest,
//                             std::vector<gem5::noc::garnet::NocRouteMapKey>& routes)
// {
//     // Make sure we're not trying to connect two end-point nodes
//     // directly together
//     assert(src >= 2 * m_nodes || dest >= 2 * m_nodes);

//     std::pair<int, int> src_dest;
//     LinkEntry link_entry;

//     if (src < m_nodes) {
//         src_dest.first = src;
//         src_dest.second = dest;
//         std::vector<LinkEntry> links = m_link_map[src_dest];
//         for (int l = 0; l < links.size(); l++) {
//             link_entry = links[l];
//             NocBasicLink *link = link_entry.link;
//             net->makeExtInLink(src, dest - (2 * m_nodes), link);
//         }
//     } else if (dest < 2*m_nodes) {
//         assert(dest >= m_nodes);
//         gem5::ruby::NodeID node = dest - m_nodes;
//         src_dest.first = src;
//         src_dest.second = dest;
//         std::vector<LinkEntry> links = m_link_map[src_dest];
//         for (int l = 0; l < links.size(); l++) {
//             link_entry = links[l];
//             NocBasicLink *link = link_entry.link;
//             net->makeExtOutLink(src - (2 * m_nodes), node, link,
//                                 routes);
//         }
//     } else {
//         assert((src >= 2 * m_nodes) && (dest >= 2 * m_nodes));
//         src_dest.first = src;
//         src_dest.second = dest;
//         std::vector<LinkEntry> links = m_link_map[src_dest];
//         for (int l = 0; l < links.size(); l++) {
//             link_entry = links[l];
//             std::vector<NocNetDest> linkRoute;
//             linkRoute.resize(m_vnets, m_noc_system);
//             NocBasicLink *link = link_entry.link;
//             net->makeInternalLink(src - (2 * m_nodes),
//                             dest - (2 * m_nodes), link, routes,
//                             link_entry.src_outport_dirn,
//                             link_entry.dst_inport_dirn);
//         }
//     }
// }

// The following all-pairs shortest path algorithm is based on the
// discussion from Cormen et al., Chapter 26.1.
void
NocTopology::extend_shortest_path(Matrix &current_dist, Matrix &latencies,
    Matrix &inter_switches)
{
    int nodes = current_dist[0].size();

    // We find the shortest path for each vnet for a given pair of
    // source and destinations. This is done simply by traversing via
    // all other nodes and finding the minimum distance.
    for (int v = 0; v < m_vnets; v++) {
        // There is a different topology for each vnet. Here we try to
        // build a topology by finding the minimum number of intermediate
        // switches needed to reach the destination
        bool change = true;
        while (change) {
            change = false;
            for (int i = 0; i < nodes; i++) {
                for (int j = 0; j < nodes; j++) {
                    // We follow an iterative process to build the shortest
                    // path tree:
                    // 1. Start from the direct connection (if there is one,
                    // otherwise assume a hypothetical infinite weight link).
                    // 2. Then we iterate through all other nodes considering
                    // new potential intermediate switches. If we find any
                    // lesser weight combination, we set(update) that as the
                    // new weight between the source and destination.
                    // 3. Repeat for all pairs of nodes.
                    // 4. Go to step 1 if there was any new update done in
                    // Step 2.
                    int minimum = current_dist[v][i][j];
                    int previous_minimum = minimum;
                    int intermediate_switch = -1;
                    for (int k = 0; k < nodes; k++) {
                        minimum = std::min(minimum,
                            current_dist[v][i][k] + current_dist[v][k][j]);
                        if (previous_minimum != minimum) {
                            intermediate_switch = k;
                            inter_switches[i][j][v] =
                                inter_switches[i][k][v] +
                                inter_switches[k][j][v] + 1;
                        }
                        previous_minimum = minimum;
                    }
                    if (current_dist[v][i][j] != minimum) {
                        change = true;
                        current_dist[v][i][j] = minimum;
                        assert(intermediate_switch >= 0);
                        assert(intermediate_switch < latencies[i].size());
                        latencies[i][j][v] =
                            latencies[i][intermediate_switch][v] +
                            latencies[intermediate_switch][j][v];
                    }
                }
            }
        }
    }
}

Matrix
NocTopology::shortest_path(const Matrix &weights, Matrix &latencies,
                        Matrix &inter_switches)
{
    Matrix dist = weights;
    extend_shortest_path(dist, latencies, inter_switches);
    return dist;
}

bool
NocTopology::link_is_shortest_path_to_node(gem5::ruby::SwitchID src, gem5::ruby::SwitchID next,
    gem5::ruby::SwitchID final, const Matrix &weights,
                                        const Matrix &dist, int vnet)
{
    return weights[vnet][src][next] + dist[vnet][next][final] ==
        dist[vnet][src][final];
}

NocNetDest
NocTopology::shortest_path_to_node(gem5::ruby::SwitchID src, gem5::ruby::SwitchID next,
                                const Matrix &weights, const Matrix &dist,
                                int vnet)
{
    NocNetDest result(m_noc_system);
    int d = 0;
    int machines;
    int max_machines;

    machines = gem5::ruby::MachineType_NUM;
    max_machines = m_noc_system->MachineType_base_number(gem5::ruby::MachineType_NUM);

    for (int m = 0; m < machines; m++) {
        for (gem5::ruby::NodeID i = 0;
            i < m_noc_system->MachineType_base_count((gem5::ruby::MachineType)m); i++) {
            // we use "d+max_machines" below since the "destination"
            // switches for the machines are numbered
            // [MachineType_base_number(MachineType_NUM)...
            //  2*MachineType_base_number(MachineType_NUM)-1] for the
            // component network
            if (link_is_shortest_path_to_node(src, next, d + max_machines,
                    weights, dist, vnet)) {
                        gem5::ruby::MachineID mach = {(gem5::ruby::MachineType)m, i};
                result.add(mach);
            }
            d++;
        }
    }

    DPRINTF(RubyNetwork, "Returning shortest path\n"
            "(src-(2*max_machines)): %d, (next-(2*max_machines)): %d, "
            "src: %d, next: %d, vnet:%d result: %s\n",
            (src-(2*max_machines)), (next-(2*max_machines)),
            src, next, vnet, result);

    return result;
}

} // namespace ruby
} // namespace gem5
