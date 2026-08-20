from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from typing import Iterable, List, Optional, Sequence, Tuple

import networkx as nx

class RoutingStrategy(ABC):
    """Abstract base class for routing algorithms."""

    @abstractmethod
    def find_routes(
        self,
        graph,
        nmu_node: str,
        nsu_node: str,
        qos: Optional[dict] = None,
        protocol: str = "aximm",
    ) -> dict:
        pass


class ShortestPathRouter(RoutingStrategy):
    """BFS shortest-path routing."""

    def find_routes(
        self,
        graph,
        nmu_node: str,
        nsu_node: str,
        qos: Optional[dict] = None,
        protocol: str = "aximm",
    ) -> dict:
        req_path = graph.find_path(nmu_node, nsu_node)
        if req_path is None:
            raise RuntimeError(
                f"No request path found from {nmu_node} to {nsu_node}"
            )

        if protocol == "axis":
            return {
                "WRITE": req_path,
            }

        resp_path = graph.find_path(nsu_node, nmu_node)
        if resp_path is None:
            raise RuntimeError(
                f"No response path found from {nsu_node} to {nmu_node}"
            )

        return {
            "READ_REQ": req_path,
            "WRITE": req_path,  # Same physical path, different VC
            "READ": resp_path,
            "WRITE_RESP": resp_path,  # Same physical path, different VC
        }


class BadRouter(RoutingStrategy):
    """Suboptimal routing that intentionally takes slightly longer paths (e.g., 3rd shortest)."""

    def __init__(self, pessimism_level: int = 3):
        self.pessimism_level = pessimism_level

    def _get_bad_path(self, nx_graph, src: str, dst: str) -> List[str]:
        try:
            # Yield paths from shortest to longest
            paths_gen = nx.shortest_simple_paths(nx_graph, src, dst)
            bad_path = None

            # Try to fetch the Nth path
            for i in range(self.pessimism_level):
                try:
                    bad_path = next(paths_gen)
                except StopIteration:
                    # If we run out of paths before pessimism_level, just use the longest one we found
                    break
                    
            if bad_path is None:
                raise nx.NetworkXNoPath()
                
            return bad_path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def find_routes(self, graph, nmu_node: str, nsu_node: str,
                    qos: Optional[dict] = None,
                    protocol: str = "aximm") -> dict:
        
        req_path = self._get_bad_path(graph.flow_graph, nmu_node, nsu_node)
        if req_path is None:
            raise RuntimeError(f"No request path found from {nmu_node} to {nsu_node}")

        if protocol == "axis":
            return {
                'WRITE': req_path,
            }

        resp_path = self._get_bad_path(graph.flow_graph, nsu_node, nmu_node)
        if resp_path is None:
            raise RuntimeError(f"No response path found from {nsu_node} to {nmu_node}")

        return {
            "READ_REQ": req_path,
            "WRITE": req_path,
            "READ": resp_path,
            "WRITE_RESP": resp_path,
        }


class OverlapAwareRouter(RoutingStrategy):
    """
    Route successive flows with a bias toward lower or higher shared-resource use.

    The router looks at a bounded set of near-shortest simple paths and scores them
    against resources already consumed by earlier routed flows. This keeps the
    topology generator deterministic while making overlap an explicit routing knob.
    """

    def __init__(
        self,
        *,
        prefer_high_overlap: bool,
        candidate_limit: int = 16,
        max_extra_hops: int = 2,
        overlap_weight: float = 4.0,
    ):
        self.prefer_high_overlap = prefer_high_overlap
        self.candidate_limit = candidate_limit
        self.max_extra_hops = max_extra_hops
        self.overlap_weight = overlap_weight
        self._resource_load: Counter[Tuple[str, str]] = Counter()

    def _path_resources(self, path: Sequence[str]) -> list[Tuple[str, str]]:
        # Model overlap on directed hops; this matches the physical notion of
        # shared routed resources more closely than endpoint-only accounting.
        return [("edge", f"{src}->{dst}") for src, dst in zip(path, path[1:])]

    def _candidate_paths(
        self, nx_graph: nx.DiGraph, src: str, dst: str
    ) -> list[list[str]]:
        try:
            generator = nx.shortest_simple_paths(nx_graph, src, dst)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

        candidates: list[list[str]] = []
        shortest_len: Optional[int] = None
        max_len: Optional[int] = None
        for path in generator:
            path_len = len(path) - 1
            if shortest_len is None:
                shortest_len = path_len
                max_len = shortest_len + self.max_extra_hops
            if max_len is not None and path_len > max_len:
                break
            candidates.append(path)
            if len(candidates) >= self.candidate_limit:
                break
        return candidates

    def _path_score(self, path: Sequence[str]) -> tuple[float, int]:
        resources = self._path_resources(path)
        overlap_score = sum(self._resource_load[resource] for resource in resources)
        hop_count = len(path) - 1
        if self.prefer_high_overlap:
            # Prefer heavily shared resources, but keep shorter routes favored
            # when overlap is tied.
            return (hop_count - self.overlap_weight * overlap_score, hop_count)
        return (hop_count + self.overlap_weight * overlap_score, hop_count)

    def _select_path(self, nx_graph: nx.DiGraph, src: str, dst: str) -> list[str]:
        candidates = self._candidate_paths(nx_graph, src, dst)
        if not candidates:
            raise RuntimeError(f"No path found from {src} to {dst}")
        return min(candidates, key=self._path_score)

    def _reserve_path(self, path: Sequence[str]) -> None:
        for resource in self._path_resources(path):
            self._resource_load[resource] += 1

    def find_routes(
        self,
        graph,
        nmu_node: str,
        nsu_node: str,
        qos: Optional[dict] = None,
        protocol: str = "aximm",
    ) -> dict:
        req_path = self._select_path(graph.flow_graph, nmu_node, nsu_node)
        self._reserve_path(req_path)

        if protocol == "axis":
            return {
                "WRITE": req_path,
            }

        resp_path = self._select_path(graph.flow_graph, nsu_node, nmu_node)
        self._reserve_path(resp_path)

        return {
            "READ_REQ": req_path,
            "WRITE": req_path,
            "READ": resp_path,
            "WRITE_RESP": resp_path,
        }


class LowOverlapRouter(OverlapAwareRouter):
    def __init__(self, **kwargs):
        super().__init__(prefer_high_overlap=False, **kwargs)


class HighOverlapRouter(OverlapAwareRouter):
    def __init__(self, **kwargs):
        super().__init__(prefer_high_overlap=True, **kwargs)


class VCAssigner(ABC):
    """Abstract base class for VC assignment strategies."""

    @abstractmethod
    def assign_vcs(self, all_paths: List[dict], num_vcs: int = 8) -> List[dict]:
        pass

class RoundRobinVCAssigner(VCAssigner):
    """Assigns VCs round-robin across NMU groups."""
    COMM_TYPE_OFFSETS = {
        'READ_REQ': 0,
        'WRITE': 1,
        'READ': 2,
        'WRITE_RESP': 3,
    }

    def assign_vcs(self, all_paths: List[dict], num_vcs: int = 8) -> List[dict]:
        nmu_to_base = {}
        nmu_counter = 0

        results = []
        for path_info in all_paths:
            nmu = path_info['nmu']
            if nmu not in nmu_to_base:
                nmu_to_base[nmu] = (nmu_counter * 4) % num_vcs
                nmu_counter += 1

            base = nmu_to_base[nmu]
            vc_assignment = {}
            for comm_type, offset in self.COMM_TYPE_OFFSETS.items():
                vc_assignment[comm_type] = (base + offset) % num_vcs
            results.append(vc_assignment)

        return results
