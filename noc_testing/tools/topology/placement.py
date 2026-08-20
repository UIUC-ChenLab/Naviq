import random
import re
import networkx as nx
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, List, Tuple

AXIMM = "aximm"
AXIS = "axis"
V2_CONNECTION_KIND = "naviq.connections"
V2_PLACEMENT_KIND = "naviq.placement"
HBM_LOGICAL_ENDPOINT_RE = re.compile(r"^hbm(\d+)_port[0-3]$")

def classify_endpoint(name: str) -> str:
    """Classify an endpoint node by type."""
    if 'NMU512' in name or 'NMU128' in name: return 'nmu'
    elif 'NSU512' in name or 'NSU128' in name: return 'nsu'
    elif 'DDRMC' in name: return 'ddrmc'
    elif 'HBM_MC' in name: return 'hbm'
    elif 'NMU_HBM2E' in name: return 'nmu_hbm'
    else: return 'unknown'

def infer_slave_physical_type(name: str, config: dict = None) -> str:
    """Infer the required physical endpoint class for a logical slave."""
    config = config or {}
    type_hint = config.get("type", "")
    hint = f"{name} {type_hint}".lower()

    if "ddr" in hint:
        return "ddrmc"
    if "hbm" in hint:
        return "hbm"
    return "nsu"

def is_v2_connections(connections_json: dict) -> bool:
    return connections_json.get("kind") == V2_CONNECTION_KIND

def _endpoint_ref(component_id: str, port_name: str) -> str:
    return f"{component_id}.{port_name}"

def _v2_endpoint_configs(connections_json: dict) -> Dict[str, dict]:
    configs = {}
    for component_id, component in connections_json.get("components", {}).items():
        node_type = component.get("node_type", "")
        for port_name, port in component.get("ports", {}).items():
            endpoint = _endpoint_ref(component_id, port_name)
            config = {
                k: v for k, v in port.items()
                if k not in ("role", "protocol")
            }
            config.setdefault("node_type", node_type)
            configs[endpoint] = config
    return configs

def _v2_endpoint_protocols(connections_json: dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    master_protocols = {}
    slave_protocols = {}
    for component_id, component in connections_json.get("components", {}).items():
        for port_name, port in component.get("ports", {}).items():
            endpoint = _endpoint_ref(component_id, port_name)
            role = str(port.get("role", "")).lower()
            protocol = str(port.get("protocol", "")).lower()
            if role == "master":
                _add_endpoint_protocol(master_protocols, endpoint, protocol, "master")
            elif role == "slave":
                _add_endpoint_protocol(slave_protocols, endpoint, protocol, "slave")
    return master_protocols, slave_protocols

def _format_placement(connections_json: dict,
                      master_placement: dict,
                      slave_placement: dict) -> dict:
    if is_v2_connections(connections_json):
        placements = {}
        placements.update(master_placement)
        placements.update(slave_placement)
        return {
            "kind": V2_PLACEMENT_KIND,
            "version": 1,
            "placements": placements,
        }
    return {
        "master_placement": master_placement,
        "slave_placement": slave_placement,
    }

def _add_endpoint_protocol(protocols: dict, name: str, protocol: str,
                           role: str) -> None:
    existing = protocols.get(name)
    if existing is not None and existing != protocol:
        raise ValueError(
            f"Endpoint '{name}' is listed as both {existing} and {protocol} {role}."
        )
    protocols[name] = protocol


def _logical_hbm_group(endpoint_ref: str) -> str | None:
    component_id = endpoint_ref.split(".", 1)[0]
    match = HBM_LOGICAL_ENDPOINT_RE.fullmatch(component_id)
    if not match:
        return None
    return f"hbm{match.group(1)}"


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))

