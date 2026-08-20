
#ifndef __MEM_RUBY_NETWORK_GARNET_0_NOCROUTER_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_NOCROUTER_HH__

#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include "mem/ruby/network/garnet/Router.hh"

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/common/NetDest.hh"
#include "mem/ruby/network/BasicRouter.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/CrossbarSwitch.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh"
#include "mem/ruby/network/garnet/RoutingUnit.hh"
#include "noc/core/network/switch/NocSwitchAllocator.hh"
#include "mem/ruby/network/garnet/flit.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "sim/serialize.hh"

#include "params/GarnetRouter.hh"
#include "params/NocGarnetRouter.hh"




// #include "noc/core/network/NocGarnetNetwork.hh"
// #include "noc/core/network/NocNetDest.hh"

template <typename T_Msg, typename T_RouteInfo> class NetworkLink;
template <typename T_Msg, typename T_RouteInfo> class CreditLink;
template <typename T_Msg, typename T_RouteInfo> class InputUnit;
template <typename T_Msg, typename T_RouteInfo> class OutputUnit;

namespace gem5 {
  namespace noc {
    class NocNetDest;
    class NocProbe;
    namespace garnet
    {
        class NocGarnetNetwork;
    }
  }
}

namespace gem5
{

namespace noc
{

class FaultModel;

namespace garnet
{



template <typename T_Msg, typename T_RouteInfo>
class NocRouter : public gem5::ruby::garnet::Router<T_Msg, T_RouteInfo>
{
  public:
    using Params = std::conditional_t<
    std::is_same_v<T_Msg, gem5::noc::NocMessage> && std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>,
    NocGarnetRouterParams,
    GarnetRouterParams>;

    using NetworkType = std::conditional_t<
        std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
        std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>,
        NocGarnetNetwork,
        gem5::ruby::garnet::GarnetNetwork
    >;

    NocRouter(const Params &p);

    ~NocRouter() = default;

    void wakeup();
    // void print(std::ostream& out) const {};

    void init();
    // void addInPort(gem5::ruby::PortDirection inport_dirn, gem5::ruby::garnet::NetworkLink<T_Msg, T_RouteInfo> *link,
    //   gem5::ruby::garnet::CreditLink<T_Msg, T_RouteInfo> *credit_link);

    // version that uses NocNetDest instead
    void addOutPort(gem5::ruby::PortDirection outport_dirn, gem5::ruby::garnet::NetworkLink<T_Msg, T_RouteInfo> *link,
                        std::vector<gem5::noc::NocNetDest>& routing_table_entry,
                        int link_weight, gem5::ruby::garnet::CreditLink<T_Msg, T_RouteInfo> *credit_link,
                        uint32_t consumerVcs,
                        Nps_Type downstreamCreditNpsType);

    void addNocOutPort(gem5::ruby::PortDirection outport_dirn, gem5::ruby::garnet::NetworkLink<T_Msg, T_RouteInfo> *link,
                        std::vector<gem5::noc::garnet::NocRouteMapKey>& routes,
                        int link_weight, gem5::ruby::garnet::CreditLink<T_Msg, T_RouteInfo> *credit_link,
                        uint32_t consumerVcs,
                        Nps_Type downstreamCreditNpsType);

    std::string get_name()            { return m_name; }
    Nps_Type get_nps_type() const { return m_nps_type; }
    /** Non-zero when NPS occupancy / flit CSV tracing is enabled. */
    uint32_t get_record_nps() const { return m_record_nps; }
    bool usesInternalIngressPipeline() const
    {
        return m_nps_type == Nps_Type::NIDB ||
               m_nps_type == Nps_Type::NCRB;
    }

    void stageInternalIngressFlits();
    bool hasReadyInternalFlit(int inport, int invc, Tick time);
    gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>*
    peekInternalFlit(int inport, int invc);
    gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>*
    getInternalFlit(int inport, int invc);

    void collateStats();
    void resetStats();

    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;

    /** Optional probe for debugging hooks (NoC flit path only). */
    void nocProbeEvent(const char* hookId);
    void nocProbeEvent(const char* hookId,
                       gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* fl);

  private:
    void initNpsOccCsv();
    void npsOccMaybeLogAfterCoreCycle();
    void sumPhysicalNpsInputBufferStats(int& occSum, int& maxCapSum);

    std::string m_name;
    Nps_Type m_nps_type;
    uint32_t m_record_nps;
    uint32_t m_record_nps_gap_cycles;
    uint64_t m_nps_noc_cycle_count;

    NocSwitchAllocator<T_Msg, T_RouteInfo> nocswitchAllocator;
    Tick m_last_tick_processed_core_logic;
    bool m_core_logic_processed_this_tick;
    std::vector<std::vector<gem5::ruby::garnet::flitBuffer<T_Msg, T_RouteInfo>>>
        m_internalIngressBuffers;

    gem5::noc::NocProbe* m_nocProbe = nullptr;
};

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_NOCROUTER_HH__
