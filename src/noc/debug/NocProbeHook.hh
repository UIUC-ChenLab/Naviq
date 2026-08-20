/**
 * Helpers to forward NoC hook string ids from generic Router/InputUnit code to
 * NocRouter's optional NocProbe (NoC flit path only).
 */
#ifndef __NOC_TEST_NOC_PROBE_HOOK_HH__
#define __NOC_TEST_NOC_PROBE_HOOK_HH__

#include <type_traits>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "noc/lib/network/NocMessage.hh"
#include "noc/core/network/switch/NocRouter.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{

template <typename T_Msg, typename T_RouteInfo>
inline void
nocProbeFromRouter(gem5::ruby::garnet::Router<T_Msg, T_RouteInfo>* router,
                   const char* hookId,
                   gem5::ruby::garnet::flit<T_Msg, T_RouteInfo>* fl)
{
    if (!router) {
        return;
    }
    if constexpr (std::is_same_v<T_Msg, gem5::noc::NocMessage> &&
                  std::is_same_v<T_RouteInfo, gem5::noc::garnet::NocRouteInfo>) {
        auto* nr = static_cast<
            NocRouter<gem5::noc::NocMessage, gem5::noc::garnet::NocRouteInfo>*>(
            router);
        nr->nocProbeEvent(hookId,
            static_cast<gem5::ruby::garnet::flit<gem5::noc::NocMessage,
                                                 gem5::noc::garnet::NocRouteInfo>*>(fl));
    } else {
        (void)hookId;
        (void)fl;
    }
}

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif // __NOC_TEST_NOC_PROBE_HOOK_HH__
