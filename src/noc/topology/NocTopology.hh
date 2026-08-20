// copied and modified from src/mem/ruby/network/Topology.hh

#ifndef __NOC_NETWORK_TOPOLOGY_HH__
#define __NOC_NETWORK_TOPOLOGY_HH__

#include <iostream>
#include <vector>

#include "mem/ruby/common/TypeDefines.hh"
#include "noc/core/network/NocBasicLink.hh"
#include "mem/ruby/protocol/LinkDirection.hh"
#include "mem/ruby/system/RubyPort.hh"
#include "noc/core/network/NocSystem.hh"
#include "noc/core/network/NocNetDest.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"

namespace gem5
{
    namespace ruby
    {
        // class NetDest;
        class RubyPort;
    }
}

namespace gem5
{

namespace noc
{

class NocSystem;
class NocNetwork;

/*
 * We use a three-dimensional vector matrix for calculating
 * the shortest paths for each pair of source and destination
 * and for each type of virtual network. The three dimensions
 * represent the source ID, destination ID, and vnet number.
 */
typedef std::vector<std::vector<std::vector<int>>> Matrix;

struct LinkEntry
{
    NocBasicLink *link;
    gem5::ruby::PortDirection src_outport_dirn;
    gem5::ruby::PortDirection dst_inport_dirn;
};

typedef std::map<std::pair<gem5::ruby::SwitchID, gem5::ruby::SwitchID>,
             std::vector<LinkEntry>> LinkMap;

class NocTopology
{
  public:
    NocTopology(uint32_t num_nodes, uint32_t num_routers, uint32_t num_vnets,
             const std::vector<NocBasicExtLink *> &ext_links,
             const std::vector<NocBasicIntLink *> &int_links,
             NocSystem *noc_system);

    uint32_t numSwitches() const { return m_number_of_switches; }
    void createLinks(NocNetwork *net);
    void createCustomLinks(NocNetwork *net, const std::string& custom_routing_table_json);
    void print(std::ostream& out) const { out << "[NocTopology]"; }

  private:
    void addLink(gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest, NocBasicLink* link,
        gem5::ruby::PortDirection src_outport_dirn = "",
        gem5::ruby::PortDirection dest_inport_dirn = "");
    void makeLink(NocNetwork *net, gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest,
                  std::vector<NocNetDest>& routing_table_entry);
    // void makeCustomLink(NocNetwork *net, gem5::ruby::SwitchID src, gem5::ruby::SwitchID dest,
    //                 std::vector<gem5::noc::garnet::NocRouteMapKey>& routes);

    // Helper functions based on chapter 29 of Cormen et al.
    void extend_shortest_path(Matrix &current_dist, Matrix &latencies,
                              Matrix &inter_switches);

    Matrix shortest_path(const Matrix &weights,
            Matrix &latencies, Matrix &inter_switches);

    bool link_is_shortest_path_to_node(gem5::ruby::SwitchID src, gem5::ruby::SwitchID next,
        gem5::ruby::SwitchID final, const Matrix &weights, const Matrix &dist,
            int vnet);

    NocNetDest shortest_path_to_node(gem5::ruby::SwitchID src, gem5::ruby::SwitchID next,
                                  const Matrix &weights, const Matrix &dist,
                                  int vnet);

    uint32_t m_nodes;
    const uint32_t m_number_of_switches;
    int m_vnets;

    std::vector<NocBasicExtLink*> m_ext_link_vector;
    std::vector<NocBasicIntLink*> m_int_link_vector;

    LinkMap m_link_map;

    NocSystem *m_noc_system = nullptr;
};

inline std::ostream&
operator<<(std::ostream& out, const NocTopology& obj)
{
    obj.print(out);
    out << std::flush;
    return out;
}

} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_TOPOLOGY_HH__
