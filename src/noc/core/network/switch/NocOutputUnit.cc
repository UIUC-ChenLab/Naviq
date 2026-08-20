#include "noc/core/network/switch/NocOutputUnit.hh"

#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/Credit.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"
#include "noc/lib/network/NocMessage.hh"
#include "sim/serialize.hh"

namespace gem5
{

namespace noc
{

namespace garnet
{

// template class NocOutputUnit<gem5::ruby::Message, gem5::ruby::garnet::RouteInfo>;
template class NocOutputUnit<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>;


template <typename T_Msg, typename T_RouteInfo>
NocOutputUnit<T_Msg, T_RouteInfo>::NocOutputUnit(int id, gem5::ruby::PortDirection direction, NocRouter<T_Msg, T_RouteInfo> *router,
  uint32_t consumerVcs, Nps_Type nps_type)
  : gem5::ruby::garnet::OutputUnit<T_Msg, T_RouteInfo>(id, direction, router, consumerVcs),
      m_nps_type(nps_type)
{
}

template <typename T_Msg, typename T_RouteInfo>
void
NocOutputUnit<T_Msg, T_RouteInfo>::serializeNocOutputUnitExtras(
    CheckpointOut &cp) const
{
    paramOutNpsType(cp, "nou_nps_type", m_nps_type);
}

template <typename T_Msg, typename T_RouteInfo>
void
NocOutputUnit<T_Msg, T_RouteInfo>::unserializeNocOutputUnitExtras(
    CheckpointIn &cp)
{
    paramInNpsType(cp, "nou_nps_type", m_nps_type);
}

// Check if the output port (i.e., input port at next router) has free VCs.
template <typename T_Msg, typename T_RouteInfo>
bool
NocOutputUnit<T_Msg, T_RouteInfo>::has_free_vc(int vnet)
{
    // if (is_vc_idle(vc, curTick())) {return true;}
    int vc_base = vnet* this->get_vc_per_vnet();
    for (int vc = vc_base; vc < vc_base + m_vc_per_vnet; vc++) {
        if (this->is_vc_idle(vc, curTick()))
            return true;
    }

    return false;
}

// Assign a free output VC to the winner of Switch Allocation
template <typename T_Msg, typename T_RouteInfo>
int
NocOutputUnit<T_Msg, T_RouteInfo>::select_free_vc(int vnet)
{
    // if (is_vc_idle(vc, curTick())) {
    //     outVcState[vc].setState(ACTIVE_, curTick());
    //     return vc;
    // }

    int vc_base = vnet*m_vc_per_vnet;

    for (int vc = vc_base; vc < vc_base + this->getVcsPerVnet(); vc++) {
        if (this->is_vc_idle(vc, curTick())) {
            outVcState[vc].setState(ACTIVE_, curTick());
            return vc;
        }
    }

    return -1;
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
