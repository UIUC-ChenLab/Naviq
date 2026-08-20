/*
 * Checkpoint helpers for gem5::noc::garnet::Nps_Type (not a SimObject).
 */

#ifndef __NOC_SERIALIZE_NPS_TYPE_HH__
#define __NOC_SERIALIZE_NPS_TYPE_HH__

#include <string>

#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "sim/serialize.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{

inline void
paramOutNpsType(CheckpointOut &cp, const std::string &name, Nps_Type t)
{
    paramOut(cp, name, static_cast<int>(t));
}

inline void
paramInNpsType(CheckpointIn &cp, const std::string &name, Nps_Type &t)
{
    int v = 0;
    paramIn(cp, name, v);
    t = static_cast<Nps_Type>(v);
}

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif // __NOC_SERIALIZE_NPS_TYPE_HH__
