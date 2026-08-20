
#ifndef __MEM_RUBY_NETWORK_GARNET_0_NOCSWITCHALLOCATOR_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_NOCSWITCHALLOCATOR_HH__

#include <iostream>
#include <vector>
#include <list>
#include <map>
#include <tuple> // For storing (inport, invc) pairs

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "sim/serialize.hh"


namespace gem5 {
namespace ruby {
namespace garnet {
    template <typename T_Msg, typename T_RouteInfo> class InputUnit;
    template <typename T_Msg, typename T_RouteInfo> class OutputUnit;
    template <typename T_Msg, typename T_RouteInfo> class flit;
}
}
}

namespace gem5
{

namespace noc
{

namespace garnet
{

template <typename T_Msg, typename T_RouteInfo> class NocRouter;

// Class definition with template
template <typename T_Msg, typename T_RouteInfo>
class NocSwitchAllocator : public gem5::ruby::Consumer
{
  public:
    NocSwitchAllocator(NocRouter<T_Msg, T_RouteInfo> *router);
    void wakeup();
    void init();
    void check_for_wakeup();
    int get_vnet (int invc);
    void print(std::ostream& out) const {};
    void arbitrate_for_output_port(const std::vector<std::tuple<int, int, int>> current_requests, int outport);
    bool is_eligible(int inport, int invc, int outport, gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit); // Check all conditions
    int get_request_priority(int inport, int invc, gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit); // Implement priority logic
    void update_lru(int outport, int win_inport, int win_invc);
    void grant_request(int outport, int win_inport, int win_invc, int win_outvc, gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit);
    void trace_arbitration(const char *event, int outport, int inport,
        int invc, int priority,
        gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit);
    bool is_write_transaction(gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit); // Heuristic/check for lock requirement
    void acquire_lock(int outport, int outvc, int inport, int invc);
    void release_lock(int outport, int outvc);

    inline double
    get_input_arbiter_activity()
    {
        return m_input_arbiter_activity;
    }
    inline double
    get_output_arbiter_activity()
    {
        return m_output_arbiter_activity;
    }

    void resetStats();

    void serializeNocCheckpoint(CheckpointOut &cp) const;
    void unserializeNocCheckpoint(CheckpointIn &cp);

  private:
    int m_num_inports, m_num_outports;
    int m_num_vcs, m_vc_per_vnet;
    double m_input_arbiter_activity, m_output_arbiter_activity;
    NocRouter<T_Msg, T_RouteInfo> *m_router;

    // LRU state per output port. Stores (inport, invc) pairs in LRU order.
    // The list::iterator allows quick removal/re-insertion for LRU update.
    // Map key: (inport, invc) pair. Map value: iterator pointing to the pair in the list.
    std::vector<std::list<std::pair<int, int>>> m_outport_lru_list;
    std::vector<std::map<std::pair<int, int>, typename std::list<std::pair<int, int>>::iterator>> m_outport_lru_map;

    // Token counters: m_tokens[outport][inport][invc]
    std::vector<std::vector<std::vector<int>>> m_tokens;
    // Initial token values (needs to be loaded, e.g., from parameters)
    std::vector<std::vector<std::vector<int>>> m_initial_tokens; // Example, adjust loading mechanism

    // Hard Lock state: Indicates which input VC currently holds the lock for an output VC.
    // Stores the locking (inport, invc) pair. (-1, -1) means not locked.
    std::vector<std::vector<std::pair<int, int>>> m_output_vc_lock; // Indexed by [outport][outvc]

    // Per-output-port tracking of requests for the current cycle
    // Stores tuples: (priority, inport, invc)
    // Using a vector of vectors, indexed by outport
    // std::vector<std::vector<std::tuple<int, int, int>>> m_current_requests;

    struct cachedData{
        int genCounter; // doubles as valid. this must equal current call count of wakeup for it to be valid cache data for this cycle
        int targetOutport;

        cachedData(): genCounter(-1), targetOutport(-1){};
    };
    //cache info needed by wakeup that check_and_reload_tokens already computes (route_compute)
    std::vector<std::vector<int>> m_cached_route;

    std::vector<bool> m_requester_without_tokens_exists;
    std::vector<bool> m_requester_with_tokens_exists;
    std::vector<std::vector<std::tuple<int, int, int>>> m_requesters_without_tokens; // (inport, invc)
    std::vector<std::vector<std::tuple<int, int, int>>> m_requesters_with_tokens; // (outport, inport, invc)

};

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_SWITCHALLOCATOR_HH__
