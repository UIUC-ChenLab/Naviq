#!/usr/bin/env python3

import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

WORKSPACE = Path(__file__).resolve().parent
ANALYSIS_DIR = WORKSPACE / "artifacts" / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


WRITE_P99_KEY = "gem5_p99_write_lat_cycles"
READ_P99_KEY = "gem5_p99_read_lat_cycles"
WRITE_P95_KEY = "gem5_p95_write_lat_cycles"
READ_P95_KEY = "gem5_p95_read_lat_cycles"
WRITE_P50_KEY = "gem5_p50_write_lat_cycles"
READ_P50_KEY = "gem5_p50_read_lat_cycles"
WRITE_AVG_LAT_KEY = "gem5_avg_write_lat_cycles"
READ_AVG_LAT_KEY = "gem5_avg_read_lat_cycles"
WRITE_BW_KEY = "gem5_achieved_write_bw_MBps"
READ_BW_KEY = "gem5_achieved_read_bw_MBps"

JFI_KEYS = [
    "gem5_jfi_write_bw",
    "gem5_jfi_read_bw",
    "gem5_jfi_write_lat",
    "gem5_jfi_read_lat",
]
FAIRNESS_MAXMIN_KEYS = [
    "gem5_maxmin_write_bw",
    "gem5_maxmin_read_bw",
    "gem5_maxmin_write_lat",
    "gem5_maxmin_read_lat",
]

JFI_TO_ENDPOINT_METRIC = {
    "gem5_jfi_write_bw": "write_bw_MBps",
    "gem5_jfi_read_bw": "read_bw_MBps",
    "gem5_jfi_write_lat": "write_avg_lat_cycles",
    "gem5_jfi_read_lat": "read_avg_lat_cycles",
}
MAXMIN_TO_ENDPOINT_METRIC = {
    "gem5_maxmin_write_bw": "write_bw_MBps",
    "gem5_maxmin_read_bw": "read_bw_MBps",
    "gem5_maxmin_write_lat": "write_avg_lat_cycles",
    "gem5_maxmin_read_lat": "read_avg_lat_cycles",
}


def _clean(value) -> str:
    return str(value if value is not None else "").strip()


def _float_or_none(value) -> Optional[float]:
    text = _clean(value)
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int_or_none(value) -> Optional[int]:
    text = _clean(value)
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _safe_max(values: Sequence[float]) -> Optional[float]:
    return max(values) if values else None


def _safe_min(values: Sequence[float]) -> Optional[float]:
    return min(values) if values else None


