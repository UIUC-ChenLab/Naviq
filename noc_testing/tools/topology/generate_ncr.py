import argparse
import json
import os
import random
import re
import sys
from pathlib import Path
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Set

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[2]
NOC_ROOT = REPO_ROOT / "src" / "noc"
for path in (
    NOC_ROOT / "testing",
    NOC_ROOT / "setup",
):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from routing import (
    BadRouter,
    HighOverlapRouter,
    LowOverlapRouter,
    RoundRobinVCAssigner,
    RoutingStrategy,
    ShortestPathRouter,
    VCAssigner,
)
from placement import (PlacementStrategy, RandomPlacer, DistanceOptimizingPlacer,
                       AXIMM, AXIS)
from setup_schema import build_setup_description, SetupDescription, PortRecord

# =============================================================================
# Topology Graph
# =============================================================================

class TopologyGraph:
    """
    Builds a directed graph from connections_list.json based on actual
    data-flow direction.

    In connections_list.json, edges are encoded by physical wiring:
      - Source/Target refer to the physical endpoints
      - Port suffixes determine data-flow direction:
        - Source has _out/req_out port + Target has _in/req port → flow: Source → Target
        - Source has _in/resp_in port + Target has _out/resp port → flow: Target → Source

    We infer the actual data-flow direction from port naming and build a unified
    directed graph where edges point in the data-flow direction. This allows
    standard shortest-path algorithms to find routes in both request and
    response directions.

    Two separate graphs are maintained:
      - req_graph: edges in the request direction (NMU→NSU for _out→_in ports)
      - resp_graph: edges in the response direction (NSU→NMU for _out→_in ports
                    on resp channels)
    """

    def __init__(self, connections_json_path: str):
        with open(connections_json_path, 'r') as f:
            data = json.load(f)

        # Unified graph with data-flow direction edges
        self.flow_graph = nx.DiGraph()
        # Original undirected graph for tracking all physical links
        self.full_graph = nx.DiGraph() 
        # Port metadata: (flow_src, flow_dst) -> list of (out_port, in_port)
        self.edge_ports: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)

        for conn in data["Connections"]:
            src = conn["Source"]
            src_port = conn["SourcePort"]
            tgt = conn["Target"]
            tgt_port = conn["TargetPort"]

            self.full_graph.add_edge(src, tgt)
            self.full_graph.add_edge(tgt, src) # Keep it effectively undirected for utility searches
            self.edge_ports[(src, tgt)].append((src_port, tgt_port))

            # Determine data-flow direction from port naming
            flow_src, flow_dst, out_port, in_port = self._resolve_flow(
                src, src_port, tgt, tgt_port)

            self.flow_graph.add_edge(flow_src, flow_dst)
            self.edge_ports[(flow_src, flow_dst)].append((out_port, in_port))

        print(f"[TopologyGraph] Loaded {self.flow_graph.number_of_nodes()} nodes, "
              f"{self.flow_graph.number_of_edges()} edges")

    @staticmethod
    def _is_output_port(port: str) -> bool:
        """Check if a port name indicates an output (data sender)."""
        return (port.endswith('_out') or port == 'req_out' or
                port == 'resp' or port.endswith('_resp'))

    @staticmethod
    def _is_input_port(port: str) -> bool:
        """Check if a port name indicates an input (data receiver)."""
        return (port.endswith('_in') or port == 'req' or
                port == 'resp_in' or port.endswith('_req'))

    def _resolve_flow(self, src: str, src_port: str,
                      tgt: str, tgt_port: str) -> Tuple[str, str, str, str]:
        """
        Determine actual data-flow direction and return
        (flow_source, flow_dest, out_port, in_port).

        Convention in connections_list.json:
        - If src_port is an output (_out, req_out, resp, *_resp):
            data flows src → tgt, src_port is the output, tgt_port is the input
        - If src_port is an input (_in, resp_in, req, *_req):
            data flows tgt → src, tgt_port is the output, src_port is the input
        """
        if self._is_output_port(src_port):
            # Source is sending data → data flows Source → Target
            return (src, tgt, src_port, tgt_port)
        elif self._is_input_port(src_port):
            # Source is receiving data → data flows Target → Source
            return (tgt, src, tgt_port, src_port)
        else:
            # Fallback: guess from target port
            if self._is_input_port(tgt_port):
                return (src, tgt, src_port, tgt_port)
            else:
                return (tgt, src, tgt_port, src_port)

    def find_path(self, src_node: str, dst_node: str) -> Optional[List[str]]:
        """Find shortest path from src to dst in the data-flow graph."""
        try:
            return nx.shortest_path(self.flow_graph, src_node, dst_node)
        except nx.NetworkXNoPath:
            return None
        except nx.NodeNotFound as e:
            print(f"[TopologyGraph] Node not found: {e}")
            return None

    def get_ports_for_edge(self, src: str, tgt: str) -> Tuple[str, str]:
        """
        Get the (out_port, in_port) for a data-flow edge from src to tgt.
        """
        ports = self.edge_ports.get((src, tgt), [])
        if not ports:
            raise ValueError(f"No data-flow edge from {src} to {tgt}")
        return ports[0]

    def build_connections_array(self, path: List[str],
                                start_port: str,
                                end_port: str) -> List[str]:
        """
        Convert a node path into the NCR Connections array format.

        The NCR format alternates: [node, port, node, port, ...]
        For each hop: [src_node, out_port, dst_node, in_port]

        The first port is overridden with start_port (e.g., "req_out" or "resp")
        and the last port is overridden with end_port (e.g., "req" or "resp_in").
        """
        if len(path) < 2:
            return [path[0], start_port]

        connections = []

        for i in range(len(path) - 1):
            src = path[i]
            tgt = path[i + 1]

            out_port, in_port = self.get_ports_for_edge(src, tgt)

            # Override first output port with start_port
            if i == 0:
                out_port = start_port
            # Override last input port with end_port
            if i == len(path) - 2:
                in_port = end_port

            connections.extend([src, out_port, tgt, in_port])

        return connections

