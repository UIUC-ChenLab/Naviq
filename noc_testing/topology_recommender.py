#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence


WORKSPACE = Path(__file__).resolve().parent
REPO_ROOT = WORKSPACE.parent

CONFIDENCE_ORDER = {"strong": 0, "moderate": 1, "weak": 2}
CLASS_ORDER = {
    "route_overlap_bottleneck": 0,
    "destination_convergence_bottleneck": 1,
    "memory_path_contention": 2,
    "path_length_bottleneck": 3,
    "endpoint_imbalance_bottleneck": 4,
    "streaming_datapath_backpressure": 5,
    "inconclusive": 6,
}

MEASURED_KEYS = (
    "worst_p99_cycles",
    "worst_p95_cycles",
    "mean_p99_cycles",
    "mean_bw_MBps",
    "min_jfi",
    "max_fairness_maxmin",
    "delta_worst_p99_vs_baseline",
    "delta_mean_bw_vs_baseline",
    "delta_min_jfi_vs_baseline",
    "hotspot_top1_share",
    "hotspot_concentration_ratio",
    "occupancy_pressure_ratio",
    "occ_peak_ratio",
    "queue_peak_depth",
    "queue_credit_share",
    "queue_data_vc_share",
    "credit_share_margin",
    "widespread_activity_ratio",
    "endpoint_bw_imbalance_ratio",
    "endpoint_latency_imbalance_ratio",
)

PAIRWISE_KEYS = (
    "pairwise_peer_name",
    "pairwise_route_overlap_ratio",
    "pairwise_worst_p99_delta",
    "pairwise_hotspot_top1_delta",
    "pairwise_avg_hop_delta",
    "pairwise_mean_bw_delta",
)

ROUTE_KEYS = (
    "avg_hop_count",
    "max_hop_count",
    "route_overlap_score",
    "average_pairwise_route_overlap",
    "fraction_of_route_resources_shared_by_2_or_more_flows",
    "shared_resource_count",
    "max_flows_on_any_resource",
    "top_shared_resource_id",
    "num_sources",
    "num_destinations",
    "num_flows",
)

ENDPOINT_KEYS = (
    "worst_p99_endpoint",
    "worst_p99_metric",
    "worst_p99_value",
    "lowest_bw_endpoint",
    "lowest_bw_metric",
    "lowest_bw_value",
    "highest_latency_endpoint",
    "highest_latency_metric",
    "highest_latency_value",
    "fairness_driver",
    "fairness_low_endpoint",
    "fairness_high_endpoint",
    "fairness_pair_metric",
)

HOTSPOT_KEYS = (
    "hotspot_primary_location",
    "hotspot_primary_source",
    "occ_top_nps_name",
    "queue_top_router_name",
    "fairness_risk",
    "localized_hotspot_risk",
    "widespread_congestion_risk",
    "tail_latency_risk",
    "credit_pressure_risk",
)


@dataclass(frozen=True)
class Diagnosis:
    classification: str
    confidence: str
    evidence_fields_used: List[str]
    recommended_action: str
    follow_up_experiment: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "classification": self.classification,
            "confidence": self.confidence,
            "evidence_fields_used": self.evidence_fields_used,
            "recommended_action": self.recommended_action,
            "follow_up_experiment": self.follow_up_experiment,
        }


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _float_or_none(value: Any) -> Optional[float]:
    text = _clean(value)
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int_or_none(value: Any) -> Optional[int]:
    text = _clean(value)
    if text == "":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _boolish(value: Any) -> bool:
    return _clean(value).lower() in {"1", "true", "yes", "y"}


def _fmt(value: Any, digits: int = 3) -> str:
    number = _float_or_none(value)
    if number is None:
        return _clean(value) or "n/a"
    return f"{number:.{digits}f}"


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _resolve_path(path_text: str, bases: Sequence[Path]) -> Optional[Path]:
    text = _clean(path_text)
    if not text:
        return None
    path = Path(text)
    candidates = [path] if path.is_absolute() else []
    if not path.is_absolute():
        candidates.extend(base / path for base in bases)
    candidates.extend((WORKSPACE / path, REPO_ROOT / path, Path.cwd() / path))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (bases[0] / path).resolve() if bases else path.resolve()


def _load_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def _detect_route_metrics_csv(summary_csv: Path) -> Optional[Path]:
    analysis_dir = summary_csv.parent
    candidates = [
        analysis_dir.parent / "route_metrics",
        analysis_dir.parent.parent / "route_metrics",
    ]
    for candidate_dir in candidates:
        if not candidate_dir.exists():
            continue
        matches = sorted(candidate_dir.glob("*route_metrics.csv"))
        if matches:
            return matches[0].resolve()
    return None


def _merge_route_metrics(
    rows: List[Dict[str, str]], route_metrics_csv: Optional[Path]
) -> List[Dict[str, str]]:
    if route_metrics_csv is None or not route_metrics_csv.exists():
        return rows

    metrics_rows = _read_csv(route_metrics_csv)
    by_name = {
        _clean(row.get("case_name") or row.get("name")): row
        for row in metrics_rows
        if _clean(row.get("case_name") or row.get("name"))
    }
    merged = []
    for row in rows:
        name = _clean(row.get("name") or row.get("case_name"))
        extra = by_name.get(name, {})
        combined = dict(row)
        for key, value in extra.items():
            if _clean(combined.get(key)) == "":
                combined[key] = value
        merged.append(combined)
    return merged


def _percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * fraction))
    return ordered[index]


def _numeric_values(rows: Sequence[Dict[str, str]], key: str) -> List[float]:
    return [v for v in (_float_or_none(row.get(key)) for row in rows) if v is not None]


def _global_stats(rows: Sequence[Dict[str, str]]) -> Dict[str, Optional[float]]:
    route_scores = _numeric_values(rows, "route_overlap_score")
    hop_counts = _numeric_values(rows, "avg_hop_count")
    p99_values = _numeric_values(rows, "worst_p99_cycles")
    return {
        "route_overlap_median": median(route_scores) if route_scores else None,
        "route_overlap_p75": _percentile(route_scores, 0.75),
        "avg_hop_median": median(hop_counts) if hop_counts else None,
        "avg_hop_p75": _percentile(hop_counts, 0.75),
        "worst_p99_median": median(p99_values) if p99_values else None,
        "worst_p99_p75": _percentile(p99_values, 0.75),
    }


