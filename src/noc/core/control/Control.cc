// New implementation switching masterNodes to use TrafficGenerator instead of tile,

#include "noc/core/control/Control.hh"

#include "sim/core.hh"
#include "sim/serialize.hh"
#include "sim/eventq.hh"
#include "sim/sim_events.hh"
#include "sim/sim_exit.hh"
#include "debug/RubyNetwork.hh"
#include "debug/NocPacketFlow.hh"
#include "debug/NocControl.hh"

#include <algorithm>
#include <cstdio>
#include <unordered_map>

namespace gem5
{
namespace noc
{

Control::Control(const Params &p)
    : ClockedObject(p),
      simCycles(p.sim_cycles),
      nocClockDomainMhz(p.noc_clock_domain_mhz),
      nocInterfaces(p.noc_interfaces),
      nodes(p.nodes),
      adjacencyList(p.adjacency_list),
      adjacencyIndex(p.adjacency_index)
{
    if (adjacencyIndex.size() != nodes.size()) {
        panic("Control: adjacency_index size (%zu) does not match nodes size (%zu)",
              adjacencyIndex.size(), nodes.size());
    }
    for (size_t node_idx = 0; node_idx < nodes.size(); ++node_idx) {
        int start = adjacencyIndex[node_idx];
        int end = (node_idx + 1 < adjacencyIndex.size())
            ? adjacencyIndex[node_idx + 1]
            : static_cast<int>(adjacencyList.size());
        if (start < 0 || end < start ||
            end > static_cast<int>(adjacencyList.size())) {
            panic("Control: invalid adjacency range for node %zu: [%d, %d)",
                  node_idx, start, end);
        }
        for (int idx = start; idx < end; ++idx) {
            int noc_idx = adjacencyList[idx];
            if (noc_idx < 0 || noc_idx >= static_cast<int>(nocInterfaces.size())) {
                panic("Control: invalid noc interface index %d for node %zu",
                      noc_idx, node_idx);
            }
            auto* node = nodes[node_idx];
            auto* noc_if = nocInterfaces[noc_idx];
            int portID = node->assignPort(noc_if->getEndpointName());
            int portClockDomain = node->getPortClockDomain(portID);
            if (std::find(clockDomains.begin(), clockDomains.end(),
                          portClockDomain) == clockDomains.end()) {
                clockDomains.push_back(portClockDomain);
            }
            connections.push_back(Connection{noc_if, node, portID, portClockDomain});
            int conn_idx = connections.size() - 1;
            clockDomainConnections[portClockDomain].push_back(conn_idx);

        }
    }

    if (std::find(clockDomains.begin(), clockDomains.end(),
                  static_cast<int>(nocClockDomainMhz)) == clockDomains.end()) {
        clockDomains.push_back(static_cast<int>(nocClockDomainMhz));
    }

    const auto directCount = p.direct_sources.size();
    panic_if(p.direct_targets.size() != directCount ||
             p.direct_source_ports.size() != directCount ||
             p.direct_target_ports.size() != directCount,
             "Control: incomplete direct AXIS connections");
    std::vector<std::pair<NocNode*, int>> usedPorts;
    for (const auto &conn : connections)
        usedPorts.emplace_back(conn.node, conn.portID);
    for (size_t i = 0; i < directCount; ++i) {
        auto *source = p.direct_sources[i];
        auto *target = p.direct_targets[i];
        const int sp = source->assignPort(p.direct_source_ports[i]);
        const int tp = target->assignPort(p.direct_target_ports[i]);
        const int cd = source->getPortClockDomain(sp);
        panic_if(cd <= 0 || target->getPortClockDomain(tp) != cd,
                 "Control: direct links require matching positive endpoint clocks");
        panic_if(!dynamic_cast<axisMasterState*>(source->getCurrentState(sp)) ||
                 !dynamic_cast<axisSlaveState*>(target->getCurrentState(tp)),
                 "Control: direct links must connect an AXIS master to an AXIS slave");
        for (auto port : {std::make_pair(source, sp), std::make_pair(target, tp)}) {
            panic_if(std::find(usedPorts.begin(), usedPorts.end(), port) != usedPorts.end(),
                     "Control: endpoint port is connected more than once");
            panic_if(std::find(nodes.begin(), nodes.end(), port.first) == nodes.end(),
                     "Control: direct endpoint is missing from nodes");
            usedPorts.push_back(port);
        }
        directConnections.push_back({source, target, sp, tp, cd});
        if (std::find(clockDomains.begin(), clockDomains.end(), cd) == clockDomains.end())
            clockDomains.push_back(cd);
    }

    nodeDone.resize(nodes.size(), 0);

    // Events must not move after schedule() stores their address on the event queue.
    // push_back without reserve can reallocate and destroy still-scheduled Events.
    tickEvents.reserve(clockDomains.size());
    for (int cd : clockDomains) {
        tickEvents.push_back({cd, EventFunctionWrapper(
            [this, cd]{ tick(cd); },
            "noc control tick",
            false,
            Event::CPU_Tick_Pri)});
    }

}

void
Control::startup()
{
    ClockedObject::startup();
    for (auto &te : tickEvents) {
        if (!te.event.scheduled()) {
            schedule(&te.event, curTick());
        }
    }
}

void Control::tick(int clockDomain)
{

    std::vector<int> connectionsToTick = clockDomainConnections[clockDomain];
    // TODO: update so it updates outs (second) and ins (first) separately
    // DPRINTF(RubyNetwork, "Control Tick Called\n");

    // Debug: trace control tick progress to help find infinite loops
    DPRINTF(NocControl, "[Control] tick @ %llu\n", (unsigned long long)curTick());

    for (auto conn_idx : connectionsToTick) {
        auto &conn = connections[conn_idx];

        conn.nocInterface->nodeSideUpdate(conn.node->getCurrentState(conn.portID));
    }

    std::vector<NocNode*> nodesToTick;
    for (auto conn_idx : connectionsToTick) {
        auto &conn = connections[conn_idx];
        conn.node->update(conn.portID, conn.nocInterface->getCurrentState());
        if (std::find(nodesToTick.begin(), nodesToTick.end(), conn.node) ==
            nodesToTick.end()) {
            nodesToTick.push_back(conn.node);
        }
    }

    // Snapshot both directions before clocking any endpoint, just as for the
    // NoC boundaries above. update() copies input state and never advances RTL.
    // A direct wire has no NoC packetization, hidden queues, or extra clock.
    for (auto &conn : directConnections) {
        if (conn.clockDomain != clockDomain) continue;
        conn.source->update(conn.sourcePort, conn.target->getCurrentState(conn.targetPort));
        conn.target->update(conn.targetPort, conn.source->getCurrentState(conn.sourcePort));
        for (auto *node : {conn.source, conn.target})
            if (std::find(nodesToTick.begin(), nodesToTick.end(), node) == nodesToTick.end())
                nodesToTick.push_back(node);
    }

    for (auto *node : nodesToTick) {
        node->tick(clockDomain);
    }

    // Commit node-side interface state on the endpoint clock that produced it.
    // The NoC side is still advanced only on the NoC clock below.
    if (clockDomain != static_cast<int>(nocClockDomainMhz)) {
        for (auto conn_idx : connectionsToTick) {
            connections[conn_idx].nocInterface->tick();
        }
    }

    // only tick noc interfaces on the NoC clock domain
    if (clockDomain == static_cast<int>(nocClockDomainMhz)) {
        for (auto *noc_if : nocInterfaces) {
            noc_if->nocSideUpdate();
            noc_if->tick();
        }
    }

    // Check if all nodes across all clock domains are done (cached)
    bool allDone = (numDoneNodes == nodes.size());
    if (!allDone) {
        for (size_t i = 0; i < nodes.size(); ++i) {
            if (!nodeDone[i] && nodes[i]->done()) {
                nodeDone[i] = 1;
                ++numDoneNodes;
            }
        }
        allDone = (numDoneNodes == nodes.size());
    }
    if (allDone) {
        nocInterfaces[0]->getNocNetworkPtr()->getTrafficMonitor().outputCSV();
        exitSimLoop("Reads and writes completed");
    }
    if (curTick() >= simCycles)
        exitSimLoop("Network Tester completed simCycles");
    else {
        for (auto& te : tickEvents) {
            if (te.clockDomainId == clockDomain && !te.event.scheduled()) {
                Tick period = sim_clock::Frequency /
                    (static_cast<uint64_t>(clockDomain) * 1000000);
                schedule(&te.event, curTick() + period);
                break;
            }
        }
    }

    DPRINTF(NocControl, "[Control] end-of-tick @ %llu, allDone=%s\n",
            (unsigned long long)curTick(), allDone ? "true" : "false");

}

void
Control::serialize(CheckpointOut &cp) const
{
    ClockedObject::serialize(cp);
    SERIALIZE_SCALAR(simCycles);
    SERIALIZE_SCALAR(nocClockDomainMhz);
    SERIALIZE_CONTAINER(nodeDone);
    uint64_t nd = numDoneNodes;
    paramOut(cp, "ctl_num_done_nodes", nd);
}

void
Control::unserialize(CheckpointIn &cp)
{
    ClockedObject::unserialize(cp);
    UNSERIALIZE_SCALAR(simCycles);
    UNSERIALIZE_SCALAR(nocClockDomainMhz);
    UNSERIALIZE_CONTAINER(nodeDone);
    uint64_t nd = 0;
    paramIn(cp, "ctl_num_done_nodes", nd);
    numDoneNodes = static_cast<size_t>(nd);
}

}
}
