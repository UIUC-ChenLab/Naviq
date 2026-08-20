/*
 * Copyright (c) 2026 University of Illinois Urbana-Champaign
 */

// Change include to match header filename
#include "noc/core/network/switch/NocRouter.hh"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <type_traits>

#include "base/logging.hh"
#include "debug/RubyNetwork.hh"
// Include necessary base classes and components
#include "mem/ruby/network/garnet/OutputUnit.hh" // Base OutputUnit needed for addOutPort
#include "mem/ruby/network/garnet/InputUnit.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "mem/ruby/network/garnet/NetworkLink.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh" // Base network needed
#include "noc/core/network/NocGarnetNetwork.hh" // Noc network needed
#include "noc/lib/network/NocMessage.hh"
#include "noc/core/network/NocNetDest.hh"
#include "noc/lib/network/NocSerializeNpsType.hh"
#include "params/NocGarnetRouter.hh" // Needed for Params type alias
#include "noc/debug/NocProbe.hh"
#include "sim/serialize.hh"

#include <cstring>
// #include "noc/router/NocOutputUnit.hh"

namespace gem5
{
// Change namespace to match header
namespace noc
{
namespace garnet
{

// Use using-declarations consistent with header
using gem5::ruby::garnet::InputUnit;
using gem5::ruby::garnet::OutputUnit; // Using base OutputUnit
using gem5::ruby::garnet::CreditLink;
using gem5::ruby::garnet::NetworkLink;
using gem5::ruby::garnet::CrossbarSwitch; // Inherited member
using gem5::ruby::garnet::RoutingUnit;   // Inherited member
using gem5::ruby::garnet::flit;
using gem5::ruby::PortDirection;
using gem5::ruby::NetDest;
using gem5::ruby::WriteMask;

namespace
{

constexpr const char *kRuntimeTraceDir = "src/noc/out/csv";
constexpr const char *kNpsOccTracePath = "src/noc/out/csv/nps_occ_all.csv";

/** Single CSV shared by all NPS routers when record_nps is enabled. */
std::ofstream npsOccAllCsv;

void
ensureNpsOccAllCsvOpen()
{
    if (npsOccAllCsv.is_open()) {
        return;
    }
    std::error_code fs_ec;
    std::filesystem::create_directories(kRuntimeTraceDir, fs_ec);
    if (fs_ec) {
        warn("NocRouter: Failed to create directory %s: %s",
             kRuntimeTraceDir, fs_ec.message().c_str());
    }
    const std::string path = kNpsOccTracePath;
    npsOccAllCsv.open(path, std::ios::out | std::ios::trunc);
    if (!npsOccAllCsv.is_open()) {
        warn("NocRouter: Failed to open shared NPS occupancy CSV %s",
             path.c_str());
        return;
    }
    // port is NA: one row per NPS per sample (aggregate over all inports).
    npsOccAllCsv << "tick,nps_name,nps_type,port,occupancy_sum,"
                    "max_buffer_size\n";
    npsOccAllCsv.flush();
}

} // namespace

// Template instantiation for NocRouter
template class NocRouter<gem5::ruby::Message, gem5::ruby::garnet::RouteInfo>; // If supporting non-Noc messages
template class NocRouter<NocMessage, NocRouteInfo>;

// Constructor Definition
template <typename T_Msg, typename T_RouteInfo>
NocRouter<T_Msg, T_RouteInfo>::NocRouter(const Params &p)
  // Call BASE Router constructor FIRST
  : gem5::ruby::garnet::Router<T_Msg, T_RouteInfo>(p),
    // Initialize in the same order as members are declared in NocRouter.hh
    m_name(p.nocname),
    m_nps_type(Nps_Type::VNOC),
    m_record_nps(p.record_nps),
    m_record_nps_gap_cycles(std::max(1u, (uint32_t)p.record_nps_gap_cycles)),
    m_nps_noc_cycle_count(0),
    nocswitchAllocator(this),
    m_last_tick_processed_core_logic(Tick(0)),
    m_core_logic_processed_this_tick(false)
{
    if constexpr (std::is_same_v<T_Msg, NocMessage> &&
                  std::is_same_v<T_RouteInfo, NocRouteInfo>) {
        m_nocProbe = p.noc_probe;
    }
    // Base constructor already handled:
    // BasicRouter(p), Consumer(this), m_latency, m_virtual_networks,
    // m_vc_per_vnet, m_num_vcs, m_bit_width, m_network_ptr,
    // routingUnit(this), crossbarSwitch(this)
    // Base constructor ALSO initialized the inherited 'switchAllocator',
    // which we will ignore.
    // Base constructor cleared m_input_unit and m_output_unit vectors.
    // Base constructor cleared m_input_unit and m_output_unit vectors.
    Cycles latency = (Cycles) 2;

    switch(p.nps_type){
        case 0: m_nps_type = Nps_Type::VNOC; break;
        case 1: m_nps_type = Nps_Type::HNOC; break;
        case 2: m_nps_type = Nps_Type::RPTR; break;
        case 3: m_nps_type = Nps_Type::NCRB; break;
        case 4: m_nps_type = Nps_Type::NIDB; break;
        default: m_nps_type = Nps_Type::VNOC; break;
    }

    this->set_latency(latency);
    DPRINTF(RubyNetwork, "Created NocRouter %s with NPS Type %s\n", m_name.c_str(), NpsTypeToString(m_nps_type).c_str());
    // printf("Created NocRouter %s with NPS Type %d %s\n", m_name.c_str(),p.nps_type, NpsTypeToString(m_nps_type).c_str());
}

// init() Implementation (Overriding Base)
template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::init()
{
    // Call base class init() which calls BasicRouter::init()
    // This ensures basic router setup and potentially base stats are registered.
    // IMPORTANT: Base Router::init() ALSO calls base switchAllocator.init().
    gem5::ruby::garnet::Router<T_Msg, T_RouteInfo>::init();

    // Initialize OUR switch allocator INSTEAD of the base one called by base init.
    nocswitchAllocator.init();

    gem5::noc::garnet::NocGarnetNetwork* noc_net = dynamic_cast<gem5::noc::garnet::NocGarnetNetwork*>(this->get_net_ptr());
    if (noc_net) {
        this->set_latency(noc_net->get_nps_latency(m_nps_type));
    }

    if (usesInternalIngressPipeline()) {
        m_internalIngressBuffers.resize(
            this->get_num_inports(),
            std::vector<gem5::ruby::garnet::flitBuffer<T_Msg, T_RouteInfo>>(
                this->get_num_vcs()));
    }

    initNpsOccCsv();
}

namespace
{

std::string
sanitizeCsvToken(std::string s)
{
    for (auto& c : s) {
        if (c == ',' || c == '\n' || c == '\r' || c == '"' || c == '/' ||
            c == '\\' || c == ' ') {
            c = '_';
        }
    }
    return s;
}

} // namespace

template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::initNpsOccCsv()
{
    if constexpr (!std::is_same_v<T_Msg, NocMessage>) {
        return;
    } else {
        if (!m_record_nps) {
            return;
        }
        ensureNpsOccAllCsvOpen();
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::sumPhysicalNpsInputBufferStats(
    int& occSum, int& maxCapSum)
{
    occSum = 0;
    maxCapSum = 0;

    auto *noc_net = dynamic_cast<gem5::noc::garnet::NocGarnetNetwork*>(
        this->get_net_ptr());

    for (int pi = 0; pi < this->get_num_inports(); pi++) {
        auto *iu = this->getInputUnit(pi);
        if (!noc_net) {
            int portOcc = 0;
            int portMaxCap = 0;
            iu->sumInputVcBufferStats(portOcc, portMaxCap);
            occSum += portOcc;
            maxCapSum += portMaxCap;
            continue;
        }

        for (int vc = 0; vc < static_cast<int>(this->get_num_vcs()); vc++) {
            occSum += iu->getVcOccupancy(vc);
            maxCapSum += static_cast<int>(
                noc_net->get_effective_physical_vc_buffer_depth(
                    vc, this->get_vc_per_vnet(), m_nps_type));
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::npsOccMaybeLogAfterCoreCycle()
{
    if constexpr (!std::is_same_v<T_Msg, NocMessage>) {
        return;
    } else {
        if (!m_record_nps || !npsOccAllCsv.is_open()) {
            return;
        }
        // Log at NoC cycle 0 and every record_nps_gap_cycles thereafter
        // (check before increment so cycle 0 is always sampled).
        if (m_nps_noc_cycle_count % m_record_nps_gap_cycles != 0) {
            m_nps_noc_cycle_count++;
            return;
        }

        const std::string safe_name = sanitizeCsvToken(m_name);
        const std::string nps_type_str = NpsTypeToString(m_nps_type);

        int occ_sum = 0;
        int max_cap_sum = 0;
        // Match the physical NPS storage model: 4 bidirectional ports, each
        // with per-port VC FIFOs. Count only InputUnit VC flit buffers and use
        // the NPS credit depth as the FIFO depth for each VC.
        sumPhysicalNpsInputBufferStats(occ_sum, max_cap_sum);

        npsOccAllCsv << curTick() << ',' << safe_name << ','
                     << nps_type_str << ",NA," << occ_sum << ','
                     << max_cap_sum << '\n';
        npsOccAllCsv.flush();
        m_nps_noc_cycle_count++;
    }
}

// wakeup() Implementation (Overriding Base)
template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::wakeup()
{
    // Use inherited members via this-> or rely on scope resolution
    DPRINTF(RubyNetwork, "Router %d [%s] woke up\n", this->get_id(), m_name);
    // printf("Router %d [%s] woke up\n", this->get_id(), m_name);
    assert(gem5::Clocked::clockEdge() == gem5::curTick());

    // check for incoming flits (using inherited m_input_unit)
    int num_inports = this->get_num_inports();
    for (int inport = 0; inport < num_inports; inport++) {
        DPRINTF(RubyNetwork, "Router %d waking up input unit %d\n", this->get_id(), inport);
        this->input_unit_wakeup(inport);
    }

    if (usesInternalIngressPipeline()) {
        stageInternalIngressFlits();
    }

    int num_outports = this->get_num_outports();
    // check for incoming credits (using inherited m_output_unit)
    for (int outport = 0; outport < num_outports; outport++) {
        // Assuming the OutputUnit pointers in m_output_unit are valid
        this->output_unit_wakeup(outport);
    }

    if (m_last_tick_processed_core_logic != curTick()) {
        m_last_tick_processed_core_logic = curTick();
        m_core_logic_processed_this_tick = false;
    }

    if (!m_core_logic_processed_this_tick) {
        DPRINTF(RubyNetwork, "Router %d [%s] tick %lld: Performing core SA/ST logic.\n",
                this->get_id(), m_name.c_str(), gem5::curTick());

        // Switch Allocation: Considers all flits now present in InputUnits
        nocswitchAllocator.wakeup();

        // Switch Traversal: Moves flits granted by the Switch Allocator
        this->crossbar_wakeup();

        // Mark that core logic has been performed for this tick.
        m_core_logic_processed_this_tick = true;

        npsOccMaybeLogAfterCoreCycle();
        if (m_record_nps) {
            if constexpr (std::is_same_v<T_Msg, NocMessage> &&
                          std::is_same_v<T_RouteInfo, NocRouteInfo>) {
                gem5::ruby::garnet::logNpsFlitTraceRefresh(
                    curTick(),
                    static_cast<uint64_t>(this->ticksToCycles(curTick())),
                    this->cyclesToTicks(Cycles(100)));
            }
        }

    } else {
        DPRINTF(RubyNetwork, "Router %d [%s] tick %lld: Core SA/ST logic already performed. Skipping.\n",
                this->get_id(), m_name.c_str(), gem5::curTick());
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::stageInternalIngressFlits()
{
    Cycles ingress_delay = this->get_pipe_stages() > Cycles(0) ?
        this->get_pipe_stages() - Cycles(1) : Cycles(0);

    for (int inport = 0; inport < this->get_num_inports(); ++inport) {
        auto input_unit = this->getInputUnit(inport);
        for (int invc = 0; invc < this->get_num_vcs(); ++invc) {
            auto& internal_buffer = m_internalIngressBuffers[inport][invc];

            if (!input_unit->isReady(invc, curTick())) {
                continue;
            }

            auto t_flit = input_unit->peekTopFlit(invc);
            if (!t_flit) {
                continue;
            }

            auto outport = this->route_compute(
                t_flit->get_route(), inport, input_unit->get_direction(), invc);

            input_unit->grant_outport(invc, outport);
            t_flit = input_unit->getTopFlit(invc);

            bool is_tail = (t_flit->get_type() == gem5::ruby::garnet::TAIL_ ||
                            t_flit->get_type() == gem5::ruby::garnet::HEAD_TAIL_);
            input_unit->increment_credit(invc, is_tail, curTick());
            if (is_tail) {
                input_unit->set_vc_idle(invc, curTick());
            }

            Tick ready_time = curTick();
            if (ingress_delay > Cycles(0)) {
                ready_time = this->clockEdge(ingress_delay);
            }
            t_flit->advance_stage(gem5::ruby::garnet::SA_, ready_time);
            internal_buffer.insert(t_flit);

            DPRINTF(RubyNetwork,
                "Router %d [%s] staged internal ingress flit PacketID %d FlitID %d "
                "from inport %d vc %d for SA at %llu\n",
                this->get_id(), m_name.c_str(), t_flit->getPacketID(),
                t_flit->get_id(), inport, invc, ready_time);

            this->schedule_wakeup(Cycles(1));
            if (ingress_delay > Cycles(0)) {
                this->schedule_wakeup(ingress_delay);
            }
        }
    }
}

template <typename T_Msg, typename T_RouteInfo>
bool
NocRouter<T_Msg, T_RouteInfo>::hasReadyInternalFlit(int inport, int invc, Tick time)
{
    auto& internal_buffer = m_internalIngressBuffers[inport][invc];
    return internal_buffer.isReady(time) &&
           internal_buffer.peekTopFlit()->is_stage(gem5::ruby::garnet::SA_, time);
}

template <typename T_Msg, typename T_RouteInfo>
gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>*
NocRouter<T_Msg, T_RouteInfo>::peekInternalFlit(int inport, int invc)
{
    auto& internal_buffer = m_internalIngressBuffers[inport][invc];
    if (internal_buffer.isEmpty()) {
        return nullptr;
    }
    return internal_buffer.peekTopFlit();
}

template <typename T_Msg, typename T_RouteInfo>
gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>*
NocRouter<T_Msg, T_RouteInfo>::getInternalFlit(int inport, int invc)
{
    auto& internal_buffer = m_internalIngressBuffers[inport][invc];
    if (internal_buffer.isEmpty()) {
        return nullptr;
    }
    return internal_buffer.getTopFlit();
}


// addOutPort (NocNetDest version) Implementation (Overriding Base)
template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::addOutPort(PortDirection outport_dirn,
                   NetworkLink<T_Msg, T_RouteInfo> *out_link,
                   std::vector<gem5::noc::NocNetDest>& routing_table_entry,
                   int link_weight,
                   CreditLink<T_Msg, T_RouteInfo> *credit_link,
                   uint32_t consumerVcs,
                   Nps_Type downstreamCreditNpsType)
{
    // Use inherited m_bit_width, m_id
    fatal_if(out_link->bitWidth != this->getBitWidth(), "Widths of units do not match."
            " Consider inserting SerDes Units");

    // Use inherited m_output_unit vector
    int port_num = this->get_num_outports();

    // *** Create an instance of the BASE OutputUnit template ***
    // Pass 'this' (NocRouter*) which is compatible with Router* expected by OutputUnit constructor.
    // Credit counters model the downstream consumer's buffering.
    OutputUnit<T_Msg, T_RouteInfo> *output_unit =
        new OutputUnit<T_Msg, T_RouteInfo>(port_num, outport_dirn, this,
                                           consumerVcs,
                                           downstreamCreditNpsType);

    // Setup links (using the created output_unit)
    output_unit->set_out_link(out_link);
    output_unit->set_credit_link(credit_link);
    credit_link->setLinkConsumer(this); // 'this' is the Consumer (NocRouter)
    credit_link->setVcsPerVnet(consumerVcs);
    out_link->setSourceQueue(output_unit->getOutQueue(), this); // 'this' is the Consumer
    out_link->setVcsPerVnet(consumerVcs);

    // Add to the inherited m_output_unit vector (stores shared_ptr<OutputUnit<...>>)
    this->addOutputUnit(std::shared_ptr<OutputUnit<T_Msg, T_RouteInfo>>(output_unit));

    // // Setup routing (using inherited routingUnit member)
    // routingUnit.addRoute(routing_table_entry); // Pass NocNetDest vector
    // routingUnit.addWeight(link_weight);
    // routingUnit.addOutDirection(outport_dirn, port_num);
    this->add_routing_unit_entry(routing_table_entry, link_weight, outport_dirn,port_num);
}

// addNocOutPort (NocRouteMapKey version) Implementation (custom routing)
template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::addNocOutPort(PortDirection outport_dirn,
                   NetworkLink<T_Msg, T_RouteInfo> *out_link,
                   std::vector<gem5::noc::garnet::NocRouteMapKey>& routes,
                   int link_weight,
                   CreditLink<T_Msg, T_RouteInfo> *credit_link,
                   uint32_t consumerVcs,
                   Nps_Type downstreamCreditNpsType)
{
    // Use inherited m_bit_width, m_id
    fatal_if(out_link->bitWidth != this->getBitWidth(), "Widths of units do not match."
            " Consider inserting SerDes Units");

    // Use inherited m_output_unit vector
    int port_num = this->get_num_outports();

    // *** Create an instance of the BASE OutputUnit template ***
    // Pass 'this' (NocRouter*) which is compatible with Router* expected by OutputUnit constructor.
    // Credit counters model the downstream consumer's buffering.
    OutputUnit<T_Msg, T_RouteInfo> *output_unit =
        new OutputUnit<T_Msg, T_RouteInfo>(port_num, outport_dirn, this,
                                           consumerVcs,
                                           downstreamCreditNpsType);

    // Setup links (using the created output_unit)
    output_unit->set_out_link(out_link);
    output_unit->set_credit_link(credit_link);
    credit_link->setLinkConsumer(this); // 'this' is the Consumer (NocRouter)
    credit_link->setVcsPerVnet(consumerVcs);
    out_link->setSourceQueue(output_unit->getOutQueue(), this); // 'this' is the Consumer
    out_link->setVcsPerVnet(consumerVcs);

    // Add to the inherited m_output_unit vector (stores shared_ptr<OutputUnit<...>>)
    this->addOutputUnit(std::shared_ptr<OutputUnit<T_Msg, T_RouteInfo>>(output_unit));

    // // Setup routing (using inherited routingUnit member)
    // routingUnit.addRoute(routing_table_entry); // Pass NocNetDest vector
    // routingUnit.addWeight(link_weight);
    // routingUnit.addOutDirection(outport_dirn, port_num);
    DPRINTF(RubyNetwork, "Adding custom routing unit entry %s for %s\n", m_name, outport_dirn);
    this->add_custom_routing_unit_entry(routes, link_weight, outport_dirn,port_num);
}

// --- Methods to Inherit (Remove definitions from NocRouter.cc) ---
// getOutportDirection, getInportDirection, route_compute, grant_switch,
// schedule_wakeup, getPortDirectionName, printFaultVector,
// printAggregateFaultProbability, regStats, functionalRead, functionalWrite

// --- collateStats Implementation (Overriding Base) ---
template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::collateStats()
{
    // // Use inherited members
    // for (int j = 0; j < this->m_virtual_networks; j++) {
    //     for (int i = 0; i < this->m_input_unit.size(); i++) {
    //         this->m_buffer_reads += this->m_input_unit[i]->get_buf_read_activity(j);
    //         this->m_buffer_writes += this->m_input_unit[i]->get_buf_write_activity(j);
    //     }
    // }

    // // *** Get stats from OUR allocator ***

    // // Use inherited crossbarSwitch
    // set_crossbar_activity(crossbarSwitch.get_crossbar_activity());
    gem5::ruby::garnet::Router<T_Msg, T_RouteInfo>::collateStats();
    this->set_sw_input_arbiter_activity(nocswitchAllocator.get_input_arbiter_activity());
    this->set_sw_output_arbiter_activity(nocswitchAllocator.get_output_arbiter_activity());
}

// --- resetStats Implementation (Overriding Base) ---
template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::resetStats()
{
    // Call base class resetStats first. It handles:
    // - Input Units reset
    // - CrossbarSwitch reset
    // - Base SwitchAllocator reset (which we ignore)
    gem5::ruby::garnet::Router<T_Msg, T_RouteInfo>::resetStats();

    // Reset OUR specific switch allocator
    nocswitchAllocator.resetStats();

    // Base::resetStats doesn't reset OutputUnits, so if NocOutputUnit
    // needs reset (or if modified base OutputUnit needs it), do it here.
    // However, original Router::resetStats doesn't reset OutputUnits either.
    // Let's stick to resetting only what the base Router resets plus our SA.
}

template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::serialize(CheckpointOut &cp) const
{
    // IMPORTANT: Emit NocRouter scalar keys before calling into the base
    // Garnet router serializer. The base serializer writes many nested
    // sections (inputUnit*, outputUnit*, crossbarSwitch, etc). In IniFile
    // checkpoints, subsequent paramOut lines can otherwise be attributed to
    // the last nested [section] header, breaking restore of these scalars.
    SERIALIZE_SCALAR(m_name);
    paramOutNpsType(cp, "nr_nps_type", m_nps_type);
    SERIALIZE_SCALAR(m_last_tick_processed_core_logic);
    SERIALIZE_SCALAR(m_core_logic_processed_this_tick);
    // Same IniFile sectioning issue: emit allocator scalars before the base
    // serializer opens nested sections.
    nocswitchAllocator.serializeNocCheckpoint(cp);

    // Include the base Garnet router checkpoint state so in-flight flits
    // (input/output units, crossbar buffers, allocator RR state) survive
    // checkpoints.
    gem5::ruby::garnet::Router<T_Msg, T_RouteInfo>::serialize(cp);
}

template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::unserialize(CheckpointIn &cp)
{
    // Load base router state first (including any buffered flits).
    gem5::ruby::garnet::Router<T_Msg, T_RouteInfo>::unserialize(cp);

    // Load NocRouter-specific state.
    UNSERIALIZE_SCALAR(m_name);
    paramInNpsType(cp, "nr_nps_type", m_nps_type);
    UNSERIALIZE_SCALAR(m_last_tick_processed_core_logic);
    UNSERIALIZE_SCALAR(m_core_logic_processed_this_tick);
    nocswitchAllocator.unserializeNocCheckpoint(cp);
}

template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::nocProbeEvent(const char* hookId)
{
    if constexpr (std::is_same_v<T_Msg, NocMessage> &&
                  std::is_same_v<T_RouteInfo, NocRouteInfo>) {
        if (m_nocProbe && m_nocProbe->needsHookEvents()) {
            m_nocProbe->onHookEvent(hookId, name().c_str(), this->clockPeriod());
        }
    } else {
        (void)hookId;
    }
}

template <typename T_Msg, typename T_RouteInfo>
void
NocRouter<T_Msg, T_RouteInfo>::nocProbeEvent(const char* hookId,
    gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* fl)
{
    if constexpr (std::is_same_v<T_Msg, NocMessage> &&
                  std::is_same_v<T_RouteInfo, NocRouteInfo>) {
        if (m_nocProbe && m_nocProbe->needsHookEvents()) {
            m_nocProbe->onHookEvent(hookId,
                static_cast<gem5::noc::NocProbe::FlitType*>(fl), name().c_str(),
                this->clockPeriod());
        }
    } else {
        (void)hookId;
        (void)fl;
    }
}

} // namespace garnet
} // namespace noc // Correct closing namespace
} // namespace gem5