# =============================================================================
# Endpoint Utilities
# =============================================================================

def classify_endpoint(name: str) -> str:
    """Classify an endpoint node by type."""
    if 'NMU512' in name or 'NMU128' in name:
        return 'nmu'
    elif 'NSU512' in name or 'NSU128' in name:
        return 'nsu'
    elif 'DDRMC' in name:
        return 'ddrmc'
    elif 'HBM_MC' in name:
        return 'hbm'
    elif 'NMU_HBM2E' in name:
        return 'nmu_hbm'
    else:
        return 'unknown'


def get_request_ports(endpoint_type: str, endpoint_name: str,
                      graph: TopologyGraph) -> Tuple[str, str]:
    """
    Get the (start_port, end_port) for request paths TO this endpoint.

    For NMU start: always "req_out"
    For NSU end: always "req"
    For DDRMC end: "Port0_req" (or whichever port is connected)
    For HBM end: "pc0_port0_in" (or similar)
    """
    if endpoint_type == 'nsu':
        return ("req_out", "req")
    elif endpoint_type == 'ddrmc':
        # Find which DDRMC port is reachable
        return ("req_out", _find_ddrmc_req_port(endpoint_name, graph))
    elif endpoint_type == 'hbm':
        return ("req_out", _find_hbm_req_port(endpoint_name, graph))
    else:
        return ("req_out", "req")


def get_response_ports(endpoint_type: str, endpoint_name: str,
                       graph: TopologyGraph) -> Tuple[str, str]:
    """
    Get the (start_port, end_port) for response paths FROM this endpoint.

    For NSU start: "resp"
    For DDRMC start: "Port0_resp"
    For HBM start: "pc0_port0_out"
    For NMU end: "resp_in"
    """
    if endpoint_type == 'nsu':
        return ("resp", "resp_in")
    elif endpoint_type == 'ddrmc':
        return (_find_ddrmc_resp_port(endpoint_name, graph), "resp_in")
    elif endpoint_type == 'hbm':
        return (_find_hbm_resp_port(endpoint_name, graph), "resp_in")
    else:
        return ("resp", "resp_in")


def _find_ddrmc_req_port(ddrmc_name: str, graph: TopologyGraph) -> str:
    """Find which Port*_req port on the DDRMC is connected."""
    # Look at incoming edges to the DDRMC
    for pred in graph.full_graph.predecessors(ddrmc_name):
        ports = graph.edge_ports.get((pred, ddrmc_name), [])
        for _, tgt_port in ports:
            if 'req' in tgt_port.lower() or 'Port' in tgt_port:
                return tgt_port
    # Try outgoing edges (DDRMC as source with _req suffix in target port)
    for succ in graph.full_graph.successors(ddrmc_name):
        ports = graph.edge_ports.get((ddrmc_name, succ), [])
        for src_port, _ in ports:
            if 'req' in src_port.lower():
                return src_port
    return "Port0_req"


def _find_ddrmc_resp_port(ddrmc_name: str, graph: TopologyGraph) -> str:
    """Find which Port*_resp port on the DDRMC is connected for responses."""
    for succ in graph.full_graph.successors(ddrmc_name):
        ports = graph.edge_ports.get((ddrmc_name, succ), [])
        for src_port, _ in ports:
            if 'resp' in src_port.lower():
                return src_port
    # Check incoming
    for pred in graph.full_graph.predecessors(ddrmc_name):
        ports = graph.edge_ports.get((pred, ddrmc_name), [])
        for _, tgt_port in ports:
            if 'resp' in tgt_port.lower():
                return tgt_port
    return "Port0_resp"


def _find_hbm_req_port(hbm_name: str, graph: TopologyGraph) -> str:
    """Find the request input port on HBM_MC."""
    for pred in graph.full_graph.predecessors(hbm_name):
        ports = graph.edge_ports.get((pred, hbm_name), [])
        for _, tgt_port in ports:
            if '_in' in tgt_port:
                return tgt_port
    # Outgoing edges
    for succ in graph.full_graph.successors(hbm_name):
        ports = graph.edge_ports.get((hbm_name, succ), [])
        for src_port, _ in ports:
            if '_out' in src_port:
                # This is a response port, the request port is the _in variant
                pass
    return "pc0_port0_in"


def _find_hbm_resp_port(hbm_name: str, graph: TopologyGraph) -> str:
    """Find the response output port on HBM_MC."""
    for succ in graph.full_graph.successors(hbm_name):
        ports = graph.edge_ports.get((hbm_name, succ), [])
        for src_port, _ in ports:
            if '_out' in src_port:
                return src_port
    return "pc0_port0_out"


def _get_protocol_indices(ports: list) -> Dict[str, int]:
    counters = defaultdict(int)
    indices = {}
    for port in ports:
        protocol = port.protocol
        indices[port.endpoint] = counters[protocol]
        counters[protocol] += 1
    return indices

def _get_nmu_logical_name(master_idx: int, protocol: str = AXIMM) -> str:
    if protocol == AXIS:
        return f"axis_noc_0/inst/S{master_idx:02d}_AXIS_nmu"
    return f"axi_noc_0/inst/S{master_idx:02d}_AXI_nmu"

def _get_ddr_logical_name(controller_idx: int) -> str:
    return f"axi_noc_0/inst/MC{controller_idx}_ddrc"


def _get_ddr_design_name(controller_idx: int) -> str:
    return "/axi_noc_0/ddrmc" if controller_idx == 0 else f"/axi_noc_0/ddrmc{controller_idx}"


