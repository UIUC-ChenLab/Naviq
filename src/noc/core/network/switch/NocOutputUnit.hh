
#ifndef __MEM_RUBY_NETWORK_GARNET_0_NOCOUTPUTUNIT_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_NOCOUTPUTUNIT_HH__

#include <iostream>
#include <vector>
#include <type_traits>

#include "mem/ruby/network/garnet/OutputUnit.hh"
// #include "base/compiler.hh"
#include "mem/ruby/common/Consumer.hh"
// #include "noc/core/network/switch/NocOutVcState.hh"
#include "noc/lib/network/NocMessage.hh" // Needed for type trait check
#include "noc/lib/network/NocSerializeNpsType.hh"
#include "sim/serialize.hh"
// #include "noc/router/NocRouteInfo.hh"


namespace gem5
{

namespace noc
{

namespace garnet
{

// template <typename T_Msg, typename T_RouteInfo> class CreditLink;
// template <typename T_Msg, typename T_RouteInfo> class NocRouter;
template <typename T_Msg, typename T_RouteInfo> class NocRouter;
template <typename T_Msg, typename T_RouteInfo>
class NocOutputUnit : public gem5::ruby::garnet::OutputUnit<T_Msg, T_RouteInfo>
{
  public:
    NocOutputUnit(int id, gem5::ruby::PortDirection direction, NocRouter<T_Msg, T_RouteInfo> *router,
               uint32_t consumerVcs, Nps_Type nps_type);

    bool has_free_vc(int vc);
    int select_free_vc(int vc);

    void serializeNocOutputUnitExtras(CheckpointOut &cp) const;
    void unserializeNocOutputUnitExtras(CheckpointIn &cp);

  private:
    Nps_Type m_nps_type;
};

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_OUTPUTUNIT_HH__
