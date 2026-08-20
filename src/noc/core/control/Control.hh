#ifndef __CONTROL_HH__
#define __CONTROL_HH__

#include <cstddef>
#include <cstdint>
#include <vector>

#include "noc/core/interface/NocInterface.hh"
#include "noc/endpoints/NocNode.hh"
#include "noc/endpoints/sink/AxisSinkNode.hh"
#include "noc/endpoints/fifo/AxisFifoNode.hh"
#include "noc/endpoints/generator/TrafficGenerator.hh"
#include "params/Control.hh"
#include "sim/serialize.hh"

namespace gem5{
namespace noc{

    /**
     * Top-level NoC scheduler.
     *
     * Control owns the endpoint/interface registry and schedules one tick event
     * per modeled clock domain. Endpoint code must not assume a single global
     * cycle: data crosses domains through NocInterface/CDC queues and advances
     * only on the event for its own domain.
     */
    class Control : public ClockedObject
    {
        public:
            typedef ControlParams Params;
            Control(const Params &p);

            void tick(int clockDomainId);
            void startup() override;

            void serialize(CheckpointOut &cp) const override;
            void unserialize(CheckpointIn &cp) override;

        private:
            struct Connection
            {
                NocInterface* nocInterface;
                NocNode* node;
                int portID;
                int clockDomain;
            };

            struct TickEvent {
                int clockDomainId;
                EventFunctionWrapper event;
            };
            std::vector<TickEvent> tickEvents;
            Tick simCycles;
            uint32_t nocClockDomainMhz;

            std::vector<NocInterface*> nocInterfaces;
            std::vector<NocNode*> nodes;
            std::vector<int> adjacencyList;
            std::vector<int> adjacencyIndex;

            std::vector<Connection> connections;
            std::vector<int> clockDomains;
            std::unordered_map<int, std::vector<int>> clockDomainConnections;

            std::vector<uint8_t> nodeDone;
            size_t numDoneNodes = 0;
    };
}
}

#endif