def _get_nsu_logical_name(slave_idx: int, phy_type: str,
                          protocol: str = AXIMM) -> str:
    if protocol == AXIS:
        return f"axis_noc_0/inst/M{slave_idx:02d}_AXIS_nsu"
    if phy_type == 'ddrmc':
        return f"axi_noc_0/inst/MC{slave_idx}_ddrc"
    elif phy_type == 'hbm':
        return f"axi_noc_0/inst/MC_hbmc/inst/hbm_st0/I_hbm_chnl{slave_idx}"
    else:
        return f"axi_noc_0/inst/M{slave_idx:02d}_AXI_nsu"

def _get_design_name(logical_name: str) -> str:
    design_name_part = logical_name.split('/')[-1].replace('_nmu', '')
    design_name_part = design_name_part.replace('_nsu', '').replace('_ddrc', '')
    return f"/{logical_name.split('/inst')[0]}/{design_name_part}"

HBM_CHANNELS_PER_STACK = 8


def _endpoint_component_id(endpoint_name: str) -> str:
    return endpoint_name.split(".", 1)[0]


def _parse_ddr_endpoint(endpoint_name: str) -> Optional[Tuple[int, int]]:
    match = re.fullmatch(r"ddr(\d+)_port(\d+)", _endpoint_component_id(endpoint_name))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _parse_hbm_endpoint(endpoint_name: str) -> Optional[Tuple[int, int, int]]:
    match = re.fullmatch(r"hbm(\d+)_port([0-3])", _endpoint_component_id(endpoint_name))
    if not match:
        return None
    controller_idx = int(match.group(1))
    port_idx = int(match.group(2))
    pseudo_channel_idx = port_idx // 2
    return controller_idx, port_idx, pseudo_channel_idx


def _get_hbm_logical_name(controller_idx: int) -> str:
    stack_idx = controller_idx // HBM_CHANNELS_PER_STACK
    channel_idx = controller_idx % HBM_CHANNELS_PER_STACK
    return f"axi_noc_0/inst/MC_hbmc/inst/hbm_st{stack_idx}/I_hbm_chnl{channel_idx}"


def _get_hbm_design_name(controller_idx: int) -> str:
    return f"/axi_noc_0/HBM{controller_idx}"


def _memory_endpoint_kind(port: PortRecord, phy_node: Optional[str] = None) -> str:
    config_type = str(port.config.get("type", "")).lower()
    if config_type in ("hbm", "ddr"):
        if phy_node is not None:
            phy_type = classify_endpoint(phy_node)
            if config_type == "hbm" and phy_type not in ("hbm", "unknown"):
                raise ValueError(
                    f"{port.endpoint} declares type 'hbm' but is placed on non-HBM endpoint '{phy_node}'."
                )
            if config_type == "ddr" and phy_type not in ("ddrmc", "unknown"):
                raise ValueError(
                    f"{port.endpoint} declares type 'ddr' but is placed on non-DDR endpoint '{phy_node}'."
                )
        return config_type

    if phy_node is None:
        return ""

    phy_type = classify_endpoint(phy_node)
    if phy_type == "hbm":
        return "hbm"
    if phy_type == "ddrmc":
        return "ddr"
    return ""


def _target_port_name(endpoint_name: str, memory_kind: str) -> str:
    if memory_kind == "hbm":
        parsed = _parse_hbm_endpoint(endpoint_name)
        if parsed:
            _, port_idx, _ = parsed
            return f"PORT{port_idx}"
    if memory_kind == "ddr":
        parsed = _parse_ddr_endpoint(endpoint_name)
        if parsed:
            _, port_idx = parsed
            return f"PORT{port_idx}"
    return "PORT0"


def build_logical_name_maps(setup: SetupDescription) -> Tuple[dict, dict, dict]:
    """Return endpoint -> generated NoC logical instance name maps."""
    master_ports = setup.master_ports()
    slave_ports = setup.slave_ports()
    master_indices = _get_protocol_indices(master_ports)
    slave_indices = _get_protocol_indices(slave_ports)

    master_names = {}
    for port in master_ports:
        master_names[port.endpoint] = _get_nmu_logical_name(
            master_indices[port.endpoint], port.protocol)

    slave_names = {}
    slave_port_names = {}
    for port in slave_ports:
        phy_node = setup.placement_for(port.endpoint)
        memory_kind = _memory_endpoint_kind(port, phy_node)
        parsed_hbm = _parse_hbm_endpoint(port.endpoint)
        parsed_ddr = _parse_ddr_endpoint(port.endpoint)
        if memory_kind == "hbm" and parsed_hbm:
            controller_idx, _, _ = parsed_hbm
            slave_names[port.endpoint] = _get_hbm_logical_name(controller_idx)
        elif memory_kind == "ddr" and parsed_ddr:
            controller_idx, _ = parsed_ddr
            slave_names[port.endpoint] = _get_ddr_logical_name(controller_idx)
        else:
            phy_type = classify_endpoint(phy_node)
            slave_names[port.endpoint] = _get_nsu_logical_name(
                slave_indices[port.endpoint], phy_type, port.protocol)
        slave_port_names[port.endpoint] = _target_port_name(port.endpoint, memory_kind)

    return master_names, slave_names, slave_port_names

def _extract_qos(target_info: dict) -> dict:
    qos = {}
    nested_qos = target_info.get("qos", {})

    if "RequiredBW" in target_info:
        qos["RequiredBW"] = target_info["RequiredBW"]
    elif "write_bw" in nested_qos:
        qos["RequiredBW"] = nested_qos["write_bw"]
    elif "read_bw" in nested_qos:
        qos["RequiredBW"] = nested_qos["read_bw"]

    if "RequiredLatency" in target_info:
        qos["RequiredLatency"] = target_info["RequiredLatency"]
    elif "latency" in nested_qos:
        qos["RequiredLatency"] = nested_qos["latency"]

    return qos