def _component_id(endpoint_ref: str) -> str:
    return endpoint_ref.split(".", 1)[0]


def _component_type(component: Dict[str, Any], port: Dict[str, Any]) -> str:
    haystack = " ".join(
        [
            str(component.get("node_type", "")),
            str(component.get("type", "")),
            str(port.get("type", "")),
            str(port.get("physical_type", "")),
        ]
    ).lower()
    if "hbm" in haystack:
        return "hbm"
    if "ddr" in haystack:
        return "ddr"
    if "axis" in haystack:
        return "axis"
    if "bram" in haystack:
        return "bram"
    return "generic"


def _connection_metadata(path: Optional[Path]) -> Dict[str, Any]:
    data = _load_json(path)
    if not data:
        return {
            "connection_json": str(path) if path else "",
            "protocols": [],
            "target_fan_in": {},
            "max_target_fan_in": None,
            "memory_targets": [],
            "has_streaming_protocol": False,
        }

    protocols = set()
    target_fan_in: Dict[str, int] = {}
    target_types: Dict[str, str] = {}
    memory_targets = set()

    if data.get("kind") == "naviq.connections":
        components = data.get("components", {})
        for component_id, component in components.items():
            for port_name, port in component.get("ports", {}).items():
                protocol = _clean(port.get("protocol")).lower()
                if protocol:
                    protocols.add(protocol)
                endpoint = f"{component_id}.{port_name}"
                target_types[endpoint] = _component_type(component, port)

        for entry in data.get("connections", []):
            target = _clean(entry.get("to"))
            if not target:
                continue
            target_fan_in[target] = target_fan_in.get(target, 0) + 1
            if target_types.get(target) in {"hbm", "ddr"}:
                memory_targets.add(target)
    else:
        for key, protocol in (
            ("aximm_masters", "aximm"),
            ("aximm_slaves", "aximm"),
            ("axis_masters", "axis"),
            ("axis_slaves", "axis"),
        ):
            if data.get(key):
                protocols.add(protocol)
        for master, targets in data.get("connections", {}).items():
            for target_entry in targets:
                target = _clean(target_entry.get("to"))
                if not target:
                    continue
                target_fan_in[target] = target_fan_in.get(target, 0) + 1
                low = target.lower()
                if "hbm" in low or "ddr" in low:
                    memory_targets.add(target)

    return {
        "connection_json": str(path) if path else "",
        "protocols": sorted(protocols),
        "target_fan_in": dict(sorted(target_fan_in.items())),
        "max_target_fan_in": max(target_fan_in.values(), default=None),
        "memory_targets": sorted(memory_targets),
        "has_streaming_protocol": "axis" in protocols,
    }


def _placement_metadata(path: Optional[Path]) -> Dict[str, Any]:
    data = _load_json(path)
    if not data:
        return {"placement_json": str(path) if path else "", "placements": {}}
    placements = {}
    if data.get("kind") == "naviq.placement":
        placements = dict(data.get("placements", {}))
    else:
        placements.update(data.get("master_placement", {}))
        placements.update(data.get("slave_placement", {}))
    return {
        "placement_json": str(path) if path else "",
        "placements": dict(sorted(placements.items())),
    }


def _physical_endpoint_type(name: str) -> str:
    if "NMU" in name:
        return "nmu"
    if "NSU" in name:
        return "nsu"
    if "DDR" in name:
        return "ddr"
    if "HBM" in name:
        return "hbm"
    if "NPS" in name:
        return "nps"
    return "other"


def _fabric_metadata(
    fabric_connections: Optional[Path], fabric_endpoints: Optional[Path]
) -> Dict[str, Any]:
    connections_data = _load_json(fabric_connections)
    endpoints_data = _load_json(fabric_endpoints)

    nodes = set()
    edges = 0
    for entry in connections_data.get("Connections", []):
        source = _clean(entry.get("Source"))
        target = _clean(entry.get("Target"))
        if source:
            nodes.add(source)
        if target:
            nodes.add(target)
        if source and target:
            edges += 1

    endpoint_type_counts: Dict[str, int] = {}
    for component in endpoints_data.get("Components", []):
        endpoint_type = _physical_endpoint_type(_clean(component.get("Name")))
        endpoint_type_counts[endpoint_type] = endpoint_type_counts.get(endpoint_type, 0) + 1

    return {
        "fabric_connections": str(fabric_connections or ""),
        "fabric_endpoints": str(fabric_endpoints or ""),
        "fabric_node_count": len(nodes) if nodes else None,
        "fabric_edge_count": edges if edges else None,
        "physical_endpoint_type_counts": dict(sorted(endpoint_type_counts.items())),
    }


