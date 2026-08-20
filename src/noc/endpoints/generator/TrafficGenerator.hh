#ifndef __TRAFFICGENERATOR_HH
#define __TRAFFICGENERATOR_HH

#include "debug/NocTiming.hh"
#include "params/TrafficGenerator.hh"
#include "noc/endpoints/NocNode.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxisTrafficGenerator/AxisTrafficGenerator.h"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/include/AxisInterface.h"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxiTrafficGenerator/AxiTrafficGenerator.h"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/include/AxiInterface.h"
#include "noc/core/interface/NocInterface.hh"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/include/NsuInfo.h"
#include <deque>
#include <memory>
#include <variant>
#include <string>

// Map older naming to the actual interface types for channel storage
using AXISInterface = std::shared_ptr<AxisInterface>;
using AXIInterface  = std::shared_ptr<AxiInterface>;

//generates traffic

//acts in place of src/cpu/testers/garnet_synthetic_traffic/GarnetSyntheticTraffic.hh

namespace gem5
{
namespace noc{


class TrafficGenerator : public NocNode
{
    public:
        typedef TrafficGeneratorParams Params;
        TrafficGenerator(const Params &p);
        ~TrafficGenerator();

        //main simulation loop (1 cycle)
        bool tick(int clockDomain) override;
        bool done() { return std::visit( [](auto& generator) { return generator.isDone(); }, trafficGenerator); }

        void update(int portID, State* inputNocInterfaceState) override;
        State* getCurrentState(int portID) override;
        int assignPort(const std::string &endpointName) override;

    protected:
        std::string protocol;
        std::string mode;

        void copyAxisValuesFromChannel(axisMasterState& state);
        void setInvalidAxisBeat(axisMasterState& state);
        void copyAxiValuesFromChannel(aximmMasterState& state);

        // Tick simCycles;

        std::unique_ptr<State> currentState;
        std::unique_ptr<State> nextState;
        std::unique_ptr<State> nocInterfaceState;
        std::variant<AXISInterface, AXIInterface> signals;
        std::variant<AxiTrafficGenerator, AxisTrafficGenerator> trafficGenerator;

        // Helper accessors for derived classes (return external generator impls)
        ::AxisTrafficGenerator* axisGenerator();
        ::AxiTrafficGenerator* axiGenerator();
        // Re-initialize current AXIS state after changing strategy/config
        void updateAxisCurrentState();
        void updateAxiCurrentState();

        bool portAssigned = false;

};
}
}

#endif