def get_endpoint_protocols(connections_json: dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return logical master/slave protocol maps from the connection config."""
    if is_v2_connections(connections_json):
        return _v2_endpoint_protocols(connections_json)

    master_protocols = {}
    slave_protocols = {}

    for protocol, master_key, slave_key in (
            (AXIMM, "aximm_masters", "aximm_slaves"),
            (AXIS, "axis_masters", "axis_slaves")):
        for master in connections_json.get(master_key, []):
            _add_endpoint_protocol(master_protocols, master["name"], protocol, "master")
        for slave in connections_json.get(slave_key, []):
            _add_endpoint_protocol(slave_protocols, slave["name"], protocol, "slave")

    # Legacy QoS-only files did not declare protocol-specific endpoint lists.
    if not master_protocols and not slave_protocols:
        for master_name, targets in connections_json.get("connections", {}).items():
            master_protocols[master_name] = AXIMM
            for target in targets:
                slave_protocols[target["to"]] = AXIMM

    return master_protocols, slave_protocols

def get_endpoint_configs(connections_json: dict) -> Dict[str, dict]:
    """Merge endpoint metadata from old and protocol-specific config shapes."""
    if is_v2_connections(connections_json):
        return _v2_endpoint_configs(connections_json)

    endpoint_configs = {
        name: dict(config)
        for name, config in connections_json.get("endpoints", {}).items()
    }

    for key in ("aximm_masters", "aximm_slaves", "axis_masters", "axis_slaves"):
        for endpoint in connections_json.get(key, []):
            name = endpoint["name"]
            config = endpoint_configs.setdefault(name, {})
            for attr, value in endpoint.items():
                if attr != "name":
                    config.setdefault(attr, value)

    return endpoint_configs

class PlacementStrategy(ABC):
    """Abstract base class for auto-placement algorithms."""
    @abstractmethod
    def place(self, connections_json: dict,
              graph,
              endpoints_json: dict) -> dict:
        pass

    def _get_available_endpoints(self, endpoints_json: dict, graph) -> Dict[str, List[str]]:
        available = defaultdict(list)
        for comp in endpoints_json.get("Components", []):
            name = comp["Name"]
            if graph.flow_graph.has_node(name):
                ctype = classify_endpoint(name)
                available[ctype].append(name)
        return available

    def _get_logical_requirements(self, connections_json: dict) -> Tuple[Dict[str, str], Dict[str, str]]:
        master_types = {}
        slave_types = {}
        endpoint_configs = get_endpoint_configs(connections_json)

        master_protocols, slave_protocols = get_endpoint_protocols(connections_json)
        for master_name in master_protocols:
            master_types[master_name] = 'nmu'
        for slave_name, protocol in slave_protocols.items():
            slave_types[slave_name] = (
                'nsu' if protocol == AXIS
                else infer_slave_physical_type(slave_name, endpoint_configs.get(slave_name))
            )

        if is_v2_connections(connections_json):
            return master_types, slave_types

        for master_name, targets in connections_json.get("connections", {}).items():
            master_types[master_name] = 'nmu'
            master_protocol = master_protocols.get(master_name, AXIMM)
            
            for target in targets:
                slave_name = target["to"]
                slave_protocol = slave_protocols.get(slave_name, master_protocol)
                slave_types[slave_name] = (
                    'nsu' if slave_protocol == AXIS
                    else infer_slave_physical_type(slave_name, endpoint_configs.get(slave_name))
                )

        return master_types, slave_types


class RandomPlacer(PlacementStrategy):
    """A fast baseline algorithm that randomly assigns logical endpoints to available physical endpoints."""
    def place(self, connections_json: dict,
              graph,
              endpoints_json: dict) -> dict:
        available = self._get_available_endpoints(endpoints_json, graph)
        available["hbm"] = _dedupe_preserve_order(available["hbm"])
        master_reqs, slave_reqs = self._get_logical_requirements(connections_json)

        for ctype in available:
            random.shuffle(available[ctype])

        master_placement = {}
        for m_name, m_type in master_reqs.items():
            if not available[m_type]:
                raise ValueError(f"Not enough physical '{m_type}' endpoints available to place '{m_name}'")
            master_placement[m_name] = available[m_type].pop()

        slave_placement = {}
        hbm_group_placement = {}
        for s_name, s_type in slave_reqs.items():
            hbm_group = _logical_hbm_group(s_name) if s_type == "hbm" else None
            if hbm_group is not None and hbm_group in hbm_group_placement:
                slave_placement[s_name] = hbm_group_placement[hbm_group]
                continue
            if not available[s_type]:
                raise ValueError(f"Not enough physical '{s_type}' endpoints available to place '{s_name}'")
            slave_placement[s_name] = available[s_type].pop()
            if hbm_group is not None:
                hbm_group_placement[hbm_group] = slave_placement[s_name]

        return _format_placement(connections_json, master_placement, slave_placement)


class DistanceOptimizingPlacer(PlacementStrategy):
    """
    A QoS-aware greedy heuristic algorithm that tries to place logically
    connected endpoints physically close to each other on the NoC.
    """
    def place(self, connections_json: dict,
              graph,
              endpoints_json: dict) -> dict:
        available = self._get_available_endpoints(endpoints_json, graph)
        available["hbm"] = _dedupe_preserve_order(available["hbm"])
        master_reqs, slave_reqs = self._get_logical_requirements(connections_json)
        
        edges = []
        if is_v2_connections(connections_json):
            for target in connections_json.get("connections", []):
                master = target["from"]
                slave = target["to"]
                latency = target.get("RequiredLatency", 300)
                bw = target.get("RequiredBW", 500)
                qos = target.get("qos", {})
                latency = qos.get("latency", latency)
                bw = qos.get("write_bw", qos.get("read_bw", bw))
                priority = (-latency, bw)
                edges.append({
                    'master': master,
                    'slave': slave,
                    'priority': priority
                })
        else:
            for master, targets in connections_json.get("connections", {}).items():
                for target in targets:
                    slave = target["to"]
                    latency = target.get("RequiredLatency", 300)
                    bw = target.get("RequiredBW", 500)
                    priority = (-latency, bw)
                    edges.append({
                        'master': master,
                        'slave': slave,
                        'priority': priority
                    })
        
        edges.sort(key=lambda x: x['priority'], reverse=True)

        master_placement = {}
        slave_placement = {}
        hbm_group_placement = {}

        for edge in edges:
            m_name = edge['master']
            s_name = edge['slave']
            m_type = master_reqs[m_name]
            s_type = slave_reqs[s_name]
            hbm_group = _logical_hbm_group(s_name) if s_type == "hbm" else None
            shared_hbm_phy = (
                hbm_group_placement.get(hbm_group) if hbm_group is not None else None
            )

            if m_name not in master_placement and s_name not in slave_placement:
                if shared_hbm_phy is not None:
                    m_phy = self._find_closest_to(shared_hbm_phy, m_type, available, graph)
                    master_placement[m_name] = m_phy
                    slave_placement[s_name] = shared_hbm_phy
                    available[m_type].remove(m_phy)
                else:
                    m_phy, s_phy = self._find_closest_pair(m_type, s_type, available, graph)
                    master_placement[m_name] = m_phy
                    slave_placement[s_name] = s_phy
                    available[m_type].remove(m_phy)
                    available[s_type].remove(s_phy)
                    if hbm_group is not None:
                        hbm_group_placement[hbm_group] = s_phy

            elif m_name in master_placement and s_name not in slave_placement:
                if shared_hbm_phy is not None:
                    slave_placement[s_name] = shared_hbm_phy
                else:
                    m_phy = master_placement[m_name]
                    s_phy = self._find_closest_to(m_phy, s_type, available, graph)
                    slave_placement[s_name] = s_phy
                    available[s_type].remove(s_phy)
                    if hbm_group is not None:
                        hbm_group_placement[hbm_group] = s_phy

            elif s_name in slave_placement and m_name not in master_placement:
                s_phy = slave_placement[s_name]
                m_phy = self._find_closest_to(s_phy, m_type, available, graph)
                master_placement[m_name] = m_phy
                available[m_type].remove(m_phy)

        for m_name, m_type in master_reqs.items():
            if m_name not in master_placement:
                if not available[m_type]:
                    raise ValueError(f"No available '{m_type}' slots for disconnected '{m_name}'")
                master_placement[m_name] = available[m_type].pop()
                
        for s_name, s_type in slave_reqs.items():
            if s_name not in slave_placement:
                hbm_group = _logical_hbm_group(s_name) if s_type == "hbm" else None
                if hbm_group is not None and hbm_group in hbm_group_placement:
                    slave_placement[s_name] = hbm_group_placement[hbm_group]
                    continue
                if not available[s_type]:
                    raise ValueError(f"No available '{s_type}' slots for disconnected '{s_name}'")
                slave_placement[s_name] = available[s_type].pop()
                if hbm_group is not None:
                    hbm_group_placement[hbm_group] = slave_placement[s_name]

        return _format_placement(connections_json, master_placement, slave_placement)

    def _find_closest_pair(self, type1: str, type2: str,
                           available: dict, graph) -> Tuple[str, str]:
        if not available[type1] or not available[type2]:
            raise ValueError(f"Not enough physical endpoints to pair '{type1}' and '{type2}'.")

        best_pair = None
        best_dist = float('inf')

        candidates1 = random.sample(available[type1], min(5, len(available[type1])))
        
        for cand1 in candidates1:
            try:
                lengths = nx.single_source_shortest_path_length(graph.flow_graph, cand1)
                
                for cand2 in available[type2]:
                    dist = lengths.get(cand2, float('inf'))
                    if dist < best_dist:
                        best_dist = dist
                        best_pair = (cand1, cand2)
                        
                        if dist <= 3:
                            return best_pair
            except nx.NetworkXError:
                continue

        if best_pair is None:
            return available[type1][0], available[type2][0]
            
        return best_pair

    def _find_closest_to(self, target_phy: str, ctype: str,
                         available: dict, graph) -> str:
        if not available[ctype]:
            raise ValueError(f"Not enough physical endpoints of type '{ctype}'.")

        best_node = available[ctype][0]
        best_dist = float('inf')

        try:
            lengths = nx.single_source_shortest_path_length(graph.flow_graph.to_undirected(), target_phy)
            
            for cand in available[ctype]:
                dist = lengths.get(cand, float('inf'))
                if dist < best_dist:
                    best_dist = dist
                    best_node = cand
        except nx.NetworkXError:
            pass

        return best_node