def _select_fields(row: Dict[str, str], keys: Iterable[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if _clean(value) == "":
            continue
        number = _float_or_none(value)
        if number is not None:
            out[key] = number
        elif _clean(value).lower() in {"true", "false"}:
            out[key] = _boolish(value)
        else:
            out[key] = _clean(value)
    return out


def _lower_overlap_peer(
    row: Dict[str, str], rows: Sequence[Dict[str, str]]
) -> Optional[Dict[str, str]]:
    current_score = _float_or_none(row.get("route_overlap_score"))
    if current_score is None:
        return None

    pattern = _clean(row.get("pattern_family"))
    connection = _clean(row.get("connection_json"))
    placement = _clean(row.get("placement_json"))

    candidates = []
    for candidate in rows:
        if candidate is row:
            continue
        candidate_score = _float_or_none(candidate.get("route_overlap_score"))
        if candidate_score is None or candidate_score >= current_score:
            continue
        same_family = pattern and _clean(candidate.get("pattern_family")) == pattern
        same_topology = (
            connection
            and placement
            and _clean(candidate.get("connection_json")) == connection
            and _clean(candidate.get("placement_json")) == placement
        )
        if same_family or same_topology:
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda item: _float_or_none(item.get("route_overlap_score")) or 0)


def _row_context(
    row: Dict[str, str],
    rows: Sequence[Dict[str, str]],
    stats: Dict[str, Optional[float]],
    bases: Sequence[Path],
) -> Dict[str, Any]:
    connection_path = _resolve_path(_clean(row.get("connection_json")), bases)
    placement_path = _resolve_path(_clean(row.get("placement_json")), bases)
    peer = _lower_overlap_peer(row, rows)
    peer_context = {}
    if peer is not None:
        peer_context = {
            "name": _clean(peer.get("name") or peer.get("case_name")),
            "route_overlap_score": _float_or_none(peer.get("route_overlap_score")),
            "avg_hop_count": _float_or_none(peer.get("avg_hop_count")),
            "worst_p99_cycles": _float_or_none(peer.get("worst_p99_cycles")),
            "hotspot_top1_share": _float_or_none(peer.get("hotspot_top1_share")),
            "mean_bw_MBps": _float_or_none(peer.get("mean_bw_MBps")),
        }

    return {
        "name": _clean(row.get("name") or row.get("case_name")),
        "run_tag": _clean(row.get("run_tag")),
        "plan_row_index": _clean(row.get("plan_row_index")),
        "pattern_family": _clean(row.get("pattern_family")),
        "overlap_class": _clean(row.get("overlap_class")),
        "topology_shape": _clean(row.get("topology_shape")),
        "measured_metrics": _select_fields(row, MEASURED_KEYS),
        "route_metadata": _select_fields(row, ROUTE_KEYS),
        "endpoint_metrics": _select_fields(row, ENDPOINT_KEYS),
        "hotspot_locations": _select_fields(row, HOTSPOT_KEYS),
        "connection_metadata": _connection_metadata(connection_path),
        "placement_metadata": _placement_metadata(placement_path),
        "lower_overlap_peer": peer_context,
        "population_thresholds": stats,
    }


def _field(name: str, value: Any) -> str:
    return f"{name}={_fmt(value)}"


def _supporting_fields(pairs: Sequence[tuple[str, Any]]) -> List[str]:
    return [_field(name, value) for name, value in pairs if _clean(value) != ""]


def _confidence(count: int) -> str:
    if count >= 3:
        return "strong"
    if count == 2:
        return "moderate"
    return "weak"


def _is_single_destination_incast(context: Dict[str, Any]) -> bool:
    route = context.get("route_metadata", {})
    connection = context.get("connection_metadata", {})
    num_sources = _int_or_none(route.get("num_sources"))
    num_destinations = _int_or_none(route.get("num_destinations"))
    max_target_fan_in = _int_or_none(connection.get("max_target_fan_in"))
    return (
        num_destinations == 1
        and num_sources is not None
        and num_sources > 1
        and max_target_fan_in is not None
        and max_target_fan_in > 1
    )


def _pairwise_route_comparison(context: Dict[str, Any]) -> Dict[str, Any]:
    metrics = context.get("measured_metrics", {})
    route = context.get("route_metadata", {})
    peer = context.get("lower_overlap_peer", {})
    if not peer:
        return {}

    high_overlap = _float_or_none(route.get("route_overlap_score"))
    low_overlap = _float_or_none(peer.get("route_overlap_score"))
    high_hop = _float_or_none(route.get("avg_hop_count"))
    low_hop = _float_or_none(peer.get("avg_hop_count"))
    high_p99 = _float_or_none(metrics.get("worst_p99_cycles"))
    low_p99 = _float_or_none(peer.get("worst_p99_cycles"))
    high_hotspot = _float_or_none(metrics.get("hotspot_top1_share"))
    low_hotspot = _float_or_none(peer.get("hotspot_top1_share"))
    high_bw = _float_or_none(metrics.get("mean_bw_MBps"))
    low_bw = _float_or_none(peer.get("mean_bw_MBps"))

    return {
        "pairwise_peer_name": peer.get("name", ""),
        "pairwise_route_overlap_ratio": (
            high_overlap / low_overlap
            if high_overlap is not None and low_overlap and low_overlap > 0
            else None
        ),
        "pairwise_worst_p99_delta": (
            high_p99 - low_p99
            if high_p99 is not None and low_p99 is not None
            else None
        ),
        "pairwise_hotspot_top1_delta": (
            high_hotspot - low_hotspot
            if high_hotspot is not None and low_hotspot is not None
            else None
        ),
        "pairwise_avg_hop_delta": (
            high_hop - low_hop if high_hop is not None and low_hop is not None else None
        ),
        "pairwise_mean_bw_delta": (
            high_bw - low_bw if high_bw is not None and low_bw is not None else None
        ),
    }


def _diagnosis_priority(context: Dict[str, Any], diagnosis: Diagnosis) -> tuple:
    class_order = dict(CLASS_ORDER)
    if _is_single_destination_incast(context):
        class_order["destination_convergence_bottleneck"] = -1
        class_order["route_overlap_bottleneck"] = 1
    return (
        CONFIDENCE_ORDER.get(diagnosis.confidence, 9),
        class_order.get(diagnosis.classification, 9),
    )


def diagnose_config(context: Dict[str, Any]) -> List[Diagnosis]:
    metrics = context["measured_metrics"]
    route = context["route_metadata"]
    endpoint = context["endpoint_metrics"]
    hotspot = context["hotspot_locations"]
    connection = context["connection_metadata"]
    peer = context.get("lower_overlap_peer", {})
    thresholds = context["population_thresholds"]

    diagnoses: List[Diagnosis] = []

    route_score = _float_or_none(route.get("route_overlap_score"))
    pairwise_overlap_metric = _float_or_none(
        route.get("average_pairwise_route_overlap")
    )
    shared_fraction = _float_or_none(
        route.get("fraction_of_route_resources_shared_by_2_or_more_flows")
    )
    max_flows = _float_or_none(route.get("max_flows_on_any_resource"))
    hotspot_share = _float_or_none(metrics.get("hotspot_top1_share"))
    worst_p99 = _float_or_none(metrics.get("worst_p99_cycles"))
    delta_p99 = _float_or_none(metrics.get("delta_worst_p99_vs_baseline"))
    peer_p99 = _float_or_none(peer.get("worst_p99_cycles"))
    peer_hotspot = _float_or_none(peer.get("hotspot_top1_share"))
    peer_overlap = _float_or_none(peer.get("route_overlap_score"))
    peer_avg_hop = _float_or_none(peer.get("avg_hop_count"))
    peer_bw = _float_or_none(peer.get("mean_bw_MBps"))
    p99_p75 = _float_or_none(thresholds.get("worst_p99_p75"))
    pairwise_comparison = _pairwise_route_comparison(context)
    pairwise_overlap_ratio = _float_or_none(
        pairwise_comparison.get("pairwise_route_overlap_ratio")
    )
    pairwise_p99_delta = _float_or_none(
        pairwise_comparison.get("pairwise_worst_p99_delta")
    )
    pairwise_hotspot_delta = _float_or_none(
        pairwise_comparison.get("pairwise_hotspot_top1_delta")
    )
    single_destination_incast = _is_single_destination_incast(context)

    route_high = (
        (route_score is not None and route_score >= 0.05)
        or (pairwise_overlap_metric is not None and pairwise_overlap_metric >= 0.025)
        or (shared_fraction is not None and shared_fraction >= 0.10)
        or (max_flows is not None and max_flows >= 3)
        or context.get("overlap_class") == "high_overlap"
    )
    route_perf_degraded = (
        (delta_p99 is not None and delta_p99 >= 10)
        or (
            peer_p99 is not None
            and worst_p99 is not None
            and worst_p99 - peer_p99 >= 10
        )
        or (p99_p75 is not None and worst_p99 is not None and worst_p99 >= p99_p75)
    )
    route_hotspot = (
        (hotspot_share is not None and hotspot_share >= 0.12)
        or _boolish(hotspot.get("localized_hotspot_risk"))
        or (
            peer_hotspot is not None
            and hotspot_share is not None
            and hotspot_share - peer_hotspot >= 0.05
        )
    )
    if route_high:
        pairwise_strong = (
            pairwise_overlap_ratio is not None
            and pairwise_overlap_ratio >= 2.0
            and (
                (pairwise_p99_delta is not None and pairwise_p99_delta >= 10)
                or (
                    pairwise_hotspot_delta is not None
                    and pairwise_hotspot_delta >= 0.05
                )
            )
        )
        pairwise_modest = bool(
            pairwise_overlap_ratio is not None and pairwise_overlap_ratio > 1.0
        )
        if pairwise_strong:
            route_confidence = "strong"
            route_action = (
                "Prefer low-overlap or path-diverse routing for this workload, "
                "and avoid the listed top shared route resources."
            )
            route_follow_up = (
                "Rerun the low-overlap/path-diverse peer at the same offered load "
                "to confirm the pairwise P99 and hotspot deltas hold across repeats."
            )
        elif pairwise_modest:
            route_confidence = "moderate"
            route_action = (
                "Treat route overlap as a hotspot-structure risk and prefer the "
                "lower-overlap route when it does not add meaningful path length."
            )
            route_follow_up = (
                "Repeat the paired route comparison; route overlap appears to affect "
                "hotspot structure, but the performance impact is modest for this workload."
            )
        elif single_destination_incast:
            route_confidence = "weak"
            route_action = (
                "Treat route overlap as a secondary amplifier after addressing "
                "single-destination convergence."
            )
            route_follow_up = (
                "After distributing target traffic, rerun low-overlap and high-overlap "
                "routes to isolate the remaining routing contribution."
            )
        else:
            support = sum(
                [
                    bool(route_perf_degraded),
                    bool(route_hotspot),
                    bool(_clean(route.get("top_shared_resource_id"))),
                ]
            )
            route_confidence = "moderate" if support >= 2 else "weak"
            route_action = (
                "Prefer lower-overlap routing when available, especially around "
                "the listed shared route resource."
            )
            route_follow_up = (
                "Create a low-overlap/path-diverse paired route and compare "
                "worst_p99_cycles, hotspot_top1_share, and mean_bw_MBps."
            )
        if single_destination_incast and not pairwise_strong:
            route_confidence = "weak" if route_confidence == "moderate" else route_confidence
        diagnoses.append(
            Diagnosis(
                "route_overlap_bottleneck",
                route_confidence,
                _supporting_fields(
                    [
                        ("route_overlap_score", route_score),
                        ("average_pairwise_route_overlap", pairwise_overlap_metric),
                        (
                            "fraction_of_route_resources_shared_by_2_or_more_flows",
                            shared_fraction,
                        ),
                        ("max_flows_on_any_resource", max_flows),
                        ("top_shared_resource_id", route.get("top_shared_resource_id")),
                        ("hotspot_top1_share", hotspot_share),
                        ("worst_p99_cycles", worst_p99),
                        ("lower_overlap_peer.route_overlap_score", peer_overlap),
                        ("lower_overlap_peer.avg_hop_count", peer_avg_hop),
                        ("lower_overlap_peer.worst_p99_cycles", peer_p99),
                        ("lower_overlap_peer.hotspot_top1_share", peer_hotspot),
                        ("lower_overlap_peer.mean_bw_MBps", peer_bw),
                        ("pairwise_route_overlap_ratio", pairwise_overlap_ratio),
                        ("pairwise_worst_p99_delta", pairwise_p99_delta),
                        ("pairwise_hotspot_top1_delta", pairwise_hotspot_delta),
                    ]
                ),
                route_action,
                route_follow_up,
            )
        )

    avg_hop = _float_or_none(route.get("avg_hop_count"))
    max_hop = _float_or_none(route.get("max_hop_count"))
    hop_p75 = _float_or_none(thresholds.get("avg_hop_p75"))
    hop_median = _float_or_none(thresholds.get("avg_hop_median"))
    hop_high = avg_hop is not None and (
        (
            hop_p75 is not None
            and hop_median is not None
            and hop_p75 > hop_median
            and avg_hop >= hop_p75
        )
        or (hop_median is not None and avg_hop >= hop_median * 1.15)
        or avg_hop >= 32
    )
    if hop_high:
        support = sum(
            [
                bool(worst_p99 is not None and p99_p75 is not None and worst_p99 >= p99_p75),
                bool(not route_high or (route_score is not None and route_score < 0.05)),
                bool(max_hop is not None and avg_hop is not None and max_hop >= avg_hop),
            ]
        )
        diagnoses.append(
            Diagnosis(
                "path_length_bottleneck",
                _confidence(support),
                _supporting_fields(
                    [
                        ("avg_hop_count", avg_hop),
                        ("max_hop_count", max_hop),
                        ("population_thresholds.avg_hop_p75", hop_p75),
                        ("worst_p99_cycles", worst_p99),
                    ]
                ),
                "Move sources closer to their targets, or test a shorter source-target placement while keeping routing policy fixed.",
                "Generate a placement with shorter source-target distances and rerun the same bandwidth point to isolate path length from route overlap.",
            )
        )

    num_sources = _int_or_none(route.get("num_sources"))
    num_destinations = _int_or_none(route.get("num_destinations"))
    num_flows = _int_or_none(route.get("num_flows"))
    max_target_fan_in = _int_or_none(connection.get("max_target_fan_in"))
    destination_convergence = (
        (num_sources is not None and num_destinations == 1 and num_sources > 1)
        or (max_target_fan_in is not None and max_target_fan_in >= 2)
        or (
            num_flows is not None
            and num_destinations is not None
            and num_destinations > 0
            and num_flows / num_destinations >= 2
        )
    )
    if destination_convergence:
        support = sum(
            [
                bool(hotspot_share is not None and hotspot_share >= 0.12),
                bool(worst_p99 is not None and p99_p75 is not None and worst_p99 >= p99_p75),
                bool(max_target_fan_in is not None and max_target_fan_in >= 2),
            ]
        )
        diagnoses.append(
            Diagnosis(
                "destination_convergence_bottleneck",
                _confidence(support),
                _supporting_fields(
                    [
                        ("num_sources", num_sources),
                        ("num_destinations", num_destinations),
                        ("num_flows", num_flows),
                        ("connection_metadata.max_target_fan_in", max_target_fan_in),
                        ("hotspot_top1_share", hotspot_share),
                        ("hotspot_primary_location", hotspot.get("hotspot_primary_location")),
                    ]
                ),
                (
                    "Because all active sources converge on one target, "
                    "destination-side convergence is the primary bottleneck. "
                    "Distribute the target traffic or split the destination-side access path."
                    if single_destination_incast
                    else "Distribute targets instead of converging this traffic on one destination-side region."
                ),
                "Compare this single-target/converged case against a distributed-target placement with the same offered bandwidth.",
            )
        )

    latency_imbalance = _float_or_none(metrics.get("endpoint_latency_imbalance_ratio"))
    bw_imbalance = _float_or_none(metrics.get("endpoint_bw_imbalance_ratio"))
    min_jfi = _float_or_none(metrics.get("min_jfi"))
    fairness_risk = _boolish(hotspot.get("fairness_risk"))
    endpoint_imbalance = (
        (latency_imbalance is not None and latency_imbalance >= 1.25)
        or (bw_imbalance is not None and bw_imbalance >= 1.25)
        or (min_jfi is not None and min_jfi < 0.90)
        or fairness_risk
    )
    if endpoint_imbalance:
        if (
            latency_imbalance is not None
            and latency_imbalance >= 1.75
            and min_jfi is not None
            and min_jfi < 0.95
        ):
            endpoint_confidence = "strong"
        elif (
            latency_imbalance is not None
            and latency_imbalance >= 1.25
            or bw_imbalance is not None
            and bw_imbalance >= 1.25
            or min_jfi is not None
            and min_jfi < 0.95
        ):
            endpoint_confidence = "moderate"
        else:
            endpoint_confidence = "weak"
        latency_driven_note = (
            " The endpoint imbalance is primarily latency-driven because "
            "endpoint_bw_imbalance_ratio is approximately 1.0 while "
            "endpoint_latency_imbalance_ratio is elevated."
            if bw_imbalance is not None
            and bw_imbalance <= 1.01
            and latency_imbalance is not None
            and latency_imbalance >= 1.25
            else ""
        )
        diagnoses.append(
            Diagnosis(
                "endpoint_imbalance_bottleneck",
                endpoint_confidence,
                _supporting_fields(
                    [
                        ("endpoint_latency_imbalance_ratio", latency_imbalance),
                        ("endpoint_bw_imbalance_ratio", bw_imbalance),
                        ("min_jfi", min_jfi),
                        ("worst_p99_endpoint", endpoint.get("worst_p99_endpoint")),
                        ("lowest_bw_endpoint", endpoint.get("lowest_bw_endpoint")),
                        ("fairness_pair_metric", endpoint.get("fairness_pair_metric")),
                    ]
                ),
                "Investigate endpoint remapping or a more balanced source-target assignment."
                + latency_driven_note,
                "Test a candidate endpoint reassignment while preserving traffic parameters, then compare endpoint_latency_imbalance_ratio and endpoint_bw_imbalance_ratio.",
            )
        )

    memory_targets = connection.get("memory_targets", [])
    name_text = f"{context.get('name', '')} {connection.get('connection_json', '')}".lower()
    has_memory = bool(memory_targets) or "hbm" in name_text or "ddr" in name_text
    memory_contention = has_memory and (
        destination_convergence
        or route_high
        or (hotspot_share is not None and hotspot_share >= 0.12)
        or (bw_imbalance is not None and bw_imbalance >= 1.20)
        or (delta_p99 is not None and delta_p99 >= 10)
    )
    if memory_contention:
        support = sum(
            [
                bool(memory_targets),
                bool(destination_convergence),
                bool(hotspot_share is not None and hotspot_share >= 0.12),
                bool(worst_p99 is not None and p99_p75 is not None and worst_p99 >= p99_p75),
            ]
        )
        diagnoses.append(
            Diagnosis(
                "memory_path_contention",
                _confidence(support),
                _supporting_fields(
                    [
                        ("connection_metadata.memory_targets", ",".join(memory_targets)),
                        ("connection_metadata.max_target_fan_in", max_target_fan_in),
                        ("hotspot_top1_share", hotspot_share),
                        ("worst_p99_cycles", worst_p99),
                        ("mean_bw_MBps", metrics.get("mean_bw_MBps")),
                    ]
                ),
                "Spread traffic across available DDR/HBM controllers or ports where the topology supports it.",
                "Run a memory-target distribution sweep at the same offered bandwidth and compare p99 latency, achieved bandwidth, and hotspot location.",
            )
        )

    protocols = set(connection.get("protocols", []))
    tg_mode = str(metrics.get("tg_mode", "")).lower()
    credit_margin = _float_or_none(metrics.get("credit_share_margin"))
    queue_peak = _float_or_none(metrics.get("queue_peak_depth"))
    data_vc_share = _float_or_none(metrics.get("queue_data_vc_share"))
    streaming_case = (
        "axis" in protocols
        or connection.get("has_streaming_protocol")
        or "axis" in name_text
        or "stream" in tg_mode
    )
    streaming_pressure = streaming_case and (
        _boolish(hotspot.get("credit_pressure_risk"))
        or (credit_margin is not None and credit_margin >= 0.15)
        or (queue_peak is not None and queue_peak >= 4)
        or (data_vc_share is not None and data_vc_share >= 0.70)
    )
    if streaming_pressure:
        support = sum(
            [
                bool("axis" in protocols or connection.get("has_streaming_protocol")),
                bool(queue_peak is not None and queue_peak >= 4),
                bool(credit_margin is not None and credit_margin >= 0.15),
                bool(data_vc_share is not None and data_vc_share >= 0.70),
            ]
        )
        diagnoses.append(
            Diagnosis(
                "streaming_datapath_backpressure",
                _confidence(support),
                _supporting_fields(
                    [
                        ("connection_metadata.protocols", ",".join(sorted(protocols))),
                        ("queue_peak_depth", queue_peak),
                        ("credit_share_margin", credit_margin),
                        ("queue_data_vc_share", data_vc_share),
                        ("queue_top_router_name", hotspot.get("queue_top_router_name")),
                    ]
                ),
                "Test downstream sink/FIFO placement or reduce convergence on the streaming datapath.",
                "Rerun with queue tracing enabled while moving the sink/FIFO endpoint or adding a less converged streaming path.",
            )
        )

    if not diagnoses:
        diagnoses.append(
            Diagnosis(
                "inconclusive",
                "weak",
                _supporting_fields(
                    [
                        ("worst_p99_cycles", worst_p99),
                        ("route_overlap_score", route_score),
                        ("avg_hop_count", avg_hop),
                        ("hotspot_top1_share", hotspot_share),
                        ("min_jfi", min_jfi),
                    ]
                ),
                "Do not make a firm routing or placement change from this run alone.",
                "Run a paired low-overlap/path-diverse and shorter-placement comparison with hotspot tracing enabled.",
            )
        )

    return sorted(
        diagnoses,
        key=lambda item: _diagnosis_priority(context, item),
    )


def _summary_sentence(context: Dict[str, Any], primary: Diagnosis) -> str:
    name = context.get("name", "")
    pairwise = _pairwise_route_comparison(context)
    if primary.classification == "destination_convergence_bottleneck":
        return (
            f"`{name}` is primarily limited by destination-side convergence: "
            "all active sources converge on one target, so routing changes should "
            "be treated as secondary until target traffic is distributed."
        )
    if primary.classification == "route_overlap_bottleneck":
        ratio = _float_or_none(pairwise.get("pairwise_route_overlap_ratio"))
        p99_delta = _float_or_none(pairwise.get("pairwise_worst_p99_delta"))
        hotspot_delta = _float_or_none(pairwise.get("pairwise_hotspot_top1_delta"))
        if ratio is not None:
            return (
                f"`{name}` shows a route-overlap effect versus "
                f"`{pairwise.get('pairwise_peer_name')}`: overlap changes by "
                f"{_fmt(ratio)}x, worst P99 changes by {_fmt(p99_delta)} cycles, "
                f"and hotspot top1 share changes by {_fmt(hotspot_delta)}."
            )
        return (
            f"`{name}` has elevated shared-route use; prefer lower-overlap "
            "routing when a paired alternative is available."
        )
    if primary.classification == "endpoint_imbalance_bottleneck":
        metrics = context.get("measured_metrics", {})
        return (
            f"`{name}` shows endpoint imbalance, mainly in latency when "
            f"endpoint_latency_imbalance_ratio={_fmt(metrics.get('endpoint_latency_imbalance_ratio'))} "
            f"and endpoint_bw_imbalance_ratio={_fmt(metrics.get('endpoint_bw_imbalance_ratio'))}."
        )
    if primary.classification == "path_length_bottleneck":
        route = context.get("route_metadata", {})
        return (
            f"`{name}` has long measured paths: avg_hop_count="
            f"{_fmt(route.get('avg_hop_count'))} and max_hop_count="
            f"{_fmt(route.get('max_hop_count'))}."
        )
    return f"`{name}` is classified as `{primary.classification}`."


def _enrich_context_with_recommendation(
    context: Dict[str, Any], diagnoses: Sequence[Diagnosis]
) -> None:
    primary = diagnoses[0]
    secondary = [diagnosis.classification for diagnosis in diagnoses[1:]]
    pairwise = _pairwise_route_comparison(context)
    context["deterministic_diagnoses"] = [
        diagnosis.as_dict() for diagnosis in diagnoses
    ]
    context["primary_diagnosis"] = primary.classification
    context["secondary_diagnoses"] = secondary
    context["recommendation_confidence"] = primary.confidence
    context["recommendation_summary"] = _summary_sentence(context, primary)
    context["recommended_action"] = primary.recommended_action
    context["follow_up_experiment"] = primary.follow_up_experiment
    for key in PAIRWISE_KEYS:
        context[key] = pairwise.get(key)


def build_evidence_bundle(
    summary_csv: Path,
    route_metrics_csv: Optional[Path] = None,
    fabric_connections: Optional[Path] = None,
    fabric_endpoints: Optional[Path] = None,
) -> Dict[str, Any]:
    detected_route_metrics = route_metrics_csv or _detect_route_metrics_csv(summary_csv)
    rows = _merge_route_metrics(_read_csv(summary_csv), detected_route_metrics)
    bases = [summary_csv.parent, WORKSPACE, REPO_ROOT, Path.cwd()]
    stats = _global_stats(rows)
    fabric = _fabric_metadata(fabric_connections, fabric_endpoints)

    configs = []
    for row in rows:
        context = _row_context(row, rows, stats, bases)
        diagnoses = diagnose_config(context)
        _enrich_context_with_recommendation(context, diagnoses)
        configs.append(context)

    return {
        "inputs": {
            "summary_csv": str(summary_csv),
            "route_metrics_csv": str(detected_route_metrics or ""),
            "fabric_connections": str(fabric_connections or ""),
            "fabric_endpoints": str(fabric_endpoints or ""),
        },
        "policy": {
            "evidence_is_authoritative": True,
            "unsupported_ideas_must_be_follow_up_experiments": True,
        },
        "fabric_metadata": fabric,
        "configs": configs,
    }


def _diagnosis_sort_key(config: Dict[str, Any], diagnosis: Dict[str, Any]) -> tuple:
    metrics = config.get("measured_metrics", {})
    p99 = _float_or_none(metrics.get("worst_p99_cycles")) or 0.0
    class_order = dict(CLASS_ORDER)
    if _is_single_destination_incast(config):
        class_order["destination_convergence_bottleneck"] = -1
        class_order["route_overlap_bottleneck"] = 1
    return (
        CONFIDENCE_ORDER.get(diagnosis.get("confidence"), 9),
        class_order.get(diagnosis.get("classification"), 9),
        -p99,
        config.get("name", ""),
    )


def _diagnosis_for_config(
    config: Dict[str, Any], classification: str
) -> Optional[Dict[str, Any]]:
    for diagnosis in config.get("deterministic_diagnoses", []):
        if diagnosis.get("classification") == classification:
            return diagnosis
    return None


def _pairwise_recommendation(config: Dict[str, Any]) -> str:
    p99_delta = _float_or_none(config.get("pairwise_worst_p99_delta"))
    hotspot_delta = _float_or_none(config.get("pairwise_hotspot_top1_delta"))
    ratio = _float_or_none(config.get("pairwise_route_overlap_ratio"))
    if ratio is None:
        return "n/a"
    if ratio >= 2.0 and (
        (p99_delta is not None and p99_delta >= 10)
        or (hotspot_delta is not None and hotspot_delta >= 0.05)
    ):
        return "prefer low-overlap/path-diverse routing"
    if ratio > 1.0:
        return "route overlap changes hotspot structure; performance impact is modest"
    return "no route-overlap action from this pair"


def _pairwise_table(configs: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "| pattern | low overlap | high overlap | avg hop delta | overlap ratio | P99 delta | hotspot top1 delta | mean BW delta | recommendation |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    rows = [
        config
        for config in configs
        if _clean(config.get("pairwise_peer_name"))
        and _float_or_none(config.get("pairwise_route_overlap_ratio")) is not None
    ]
    if not rows:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | no paired lower-overlap cases found |")
        return "\n".join(lines)
    for config in sorted(rows, key=lambda item: (item.get("pattern_family", ""), item.get("name", ""))):
        lines.append(
            "| {pattern} | {low} | {high} | {hop_delta} | {ratio} | {p99_delta} | {hotspot_delta} | {bw_delta} | {rec} |".format(
                pattern=config.get("pattern_family") or config.get("topology_shape") or "n/a",
                low=config.get("pairwise_peer_name") or "n/a",
                high=config.get("name") or "n/a",
                hop_delta=_fmt(config.get("pairwise_avg_hop_delta")),
                ratio=_fmt(config.get("pairwise_route_overlap_ratio")),
                p99_delta=_fmt(config.get("pairwise_worst_p99_delta")),
                hotspot_delta=_fmt(config.get("pairwise_hotspot_top1_delta")),
                bw_delta=_fmt(config.get("pairwise_mean_bw_delta")),
                rec=_pairwise_recommendation(config),
            )
        )
    return "\n".join(lines)


def _bottleneck_table(configs: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "| diagnosis | applies to | confidence | measured evidence | recommended action |",
        "| --- | --- | --- | --- | --- |",
    ]
    rows = []
    for config in configs:
        diagnosis = _diagnosis_for_config(config, config.get("primary_diagnosis", ""))
        if diagnosis:
            rows.append((config, diagnosis))
    for config, diagnosis in sorted(rows, key=lambda pair: _diagnosis_sort_key(pair[0], pair[1])):
        evidence = "; ".join(diagnosis.get("evidence_fields_used", [])[:5]) or "n/a"
        lines.append(
            "| `{diagnosis}` | `{config}` | `{confidence}` | {evidence} | {action} |".format(
                diagnosis=diagnosis.get("classification", ""),
                config=config.get("name", ""),
                confidence=diagnosis.get("confidence", ""),
                evidence=evidence,
                action=diagnosis.get("recommended_action", ""),
            )
        )
    return "\n".join(lines)


def _follow_up_list(configs: Sequence[Dict[str, Any]]) -> str:
    seen = set()
    lines = []
    for config in configs:
        for diagnosis in config.get("deterministic_diagnoses", []):
            text = _clean(diagnosis.get("follow_up_experiment"))
            if not text or text in seen:
                continue
            seen.add(text)
            lines.append(f"- `{config.get('name', '')}` / `{diagnosis.get('classification', '')}`: {text}")
    return "\n".join(lines) if lines else "- No follow-up experiments generated."


def _executive_recommendations(configs: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    route_configs = [
        config
        for config in configs
        if _diagnosis_for_config(config, "route_overlap_bottleneck")
        and not _is_single_destination_incast(config)
        and _float_or_none(config.get("pairwise_route_overlap_ratio")) is not None
    ]
    if route_configs:
        strong = [
            config
            for config in route_configs
            if (_diagnosis_for_config(config, "route_overlap_bottleneck") or {}).get(
                "confidence"
            )
            == "strong"
        ]
        selected = strong or route_configs
        patterns = ", ".join(
            sorted({config.get("pattern_family") or config.get("name", "") for config in selected})
        )
        best = max(
            selected,
            key=lambda item: _float_or_none(item.get("pairwise_route_overlap_ratio"))
            or 0.0,
        )
        lines.extend(
            [
                f"1. Prefer low-overlap/path-diverse routing for {patterns} traffic patterns.",
                f"   - Confidence: {(_diagnosis_for_config(best, 'route_overlap_bottleneck') or {}).get('confidence', 'moderate')}",
                "   - Evidence: paired route comparisons show "
                f"route_overlap_score changing by up to {_fmt(best.get('pairwise_route_overlap_ratio'))}x, "
                f"worst_p99_cycles changing by {_fmt(best.get('pairwise_worst_p99_delta'))} cycles, "
                f"and hotspot_top1_share changing by {_fmt(best.get('pairwise_hotspot_top1_delta'))}.",
                "   - Action: avoid the listed top shared resources or use the low-overlap/path-diverse route generator.",
                "",
            ]
        )

    incast_configs = [config for config in configs if _is_single_destination_incast(config)]
    if incast_configs:
        best = max(
            incast_configs,
            key=lambda item: _float_or_none(
                item.get("measured_metrics", {}).get("hotspot_top1_share")
            )
            or 0.0,
        )
        diagnosis = _diagnosis_for_config(best, "destination_convergence_bottleneck")
        lines.extend(
            [
                f"{len(lines) // 5 + 1}. Distribute targets for incast/single-destination traffic.",
                f"   - Confidence: {(diagnosis or {}).get('confidence', 'strong')}",
                "   - Evidence: "
                f"{_fmt(best.get('route_metadata', {}).get('num_sources'))} sources converge on "
                f"{_fmt(best.get('route_metadata', {}).get('num_destinations'))} destination, "
                f"connection_metadata.max_target_fan_in={_fmt(best.get('connection_metadata', {}).get('max_target_fan_in'))}, "
                f"and hotspot_top1_share reaches {_fmt(best.get('measured_metrics', {}).get('hotspot_top1_share'))}.",
                "   - Action: split traffic across multiple BRAM/DDR/HBM-side endpoints or use multiple target regions.",
                "",
            ]
        )

    endpoint_configs = [
        config
        for config in configs
        if _diagnosis_for_config(config, "endpoint_imbalance_bottleneck")
    ]
    if endpoint_configs:
        best = max(
            endpoint_configs,
            key=lambda item: _float_or_none(
                item.get("measured_metrics", {}).get("endpoint_latency_imbalance_ratio")
            )
            or 0.0,
        )
        diagnosis = _diagnosis_for_config(best, "endpoint_imbalance_bottleneck")
        lines.extend(
            [
                f"{len(lines) // 5 + 1}. Investigate endpoint remapping where latency imbalance is high.",
                f"   - Confidence: {(diagnosis or {}).get('confidence', 'moderate')}",
                "   - Evidence: "
                f"endpoint_latency_imbalance_ratio reaches {_fmt(best.get('measured_metrics', {}).get('endpoint_latency_imbalance_ratio'))} "
                f"while endpoint_bw_imbalance_ratio is {_fmt(best.get('measured_metrics', {}).get('endpoint_bw_imbalance_ratio'))}.",
                "   - Action: investigate a more balanced source-target assignment; treat this as latency-driven unless bandwidth imbalance also rises.",
                "",
            ]
        )

    return "\n".join(lines).strip() or "No direct design recommendations met the deterministic thresholds."


def render_deterministic_markdown(evidence: Dict[str, Any]) -> str:
    configs = evidence.get("configs", [])
    lines = [
        "# Automated NoC Recommendation Report",
        "",
        "## Summary",
        "",
        "This report converts topology sweep metrics, route metadata, endpoint metrics, and hotspot data into evidence-based design recommendations.",
        "",
        "## Executive Recommendations",
        "",
        _executive_recommendations(configs),
        "",
        "## Pairwise Route-Overlap Comparisons",
        "",
        _pairwise_table(configs),
        "",
        "## Bottleneck Diagnoses",
        "",
        _bottleneck_table(configs),
        "",
        "## Follow-Up Experiments",
        "",
        _follow_up_list(configs),
        "",
    ]
    lines.extend(
        [
            "## Audit Notes",
            "",
            "- `inconclusive` means the deterministic evidence did not meet the threshold for a firm routing or placement recommendation.",
            "- Recommended actions are separated from follow-up experiments; the latter still need validation.",
            "- Placement guidance is intentionally general in v1; the script does not generate candidate replacement placements.",
            "- Every recommendation is derived from the measured fields listed in this report.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate auditable deterministic NoC topology recommendations."
    )
    parser.add_argument("--summary-csv", type=Path, required=True)
    parser.add_argument("--route-metrics-csv", type=Path)
    parser.add_argument(
        "--fabric-connections",
        type=Path,
        default=WORKSPACE / "topology_generation" / "connections_list.json",
    )
    parser.add_argument(
        "--fabric-endpoints",
        type=Path,
        default=WORKSPACE / "topology_generation" / "endpoints_list.json",
    )
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--evidence-json", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    evidence = build_evidence_bundle(
        summary_csv=args.summary_csv.resolve(),
        route_metrics_csv=args.route_metrics_csv.resolve()
        if args.route_metrics_csv
        else None,
        fabric_connections=args.fabric_connections,
        fabric_endpoints=args.fabric_endpoints,
    )

    if args.evidence_json:
        _write_json(args.evidence_json, evidence)

    markdown = render_deterministic_markdown(evidence)
    _write_text(args.output_md, markdown)
    print(f"Recommendation Markdown written to: {args.output_md}")
    if args.evidence_json:
        print(f"Evidence JSON written to: {args.evidence_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
