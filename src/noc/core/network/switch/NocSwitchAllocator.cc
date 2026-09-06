#include "noc/core/network/switch/NocSwitchAllocator.hh"

#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh"
#include "mem/ruby/network/garnet/InputUnit.hh"
#include "noc/debug/NocProbeHook.hh"
#include "mem/ruby/network/garnet/OutputUnit.hh"
#include "noc/core/network/switch/NocRouter.hh"
#include "noc/lib/network/NocMessage.hh"

#include "base/str.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace noc
{

namespace garnet
{

template class NocSwitchAllocator<gem5::ruby::Message, gem5::ruby::garnet::RouteInfo>;
template class NocSwitchAllocator<NocMessage, NocRouteInfo>;

template <typename T_Msg, typename T_RouteInfo>
NocSwitchAllocator<T_Msg, T_RouteInfo>::NocSwitchAllocator(NocRouter<T_Msg, T_RouteInfo> *router)
: Consumer(router)
{
    m_router = router;
    m_num_vcs = m_router->get_num_vcs();
    m_vc_per_vnet = m_router->get_vc_per_vnet();

    m_input_arbiter_activity = 0;
    m_output_arbiter_activity = 0;
}

template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::init()
{
    m_num_inports = m_router->get_num_inports();
    m_num_outports = m_router->get_num_outports();

    m_outport_lru_list.resize(m_num_outports);
    m_outport_lru_map.resize(m_num_outports);

    int default_initial_tokens = 16; // Not sure what this should be? pull from file somewhere?????
    m_initial_tokens.resize(m_num_outports,
        std::vector<std::vector<int>>(m_num_inports,
            std::vector<int>(m_num_vcs, default_initial_tokens)));
    m_tokens = m_initial_tokens; // Initialize current tokens

    m_output_vc_lock.resize(m_num_outports,
        std::vector<std::pair<int, int>>(m_num_vcs, {-1, -1})); // -1 indicates no lock

    // m_current_requests.resize(m_num_outports);
    // for (int inport = 0; inport < m_num_inports; ++inport) {
    //     auto input_unit = m_router->getInputUnit(inport);
    //     for (int invc = 0; invc < m_num_vcs; ++invc) {
    //         input_unit->set_vc_active(invc, curTick());
    //     }
    // }

    m_cached_route.resize(m_num_inports, std::vector<int>(m_num_vcs, -1));
    m_requester_without_tokens_exists.resize(m_num_outports);
    m_requester_with_tokens_exists.resize(m_num_outports);
    m_requesters_without_tokens.resize(m_num_outports);
    m_requesters_with_tokens.resize(m_num_outports);
}


template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::wakeup()
{
    // Preserve the NCRB/NIDB/RPTR pipeline, but arbitrate where configured
    // paths converge. Different input ports must not interleave NPPs on one
    // output VC: downstream route caches and assemblers hold one NPP per VC.
    Nps_Type nps = m_router->get_nps_type();
    if (nps == Nps_Type::NCRB || nps == Nps_Type::NIDB || nps == Nps_Type::RPTR) {
        const bool use_internal_pipe = m_router->usesInternalIngressPipeline();
        using Request = std::pair<int, int>; // (inport, invc)
        std::vector<std::vector<Request>> requests(m_num_outports);

        for (int inport = 0; inport < m_num_inports; ++inport) {
            auto iu = m_router->getInputUnit(inport);
            for (int invc = 0; invc < m_num_vcs; ++invc) {
                const bool ready = use_internal_pipe ?
                    m_router->hasReadyInternalFlit(inport, invc, curTick()) :
                    iu->need_stage(invc, gem5::ruby::garnet::SA_, curTick());
                if (!ready) continue;

                auto flit = use_internal_pipe ?
                    m_router->peekInternalFlit(inport, invc) :
                    iu->peekTopFlit(invc);
                if (!flit) continue;
                const int outport = m_router->route_compute(
                    flit->get_route(), inport, iu->get_direction(), invc);
                panic_if(outport < 0 || outport >= m_num_outports,
                    "Router %d pass-through has invalid output %d",
                    m_router->get_id(), outport);

                const Request request{inport, invc};
                // Unseen requesters enter as least recently served. Merely
                // falling back to them when the existing LRU list is empty
                // would starve a newly active input under sustained traffic.
                auto &lru = m_outport_lru_list[outport];
                auto &lru_map = m_outport_lru_map[outport];
                if (lru_map.find(request) == lru_map.end()) {
                    lru.push_front(request);
                    lru_map.emplace(request, lru.begin());
                }

                const auto &owner = m_output_vc_lock[outport][invc];
                if (owner.first != -1 && owner != request) continue;
                if (!m_router->getOutputUnit(outport)->has_noccredit(invc))
                    continue;
                requests[outport].push_back(request);
                trace_arbitration("request", outport, inport, invc, 0, flit);
            }
        }

        // One grant per output models the physical link. Also limit each
        // input to one grant: CrossbarSwitch drains one flit per input per
        // cycle, so a tail cannot linger there after its VC lock is released
        // while another input's next head overtakes it. Rotate output order
        // to share an input fairly when its VCs request different outputs.
        std::vector<bool> input_granted(m_num_inports, false);
        const int first_outport = m_num_outports ?
            static_cast<uint64_t>(m_router->curCycle()) % m_num_outports : 0;
        bool granted = false;
        for (int offset = 0; offset < m_num_outports; ++offset) {
            const int outport = (first_outport + offset) % m_num_outports;
            Request winner{-1, -1};
            for (const auto &request : m_outport_lru_list[outport]) {
                if (!input_granted[request.first] &&
                    std::find(requests[outport].begin(), requests[outport].end(),
                              request) != requests[outport].end()) {
                    winner = request;
                    break;
                }
            }
            if (winner.first == -1) continue;

            const int inport = winner.first;
            const int invc = winner.second;
            auto iu = m_router->getInputUnit(inport);
            auto flit = use_internal_pipe ?
                m_router->getInternalFlit(inport, invc) :
                iu->getTopFlit(invc);
            const bool is_tail =
                flit->get_type() == gem5::ruby::garnet::TAIL_ ||
                flit->get_type() == gem5::ruby::garnet::HEAD_TAIL_;

            trace_arbitration("grant", outport, inport, invc, 0, flit);
            m_router->getOutputUnit(outport)->decrement_credit(invc);
            flit->set_outport(outport);
            flit->set_vc(invc);
            flit->advance_stage(gem5::ruby::garnet::ST_, curTick());
            m_router->grant_switch(inport, flit);
            gem5::noc::garnet::nocProbeFromRouter(
                m_router, "router.flit.sa_grant", flit);

            if (is_tail)
                release_lock(outport, invc);
            else
                acquire_lock(outport, invc, inport, invc);

            // Internal NCRB/NIDB ingress already returned this credit when
            // staging the flit. RPTR/direct ingress returns it only here.
            // grant_request() cannot be reused because it always returns one.
            if (!use_internal_pipe) {
                iu->increment_credit(invc, is_tail, curTick());
                if (is_tail) iu->set_vc_idle(invc, curTick());
            }
            update_lru(outport, inport, invc);
            input_granted[inport] = true;
            granted = true;
        }
        if (granted) m_router->schedule_wakeup(Cycles(1));
        // Retry ready flits held by credits, packet ownership or arbitration;
        // future pipeline-ready events retain their original scheduling.
        check_for_wakeup();
        return;
    }

     // Clear request lists from the previous cycle
    std::fill(m_requester_without_tokens_exists.begin(), m_requester_without_tokens_exists.end(), false);
    std::fill(m_requester_with_tokens_exists.begin(), m_requester_with_tokens_exists.end(), false);
    for (int i = 0; i < m_num_outports; ++i) {
        m_requesters_without_tokens[i].clear(); // Retains capacity
        m_requesters_with_tokens[i].clear();    // Retains capacity
    }

    // --- Stage 1: Gather and Filter Requests for each Output Port ---
    for (int inport = 0; inport < m_num_inports; ++inport) {
        auto input_unit = m_router->getInputUnit(inport);
        for (int invc = 0; invc < m_num_vcs; ++invc) {
            if (input_unit->need_stage(invc, gem5::ruby::garnet::flit_stage::SA_, curTick())) {


                gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit = input_unit->peekTopFlit(invc); // Peek, don't remove yet
                if (!t_flit) continue; // Should not happen if need_stage is true

                int outport = -1;
                // if something is stored for this inport and invc
                if (m_cached_route[inport][invc] ==-1){
                    outport = m_router->route_compute(t_flit->get_route(),
                                                               inport,
                                                               input_unit->get_direction(), invc);
                    m_cached_route[inport][invc] = outport;
                }
                else{
                    outport = m_cached_route[inport][invc];
                }


                // int outport = input_unit->get_outport(invc);
                if (outport < 0 || outport >= m_num_outports) {
                    // Should not happen if route computation is correct
                    DPRINTF(RubyNetwork, "Router %d Inport %d invc %d has invalid outport %d\n",
                        m_router->get_id(), inport, invc, outport);
                    continue;
                }
                // Check basic eligibility (Credits, Locking, Tokens)
                // We pass temp_outvc by reference so is_eligible can update it
                // if it performs VC allocation for a HEAD flit.
                if (is_eligible(inport, invc, outport, t_flit)) {
                    int priority = get_request_priority(inport, invc, t_flit);
                    trace_arbitration("request", outport, inport, invc,
                        priority, t_flit);
                    if (m_tokens[outport][inport][invc] <= 0){
                        m_requesters_without_tokens[outport].emplace_back(inport, invc, priority);
                        m_requester_without_tokens_exists[outport] = true;
                    } else {
                        m_requesters_with_tokens[outport].emplace_back(inport, invc, priority);
                        m_requester_with_tokens_exists[outport] = true;
                    }
                    DPRINTF(RubyNetwork, "Router %d Cycle %lld: Adding eligible request for Outport %d from Inport %d, InVC %d (Priority %d)\n",
                        m_router->get_id(), curTick(), outport, inport, invc, priority);
                 } else {
                     DPRINTF(RubyNetwork, "Router %d Cycle %lld: Request for Outport %d from Inport %d, InVC %d is NOT eligible\n",
                        m_router->get_id(), curTick(), outport, inport, invc);

                 }
            }
        }
    }

    // --- Stage 2: Arbitrate for each Output Port ---
    // CrossbarSwitch traverses one flit per physical input per cycle. Granting
    // different VCs from that input to multiple outputs would queue flits in
    // the crossbar after their output-VC locks have already been released;
    // another input's HEAD could then overtake a queued TAIL. Share inputs
    // across outputs and rotate the output order to avoid fixed preference.
    std::vector<bool> input_granted(m_num_inports, false);
    const int first_outport = m_num_outports ?
        static_cast<uint64_t>(m_router->curCycle()) % m_num_outports : 0;
    for (int offset = 0; offset < m_num_outports; ++offset) {
        const int outport = (first_outport + offset) % m_num_outports;
        // Filter both token classes before selecting/reloading one. A served
        // input must not suppress another eligible input on this output.
        const auto already_granted = [&input_granted](const auto &request) {
            return input_granted[std::get<0>(request)];
        };
        auto &without_tokens = m_requesters_without_tokens[outport];
        auto &with_tokens = m_requesters_with_tokens[outport];
        without_tokens.erase(std::remove_if(without_tokens.begin(),
            without_tokens.end(), already_granted), without_tokens.end());
        with_tokens.erase(std::remove_if(with_tokens.begin(),
            with_tokens.end(), already_granted), with_tokens.end());
        m_requester_without_tokens_exists[outport] = !without_tokens.empty();
        m_requester_with_tokens_exists[outport] = !with_tokens.empty();
        int granted_inport = -1;
        if (m_requester_without_tokens_exists[outport] && !m_requester_with_tokens_exists[outport]) {
            DPRINTF(RubyNetwork, "Router %d Outport %d: Triggering Token Reload.\n", m_router->get_id(), outport);
            for(const auto& vc_pair : m_requesters_without_tokens[outport]) {

                int reload_inport = std::get<0>(vc_pair);
                int reload_invc = std::get<1>(vc_pair);
                m_tokens[outport][reload_inport][reload_invc] = m_initial_tokens[outport][reload_inport][reload_invc];
            }
            granted_inport = arbitrate_for_output_port(
                m_requesters_without_tokens[outport], outport);
        }
        else{
            granted_inport = arbitrate_for_output_port(
                m_requesters_with_tokens[outport], outport);
        }
        if (granted_inport >= 0) input_granted[granted_inport] = true;
    }

    check_for_wakeup();
}

// Main arbitration logic for a single output port
template <typename T_Msg, typename T_RouteInfo>
int
NocSwitchAllocator<T_Msg, T_RouteInfo>::arbitrate_for_output_port(const std::vector<std::tuple<int, int, int>> current_requests, int outport)
{
    if (current_requests.empty()) {
        return -1; // No requests for this output port
    }

    // Separate requests by priority (Assuming 1=High, 0=Low for simplicity)
    std::vector<std::pair<int, int>> high_priority_reqs; // (inport, invc)
    std::vector<std::pair<int, int>> low_priority_reqs;  // (inport, invc)
    low_priority_reqs.reserve(current_requests.size());

    for (const auto& req_tuple : current_requests) {
        int i = std::get<0>(req_tuple); // inport
        int v = std::get<1>(req_tuple); // invc
        int p = std::get<2>(req_tuple); // priority

        // **Eligibility Check Refinement**: Re-check eligibility JUST before arbitration?
        // The initial check in wakeup() might be sufficient if state doesn't change mid-cycle.
        // However, a grant on another outport could potentially free up resources.
        // For simplicity here, we assume the initial check holds.

        if (p > 0) { // Define your priority levels clearly
             high_priority_reqs.push_back({i, v});
        } else {
             low_priority_reqs.push_back({i, v});
        }
    }

    std::pair<int, int> winner = {-1, -1}; // (win_inport, win_invc)

    // Newly-active requesters must participate in the LRU ordering before the
    // winner is chosen. Otherwise a requester that has not won yet can be
    // invisible to the LRU scan and lose repeatedly to already-known requesters.
    auto& lru_list = m_outport_lru_list[outport];
    auto& lru_map = m_outport_lru_map[outport];
    for (const auto& req_tuple : current_requests) {
        std::pair<int, int> req = {
            std::get<0>(req_tuple), std::get<1>(req_tuple)};
        if (lru_map.find(req) == lru_map.end()) {
            lru_list.push_front(req);
            lru_map[req] = lru_list.begin();
        }
    }

    // Arbitrate High Priority first
    if (!high_priority_reqs.empty()) {
        // Find the LRU among high priority requests
        for (const auto& lru_entry : m_outport_lru_list[outport]) {
            auto it = std::find_if(high_priority_reqs.begin(), high_priority_reqs.end(),
                                   [&](const std::pair<int, int>& req){ return req == lru_entry; });
            if (it != high_priority_reqs.end()) {
                winner = *it;
                DPRINTF(RubyNetwork, "Router %d Outport %d: High Priority LRU winner: Inport %d InVC %d\n",
                    m_router->get_id(), outport, winner.first, winner.second);
                break;
            }
        }
        // Fallback if LRU list doesn't contain any current high-prio reqs (e.g., new flows)
        // Or handle this during LRU update (add new flows)
        if (winner.first == -1) {
             winner = high_priority_reqs.front(); // Simple fallback: pick the first one
             DPRINTF(RubyNetwork, "Router %d Outport %d: High Priority LRU fallback winner: Inport %d InVC %d\n",
                m_router->get_id(), outport, winner.first, winner.second);
        }

    } else if (!low_priority_reqs.empty()) {
        // Arbitrate Low Priority using LRU
         for (const auto& lru_entry : m_outport_lru_list[outport]) {
            auto it = std::find_if(low_priority_reqs.begin(), low_priority_reqs.end(),
                                   [&](const std::pair<int, int>& req){ return req == lru_entry; });
            if (it != low_priority_reqs.end()) {
                winner = *it;
                 DPRINTF(RubyNetwork, "Router %d Outport %d: Low Priority LRU winner: Inport %d InVC %d\n",
                    m_router->get_id(), outport, winner.first, winner.second);
               break;
            }
        }
        // Fallback
        if (winner.first == -1) {
             winner = low_priority_reqs.front(); // Simple fallback
             DPRINTF(RubyNetwork, "Router %d Outport %d: Low Priority LRU fallback winner: Inport %d InVC %d\n",
                m_router->get_id(), outport, winner.first, winner.second);
        }
    }

    // Grant the winner if one was selected
    if (winner.first != -1) {
        int win_inport = winner.first;
        int win_invc = winner.second;
        // int vnet = get_vnet(win_invc);
        auto input_unit = m_router->getInputUnit(win_inport);
        gem5::ruby::garnet::flit<T_Msg, T_RouteInfo> *t_flit = input_unit->getTopFlit(win_invc); // Now actually get it

        grant_request(outport, win_inport, win_invc, win_invc, t_flit);
        update_lru(outport, win_inport, win_invc);
    }
    return winner.first;
}

// Check all NPS eligibility conditions for a request
template <typename T_Msg, typename T_RouteInfo>
bool
NocSwitchAllocator<T_Msg, T_RouteInfo>::is_eligible(int inport, int invc, int outport, gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit)
{
    // 1. Valid Request (Implicitly true if called from wakeup)
    // Flit should exist
    assert(t_flit != nullptr);

    auto output_unit = m_router->getOutputUnit(outport);

    // 2. Output Port Credit  Availability
    // int vnet = get_vnet(invc);
    // BODY or TAIL flit, needs credit in the already assigned outvc
    if (!output_unit->has_noccredit(invc)) {
        DPRINTF(RubyNetwork, "Router %d Eligibility Fail (In %d VC %d -> Out %d VC %d): No credit for BODY/TAIL\n",
                m_router->get_id(), inport, invc, outport, invc);
        return false; // No credit for body/tail
    }

    // 3. No Blocking (Hard Lock Check)
    const auto& lock_holder = m_output_vc_lock[outport][invc];
    if (lock_holder.first != -1 && // Lock is held
        lock_holder.first != inport) { // Lock is held by a *different* input port
            DPRINTF(RubyNetwork, "Router %d Eligibility Fail (In %d VC %d -> Out %d VC %d): OutVC locked by Inport %d InVC %d\n",
                m_router->get_id(), inport, invc, outport, invc, lock_holder.first, lock_holder.second);
        return false; // Blocked by lock from another input port
    }
    // If lock_holder.first == inport, it means this input port holds the lock, which is allowed.

    // 4. Token Availability
    // assert(inport < m_tokens[outport].size() && invc < m_tokens[outport][inport].size());
    // if (m_tokens[outport][inport][invc] <= 0) {
    //     // Simplification: We are not implementing the complex reload condition here.
    //     // Assume tokens are required. A more complex implementation would check reload conditions.
    //      DPRINTF(RubyNetwork, "Router %d Eligibility Fail (In %d VC %d -> Out %d): No tokens (%d)\n",
    //                 m_router->get_id(), inport, invc, outport, m_tokens[outport][inport][invc]);
    //    return false; // No tokens available
    // }

    // Moved into wakeup

    // 5. No Higher Priority Requests (This check is done *during* arbitration, not here)

    // If all checks passed
    return true;
}

// This allocator currently gives every eligible request the same priority.
// Fairness is provided by the per-output LRU ordering, not by QoS classes.
template <typename T_Msg, typename T_RouteInfo>
int
NocSwitchAllocator<T_Msg, T_RouteInfo>::get_request_priority(int inport, int invc, gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit)
{
    (void)inport;
    (void)invc;
    (void)t_flit;
    return 0;

}

// Update LRU list for the winning request. The front of the list is the
// least-recently granted requester; arbitration scans from the front.
template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::update_lru(int outport, int win_inport, int win_invc)
{
    std::pair<int, int> winner_pair = {win_inport, win_invc};
    auto& lru_list = m_outport_lru_list[outport];
    auto& lru_map = m_outport_lru_map[outport];

    auto map_it = lru_map.find(winner_pair);
    if (map_it != lru_map.end()) {
        // Entry exists, move it to the back (MRU position).
        lru_list.splice(lru_list.end(), lru_list, map_it->second);
    } else {
        // New entry has just been served, so it starts as MRU.
        lru_list.push_back(winner_pair);
        auto it = lru_list.end();
        --it;
        lru_map[winner_pair] = it;
    }
    // Optional: Limit LRU list size if needed
}

// Grant the switch to the winning flit and update states
template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::grant_request(int outport, int win_inport, int win_invc, int win_outvc, gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit)
{
    auto input_unit = m_router->getInputUnit(win_inport);
    auto output_unit = m_router->getOutputUnit(outport);

    DPRINTF(RubyNetwork, "Router %d Cycle %lld: Granting Outport %d (OutVC %d) to Inport %d (InVC %d) for flit %s\n",
            m_router->get_id(), curTick(), outport, win_outvc, win_inport, win_invc, *t_flit);

    // Decrement token for the granted VC
    assert(m_tokens[outport][win_inport][win_invc] > 0);
    trace_arbitration("grant", outport, win_inport, win_invc,
        get_request_priority(win_inport, win_invc, t_flit), t_flit);
    m_tokens[outport][win_inport][win_invc]--;
    DPRINTF(RubyNetwork, "Router %d Decremented token for Out %d, In %d, VC %d. Remaining: %d\n",
            m_router->get_id(), outport, win_inport, win_invc, m_tokens[outport][win_inport][win_invc]);


    // Update flit details (outport, outvc for next hop)
    t_flit->set_outport(outport);
    t_flit->set_vc(win_outvc);

    // Decrement credit in the output VC buffer
    output_unit->decrement_credit(win_outvc);

    // Advance flit stage and grant switch traversal
    Tick when = curTick();
    // if (m_router->get_nps_type() == Nps_Type::NCRB){
    //     when = when + Cycles(2);
    // }
    t_flit->advance_stage(gem5::ruby::garnet::ST_, when);
    m_router->grant_switch(win_inport, t_flit);
    gem5::noc::garnet::nocProbeFromRouter(m_router, "router.flit.sa_grant", t_flit);
    // m_output_arbiter_activity++; // Update counter if used

    // Handle VC state and credits based on flit type
    bool is_tail = (t_flit->get_type() == gem5::ruby::garnet::TAIL_ || t_flit->get_type() == gem5::ruby::garnet::HEAD_TAIL_);

    if (is_tail) {
        // Free the input VC
        DPRINTF(RubyNetwork,"Setting inport %d VC %d to idle\n", win_inport, win_invc);
        input_unit->set_vc_idle(win_invc, curTick());
        // Send credit back indicating VC is now free
        input_unit->increment_credit(win_invc, true, curTick());
        // Release lock if held by this transaction
        release_lock(outport, win_outvc);
        m_cached_route[win_inport][win_invc] = -1;
    } else {
        // Send credit back, VC remains busy
        input_unit->increment_credit(win_invc, false, curTick());
        // Acquire or maintain lock if needed (e.g., for write transactions)
        if (is_write_transaction(t_flit)) {
             acquire_lock(outport, win_outvc, win_inport, win_invc);
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::trace_arbitration(
    const char *event,
    int outport,
    int inport,
    int invc,
    int priority,
    gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit)
{
    if constexpr (std::is_same_v<T_Msg, NocMessage> &&
                  std::is_same_v<T_RouteInfo, NocRouteInfo>) {
        auto *net = m_router->get_net_ptr();
        if (!net || !t_flit)
            return;

        const auto route = t_flit->get_route();
        const auto &lock_holder = m_output_vc_lock[outport][invc];
        const int tokens = m_tokens[outport][inport][invc];
        net->traceNpsSwitchArb(
            event,
            m_router->get_id(),
            m_router->get_name(),
            m_router->get_nps_type(),
            outport,
            inport,
            invc,
            priority,
            tokens,
            lock_holder.first,
            lock_holder.second,
            t_flit->getPacketID(),
            t_flit->get_id(),
            route.src_ni,
            route.dest_ni,
            t_flit->get_vnet(),
            static_cast<int>(t_flit->get_type()),
            static_cast<int>(t_flit->get_axi_type()));
    } else {
        (void)event;
        (void)outport;
        (void)inport;
        (void)invc;
        (void)priority;
        (void)t_flit;
    }
}

// Historical name retained for compatibility.  The lock protects every
// multi-flit packet, not only AXI writes, so a packet's body cannot be
// interleaved on its chosen output VC before its tail releases the lock.
template <typename T_Msg, typename T_RouteInfo>
bool
NocSwitchAllocator<T_Msg, T_RouteInfo>::is_write_transaction(gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* t_flit) {
    return t_flit->get_type() == gem5::ruby::garnet::HEAD_ ||
           t_flit->get_type() == gem5::ruby::garnet::BODY_;
}
// Acquire the hard lock for an output VC
template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::acquire_lock(int outport, int outvc, int inport, int invc) {
    if (m_output_vc_lock[outport][outvc].first == -1) { // Acquire lock only if free
        m_output_vc_lock[outport][outvc] = {inport, invc};
        DPRINTF(RubyNetwork, "Router %d Outport %d OutVC %d: Acquired lock for Inport %d InVC %d\n",
                m_router->get_id(), outport, outvc, inport, invc);
    } else {
         // Lock should ideally only be acquired if free or already held by the requester.
         // If held by the same requester, this call is effectively redundant but harmless.
         assert(m_output_vc_lock[outport][outvc].first == inport);
         DPRINTF(RubyNetwork, "Router %d Outport %d OutVC %d: Maintaining lock for Inport %d InVC %d\n",
                m_router->get_id(), outport, outvc, inport, invc);
    }
}
// Release the hard lock for an output VC
template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::release_lock(int outport, int outvc) {
    if (m_output_vc_lock[outport][outvc].first != -1) { // Only release if locked
         DPRINTF(RubyNetwork, "Router %d Outport %d OutVC %d: Releasing lock held by Inport %d InVC %d\n",
                m_router->get_id(), outport, outvc, m_output_vc_lock[outport][outvc].first, m_output_vc_lock[outport][outvc].second);
        m_output_vc_lock[outport][outvc] = {-1, -1};
    }
}


// Wakeup the router next cycle to perform SA again
// if there are flits ready.
template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::check_for_wakeup()
{
    Tick nextCycle = m_router->clockEdge(Cycles(1));
    DPRINTF(RubyNetwork, "Router %d checking for wakeup\n",
                        m_router->get_id());

    if (m_router->alreadyScheduled(nextCycle)) {
        return;
    }

    for (int i = 0; i < m_num_inports; i++) {
        for (int j = 0; j < m_num_vcs; j++) {
            bool nidb_internal_ready =
                m_router->usesInternalIngressPipeline() &&
                m_router->hasReadyInternalFlit(i, j, nextCycle);
            if (nidb_internal_ready ||
                m_router->getInputUnit(i)->need_stage(
                    j, gem5::ruby::garnet::SA_, nextCycle)) {
                m_router->schedule_wakeup(Cycles(1));
                DPRINTF(RubyNetwork, "Router %d scheduling wakeup for next cycle\n",
                        m_router->get_id());
                return;
            }
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
int
NocSwitchAllocator<T_Msg, T_RouteInfo>::get_vnet(int invc)
{
    int vnet = invc/m_vc_per_vnet;
    assert(vnet < m_router->get_num_vnets());
    return vnet;
}

template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::resetStats()
{
    m_input_arbiter_activity = 0;
    m_output_arbiter_activity = 0;
}

namespace
{

static void
paramOut3DInt(CheckpointOut &cp, const std::string &pfx,
    const std::vector<std::vector<std::vector<int>>> &t)
{
    uint32_t n0 = t.size();
    paramOut(cp, pfx + "_d0", n0);
    for (uint32_t i = 0; i < n0; ++i) {
        uint32_t n1 = t[i].size();
        paramOut(cp, csprintf("%s_d1_%u", pfx.c_str(), i), n1);
        for (uint32_t j = 0; j < n1; ++j) {
            uint32_t n2 = t[i][j].size();
            paramOut(cp, csprintf("%s_d2_%u_%u", pfx.c_str(), i, j), n2);
            for (uint32_t k = 0; k < n2; ++k) {
                paramOut(cp, csprintf("%s_v_%u_%u_%u", pfx.c_str(), i, j, k),
                    t[i][j][k]);
            }
        }
    }
}

static void
paramIn3DInt(CheckpointIn &cp, const std::string &pfx,
    std::vector<std::vector<std::vector<int>>> &t)
{
    uint32_t n0 = 0;
    paramIn(cp, pfx + "_d0", n0);
    t.resize(n0);
    for (uint32_t i = 0; i < n0; ++i) {
        uint32_t n1 = 0;
        paramIn(cp, csprintf("%s_d1_%u", pfx.c_str(), i), n1);
        t[i].resize(n1);
        for (uint32_t j = 0; j < n1; ++j) {
            uint32_t n2 = 0;
            paramIn(cp, csprintf("%s_d2_%u_%u", pfx.c_str(), i, j), n2);
            t[i][j].resize(n2);
            for (uint32_t k = 0; k < n2; ++k) {
                paramIn(cp, csprintf("%s_v_%u_%u_%u", pfx.c_str(), i, j, k),
                    t[i][j][k]);
            }
        }
    }
}

} // namespace

template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::serializeNocCheckpoint(
    CheckpointOut &cp) const
{
    paramOut(cp, "nsa_num_inports", m_num_inports);
    paramOut(cp, "nsa_num_outports", m_num_outports);
    paramOut(cp, "nsa_num_vcs", m_num_vcs);
    paramOut(cp, "nsa_vc_per_vnet", m_vc_per_vnet);
    paramOut(cp, "nsa_in_arb", m_input_arbiter_activity);
    paramOut(cp, "nsa_out_arb", m_output_arbiter_activity);

    paramOut3DInt(cp, "nsa_tokens", m_tokens);
    paramOut3DInt(cp, "nsa_initial_tokens", m_initial_tokens);

    for (int op = 0; op < m_num_outports; op++) {
        for (int vc = 0; vc < m_num_vcs; vc++) {
            paramOut(cp, csprintf("nsa_lock_%d_%d_a", op, vc),
                m_output_vc_lock[op][vc].first);
            paramOut(cp, csprintf("nsa_lock_%d_%d_b", op, vc),
                m_output_vc_lock[op][vc].second);
        }
    }

    for (int op = 0; op < m_num_outports; op++) {
        uint32_t n = m_outport_lru_list[op].size();
        paramOut(cp, csprintf("nsa_lru_%d_sz", op), n);
        int idx = 0;
        for (const auto &pr : m_outport_lru_list[op]) {
            paramOut(cp, csprintf("nsa_lru_%d_%d_a", op, idx), pr.first);
            paramOut(cp, csprintf("nsa_lru_%d_%d_b", op, idx), pr.second);
            idx++;
        }
    }

    for (int i = 0; i < m_num_inports; i++) {
        for (int j = 0; j < m_num_vcs; j++) {
            paramOut(cp, csprintf("nsa_cr_%d_%d", i, j), m_cached_route[i][j]);
        }
    }

    for (int op = 0; op < m_num_outports; op++) {
        bool b = m_requester_without_tokens_exists[op];
        paramOut(cp, csprintf("nsa_rqwoe_%d", op), b);
    }
    for (int op = 0; op < m_num_outports; op++) {
        bool b = m_requester_with_tokens_exists[op];
        paramOut(cp, csprintf("nsa_rqwie_%d", op), b);
    }

    for (int op = 0; op < m_num_outports; op++) {
        uint32_t n = m_requesters_without_tokens[op].size();
        paramOut(cp, csprintf("nsa_rqwo_%d_sz", op), n);
        for (uint32_t j = 0; j < n; j++) {
            const auto &t = m_requesters_without_tokens[op][j];
            paramOut(cp, csprintf("nsa_rqwo_%d_%u_a", op, j), std::get<0>(t));
            paramOut(cp, csprintf("nsa_rqwo_%d_%u_b", op, j), std::get<1>(t));
            paramOut(cp, csprintf("nsa_rqwo_%d_%u_c", op, j), std::get<2>(t));
        }
    }
    for (int op = 0; op < m_num_outports; op++) {
        uint32_t n = m_requesters_with_tokens[op].size();
        paramOut(cp, csprintf("nsa_rqwi_%d_sz", op), n);
        for (uint32_t j = 0; j < n; j++) {
            const auto &t = m_requesters_with_tokens[op][j];
            paramOut(cp, csprintf("nsa_rqwi_%d_%u_a", op, j), std::get<0>(t));
            paramOut(cp, csprintf("nsa_rqwi_%d_%u_b", op, j), std::get<1>(t));
            paramOut(cp, csprintf("nsa_rqwi_%d_%u_c", op, j), std::get<2>(t));
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NocSwitchAllocator<T_Msg, T_RouteInfo>::unserializeNocCheckpoint(
    CheckpointIn &cp)
{
    paramIn(cp, "nsa_num_inports", m_num_inports);
    paramIn(cp, "nsa_num_outports", m_num_outports);
    paramIn(cp, "nsa_num_vcs", m_num_vcs);
    paramIn(cp, "nsa_vc_per_vnet", m_vc_per_vnet);
    paramIn(cp, "nsa_in_arb", m_input_arbiter_activity);
    paramIn(cp, "nsa_out_arb", m_output_arbiter_activity);

    paramIn3DInt(cp, "nsa_tokens", m_tokens);
    paramIn3DInt(cp, "nsa_initial_tokens", m_initial_tokens);

    m_output_vc_lock.resize(m_num_outports,
        std::vector<std::pair<int, int>>(m_num_vcs, {-1, -1}));
    for (int op = 0; op < m_num_outports; op++) {
        for (int vc = 0; vc < m_num_vcs; vc++) {
            paramIn(cp, csprintf("nsa_lock_%d_%d_a", op, vc),
                m_output_vc_lock[op][vc].first);
            paramIn(cp, csprintf("nsa_lock_%d_%d_b", op, vc),
                m_output_vc_lock[op][vc].second);
        }
    }

    m_outport_lru_list.resize(m_num_outports);
    m_outport_lru_map.resize(m_num_outports);
    for (int op = 0; op < m_num_outports; op++) {
        m_outport_lru_list[op].clear();
        m_outport_lru_map[op].clear();
        uint32_t n = 0;
        paramIn(cp, csprintf("nsa_lru_%d_sz", op), n);
        for (uint32_t idx = 0; idx < n; idx++) {
            int a = 0, b = 0;
            paramIn(cp, csprintf("nsa_lru_%d_%u_a", op, idx), a);
            paramIn(cp, csprintf("nsa_lru_%d_%u_b", op, idx), b);
            std::pair<int, int> pr(a, b);
            auto it = m_outport_lru_list[op].insert(
                m_outport_lru_list[op].end(), pr);
            m_outport_lru_map[op][pr] = it;
        }
    }

    m_cached_route.resize(m_num_inports,
        std::vector<int>(m_num_vcs, -1));
    for (int i = 0; i < m_num_inports; i++) {
        for (int j = 0; j < m_num_vcs; j++) {
            paramIn(cp, csprintf("nsa_cr_%d_%d", i, j), m_cached_route[i][j]);
        }
    }

    m_requester_without_tokens_exists.resize(m_num_outports);
    m_requester_with_tokens_exists.resize(m_num_outports);
    for (int op = 0; op < m_num_outports; op++) {
        bool b = false;
        paramIn(cp, csprintf("nsa_rqwoe_%d", op), b);
        m_requester_without_tokens_exists[op] = b;
    }
    for (int op = 0; op < m_num_outports; op++) {
        bool b = false;
        paramIn(cp, csprintf("nsa_rqwie_%d", op), b);
        m_requester_with_tokens_exists[op] = b;
    }

    m_requesters_without_tokens.resize(m_num_outports);
    m_requesters_with_tokens.resize(m_num_outports);
    for (int op = 0; op < m_num_outports; op++) {
        uint32_t n = 0;
        paramIn(cp, csprintf("nsa_rqwo_%d_sz", op), n);
        m_requesters_without_tokens[op].clear();
        for (uint32_t j = 0; j < n; j++) {
            int a = 0, b = 0, c = 0;
            paramIn(cp, csprintf("nsa_rqwo_%d_%u_a", op, j), a);
            paramIn(cp, csprintf("nsa_rqwo_%d_%u_b", op, j), b);
            paramIn(cp, csprintf("nsa_rqwo_%d_%u_c", op, j), c);
            m_requesters_without_tokens[op].push_back(
                std::make_tuple(a, b, c));
        }
    }
    for (int op = 0; op < m_num_outports; op++) {
        uint32_t n = 0;
        paramIn(cp, csprintf("nsa_rqwi_%d_sz", op), n);
        m_requesters_with_tokens[op].clear();
        for (uint32_t j = 0; j < n; j++) {
            int a = 0, b = 0, c = 0;
            paramIn(cp, csprintf("nsa_rqwi_%d_%u_a", op, j), a);
            paramIn(cp, csprintf("nsa_rqwi_%d_%u_b", op, j), b);
            paramIn(cp, csprintf("nsa_rqwi_%d_%u_c", op, j), c);
            m_requesters_with_tokens[op].push_back(
                std::make_tuple(a, b, c));
        }
    }
}

} // namespace garnet
} // namespace noc
} // namespace gem5
