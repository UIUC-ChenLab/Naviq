#ifndef __NOC_NODE_HH__
#define __NOC_NODE_HH__

#include <string>
#include <vector>

#include "sim/sim_object.hh"
#include "sim/serialize.hh"
#include "params/NocNode.hh"
#include "noc/lib/axi/AXITypes.hh"


namespace gem5
{
namespace noc
{

class FunctionalMemoryEndpoint
{
  public:
    virtual void functionalWrite(Addr addr, const uint8_t* data, size_t size) = 0;
    virtual void functionalRead(Addr addr, uint8_t* data, size_t size) = 0;
    virtual bool addressInRange(Addr addr) const = 0;
    virtual ~FunctionalMemoryEndpoint() = default;
};

class NocNode : public SimObject
{
  public:
    typedef NocNodeParams Params;
    NocNode(const Params &p);
    virtual bool done() = 0;
    virtual bool tick(int clockDomain) = 0;
    virtual void update(int portID, State* inputNocInterfaceState) = 0;
    virtual State* getCurrentState(int portID) = 0;
    virtual int assignPort(const std::string &endpointName) = 0;
    int getPrimaryClockDomain() const {
        return clockDomains.empty() ? 0 : clockDomains[0];
    }
    int getPortClockDomain(int portID) const {
        if (portID < 0 || static_cast<size_t>(portID) >= clockDomains.size())
            return 0;
        return clockDomains[portID];
    }

    virtual ~NocNode() = default;

    void serialize(CheckpointOut &cp) const override final;
    void unserialize(CheckpointIn &cp) override final;

  protected:
    /** Per-node checkpoint body; default is a no-op. */
    virtual void serializeNocNodeState(CheckpointOut &cp) const;
    virtual void unserializeNocNodeState(CheckpointIn &cp);

    int maxPorts;
    std::vector<int> clockDomains;
    std::vector<std::string> portEndpointNames;
};

} // namespace noc
} // namespace gem5

#endif