def _src_sort_key(value: object) -> tuple:
    text = _clean(value)
    as_int = _int_or_none(text)
    if as_int is not None:
        return (0, as_int)
    return (1, text)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate gem5 sweep results into per-configuration topology analysis."
    )
    parser.add_argument("--gem5-results", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--tail-risk-ratio", type=float, default=2.0)
    parser.add_argument("--fairness-risk-threshold", type=float, default=0.90)
    parser.add_argument(
        "--localized-hotspot-ratio-threshold",
        type=float,
        default=1.5,
        help="Flag hotspot localization only when top1 share exceeds the ideal uniform share by this factor.",
    )
    parser.add_argument("--widespread-hotspot-threshold", type=float, default=0.30)
    parser.add_argument(
        "--widespread-pressure-threshold",
        type=float,
        default=0.05,
        help="Require at least this occupancy-pressure ratio before widespread activity is treated as congestion risk.",
    )
    parser.add_argument(
        "--credit-pressure-margin-threshold",
        type=float,
        default=0.15,
        help="Require credit share to exceed data_vc share by at least this margin before flagging credit pressure risk.",
    )
    parser.add_argument("--baseline-plan-row-index", type=int)
    parser.add_argument("--top-n", type=int, default=10)
    return parser.parse_args()


def _load_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _existing_paths(rows: Iterable[Dict[str, str]], key: str) -> List[Path]:
    seen = set()
    out = []
    for row in rows:
        raw = _clean(row.get(key))
        if not raw:
            continue
        path = Path(raw)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        token = str(resolved)
        if token in seen:
            continue
        seen.add(token)
        if resolved.exists():
            out.append(resolved)
    return out


def _first_joined(rows: Sequence[Dict[str, str]], key: str) -> str:
    values = sorted({_clean(row.get(key)) for row in rows if _clean(row.get(key))})
    return ";".join(values)


def _load_occ_metrics(paths: Sequence[Path]) -> Dict[str, Optional[float]]:
    ratio_values: List[float] = []
    cumulative_by_nps: Dict[str, float] = defaultdict(float)
    tick_to_nps: Dict[str, set] = defaultdict(set)
    sample_count = 0

    for path in paths:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sample_count += 1
                nps_name = _clean(row.get("nps_name")) or _clean(row.get("nocname"))
                tick = _clean(row.get("tick"))
                occ = _float_or_none(row.get("occupancy_sum"))
                max_buffer_size = _float_or_none(row.get("max_buffer_size"))
                if nps_name:
                    tick_to_nps[tick].add(nps_name)
                if occ is None or nps_name == "":
                    continue
                cumulative_by_nps[nps_name] += occ
                if max_buffer_size and max_buffer_size > 0:
                    ratio_values.append(occ / max_buffer_size)

    total_occ = sum(cumulative_by_nps.values())
    top_name = ""
    top_share = None
    if cumulative_by_nps and total_occ > 0:
        top_name, top_total = max(cumulative_by_nps.items(), key=lambda item: item[1])
        top_share = top_total / total_occ

    peak_active = max((len(names) for names in tick_to_nps.values()), default=0)
    total_unique = len(cumulative_by_nps)

    return {
        "occ_peak_ratio": _safe_max(ratio_values),
        "occ_mean_ratio": _mean(ratio_values),
        "occ_active_nps_count": peak_active if peak_active > 0 else None,
        "occ_top1_share": top_share,
        "occ_top_nps_name": top_name,
        "occ_sample_count": sample_count if sample_count > 0 else None,
        "occ_total_unique_nps": total_unique if total_unique > 0 else None,
    }


def _load_queue_metrics(paths: Sequence[Path]) -> Dict[str, Optional[float]]:
    cumulative_by_router: Dict[str, float] = defaultdict(float)
    tick_to_router: Dict[str, set] = defaultdict(set)
    credit_total = 0.0
    data_total = 0.0
    total_depth = 0.0
    peak_depth = 0.0
    sample_count = 0

    for path in paths:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sample_count += 1
                router_name = _clean(row.get("nocname")) or _clean(row.get("router_id"))
                tick = _clean(row.get("tick"))
                depth = _float_or_none(row.get("depth"))
                queue_kind = _clean(row.get("queue_kind"))
                if router_name:
                    tick_to_router[tick].add(router_name)
                if depth is None or router_name == "":
                    continue
                cumulative_by_router[router_name] += depth
                total_depth += depth
                peak_depth = max(peak_depth, depth)
                if queue_kind == "credit":
                    credit_total += depth
                elif queue_kind == "data_vc":
                    data_total += depth

    top_name = ""
    top_share = None
    if cumulative_by_router and total_depth > 0:
        top_name, top_total = max(cumulative_by_router.items(), key=lambda item: item[1])
        top_share = top_total / total_depth

    peak_active = max((len(names) for names in tick_to_router.values()), default=0)
    total_unique = len(cumulative_by_router)

    return {
        "queue_peak_depth": peak_depth if sample_count > 0 else None,
        "queue_active_router_count": peak_active if peak_active > 0 else None,
        "queue_top1_share": top_share,
        "queue_credit_share": (credit_total / total_depth) if total_depth > 0 else None,
        "queue_data_vc_share": (data_total / total_depth) if total_depth > 0 else None,
        "queue_top_router_name": top_name,
        "queue_sample_count": sample_count if sample_count > 0 else None,
        "queue_total_unique_routers": total_unique if total_unique > 0 else None,
    }


def _tail_ratio(rows: Sequence[Dict[str, str]]) -> Optional[float]:
    ratios = []
    for row in rows:
        for p99_key, p50_key in (
            (WRITE_P99_KEY, WRITE_P50_KEY),
            (READ_P99_KEY, READ_P50_KEY),
        ):
            p99 = _float_or_none(row.get(p99_key))
            p50 = _float_or_none(row.get(p50_key))
            if p99 is None or p50 is None or p50 <= 0:
                continue
            ratios.append(p99 / p50)
    return _safe_max(ratios)


def _dominant_hotspot_trace(
    occ_top1: Optional[float], queue_top1: Optional[float]
) -> str:
    if occ_top1 is not None and queue_top1 is not None:
        return "occ" if occ_top1 >= queue_top1 else "queue"
    if occ_top1 is not None:
        return "occ"
    if queue_top1 is not None:
        return "queue"
    return ""


def _endpoint_total_bw(
    read_bw: Optional[float], write_bw: Optional[float]
) -> Optional[float]:
    values = [v for v in (read_bw, write_bw) if v is not None]
    return sum(values) if values else None


def _assign_endpoint_rank(
    rows: List[Dict[str, object]],
    value_key: str,
    out_key: str,
    *,
    descending: bool,
) -> None:
    ordered = sorted(
        rows,
        key=lambda row: (
            -_sort_value(row.get(value_key), reverse=True)
            if descending
            else _sort_value(row.get(value_key), reverse=False),
            _src_sort_key(row.get("src_id")),
        ),
    )
    for rank, row in enumerate(ordered, 1):
        row[out_key] = rank


def _select_endpoint_metric_culprit(
    endpoint_rows: Sequence[Dict[str, object]],
    field_names: Sequence[str],
    *,
    mode: str,
) -> Dict[str, object]:
    candidates = []
    for row in endpoint_rows:
        for field_name in field_names:
            value = row.get(field_name)
            if not isinstance(value, (int, float)):
                continue
            candidates.append(
                {
                    "endpoint": _clean(row.get("endpoint_id")),
                    "src_id": _clean(row.get("src_id")),
                    "metric": field_name,
                    "value": value,
                }
            )

    if not candidates:
        return {"endpoint": "", "src_id": "", "metric": "", "value": None}

    if mode == "max":
        chosen = sorted(
            candidates,
            key=lambda item: (
                -item["value"],
                _src_sort_key(item["src_id"]),
                item["metric"],
            ),
        )[0]
    else:
        chosen = sorted(
            candidates,
            key=lambda item: (
                item["value"],
                _src_sort_key(item["src_id"]),
                item["metric"],
            ),
        )[0]
    return chosen


def _select_keyed_metric(
    rows: Sequence[Dict[str, str]], keys: Sequence[str], *, mode: str
) -> Dict[str, object]:
    candidates = []
    for row in rows:
        for key in keys:
            value = _float_or_none(row.get(key))
            if value is None:
                continue
            candidates.append({"key": key, "value": value})

    if not candidates:
        return {"key": "", "value": None}

    if mode == "max":
        chosen = sorted(candidates, key=lambda item: (-item["value"], item["key"]))[0]
    else:
        chosen = sorted(candidates, key=lambda item: (item["value"], item["key"]))[0]
    return chosen


def _fairness_driver_from_metric(metric_name: str) -> str:
    metric = _clean(metric_name)
    if metric.endswith("_avg_lat_cycles"):
        return "latency"
    if metric.endswith("_bw_MBps"):
        return "bandwidth"
    return ""


def _select_metric_pair(
    endpoint_rows: Sequence[Dict[str, object]], metric_name: str
) -> Dict[str, object]:
    metric = _clean(metric_name)
    candidates = []
    for row in endpoint_rows:
        value = row.get(metric)
        if not isinstance(value, (int, float)):
            continue
        candidates.append(
            {
                "endpoint": _clean(row.get("endpoint_id")),
                "src_id": _clean(row.get("src_id")),
                "metric": metric,
                "value": value,
            }
        )

    if not candidates:
        return {
            "metric": metric,
            "low_endpoint": "",
            "low_src_id": "",
            "low_value": None,
            "high_endpoint": "",
            "high_src_id": "",
            "high_value": None,
        }

    low = sorted(
        candidates,
        key=lambda item: (item["value"], _src_sort_key(item["src_id"]), item["metric"]),
    )[0]
    high = sorted(
        candidates,
        key=lambda item: (-item["value"], _src_sort_key(item["src_id"]), item["metric"]),
    )[0]
    return {
        "metric": metric,
        "low_endpoint": low["endpoint"],
        "low_src_id": low["src_id"],
        "low_value": low["value"],
        "high_endpoint": high["endpoint"],
        "high_src_id": high["src_id"],
        "high_value": high["value"],
    }


def _build_endpoint_rows(
    config_id: str, rows: Sequence[Dict[str, str]]
) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        endpoint_key = _clean(row.get("endpoint_label")) or _clean(row.get("src_id"))
        grouped[endpoint_key].append(row)

    endpoint_rows: List[Dict[str, object]] = []
    for endpoint_key, group_rows in sorted(grouped.items(), key=lambda item: _src_sort_key(item[0])):
        src_id = _first_joined(group_rows, "src_id")
        endpoint_label = (
            _first_joined(group_rows, "endpoint_label")
            or (f"src_{src_id}" if src_id else "src_unknown")
        )
        read_p99_values = [
            value
            for value in (_float_or_none(row.get(READ_P99_KEY)) for row in group_rows)
            if value is not None
        ]
        write_p99_values = [
            value
            for value in (_float_or_none(row.get(WRITE_P99_KEY)) for row in group_rows)
            if value is not None
        ]
        read_bw_values = [
            value
            for value in (_float_or_none(row.get(READ_BW_KEY)) for row in group_rows)
            if value is not None
        ]
        write_bw_values = [
            value
            for value in (_float_or_none(row.get(WRITE_BW_KEY)) for row in group_rows)
            if value is not None
        ]
        read_avg_lat_values = [
            value
            for value in (_float_or_none(row.get(READ_AVG_LAT_KEY)) for row in group_rows)
            if value is not None
        ]
        write_avg_lat_values = [
            value
            for value in (_float_or_none(row.get(WRITE_AVG_LAT_KEY)) for row in group_rows)
            if value is not None
        ]

        read_p99 = _safe_max(read_p99_values)
        write_p99 = _safe_max(write_p99_values)
        read_bw = _mean(read_bw_values)
        write_bw = _mean(write_bw_values)
        read_avg_lat = _mean(read_avg_lat_values)
        write_avg_lat = _mean(write_avg_lat_values)

        endpoint_rows.append(
            {
                "config_id": config_id,
                "run_tag": _first_joined(group_rows, "run_tag"),
                "plan_row_index": _first_joined(group_rows, "plan_row_index"),
                "name": _first_joined(group_rows, "name"),
                "src_id": src_id,
                "endpoint_id": endpoint_label,
                "measurement_valid": _first_joined(group_rows, "measurement_valid"),
                "invalid_reason": _first_joined(group_rows, "invalid_reason"),
                "read_p99_cycles": read_p99,
                "write_p99_cycles": write_p99,
                "read_bw_MBps": read_bw,
                "write_bw_MBps": write_bw,
                "read_avg_lat_cycles": read_avg_lat,
                "write_avg_lat_cycles": write_avg_lat,
                "endpoint_max_p99_cycles": _safe_max(
                    [value for value in (read_p99, write_p99) if value is not None]
                ),
                "endpoint_total_bw_MBps": _endpoint_total_bw(read_bw, write_bw),
                "endpoint_max_avg_lat_cycles": _safe_max(
                    [
                        value
                        for value in (read_avg_lat, write_avg_lat)
                        if value is not None
                    ]
                ),
            }
        )

    p99_mean = _mean(
        [
            value
            for value in (
                row.get("endpoint_max_p99_cycles") for row in endpoint_rows
            )
            if isinstance(value, (int, float))
        ]
    )
    bw_mean = _mean(
        [
            value
            for value in (
                row.get("endpoint_total_bw_MBps") for row in endpoint_rows
            )
            if isinstance(value, (int, float))
        ]
    )
    lat_mean = _mean(
        [
            value
            for value in (
                row.get("endpoint_max_avg_lat_cycles") for row in endpoint_rows
            )
            if isinstance(value, (int, float))
        ]
    )

    _assign_endpoint_rank(
        endpoint_rows,
        "endpoint_max_p99_cycles",
        "p99_rank_within_config",
        descending=True,
    )
    _assign_endpoint_rank(
        endpoint_rows,
        "endpoint_total_bw_MBps",
        "bw_rank_within_config",
        descending=False,
    )
    _assign_endpoint_rank(
        endpoint_rows,
        "endpoint_max_avg_lat_cycles",
        "latency_rank_within_config",
        descending=True,
    )

    for row in endpoint_rows:
        endpoint_p99 = row.get("endpoint_max_p99_cycles")
        endpoint_bw = row.get("endpoint_total_bw_MBps")
        endpoint_lat = row.get("endpoint_max_avg_lat_cycles")
        row["p99_vs_config_mean"] = (
            endpoint_p99 - p99_mean
            if isinstance(endpoint_p99, (int, float)) and p99_mean is not None
            else None
        )
        row["bw_vs_config_mean"] = (
            endpoint_bw - bw_mean
            if isinstance(endpoint_bw, (int, float)) and bw_mean is not None
            else None
        )
        row["latency_vs_config_mean"] = (
            endpoint_lat - lat_mean
            if isinstance(endpoint_lat, (int, float)) and lat_mean is not None
            else None
        )
        row["is_worst_p99_endpoint"] = (
            row.get("p99_rank_within_config") == 1
            and isinstance(endpoint_p99, (int, float))
        )
        row["is_lowest_bw_endpoint"] = (
            row.get("bw_rank_within_config") == 1
            and isinstance(endpoint_bw, (int, float))
        )
        row["is_highest_latency_endpoint"] = (
            row.get("latency_rank_within_config") == 1
            and isinstance(endpoint_lat, (int, float))
        )

    return endpoint_rows


def _config_summary(
    config_id: str,
    rows: Sequence[Dict[str, str]],
    endpoint_rows: Sequence[Dict[str, object]],
    args: argparse.Namespace,
) -> Dict[str, object]:
    occ_paths = _existing_paths(rows, "hotspot_occ_trace_csv")
    queue_paths = _existing_paths(rows, "hotspot_queue_trace_csv")
    occ_metrics = {
        "occ_peak_ratio": None,
        "occ_mean_ratio": None,
        "occ_active_nps_count": None,
        "occ_top1_share": None,
        "occ_top_nps_name": "",
        "occ_sample_count": None,
        "occ_total_unique_nps": None,
    }
    queue_metrics = {
        "queue_peak_depth": None,
        "queue_active_router_count": None,
        "queue_top1_share": None,
        "queue_credit_share": None,
        "queue_data_vc_share": None,
        "queue_top_router_name": "",
        "queue_sample_count": None,
        "queue_total_unique_routers": None,
    }
    if occ_paths:
        occ_metrics.update(_load_occ_metrics(occ_paths))
    if queue_paths:
        queue_metrics.update(_load_queue_metrics(queue_paths))

    p99_values = []
    p95_values = []
    bw_values = []
    for row in rows:
        for key in (WRITE_P99_KEY, READ_P99_KEY):
            value = _float_or_none(row.get(key))
            if value is not None:
                p99_values.append(value)
        for key in (WRITE_P95_KEY, READ_P95_KEY):
            value = _float_or_none(row.get(key))
            if value is not None:
                p95_values.append(value)
        for key in (WRITE_BW_KEY, READ_BW_KEY):
            value = _float_or_none(row.get(key))
            if value is not None:
                bw_values.append(value)

    jfi_values = [
        value
        for row in rows
        for value in (_float_or_none(row.get(key)) for key in JFI_KEYS)
        if value is not None
    ]
    fairness_maxmin_values = [
        value
        for row in rows
        for value in (_float_or_none(row.get(key)) for key in FAIRNESS_MAXMIN_KEYS)
        if value is not None
    ]
    min_jfi_entry = _select_keyed_metric(rows, JFI_KEYS, mode="min")
    max_fairness_maxmin_entry = _select_keyed_metric(
        rows, FAIRNESS_MAXMIN_KEYS, mode="max"
    )
    min_jfi_metric = JFI_TO_ENDPOINT_METRIC.get(_clean(min_jfi_entry.get("key")), "")
    max_fairness_maxmin_metric = MAXMIN_TO_ENDPOINT_METRIC.get(
        _clean(max_fairness_maxmin_entry.get("key")), ""
    )
    fairness_driver_metric = min_jfi_metric or max_fairness_maxmin_metric
    fairness_driver = _fairness_driver_from_metric(fairness_driver_metric)
    fairness_pair = _select_metric_pair(endpoint_rows, fairness_driver_metric)

    occ_top1 = occ_metrics.get("occ_top1_share")
    queue_top1 = queue_metrics.get("queue_top1_share")
    hotspot_top1_share = _safe_max(
        [v for v in (occ_top1, queue_top1) if isinstance(v, (int, float))]
    )
    hotspot_primary_source = _dominant_hotspot_trace(occ_top1, queue_top1)
    hotspot_primary_location = ""
    if hotspot_primary_source == "occ":
        hotspot_primary_location = _clean(occ_metrics.get("occ_top_nps_name"))
    elif hotspot_primary_source == "queue":
        hotspot_primary_location = _clean(queue_metrics.get("queue_top_router_name"))

    tail_ratio = _tail_ratio(rows)
    min_jfi = _safe_min(jfi_values)
    credit_share = queue_metrics.get("queue_credit_share")
    data_vc_share = queue_metrics.get("queue_data_vc_share")
    credit_share_margin = None
    if credit_share is not None and data_vc_share is not None:
        credit_share_margin = credit_share - data_vc_share

    occ_peak_active = _int_or_none(occ_metrics.get("occ_active_nps_count"))
    occ_total_unique = _int_or_none(occ_metrics.get("occ_total_unique_nps"))
    queue_peak_active = _int_or_none(queue_metrics.get("queue_active_router_count"))
    queue_total_unique = _int_or_none(queue_metrics.get("queue_total_unique_routers"))
    activity_ratios = []
    if occ_peak_active and occ_total_unique:
        activity_ratios.append(occ_peak_active / occ_total_unique)
    if queue_peak_active and queue_total_unique:
        activity_ratios.append(queue_peak_active / queue_total_unique)
    widespread_ratio = _safe_max(activity_ratios)
    occupancy_pressure = _safe_max(
        [
            v
            for v in (
                occ_metrics.get("occ_mean_ratio"),
                occ_metrics.get("occ_peak_ratio"),
            )
            if isinstance(v, (int, float))
        ]
    )

    hotspot_active_resource_count: Optional[int] = None
    if hotspot_primary_source == "occ":
        hotspot_active_resource_count = occ_total_unique
    elif hotspot_primary_source == "queue":
        hotspot_active_resource_count = queue_total_unique

    hotspot_concentration_ratio = None
    if (
        hotspot_top1_share is not None
        and hotspot_active_resource_count is not None
        and hotspot_active_resource_count > 0
    ):
        hotspot_concentration_ratio = hotspot_top1_share * hotspot_active_resource_count

    worst_p99 = _select_endpoint_metric_culprit(
        endpoint_rows,
        ("read_p99_cycles", "write_p99_cycles"),
        mode="max",
    )
    lowest_bw = _select_endpoint_metric_culprit(
        endpoint_rows,
        ("read_bw_MBps", "write_bw_MBps"),
        mode="min",
    )
    highest_bw = _select_endpoint_metric_culprit(
        endpoint_rows,
        ("read_bw_MBps", "write_bw_MBps"),
        mode="max",
    )
    lowest_latency = _select_endpoint_metric_culprit(
        endpoint_rows,
        ("read_avg_lat_cycles", "write_avg_lat_cycles"),
        mode="min",
    )
    highest_latency = _select_endpoint_metric_culprit(
        endpoint_rows,
        ("read_avg_lat_cycles", "write_avg_lat_cycles"),
        mode="max",
    )

    endpoint_bw_imbalance_ratio = None
    if (
        isinstance(highest_bw.get("value"), (int, float))
        and isinstance(lowest_bw.get("value"), (int, float))
        and lowest_bw["value"] > 0
    ):
        endpoint_bw_imbalance_ratio = highest_bw["value"] / lowest_bw["value"]

    endpoint_latency_imbalance_ratio = None
    if (
        isinstance(highest_latency.get("value"), (int, float))
        and isinstance(lowest_latency.get("value"), (int, float))
        and lowest_latency["value"] > 0
    ):
        endpoint_latency_imbalance_ratio = (
            highest_latency["value"] / lowest_latency["value"]
        )

    summary: Dict[str, object] = {
        "config_id": config_id,
        "run_tag": _first_joined(rows, "run_tag"),
        "plan_row_index": _first_joined(rows, "plan_row_index"),
        "name": _first_joined(rows, "name"),
        "hotspot_mode": _first_joined(rows, "hotspot_mode"),
        "hotspot_capture_status": _first_joined(rows, "hotspot_capture_status"),
        "worst_p99_cycles": _safe_max(p99_values),
        "worst_p95_cycles": _safe_max(p95_values),
        "mean_p99_cycles": _mean(p99_values),
        "mean_bw_MBps": _mean(bw_values),
        "min_jfi": min_jfi,
        "min_jfi_metric": min_jfi_metric,
        "max_fairness_maxmin": _safe_max(fairness_maxmin_values),
        "max_fairness_maxmin_metric": max_fairness_maxmin_metric,
        "fairness_driver": fairness_driver,
        "worst_tail_ratio": tail_ratio,
        "hotspot_top1_share": hotspot_top1_share,
        "hotspot_concentration_ratio": hotspot_concentration_ratio,
        "hotspot_active_resource_count": hotspot_active_resource_count,
        "hotspot_primary_source": hotspot_primary_source,
        "hotspot_primary_location": hotspot_primary_location,
        "widespread_activity_ratio": widespread_ratio,
        "widespread_activity_flag": (
            widespread_ratio is not None
            and widespread_ratio >= args.widespread_hotspot_threshold
        ),
        "occupancy_pressure_ratio": occupancy_pressure,
        "credit_share_margin": credit_share_margin,
        "worst_p99_endpoint": worst_p99["endpoint"],
        "worst_p99_src_id": worst_p99["src_id"],
        "worst_p99_metric": worst_p99["metric"],
        "worst_p99_value": worst_p99["value"],
        "lowest_bw_endpoint": lowest_bw["endpoint"],
        "lowest_bw_src_id": lowest_bw["src_id"],
        "lowest_bw_metric": lowest_bw["metric"],
        "lowest_bw_value": lowest_bw["value"],
        "highest_bw_endpoint": highest_bw["endpoint"],
        "highest_bw_src_id": highest_bw["src_id"],
        "highest_bw_metric": highest_bw["metric"],
        "highest_bw_value": highest_bw["value"],
        "lowest_latency_endpoint": lowest_latency["endpoint"],
        "lowest_latency_src_id": lowest_latency["src_id"],
        "lowest_latency_metric": lowest_latency["metric"],
        "lowest_latency_value": lowest_latency["value"],
        "highest_latency_endpoint": highest_latency["endpoint"],
        "highest_latency_src_id": highest_latency["src_id"],
        "highest_latency_metric": highest_latency["metric"],
        "highest_latency_value": highest_latency["value"],
        "endpoint_bw_imbalance_ratio": endpoint_bw_imbalance_ratio,
        "endpoint_latency_imbalance_ratio": endpoint_latency_imbalance_ratio,
        "fairness_pair_metric": fairness_pair["metric"],
        "fairness_low_endpoint": fairness_pair["low_endpoint"],
        "fairness_low_src_id": fairness_pair["low_src_id"],
        "fairness_low_value": fairness_pair["low_value"],
        "fairness_high_endpoint": fairness_pair["high_endpoint"],
        "fairness_high_src_id": fairness_pair["high_src_id"],
        "fairness_high_value": fairness_pair["high_value"],
    }
    summary.update(occ_metrics)
    summary.update(queue_metrics)

    summary["tail_latency_risk"] = (
        tail_ratio is not None and tail_ratio >= args.tail_risk_ratio
    )
    summary["fairness_risk"] = (
        min_jfi is not None and min_jfi < args.fairness_risk_threshold
    )
    summary["localized_hotspot_risk"] = (
        hotspot_concentration_ratio is not None
        and hotspot_concentration_ratio >= args.localized_hotspot_ratio_threshold
    )
    summary["credit_pressure_risk"] = (
        credit_share_margin is not None
        and credit_share_margin >= args.credit_pressure_margin_threshold
    )
    summary["widespread_congestion_risk"] = (
        widespread_ratio is not None
        and widespread_ratio >= args.widespread_hotspot_threshold
        and occupancy_pressure is not None
        and occupancy_pressure >= args.widespread_pressure_threshold
    )
    return summary


def _sort_value(value: Optional[float], *, reverse: bool) -> float:
    if value is None:
        return -math.inf if reverse else math.inf
    return value


def _assign_ranks(rows: List[Dict[str, object]]) -> None:
    risk_sorted = sorted(
        rows,
        key=lambda row: (
            -_sort_value(row.get("worst_p99_cycles"), reverse=True),
            _sort_value(row.get("min_jfi"), reverse=False),
            -_sort_value(row.get("hotspot_top1_share"), reverse=True),
            _clean(row.get("name")),
        ),
    )
    candidate_sorted = sorted(
        rows,
        key=lambda row: (
            _sort_value(row.get("worst_p99_cycles"), reverse=False),
            -_sort_value(row.get("min_jfi"), reverse=True),
            _sort_value(row.get("hotspot_top1_share"), reverse=False),
            _clean(row.get("name")),
        ),
    )
    for rank, row in enumerate(risk_sorted, 1):
        row["risk_rank"] = rank
    for rank, row in enumerate(candidate_sorted, 1):
        row["candidate_rank"] = rank


def _apply_baseline(rows: List[Dict[str, object]], baseline_index: int) -> None:
    baseline_matches = [
        row for row in rows if _clean(row.get("plan_row_index")) == str(baseline_index)
    ]
    if not baseline_matches:
        raise SystemExit(
            f"Baseline plan_row_index {baseline_index} was not found in the aggregated results."
        )
    baseline = sorted(
        baseline_matches,
        key=lambda row: (_clean(row.get("run_tag")), _clean(row.get("name"))),
    )[0]

    # TODO: add --baseline-config-id as a more stable selection mode.
    for row in rows:
        for metric, out_key in (
            ("worst_p99_cycles", "delta_worst_p99_vs_baseline"),
            ("mean_bw_MBps", "delta_mean_bw_vs_baseline"),
            ("min_jfi", "delta_min_jfi_vs_baseline"),
            ("hotspot_top1_share", "delta_hotspot_top1_share_vs_baseline"),
        ):
            value = row.get(metric)
            base = baseline.get(metric)
            if isinstance(value, (int, float)) and isinstance(base, (int, float)):
                row[out_key] = value - base
            else:
                row[out_key] = None
        row["top_hotspot_changed_vs_baseline"] = (
            _clean(row.get("hotspot_primary_location"))
            != _clean(baseline.get("hotspot_primary_location"))
        )


def _write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _format_metric(value: object, digits: int = 3) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    text = _clean(value)
    return text or "n/a"


def _flag_list(row: Dict[str, object]) -> str:
    names = [
        flag
        for flag in (
            "tail_latency_risk",
            "fairness_risk",
            "localized_hotspot_risk",
            "credit_pressure_risk",
            "widespread_congestion_risk",
        )
        if row.get(flag)
    ]
    return ", ".join(names) if names else "none"


def _culprit_snippets(row: Dict[str, object]) -> str:
    snippets = []
    if isinstance(row.get("worst_p99_value"), (int, float)):
        snippets.append(
            "worst_p99="
            f"{_format_metric(row.get('worst_p99_value'))} from src_id="
            f"{_clean(row.get('worst_p99_src_id')) or 'n/a'} "
            f"{_clean(row.get('worst_p99_metric')) or 'n/a'}"
        )
    if (
        row.get("fairness_risk")
        and _clean(row.get("fairness_driver"))
        and _clean(row.get("fairness_pair_metric"))
        and _clean(row.get("fairness_low_src_id"))
        and _clean(row.get("fairness_high_src_id"))
    ):
        snippets.append(
            "fairness_issue: "
            f"{_clean(row.get('fairness_driver'))} imbalance, "
            f"high src_id={_clean(row.get('fairness_high_src_id')) or 'n/a'} "
            f"{_clean(row.get('fairness_pair_metric')) or 'n/a'} / "
            f"low src_id={_clean(row.get('fairness_low_src_id')) or 'n/a'} "
            f"{_clean(row.get('fairness_pair_metric')) or 'n/a'}"
        )
    return ", ".join(snippets) if snippets else "n/a"


def _write_report(path: Path, rows: Sequence[Dict[str, object]], top_n: int) -> None:
    risk_rows = sorted(rows, key=lambda row: int(row["risk_rank"]))[:top_n]
    candidate_rows = sorted(rows, key=lambda row: int(row["candidate_rank"]))[:top_n]

    with path.open("w") as f:
        f.write("# Topology Analysis Report\n\n")
        f.write("## Highest-Risk Configurations\n\n")
        for row in risk_rows:
            f.write(
                f"- `{row['config_id']}` `{_clean(row.get('name'))}` "
                f"(row `{_clean(row.get('plan_row_index'))}`, risk rank `{row['risk_rank']}`): "
                f"worst_p99={_format_metric(row.get('worst_p99_cycles'))}, "
                f"mean_bw={_format_metric(row.get('mean_bw_MBps'))}, "
                f"min_jfi={_format_metric(row.get('min_jfi'))}, "
                f"hotspot_top1_share={_format_metric(row.get('hotspot_top1_share'))}, "
                f"top_hotspot=`{_clean(row.get('hotspot_primary_location')) or 'n/a'}`, "
                f"flags={_flag_list(row)}, "
                f"culprits={_culprit_snippets(row)}\n"
            )
        f.write("\n## Best Candidate Configurations\n\n")
        for row in candidate_rows:
            f.write(
                f"- `{row['config_id']}` `{_clean(row.get('name'))}` "
                f"(row `{_clean(row.get('plan_row_index'))}`, candidate rank `{row['candidate_rank']}`): "
                f"worst_p99={_format_metric(row.get('worst_p99_cycles'))}, "
                f"mean_bw={_format_metric(row.get('mean_bw_MBps'))}, "
                f"min_jfi={_format_metric(row.get('min_jfi'))}, "
                f"hotspot_top1_share={_format_metric(row.get('hotspot_top1_share'))}, "
                f"top_hotspot=`{_clean(row.get('hotspot_primary_location')) or 'n/a'}`, "
                f"flags={_flag_list(row)}, "
                f"culprits={_culprit_snippets(row)}\n"
            )


def main() -> int:
    args = _parse_args()
    if not args.gem5_results.exists():
        raise SystemExit(f"gem5 results CSV not found: {args.gem5_results}")

    rows = _load_rows(args.gem5_results)
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        config_id = _clean(row.get("config_id"))
        if not config_id:
            raise SystemExit("Input CSV is missing config_id values.")
        grouped[config_id].append(row)

    endpoint_rows: List[Dict[str, object]] = []
    summaries = []
    for config_id, group_rows in sorted(grouped.items()):
        config_endpoint_rows = _build_endpoint_rows(config_id, group_rows)
        endpoint_rows.extend(config_endpoint_rows)
        summaries.append(_config_summary(config_id, group_rows, config_endpoint_rows, args))
    _assign_ranks(summaries)
    if args.baseline_plan_row_index is not None:
        _apply_baseline(summaries, args.baseline_plan_row_index)

    prefix = args.output_prefix
    if prefix is None:
        prefix = ANALYSIS_DIR / f"{args.gem5_results.stem}_analysis"

    csv_path = prefix.with_suffix(".csv")
    endpoint_csv_path = prefix.with_name(f"{prefix.name}_endpoints").with_suffix(".csv")
    report_path = prefix.with_suffix(".md")
    _write_csv(csv_path, summaries)
    _write_csv(endpoint_csv_path, endpoint_rows)
    _write_report(report_path, summaries, max(1, args.top_n))

    print(f"Analysis CSV written to: {csv_path}")
    print(f"Endpoint analysis CSV written to: {endpoint_csv_path}")
    print(f"Analysis report written to: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