# =============================================================================
# NCR File Builder
# =============================================================================

class NCRBuilder:
    """
    Assembles a complete NCR JSON from placement, connections, routing,
    and VC assignment results.
    """

    DEFAULT_BW = 500
    DEFAULT_LATENCY = 300

    def __init__(self, graph: TopologyGraph,
                 router: RoutingStrategy,
                 vc_assigner: VCAssigner,
                 num_vcs: int = 8):
        self.graph = graph
        self.router = router
        self.vc_assigner = vc_assigner
        self.num_vcs = num_vcs

    def build(self, setup: SetupDescription, endpoints_json: dict) -> dict:
        """
        Build the complete NCR JSON.
        """
        master_logical_names, slave_logical_names, slave_port_names = build_logical_name_maps(setup)

        # Collect all path requests
        path_requests = []
        for connection in setup.connections:
            master_port = setup.port(connection.source)
            nmu_node = setup.placement_for(connection.source)
            nsu_node = setup.placement_for(connection.target)
            qos = _extract_qos(connection.attrs)

            path_requests.append({
                'nmu': nmu_node,
                'nsu': nsu_node,
                'master_name': connection.source,
                'target_name': connection.target,
                'from_name': master_logical_names[connection.source],
                'to_name': slave_logical_names[connection.target],
                'target_port_name': slave_port_names[connection.target],
                'protocol': master_port.protocol,
                'qos': qos if qos else None,
            })

        # Validate endpoints exist
        missing_nodes = set()
        for req in path_requests:
            if not self.graph.flow_graph.has_node(req['nmu']):
                missing_nodes.add(req['nmu'])
            if not self.graph.flow_graph.has_node(req['nsu']):
                missing_nodes.add(req['nsu'])
        
        if missing_nodes:
            raise ValueError(
                f"The following endpoints do not exist in the topology graph:\n  " + 
                "\n  ".join(missing_nodes)
            )

        # Route all paths
        all_routes = []
        for req in path_requests:
            routes = self.router.find_routes(
                self.graph, req['nmu'], req['nsu'], req.get('qos'), req['protocol'])
            all_routes.append(routes)

        # Assign VCs
        vc_assignments = self.vc_assigner.assign_vcs(path_requests, self.num_vcs)

        # Build NCR paths
        ncr_paths = []
        for i, (req, routes, vcs) in enumerate(
                zip(path_requests, all_routes, vc_assignments)):
            path_entry = self._build_path_entry(req, routes, vcs)
            ncr_paths.append(path_entry)

        # Build Components section
        components = self._build_components(endpoints_json, setup)

        return {
            "SolutionType": "OPTIMAL",
            "LockAllDestIds": False,
            "Paths": ncr_paths,
            "Components": components,
        }

    def _build_path_entry(self, req: dict, routes: dict, vcs: dict) -> dict:
        nmu_node = req['nmu']
        nsu_node = req['nsu']
        protocol = req['protocol']

        nsu_type = classify_endpoint(nsu_node)
        bw = (req.get('qos') or {}).get('RequiredBW', self.DEFAULT_BW)
        latency = (req.get('qos') or {}).get('RequiredLatency', self.DEFAULT_LATENCY)

        from_name = req['from_name']
        to_name = req['to_name']

        req_start_port, req_end_port = get_request_ports(nsu_type, nsu_node, self.graph)
        resp_start_port, resp_end_port = get_response_ports(nsu_type, nsu_node, self.graph)

        nets = []
        if protocol == AXIS:
            write_path = routes['WRITE']
            nets.append(self._build_net(
                nmu_node, nsu_node, vcs['WRITE'], "WRITE",
                self.graph.build_connections_array(write_path, req_start_port, req_end_port),
                bw, latency, write_path))

            return {
                "Phase": 0, "From": from_name, "FromLocked": False,
                "To": to_name, "ToLocked": False, "Port": req['target_port_name'],
                "ReadTC": "BE", "WriteTC": "BE",
                "ReadBW": 0, "WriteBW": bw,
                "ReadAchievedBW": 0, "WriteAchievedBW": bw,
                "ReadLatency": 0, "WriteLatency": latency,
                "ReadBestPossibleLatency": 0, "WriteBestPossibleLatency": latency,
                "PathLocked": False, "Nets": nets,
            }

        read_path = routes['READ']
        nets.append(self._build_net(
            nsu_node, nmu_node, vcs['READ'], "READ",
            self.graph.build_connections_array(read_path, resp_start_port, resp_end_port),
            bw, latency, read_path))

        read_req_path = routes['READ_REQ']
        req_bw = max(1, bw // 16)
        nets.append(self._build_net(
            nmu_node, nsu_node, vcs['READ_REQ'], "READ_REQ",
            self.graph.build_connections_array(read_req_path, req_start_port, req_end_port),
            req_bw, latency, read_req_path))

        write_path = routes['WRITE']
        write_bw = bw + req_bw
        nets.append(self._build_net(
            nmu_node, nsu_node, vcs['WRITE'], "WRITE",
            self.graph.build_connections_array(write_path, req_start_port, req_end_port),
            write_bw, latency, write_path))

        write_resp_path = routes['WRITE_RESP']
        nets.append(self._build_net(
            nsu_node, nmu_node, vcs['WRITE_RESP'], "WRITE_RESP",
            self.graph.build_connections_array(write_resp_path, resp_start_port, resp_end_port),
            req_bw, latency, write_resp_path))

        return {
            "Phase": 0, "From": from_name, "FromLocked": False,
            "To": to_name, "ToLocked": False, "Port": req['target_port_name'],
            "ReadTC": "BE", "WriteTC": "BE",
            "ReadBW": bw, "WriteBW": bw,
            "ReadAchievedBW": bw, "WriteAchievedBW": bw,
            "ReadLatency": latency, "WriteLatency": latency,
            "ReadBestPossibleLatency": latency, "WriteBestPossibleLatency": latency,
            "PathLocked": True, "Nets": nets,
        }

    def _estimate_path_latency(self, path: List[str]) -> int:
        latency = 0
        for node in path:
            if 'NMU_HBM2E' in node: latency += 3
            elif 'NMU' in node: latency += 5
            elif 'NSU' in node: latency += 5
            elif 'DDRMC' in node: latency += 5
            elif 'HBM_MC' in node: latency += 5
            elif 'NCRB' in node: latency += 5
            elif 'NIDB' in node: latency += 6
            elif 'NPS' in node: latency += 2
            else: latency += 2
        return max(latency, 14)

    def _build_net(self, phy_start: str, phy_end: str, vc: int,
                   comm_type: str, connections: list, bw: int,
                   latency: int, path: List[str]) -> dict:
        return {
            "PhyInstanceStart": phy_start, "PhyInstanceEnd": phy_end,
            "VC": vc, "CommType": comm_type, "Connections": connections,
            "RequiredBW": bw, "AchievedBW": bw,
            "RequiredLatency": latency, "AchievedLatency": self._estimate_path_latency(path),
        }

    def _build_components(self, endpoints_json: dict,
                          setup: SetupDescription) -> list:
        components = []
        dest_id_counter = 1

        active_endpoints = {}
        master_logical_names, slave_logical_names, _ = build_logical_name_maps(setup)

        for port in setup.master_ports():
            active_endpoints[setup.placement_for(port.endpoint)] = master_logical_names[port.endpoint]

        for port in setup.slave_ports():
            active_endpoints[setup.placement_for(port.endpoint)] = slave_logical_names[port.endpoint]

        for comp in endpoints_json["Components"]:
            comp_name = comp["Name"]
            entry = {"Name": comp_name}
            if comp_name in active_endpoints:
                entry["TrafficLInst"] = active_endpoints[comp_name]
                entry["DestId"] = dest_id_counter * 64
                dest_id_counter += 1
            else:
                entry["DestId"] = 0
            components.append(entry)

        return components

# =============================================================================
# NTS File Builder
# =============================================================================

class NTSBuilder:
    """
    Assembles a complete NTS JSON from placement, connection parameters,
    and QoS settings.
    """

    DEFAULT_BW = 500
    DEFAULT_LATENCY = 300
    DEFAULT_BURST = 4
    DEFAULT_ORDER = "strict"

    DDRMC_PARAMS_TEMPLATE = {
        "CONTROLLERTYPE": "DDR4_SDRAM",
        "MC_ADD_CMD_DELAY": "0",
        "MC_ADD_CMD_DELAY_EN": "Disable",
        "MC_BA_WIDTH": "2",
        "MC_BG_WIDTH": "2",
        "MC_BURST_LENGTH": "8",
        "MC_CASLATENCY": "24",
        "MC_CASWRITELATENCY": "16",
        "MC_CA_MIRROR": "false",
        "MC_CHAN_REGION0": "DDR_LOW0",
        "MC_CHAN_REGION0_BASEADDR": "0x0",
        "MC_CHAN_REGION0_RANGE": "0x100000000",
        "MC_CLA": "0",
        "MC_CLAMSHELL": "false",
        "MC_COLUMNADDRESSWIDTH": "10",
        "MC_COMPONENT_DENSITY": "8Gb",
        "MC_COMPONENT_WIDTH": "x8",
        "MC_CONFIG_NUM": "config11",
        "MC_DATAWIDTH": "64",
        "MC_DEVICE_TYPE": "NON_S80",
        "MC_ECC": "false",
        "MC_F0_MR0": "0x0000D54",
        "MC_F0_MR1": "0x0000301",
        "MC_F0_MR2": "0x00000E8",
        "MC_F0_MR3": "0x0000020",
        "MC_MEMORY_CAPACITY": "8GB",
        "MC_MEMORY_DENSITY": "8GB",
        "MC_MEMORY_SPEEDGRADE": "DDR4-3200AC(24-24-24)",
        "MC_NO_CHANNELS": "Single",
        "MC_RANK": "1",
        "MC_SLOT": "Single",
        "MC_STACKHEIGHT": "1",
        "NUM_MC": "1"
    }

    HBM_MEMORY_PARAMS_TEMPLATE = {
        "Frequency": "1600",
        "HBM_DENSITY_PER_CHNL": "2G",
        "HBM_NUM_CHNL": "16",
        "HBM_START_CHNL": "0",
        "HBM_START_PHYSICAL_CHNL": "-1",
    }

    def _ddr_settings(self, setup: SetupDescription) -> dict:
        settings = dict(setup.global_settings.get("ddr_settings", {}))
        return {
            "controller_type": settings.get("controller_type", "DDR4_SDRAM"),
            "speed_grade": settings.get("speed_grade", "DDR4-3200AC(24-24-24)"),
            "data_width": int(settings.get("data_width", 64)),
            "memory_density": settings.get("memory_density", "8GB"),
            "component_width": settings.get("component_width", "x8"),
            "rank": str(settings.get("rank", "1")),
            "slot": str(settings.get("slot", "Single")),
            "stackheight": str(settings.get("stackheight", "1")),
            "num_mc": int(settings.get("num_mc", 1)),
        }

    def _build_hbm_instance(self, controller_idx: int, controller_ports: list) -> dict:
        logical_name = _get_hbm_logical_name(controller_idx)
        stack_idx = controller_idx // HBM_CHANNELS_PER_STACK
        channel_idx = controller_idx % HBM_CHANNELS_PER_STACK

        pseudo_channel_ranges = {}
        user_specified_nonzero_base = False
        for port in controller_ports:
            config = port.config
            parsed = _parse_hbm_endpoint(port.endpoint)
            if parsed is None:
                raise ValueError(
                    f"HBM endpoint '{port.endpoint}' must follow the naming rule hbm<mc>_port<0..3>."
                )

            _, _, pseudo_channel_idx = parsed
            base = int(config.get("base_address", "0x00000000"), 16)
            size = int(config.get("size", "0x40000000"), 16)
            user_specified_nonzero_base |= base != 0
            existing = pseudo_channel_ranges.get(pseudo_channel_idx)
            if existing and existing != (base, size):
                raise ValueError(
                    f"HBM controller {controller_idx} pseudo channel {pseudo_channel_idx} "
                    f"has conflicting address ranges: {existing} vs {(base, size)}."
                )
            pseudo_channel_ranges[pseudo_channel_idx] = (base, size)

        if 0 not in pseudo_channel_ranges:
            pseudo_channel_ranges[0] = (0, 0x40000000)
        if 1 not in pseudo_channel_ranges:
            base0, size0 = pseudo_channel_ranges[0]
            pseudo_channel_ranges[1] = (base0 + size0, size0)
        elif not user_specified_nonzero_base:
            base0, size0 = pseudo_channel_ranges[0]
            base1, size1 = pseudo_channel_ranges[1]
            if base0 == base1:
                pseudo_channel_ranges[1] = (base0 + size0, size1)

        # In the V2/generated flow, many connection JSONs use 0x0-based HBM
        # endpoint ranges as placeholders. For multi-controller HBM topologies,
        # keep explicit non-zero user bases intact, but canonicalize the default
        # placeholder pattern into unique per-controller windows so gem5 does not
        # build overlapping HBMCtrl address ranges.
        if controller_idx > 0 and not user_specified_nonzero_base:
            size0 = pseudo_channel_ranges[0][1]
            size1 = pseudo_channel_ranges[1][1]
            controller_span = size0 + size1
            controller_base = controller_idx * controller_span
            pseudo_channel_ranges[0] = (controller_base, size0)
            pseudo_channel_ranges[1] = (controller_base + size0, size1)

        sys_addresses = [
            {
                "Base": f"0x{pseudo_channel_ranges[pc_idx][0]:X}",
                "Size": f"0x{pseudo_channel_ranges[pc_idx][1]:X}",
            }
            for pc_idx in (0, 1)
        ]

        params = dict(self.HBM_MEMORY_PARAMS_TEMPLATE)
        params["ChannelNumber"] = str(channel_idx)
        params["StackNumber"] = str(stack_idx)

        return {
            "Name": logical_name,
            "DesignName": _get_hbm_design_name(controller_idx),
            "IsMaster": False,
            "CompType": "HBMMC",
            "Protocol": "AXI_MM",
            "Ports": [f"PORT{i}" for i in range(4)],
            "SysAddresses": sys_addresses,
            "MemoryParams": params,
        }

    def build(self, setup: SetupDescription) -> dict:
        """Build the complete NTS JSON."""
        master_logical_names, slave_logical_names, slave_port_names = build_logical_name_maps(setup)
        ddr_settings = self._ddr_settings(setup)

        logical_instances = []
        paths = []
        emitted_hbm_controllers = set()

        # 1. Build Master Logical Instances
        for port in setup.master_ports():
            phy_node = setup.placement_for(port.endpoint)
            protocol = port.protocol
            logical_name = master_logical_names[port.endpoint]
            design_name = _get_design_name(logical_name)

            # Check if type is 512 or 128 bit
            config = port.config
            is_128 = '128' in config.get('type', '') or '128' in phy_node
            
            inst = {
                "Name": logical_name,
                "DesignName": design_name,
                "IsMaster": True,
                "CompType": "PL_NMU",
                "Protocol": "AXI_STRM" if protocol == AXIS else "AXI_MM",
                "ReadTC": config.get("ReadTC", "BE"),
                "WriteTC": config.get("WriteTC", "BE"),
                "AxiDataWidth": 128 if is_128 else 512,
                "SysAddresses": [],
                "SimMetaData": {
                    "IPName": f"bd_gen_{logical_name.split('/')[-1]}_0"
                }
            }
            logical_instances.append(inst)

        # 2. Build Slave Logical Instances
        slave_ports = setup.slave_ports()
        hbm_ports_by_controller = defaultdict(list)
        for port in slave_ports:
            parsed_hbm = _parse_hbm_endpoint(port.endpoint)
            if parsed_hbm is not None:
                controller_idx, _, _ = parsed_hbm
                hbm_ports_by_controller[controller_idx].append(port)

        for slave_idx, port in enumerate(slave_ports):
            phy_node = setup.placement_for(port.endpoint)
            protocol = port.protocol
            memory_kind = _memory_endpoint_kind(port, phy_node)
            phy_type = classify_endpoint(phy_node)
            logical_name = slave_logical_names[port.endpoint]
            design_name_part = logical_name.split('/')[-1].replace('_nsu', '').replace('_ddrc', '')
            design_name = _get_design_name(logical_name)

            config = port.config
            is_128 = '128' in config.get('type', '') or '128' in phy_node

            parsed_hbm = _parse_hbm_endpoint(port.endpoint)
            if parsed_hbm is not None:
                controller_idx, _, _ = parsed_hbm
                if controller_idx not in emitted_hbm_controllers:
                    logical_instances.append(
                        self._build_hbm_instance(
                            controller_idx,
                            sorted(
                                hbm_ports_by_controller[controller_idx],
                                key=lambda item: _parse_hbm_endpoint(item.endpoint)[1],
                            ),
                        )
                    )
                    emitted_hbm_controllers.add(controller_idx)
                continue

            parsed_ddr = _parse_ddr_endpoint(port.endpoint)
            if parsed_ddr is not None and memory_kind == "ddr":
                design_name = _get_ddr_design_name(parsed_ddr[0])

            base = config.get("base_address", "0x00000000")
            size = config.get("size", "0x10000")

            inst = {
                "Name": logical_name,
                "DesignName": design_name,
                "IsMaster": False,
                "CompType": "DDRC" if protocol == AXIMM and memory_kind == "ddr" else "PL_NSU",
                "Protocol": "AXI_STRM" if protocol == AXIS else "AXI_MM",
                "AxiDataWidth": 128 if is_128 else 512, # DDRC usually infers this or it defaults to missing 
            }

            if protocol == AXIMM and memory_kind == "ddr":
                inst["Ports"] = ["PORT0"]
                # We optionally remove AxiDataWidth for DDRMCs to match exactly the template
                if "AxiDataWidth" in inst:
                    del inst["AxiDataWidth"]

            if protocol == AXIS:
                inst["SysAddresses"] = []
            else:
                inst["SysAddresses"] = [{
                    "Base": base,
                    "Size": size
                }]

            if protocol == AXIMM and memory_kind == "ddr":
                # Add massive DDR config
                params = dict(self.DDRMC_PARAMS_TEMPLATE)
                controller_idx = parsed_ddr[0] if parsed_ddr is not None else slave_idx
                params["Component_Name"] = f"bd_gen_MC{controller_idx}_ddrc_0"
                params["MC_MAIN_MODULE_NAME"] = f"DDRMC_MAIN_{controller_idx}"
                params["MC_NOC_MODULE_NAME"] = f"DDRMC_NOC_{controller_idx}"
                params["CONTROLLERTYPE"] = str(
                    config.get("controller_type", ddr_settings["controller_type"])
                )
                params["MC_MEMORY_SPEEDGRADE"] = str(
                    config.get("speed_grade", ddr_settings["speed_grade"])
                )
                memory_density = str(
                    config.get("memory_density", ddr_settings["memory_density"])
                )
                params["MC_MEMORY_DENSITY"] = memory_density
                params["MC_MEMORY_CAPACITY"] = memory_density
                params["MC_COMPONENT_WIDTH"] = str(
                    config.get("component_width", ddr_settings["component_width"])
                )
                params["MC_DATAWIDTH"] = str(
                    config.get("data_width", ddr_settings["data_width"])
                )
                params["MC_RANK"] = str(config.get("rank", ddr_settings["rank"]))
                params["MC_SLOT"] = str(config.get("slot", ddr_settings["slot"]))
                params["MC_STACKHEIGHT"] = str(
                    config.get("stackheight", ddr_settings["stackheight"])
                )
                params["NUM_MC"] = str(ddr_settings["num_mc"])
                params["MC_CHAN_REGION0_BASEADDR"] = str(base)
                params["MC_CHAN_REGION0_RANGE"] = str(size)
                inst["MemoryParams"] = params
            else:
                inst["SimMetaData"] = {
                    "IPName": f"bd_gen_{logical_name.split('/')[-1]}_0"
                }
            logical_instances.append(inst)

        # 3. Build Paths
        for connection in setup.connections:
            master_port = setup.port(connection.source)
            from_name = master_logical_names[connection.source]
            to_name = slave_logical_names[connection.target]
            qos = _extract_qos(connection.attrs)

            bw = qos.get("RequiredBW", self.DEFAULT_BW)
            latency = qos.get("RequiredLatency", self.DEFAULT_LATENCY)
            burst = connection.attrs.get("AvgBurst", self.DEFAULT_BURST)
            order = connection.attrs.get("WriteOrder", self.DEFAULT_ORDER)
            is_axis = master_port.protocol == AXIS

            path = {
                "Phase": 0,
                "From": from_name,
                "To": to_name,
                "Port": slave_port_names[connection.target],
                "CommType": "STRM" if is_axis else "MM_ReadWrite",
                "ReadBW": 0 if is_axis else bw,
                "ReadLatency": 0 if is_axis else latency,
                "ReadAvgBurst": 0 if is_axis else burst,
                "WriteBW": bw,
                "WriteLatency": latency,
                "WriteAvgBurst": burst,
                "WriteOrder": order
            }
            paths.append(path)

        return {
            "SystemProperties": {
                "DeviceName": "xcv80"
            },
            "LogicalInstances": logical_instances,
            "Paths": paths
        }


# =============================================================================
# CLI
# =============================================================================

def create_router(
    name: str,
    *,
    overlap_candidate_limit: int = 16,
    overlap_max_extra_hops: int = 2,
    overlap_weight: float = 4.0,
) -> RoutingStrategy:
    """Factory for routing strategies."""
    routers = {
        'shortest_path': ShortestPathRouter,
        'bad_path': BadRouter,
        'low_overlap': LowOverlapRouter,
        'high_overlap': HighOverlapRouter,
    }
    if name not in routers:
        raise ValueError(f"Unknown router: {name}. Available: {list(routers.keys())}")
    if name in {"low_overlap", "high_overlap"}:
        return routers[name](
            candidate_limit=overlap_candidate_limit,
            max_extra_hops=overlap_max_extra_hops,
            overlap_weight=overlap_weight,
        )
    return routers[name]()


def create_vc_assigner(name: str) -> VCAssigner:
    """Factory for VC assignment strategies."""
    assigners = {
        'round_robin': RoundRobinVCAssigner,
    }
    if name not in assigners:
        raise ValueError(
            f"Unknown VC assigner: {name}. Available: {list(assigners.keys())}")
    return assigners[name]()


def create_placer(name: str) -> PlacementStrategy:
    """Factory for auto-placement strategies."""
    placers = {
        'random': RandomPlacer,
        'distance_optimized': DistanceOptimizingPlacer,
    }
    if name not in placers:
        raise ValueError(
            f"Unknown placer: {name}. Available: {list(placers.keys())}")
    return placers[name]()


def main():
    parser = argparse.ArgumentParser(
        description="Unified Topology Generator for Versal NoC (NCR & NTS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_topology = os.path.join(script_dir, 'connections_list.json')
    default_endpoints = os.path.join(script_dir, 'endpoints_list.json')

    parser.add_argument('--topology', default=default_topology,
                        help=f'Path to connections_list.json (default: {default_topology})')
    parser.add_argument('--connections', required=True,
                        help='Path to connections/QoS JSON config')
    parser.add_argument('--endpoints', default=default_endpoints,
                        help=f'Path to endpoints_list.json (default: {default_endpoints})')
    parser.add_argument('--placement', required=False,
                        help='Path to manual placement JSON. If omitted, auto-placement is used.')
    parser.add_argument('--placement-out', required=False,
                        help='Output path for an auto-generated placement JSON.')
    parser.add_argument('--ncr', required=False,
                        help='Output NCR file path')
    parser.add_argument('--nts', required=False,
                        help='Output NTS file path')
    parser.add_argument('--save-placement', action='store_true',
                        help='Deprecated compatibility flag. Auto-placement is always saved when --placement is omitted.')
    parser.add_argument('--router', default='shortest_path',
                        choices=['shortest_path', 'bad_path', 'low_overlap', 'high_overlap'],
                        help='Routing algorithm (default: shortest_path)')
    parser.add_argument('--overlap-candidate-limit', type=int, default=16,
                        help='Maximum near-shortest candidates considered by overlap routers')
    parser.add_argument('--overlap-max-extra-hops', type=int, default=2,
                        help='Maximum detour over the shortest path for overlap routers')
    parser.add_argument('--overlap-weight', type=float, default=4.0,
                        help='Shared-resource weighting for overlap routers')
    parser.add_argument('--placer', default='distance_optimized',
                        choices=['random', 'distance_optimized'],
                        help='Auto-placement algorithm (default: distance_optimized)')
    parser.add_argument('--vc-assigner', default='round_robin',
                        choices=['round_robin'],
                        help='VC assignment strategy (default: round_robin)')
    parser.add_argument('--num-vcs', type=int, default=8,
                        help='Number of VCs available (default: 8)')

    args = parser.parse_args()

    if args.overlap_candidate_limit < 1:
        parser.error('--overlap-candidate-limit must be positive')
    if args.overlap_max_extra_hops < 0:
        parser.error('--overlap-max-extra-hops must be non-negative')
    if args.overlap_weight < 0:
        parser.error('--overlap-weight must be non-negative')

    if not args.ncr and not args.nts:
        sys.exit("Error: You must specify at least one output type (--ncr and/or --nts)")

    # Load input files
    print(f"Loading topology from: {args.topology}")
    graph = TopologyGraph(args.topology)

    print(f"Loading connections from: {args.connections}")
    with open(args.connections) as f:
        connections_data = json.load(f)

    print(f"Loading endpoints from: {args.endpoints}")
    with open(args.endpoints) as f:
        endpoints_data = json.load(f)

    if args.placement:
        print(f"Loading manual placement from: {args.placement}")
        with open(args.placement) as f:
            placement_data = json.load(f)
    else:
        print(f"Auto-placing endpoints with placer: {args.placer}")
        placer = create_placer(args.placer)
        placement_data = placer.place(connections_data, graph, endpoints_data)

        placement_out = args.placement_out
        if not placement_out:
            base = args.ncr or args.nts
            placement_out = os.path.splitext(base)[0] + ".place.json"

        os.makedirs(os.path.dirname(os.path.abspath(placement_out)), exist_ok=True)
        with open(placement_out, 'w') as f:
            json.dump(placement_data, f, indent=2)
        print(f"Saved auto-generated placement to: {placement_out}")

    setup = build_setup_description(connections_data, placement_data)

    # 2. Generate NCR File
    if args.ncr:
        print(f"Generating NCR file...")
        router = create_router(
            args.router,
            overlap_candidate_limit=args.overlap_candidate_limit,
            overlap_max_extra_hops=args.overlap_max_extra_hops,
            overlap_weight=args.overlap_weight,
        )
        vc_assigner = create_vc_assigner(args.vc_assigner)
        builder = NCRBuilder(graph, router, vc_assigner, args.num_vcs)
        ncr = builder.build(setup, endpoints_data)

        with open(args.ncr, 'w') as f:
            json.dump(ncr, f, indent=2)

        num_paths = len(ncr['Paths'])
        num_nets = sum(len(p['Nets']) for p in ncr['Paths'])
        num_components = len(ncr['Components'])
        print(f"NCR Summary: [{args.ncr}]")
        print(f"  Paths: {num_paths}")
        print(f"  Nets: {num_nets}")
        print(f"  Components: {num_components}")

    # 3. Generate NTS File
    if args.nts:
        print(f"Generating NTS file...")
        nts_builder = NTSBuilder()
        nts = nts_builder.build(setup)

        with open(args.nts, 'w') as f:
            json.dump(nts, f, indent=2)

        print(f"NTS Summary: [{args.nts}]")
        print(f"  Logical Instances: {len(nts['LogicalInstances'])}")
        print(f"  Logical Paths: {len(nts['Paths'])}")

    print("\nGeneration Complete.")

if __name__ == '__main__':
    main()
