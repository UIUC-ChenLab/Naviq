#include "noc/endpoints/NocNode.hh"

namespace gem5
{
namespace noc
{

NocNode::NocNode(const Params &p)
    : SimObject(p), clockDomains(p.clockDomains),
      portEndpointNames(p.port_endpoint_names)
{
}

void
NocNode::serialize(CheckpointOut &cp) const
{
    SimObject::serialize(cp);
    serializeNocNodeState(cp);
}

void
NocNode::unserialize(CheckpointIn &cp)
{
    SimObject::unserialize(cp);
    unserializeNocNodeState(cp);
}

void
NocNode::serializeNocNodeState(CheckpointOut &cp) const
{}

void
NocNode::unserializeNocNodeState(CheckpointIn &cp)
{}

} // namespace noc
} // namespace gem5


