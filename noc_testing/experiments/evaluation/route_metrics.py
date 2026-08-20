from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


DATA_BEARING_COMM_TYPES = {"READ", "WRITE"}


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _resource_nodes_from_connections(connections: List[str]) -> List[str]:
    nodes = connections[0::2]
    if len(nodes) <= 2:
        return []
    return nodes[1:-1]


def compute_route_metrics(ncr_path: Path) -> Dict[str, Any]:
    data = _load_json(ncr_path)
    paths = data.get("Paths", [])
    flow_resources: List[set[str]] = []
    data_net_hops: List[int] = []

    for path in paths:
        resources: set[str] = set()
        for net in path.get("Nets", []):
            if str(net.get("CommType", "")).upper() not in DATA_BEARING_COMM_TYPES:
                continue
            connections = list(net.get("Connections", []))
            nodes = connections[0::2]
            if len(nodes) >= 2:
                data_net_hops.append(len(nodes) - 1)
            resources.update(_resource_nodes_from_connections(connections))
        flow_resources.append(resources)

    resource_counts: Counter[str] = Counter()
    for resources in flow_resources:
        resource_counts.update(resources)

    pairwise_overlaps: List[float] = []
    for i in range(len(flow_resources)):
        for j in range(i + 1, len(flow_resources)):
            union = flow_resources[i] | flow_resources[j]
            if not union:
                pairwise_overlaps.append(0.0)
            else:
                pairwise_overlaps.append(
                    len(flow_resources[i] & flow_resources[j]) / len(union)
                )

    avg_pairwise_overlap = (
        sum(pairwise_overlaps) / len(pairwise_overlaps) if pairwise_overlaps else 0.0
    )
    max_flows = max(resource_counts.values(), default=0)
    route_overlap_score = max_flows * avg_pairwise_overlap
    shared_resource_count = sum(1 for count in resource_counts.values() if count >= 2)
    top_shared_resource_id = ""
    if resource_counts:
        top_shared_resource_id = max(
            sorted(resource_counts),
            key=lambda resource_id: (resource_counts[resource_id], resource_id),
        )

    return {
        "avg_hop_count": round(
            sum(data_net_hops) / len(data_net_hops), 6
        )
        if data_net_hops
        else 0.0,
        "max_hop_count": max(data_net_hops, default=0),
        "max_flows_on_any_resource": max_flows,
        "fraction_of_route_resources_shared_by_2_or_more_flows": round(
            shared_resource_count / len(resource_counts), 6
        )
        if resource_counts
        else 0.0,
        "shared_resource_count": shared_resource_count,
        "top_shared_resource_id": top_shared_resource_id,
        "average_pairwise_route_overlap": round(avg_pairwise_overlap, 6),
        "route_overlap_score": round(route_overlap_score, 6),
        "num_data_nets": len(data_net_hops),
        "num_paths": len(paths),
    }


def load_nts_shape(nts_path: Path) -> Dict[str, int]:
    data = _load_json(nts_path)
    paths = data.get("Paths", [])
    return {
        "num_paths": len(paths),
        "num_sources": len({str(path.get("From", "")) for path in paths}),
        "num_destinations": len({str(path.get("To", "")) for path in paths}),
    }


def load_ncr_shape(ncr_path: Path) -> Dict[str, int]:
    data = _load_json(ncr_path)
    paths = data.get("Paths", [])
    return {
        "num_paths": len(paths),
        "num_sources": len({str(path.get("From", "")) for path in paths}),
        "num_destinations": len({str(path.get("To", "")) for path in paths}),
    }
