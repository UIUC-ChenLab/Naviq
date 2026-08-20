#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import re
import shlex
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import route_metrics


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parents[1]
REPO_ROOT = WORKSPACE.parent
RESULTS_DIR = WORKSPACE / "artifacts" / "results"
DEFAULT_ARTIFACT_ROOT = SCRIPT_DIR / "artifacts"
NOC_DESC_DIR = WORKSPACE / "artifacts" / "noc_desc"
SIMLOGS_DIR = WORKSPACE / "artifacts" / "simlogs"
HOTSPOT_DIR = WORKSPACE / "artifacts" / "hotspot"

DEFAULT_RUN_TAG_PREFIX = "experiment2"
DEFAULT_TG_MODE = "rw_interleaved"
DEFAULT_BANDWIDTH_MBPS = 800
DEFAULT_NUM_TRANSACTIONS = 64
DEFAULT_BEAT_BYTES = 32
DEFAULT_BEAT_COUNT = 16
DEFAULT_DATA_WIDTH_BITS = 512
DEFAULT_BRAM_DATA_WIDTH_BITS = 512
DEFAULT_NOC_CLK_MHZ = 1000
DEFAULT_ABS_MAX_TICK = 10000000000

HOTSPOT_PROFILE_NONE = "none"
HOTSPOT_PROFILE_ALL = "all"
HOTSPOT_PROFILE_RECOMMENDED = "recommended"


@dataclass(frozen=True)
class CaseSpec:
    case_name: str
    pattern_family: str
    overlap_class: str
    topology_shape: str
    connection_json: str
    placement_json: str
    router_name: str
    router_max_extra_hops: Optional[int] = None
    router_overlap_weight: Optional[float] = None


CASE_SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        "shift_low_overlap",
        "shift",
        "low_overlap",
        "4x4",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_shift_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_shift.place.json",
        "low_overlap",
    ),
    CaseSpec(
        "shift_high_overlap",
        "shift",
        "high_overlap",
        "4x4",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_shift_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_shift.place.json",
        "high_overlap",
        3,
        2.0,
    ),
    CaseSpec(
        "reverse_low_overlap",
        "reverse",
        "low_overlap",
        "4x4",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_reverse_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_reverse.place.json",
        "low_overlap",
    ),
    CaseSpec(
        "reverse_high_overlap",
        "reverse",
        "high_overlap",
        "4x4",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_reverse_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_reverse.place.json",
        "high_overlap",
        1,
        4.0,
    ),
    CaseSpec(
        "tornado_low_overlap",
        "tornado",
        "low_overlap",
        "4x4",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_tornado_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_tornado.place.json",
        "low_overlap",
    ),
    CaseSpec(
        "tornado_high_overlap",
        "tornado",
        "high_overlap",
        "4x4",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_tornado_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_tornado.place.json",
        "high_overlap",
    ),
    CaseSpec(
        "hotspot_low_overlap",
        "hotspot",
        "low_overlap",
        "4x1",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_hotspot.place.json",
        "low_overlap",
    ),
    CaseSpec(
        "hotspot_high_overlap",
        "hotspot",
        "high_overlap",
        "4x1",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_hotspot.place.json",
        "high_overlap",
    ),
)
CASE_BY_NAME = {case.case_name: case for case in CASE_SPECS}
CASE_ROW_INDEX = {case.case_name: index for index, case in enumerate(CASE_SPECS, 1)}
PATTERN_FAMILIES = sorted({case.pattern_family for case in CASE_SPECS})
HOTSPOT_RECOMMENDED_CASES = {
    case.case_name for case in CASE_SPECS if case.overlap_class == "high_overlap"
}
PLAN_FILENAME = "experiment2_plan.csv"


def _repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(REPO_ROOT.resolve())
        return str(rel)
    except ValueError:
        return str(resolved)


def _workspace_path(rel_path: str) -> Path:
    return (WORKSPACE / rel_path).resolve()


def _case_list_from_args(args: argparse.Namespace) -> list[str]:
    selected: list[str] = []
    if args.case:
        selected.extend(args.case)
    if args.cases:
        for chunk in args.cases.split(","):
            token = chunk.strip()
            if token:
                selected.append(token)
    if not selected:
        return [case.case_name for case in CASE_SPECS]

    ordered: list[str] = []
    seen = set()
    for name in selected:
        if name not in CASE_BY_NAME:
            raise SystemExit(f"Unknown Experiment 2 case: {name}")
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _repeat_indices(args: argparse.Namespace) -> list[int]:
    if args.repeats < 1:
        raise SystemExit("--repeats must be 1 or greater.")
    if args.repeat_index is None:
        return list(range(1, args.repeats + 1))
    if args.repeat_index < 1 or args.repeat_index > args.repeats:
        raise SystemExit("--repeat-index must be within 1..--repeats.")
    return [args.repeat_index]


def _run_tag(args: argparse.Namespace) -> str:
    if args.run_tag:
        return args.run_tag
    return f"{DEFAULT_RUN_TAG_PREFIX}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _clean_stem(path_text: str) -> str:
    name = Path(path_text).name
    for suffix in (".conn.json", ".place.json", ".json", ".ncr", ".nts"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def _sanitize_name_token(name: str) -> str:
    token = re.sub(r"[\s,:/]+", "_", name).strip("_")
    return token or "unnamed_row"


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _port_component(endpoint: str) -> str:
    return endpoint.split(".", 1)[0]


def validate_case_topology(case: CaseSpec) -> Dict[str, Any]:
    path = _workspace_path(case.connection_json)
    data = _load_json(path)
    if data.get("kind") != "naviq.connections":
        raise SystemExit(f"{path} is not a V2 connections JSON.")

    components = data.get("components", {})
    connections = data.get("connections", [])
    if not isinstance(connections, list):
        raise SystemExit(f"{path} has an invalid connections list.")

    masters = {
        name
        for name, component in components.items()
        for port in component.get("ports", {}).values()
        if str(port.get("role", "")).lower() == "master"
        and str(port.get("protocol", "")).lower() == "aximm"
    }
    slaves = {
        name
        for name, component in components.items()
        for port in component.get("ports", {}).values()
        if str(port.get("role", "")).lower() == "slave"
        and str(port.get("protocol", "")).lower() == "aximm"
    }

    source_counts: Counter[str] = Counter()
    dest_counts: Counter[str] = Counter()
    referenced_sources = set()
    referenced_dests = set()
    for entry in connections:
        src = _port_component(str(entry.get("from", "")))
        dst = _port_component(str(entry.get("to", "")))
        if src not in masters:
            raise SystemExit(f"{path} references non-master source '{src}'.")
        if dst not in slaves:
            raise SystemExit(f"{path} references non-slave destination '{dst}'.")
        referenced_sources.add(src)
        referenced_dests.add(dst)
        source_counts[src] += 1
        dest_counts[dst] += 1

    num_sources = len(referenced_sources)
    num_destinations = len(referenced_dests)
    num_flows = len(connections)

    if case.topology_shape == "4x4":
        if len(masters) != 4 or len(slaves) != 4:
            raise SystemExit(
                f"{path} does not define exactly four AXI-MM masters and four AXI-MM slaves."
            )
        if referenced_sources != masters or referenced_dests != slaves:
            raise SystemExit(f"{path} does not connect every 4x4 endpoint exactly once.")
        if num_sources != 4 or num_destinations != 4 or num_flows != 4:
            raise SystemExit(
                f"{path} is not a valid 4x4 mapping: "
                f"sources={num_sources}, destinations={num_destinations}, flows={num_flows}."
            )
        if any(count != 1 for count in source_counts.values()):
            raise SystemExit(f"{path} has a source with fanout != 1.")
        if any(count != 1 for count in dest_counts.values()):
            raise SystemExit(f"{path} has a destination with fanin != 1.")
    elif case.topology_shape == "4x1":
        if len(masters) != 4 or len(slaves) != 1:
            raise SystemExit(
                f"{path} does not define exactly four AXI-MM masters and one AXI-MM slave."
            )
        if referenced_sources != masters or referenced_dests != slaves:
            raise SystemExit(f"{path} does not connect every 4x1 endpoint as expected.")
        if num_sources != 4 or num_destinations != 1 or num_flows != 4:
            raise SystemExit(
                f"{path} is not a valid 4x1 mapping: "
                f"sources={num_sources}, destinations={num_destinations}, flows={num_flows}."
            )
        if any(count != 1 for count in source_counts.values()):
            raise SystemExit(f"{path} has a source with fanout != 1.")
        if sorted(dest_counts.values()) != [4]:
            raise SystemExit(f"{path} does not route all four sources into one destination.")
    else:
        raise SystemExit(f"Unsupported topology shape: {case.topology_shape}")

    return {
        "case_name": case.case_name,
        "pattern_family": case.pattern_family,
        "overlap_class": case.overlap_class,
        "topology_shape": case.topology_shape,
        "connection_json": f"noc_testing/{case.connection_json}",
        "placement_json": f"noc_testing/{case.placement_json}",
        "routing_mode": case.router_name,
        "num_sources": num_sources,
        "num_destinations": num_destinations,
        "num_flows": num_flows,
    }


def _generated_route_paths(route_root: Path, case: CaseSpec) -> Dict[str, Path]:
    case_root = route_root / case.case_name
    return {
        "case_root": case_root,
        "ncr": case_root / "noc_subsystem.ncr",
        "nts": case_root / "noc_subsystem.nts",
        "place": case_root / "noc_subsystem.place.json",
    }


def _generate_route_artifacts(
    *,
    case: CaseSpec,
    route_root: Path,
    command_log: List[Dict[str, Any]],
) -> Dict[str, Path]:
    paths = _generated_route_paths(route_root, case)
    if paths["case_root"].exists():
        shutil.rmtree(paths["case_root"])
    paths["case_root"].mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(WORKSPACE / "topology_generation" / "generate_ncr.py"),
        "--connections",
        str(_workspace_path(case.connection_json)),
        "--placement",
        str(_workspace_path(case.placement_json)),
        "--ncr",
        str(paths["ncr"]),
        "--nts",
        str(paths["nts"]),
        "--router",
        case.router_name,
    ]
    if case.router_max_extra_hops is not None:
        cmd.extend(["--overlap-max-extra-hops", str(case.router_max_extra_hops)])
    if case.router_overlap_weight is not None:
        cmd.extend(["--overlap-weight", str(case.router_overlap_weight)])
    _run_cmd(
        cmd,
        cwd=REPO_ROOT,
        command_log=command_log,
        label=f"generate_routes:{case.case_name}",
    )
    return paths


def validate_route_artifacts(
    case: CaseSpec,
    topology_meta: Dict[str, Any],
    *,
    ncr_path: Path,
    nts_path: Path,
) -> Dict[str, Any]:
    if not ncr_path.exists():
        raise SystemExit(f"Missing NCR route file for {case.case_name}: {ncr_path}")
    if not nts_path.exists():
        raise SystemExit(f"Missing NTS route file for {case.case_name}: {nts_path}")

    nts_shape = route_metrics.load_nts_shape(nts_path)
    ncr_shape = route_metrics.load_ncr_shape(ncr_path)
    if nts_shape["num_paths"] != topology_meta["num_flows"]:
        raise SystemExit(
            f"{nts_path} path count {nts_shape['num_paths']} does not match "
            f"{case.case_name} flow count {topology_meta['num_flows']}."
        )
    if ncr_shape["num_paths"] != topology_meta["num_flows"]:
        raise SystemExit(
            f"{ncr_path} path count {ncr_shape['num_paths']} does not match "
            f"{case.case_name} flow count {topology_meta['num_flows']}."
        )
    if nts_shape["num_sources"] != topology_meta["num_sources"]:
        raise SystemExit(
            f"{nts_path} source count {nts_shape['num_sources']} does not match "
            f"{case.case_name} source count {topology_meta['num_sources']}."
        )
    if nts_shape["num_destinations"] != topology_meta["num_destinations"]:
        raise SystemExit(
            f"{nts_path} destination count {nts_shape['num_destinations']} does not match "
            f"{case.case_name} destination count {topology_meta['num_destinations']}."
        )

    metrics = route_metrics.compute_route_metrics(ncr_path)
    return {
        **topology_meta,
        "router_name": case.router_name,
        "router_max_extra_hops": case.router_max_extra_hops,
        "router_overlap_weight": case.router_overlap_weight,
        "ncr": _repo_rel(ncr_path),
        "nts": _repo_rel(nts_path),
        "route_source_path": _repo_rel(ncr_path),
        "route_to_vc_path": "",
        "hop_summary_status": "computed",
        **metrics,
    }


def _hotspot_mode(profile: str, case_name: str) -> str:
    if profile == HOTSPOT_PROFILE_NONE:
        return "off"
    if profile == HOTSPOT_PROFILE_ALL:
        return "both"
    if profile == HOTSPOT_PROFILE_RECOMMENDED:
        return "both" if case_name in HOTSPOT_RECOMMENDED_CASES else "off"
    raise SystemExit(f"Unsupported hotspot profile: {profile}")


def _workload_settings(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "tg_mode": args.tg_mode,
        "axi_write_len_beats": args.beat_count,
        "axi_write_size_bytes": args.beat_bytes,
        "axi_write_bandwidth_cfg_MBps": args.bandwidth_mbps,
        "num_write_transactions_cfg": args.num_transactions,
        "tg_axi_data_width_bits": args.data_width_bits,
        "bram_data_width": args.bram_data_width_bits,
        "noc_axi_clk_mhz": args.noc_clk_mhz,
        "abs_max_tick": args.abs_max_tick,
    }


def build_plan_rows(
    settings: Dict[str, Any],
    validations: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for case in CASE_SPECS:
        row = {
            "name": case.case_name,
            "topology_json": case.connection_json,
            "placement_json": case.placement_json,
            "ncr": validations[case.case_name]["ncr"],
            "nts": validations[case.case_name]["nts"],
        }
        row.update(settings)
        rows.append(row)
    return rows


def write_plan_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        raise SystemExit("No Experiment 2 plan rows were generated.")
    fieldnames = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _stringify_cmd(cmd: Sequence[str]) -> str:
    return shlex.join(list(map(str, cmd)))


def _run_cmd(
    cmd: Sequence[str],
    *,
    cwd: Path,
    command_log: List[Dict[str, Any]],
    label: str,
) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    command_log.append(
        {
            "label": label,
            "command": _stringify_cmd(cmd),
            "cwd": str(cwd),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"{label} failed with exit code {proc.returncode}.\n"
            f"Command: {_stringify_cmd(cmd)}\n"
            f"STDOUT:\n{proc.stdout[-4000:]}\n"
            f"STDERR:\n{proc.stderr[-4000:]}"
        )


def _case_run_tag(base_run_tag: str, repeat_index: int, case_name: str) -> str:
    return f"{base_run_tag}__r{repeat_index:02d}__{case_name}"


def _repeat_slug(repeat_index: int) -> str:
    return f"repeat_{repeat_index:02d}"


def _per_case_paths(plan_path: Path, base_run_tag: str, repeat_index: int, case: CaseSpec) -> Dict[str, Path]:
    case_tag = _case_run_tag(base_run_tag, repeat_index, case.case_name)
    sanitized_name = _sanitize_name_token(case.case_name)
    return {
        "case_run_tag": Path(case_tag),
        "gem5_results_csv": RESULTS_DIR / f"gem5_{plan_path.stem}_{case_tag}.csv",
        "topology_artifact_dir": NOC_DESC_DIR / case_tag,
        "simlog_dir": SIMLOGS_DIR / f"simlogs_{case_tag}",
        "simlog_path": SIMLOGS_DIR / f"simlogs_{case_tag}" / f"gem5_{sanitized_name}.log",
        "hotspot_artifact_dir": HOTSPOT_DIR / case_tag / f"row_{CASE_ROW_INDEX[case.case_name]}_{sanitized_name}",
    }


def _copy_file_if_exists(src: Path, dst: Path) -> str:
    if not src.exists():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def _copy_tree_if_exists(src: Path, dst: Path) -> str:
    if not src.exists():
        return ""
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    return str(dst)


def _collect_case_outputs(
    *,
    artifact_root: Path,
    repeat_index: int,
    case: CaseSpec,
    source_paths: Dict[str, Path],
    validation: Dict[str, Any],
    route_metrics_json: Path,
    route_metrics_csv: Path,
) -> Dict[str, str]:
    case_root = artifact_root / "collected" / _repeat_slug(repeat_index) / case.case_name
    return {
        "collected_case_dir": str(case_root),
        "collected_gem5_results_csv": _copy_file_if_exists(
            source_paths["gem5_results_csv"],
            case_root / "results" / source_paths["gem5_results_csv"].name,
        ),
        "collected_ncr_path": _copy_file_if_exists(
            REPO_ROOT / validation["ncr"],
            case_root / "routes" / "noc_subsystem.ncr",
        ),
        "collected_nts_path": _copy_file_if_exists(
            REPO_ROOT / validation["nts"],
            case_root / "routes" / "noc_subsystem.nts",
        ),
        "collected_generated_topology_artifact_dir": _copy_tree_if_exists(
            source_paths["topology_artifact_dir"],
            case_root / "noc_desc",
        ),
        "collected_simlog_path": _copy_file_if_exists(
            source_paths["simlog_path"],
            case_root / "simlogs" / source_paths["simlog_path"].name,
        ),
        "collected_hotspot_artifact_dir": _copy_tree_if_exists(
            source_paths["hotspot_artifact_dir"],
            case_root / "hotspot",
        ),
        "collected_route_metrics_json": _copy_file_if_exists(
            route_metrics_json,
            case_root / "route_metrics" / route_metrics_json.name,
        ),
        "collected_route_metrics_csv": _copy_file_if_exists(
            route_metrics_csv,
            case_root / "route_metrics" / route_metrics_csv.name,
        ),
    }


def _combine_case_rows(
    raw_rows: Sequence[Dict[str, str]],
    *,
    case: CaseSpec,
    repeat_index: int,
    validation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    combined: list[Dict[str, Any]] = []
    for row in raw_rows:
        merged = dict(row)
        merged.update(
            {
                "experiment_case": case.case_name,
                "repeat_index": repeat_index,
                "pattern_family": case.pattern_family,
                "overlap_class": case.overlap_class,
                "connection_json": validation["connection_json"],
                "placement_json": validation["placement_json"],
                "avg_hop_count": validation["avg_hop_count"],
                "max_hop_count": validation["max_hop_count"],
                "max_flows_on_any_resource": validation["max_flows_on_any_resource"],
                "average_pairwise_route_overlap": validation["average_pairwise_route_overlap"],
                "top_shared_resource_id": validation["top_shared_resource_id"],
                "route_overlap_score": validation["route_overlap_score"],
                "fraction_of_route_resources_shared_by_2_or_more_flows": validation[
                    "fraction_of_route_resources_shared_by_2_or_more_flows"
                ],
            }
        )
        combined.append(merged)
    return combined


def _analysis_prefix(artifact_root: Path, repeat_index: int) -> Path:
    return artifact_root / "analysis" / f"{_repeat_slug(repeat_index)}_topology"


def _run_analysis(
    *,
    gem5_results: Path,
    output_prefix: Path,
    baseline_row_index: int,
    command_log: List[Dict[str, Any]],
) -> Dict[str, str]:
    cmd = [
        sys.executable,
        str(WORKSPACE / "topology_analysis.py"),
        "--gem5-results",
        str(gem5_results),
        "--output-prefix",
        str(output_prefix),
        "--baseline-plan-row-index",
        str(baseline_row_index),
    ]
    _run_cmd(cmd, cwd=REPO_ROOT, command_log=command_log, label="topology_analysis")
    return {
        "summary_csv": str(output_prefix.with_suffix(".csv")),
        "endpoint_csv": str(
            output_prefix.with_name(f"{output_prefix.name}_endpoints").with_suffix(".csv")
        ),
        "report_md": str(output_prefix.with_suffix(".md")),
    }


def _baseline_row_index(baseline_case: str) -> int:
    if baseline_case not in CASE_ROW_INDEX:
        raise SystemExit(f"Unknown baseline case: {baseline_case}")
    return CASE_ROW_INDEX[baseline_case]


def _validate_baseline_present(selected_cases: Sequence[str], baseline_case: str) -> None:
    if baseline_case not in selected_cases:
        raise SystemExit(
            f"Baseline case '{baseline_case}' is not included in the selected case set."
        )


def _validate_baseline_in_csv(path: Path, baseline_case: str) -> None:
    baseline_index = str(_baseline_row_index(baseline_case))
    rows = _csv_rows(path)
    if not any(str(row.get("plan_row_index", "")).strip() == baseline_index for row in rows):
        raise SystemExit(
            f"Baseline case '{baseline_case}' (plan_row_index {baseline_index}) is not present in {path}."
        )


def _pair_validation_result(
    *,
    family: str,
    low_case: Dict[str, Any],
    high_case: Dict[str, Any],
    hop_tolerance: float,
    min_overlap_ratio: float,
) -> Dict[str, Any]:
    hop_delta = abs(
        float(low_case["avg_hop_count"]) - float(high_case["avg_hop_count"])
    )
    low_score = float(low_case["route_overlap_score"])
    high_score = float(high_case["route_overlap_score"])
    ratio = None
    passes_hop = hop_delta <= hop_tolerance
    if low_score == 0.0:
        passes_overlap = high_score > 0.0 and (
            int(high_case["max_flows_on_any_resource"])
            > int(low_case["max_flows_on_any_resource"])
        )
    else:
        ratio = high_score / low_score
        passes_overlap = ratio >= min_overlap_ratio
    return {
        "pattern_family": family,
        "low_case": low_case["case_name"],
        "high_case": high_case["case_name"],
        "avg_hop_count_low": low_case["avg_hop_count"],
        "avg_hop_count_high": high_case["avg_hop_count"],
        "hop_delta": round(hop_delta, 6),
        "hop_match_tolerance": hop_tolerance,
        "route_overlap_score_low": low_score,
        "route_overlap_score_high": high_score,
        "measured_overlap_ratio": round(ratio, 6) if ratio is not None else None,
        "min_overlap_ratio": min_overlap_ratio,
        "passes_hop_match": passes_hop,
        "passes_overlap_separation": passes_overlap,
        "passes": passes_hop and passes_overlap,
    }


def _validate_pair_requirements(
    validations: Dict[str, Dict[str, Any]],
    *,
    hop_tolerance: float,
    min_overlap_ratio: float,
    allow_validation_failures: bool,
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    by_family: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for case_name, validation in validations.items():
        by_family[validation["pattern_family"]][validation["overlap_class"]] = validation

    for family in PATTERN_FAMILIES:
        variants = by_family.get(family, {})
        low_case = variants.get("low_overlap")
        high_case = variants.get("high_overlap")
        if low_case is None or high_case is None:
            raise SystemExit(f"Pattern family '{family}' is missing low/high overlap cases.")
        result = _pair_validation_result(
            family=family,
            low_case=low_case,
            high_case=high_case,
            hop_tolerance=hop_tolerance,
            min_overlap_ratio=min_overlap_ratio,
        )
        results[family] = result
        if not result["passes"] and not allow_validation_failures:
            raise SystemExit(
                f"Experiment 2 pair validation failed for {family}: "
                f"hop_delta={result['hop_delta']} "
                f"(tolerance {hop_tolerance}), "
                f"overlap_ratio={result['measured_overlap_ratio']} "
                f"(minimum {min_overlap_ratio})."
            )
    return results


def _build_validations(
    *,
    artifact_root: Path,
    command_log: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    route_root = artifact_root / "generated_routes"
    validations: Dict[str, Dict[str, Any]] = {}
    for case in CASE_SPECS:
        topology_meta = validate_case_topology(case)
        generated_paths = _generate_route_artifacts(
            case=case,
            route_root=route_root,
            command_log=command_log,
        )
        validations[case.case_name] = validate_route_artifacts(
            case,
            topology_meta,
            ncr_path=generated_paths["ncr"],
            nts_path=generated_paths["nts"],
        )
    return validations


def _write_route_metric_artifacts(
    artifact_root: Path, validations: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, str]]:
    metrics_dir = artifact_root / "route_metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    per_case_paths: Dict[str, Dict[str, str]] = {}
    aggregate_rows: List[Dict[str, Any]] = []
    for case in CASE_SPECS:
        validation = validations[case.case_name]
        row = {
            key: validation[key]
            for key in (
                "case_name",
                "pattern_family",
                "overlap_class",
                "topology_shape",
                "connection_json",
                "placement_json",
                "ncr",
                "nts",
                "num_sources",
                "num_destinations",
                "num_flows",
                "avg_hop_count",
                "max_hop_count",
                "max_flows_on_any_resource",
                "fraction_of_route_resources_shared_by_2_or_more_flows",
                "shared_resource_count",
                "top_shared_resource_id",
                "average_pairwise_route_overlap",
                "route_overlap_score",
                "num_data_nets",
            )
        }
        aggregate_rows.append(row)
        json_path = metrics_dir / f"{case.case_name}.json"
        csv_path = metrics_dir / f"{case.case_name}.csv"
        with json_path.open("w") as f:
            json.dump(row, f, indent=2, sort_keys=True)
            f.write("\n")
        _write_csv(csv_path, [row])
        per_case_paths[case.case_name] = {
            "route_metrics_json": str(json_path),
            "route_metrics_csv": str(csv_path),
        }
    _write_csv(metrics_dir / "experiment2_route_metrics.csv", aggregate_rows)
    with (metrics_dir / "experiment2_route_metrics.json").open("w") as f:
        json.dump(aggregate_rows, f, indent=2, sort_keys=True)
        f.write("\n")
    return per_case_paths


def _planned_case_manifest(
    *,
    case: CaseSpec,
    repeat_index: int,
    plan_path: Path,
    base_run_tag: str,
    hotspot_profile: str,
    validation: Dict[str, Any],
    route_metric_paths: Dict[str, str],
    analysis_included: bool,
) -> Dict[str, Any]:
    paths = _per_case_paths(plan_path, base_run_tag, repeat_index, case)
    collected_case_root = plan_path.parent.parent / "collected" / _repeat_slug(repeat_index) / case.case_name
    return {
        **validation,
        "repeat_index": repeat_index,
        "hotspot_mode": _hotspot_mode(hotspot_profile, case.case_name),
        "analysis_included": analysis_included,
        "gem5_results_csv": str(collected_case_root / "results" / paths["gem5_results_csv"].name),
        "route_metrics_json": route_metric_paths["route_metrics_json"],
        "route_metrics_csv": route_metric_paths["route_metrics_csv"],
        "route_source_path": str(collected_case_root / "routes" / "noc_subsystem.ncr"),
        "route_to_vc_path": "",
        "topology_artifact_dir": str(collected_case_root / "noc_desc"),
        "simlog_path": str(collected_case_root / "simlogs" / paths["simlog_path"].name),
        "hotspot_artifact_dir": str(collected_case_root / "hotspot"),
    }


def _build_noc_sweep_cmd(
    *,
    plan_path: Path,
    row_index: int,
    run_tag: str,
    hotspot_mode: str,
) -> List[str]:
    return [
        sys.executable,
        str(WORKSPACE / "noc_sweep.py"),
        "--plan",
        str(plan_path),
        "--mode",
        "gem5_only",
        "--row",
        str(row_index),
        "--run-tag",
        run_tag,
        "--hotspot-mode",
        hotspot_mode,
    ]


def _default_manifest(
    *,
    args: argparse.Namespace,
    base_run_tag: str,
    selected_cases: Sequence[str],
    repeat_indices: Sequence[int],
    plan_path: Path,
    validations: Dict[str, Dict[str, Any]],
    pair_validations: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "experiment": "experiment2",
        "mode": args.mode,
        "run_tag": base_run_tag,
        "artifact_root": str(plan_path.parent.parent),
        "plan_csv": str(plan_path),
        "selected_cases": list(selected_cases),
        "hotspot_profile": args.hotspot_profile,
        "repeats": args.repeats,
        "selected_repeat_indices": list(repeat_indices),
        "baseline_case": args.baseline_case,
        "baseline_plan_row_index": _baseline_row_index(args.baseline_case),
        "hop_match_tolerance": args.hop_match_tolerance,
        "min_overlap_ratio": args.min_overlap_ratio,
        "allow_validation_failures": args.allow_validation_failures,
        "workload": _workload_settings(args),
        "case_validation": validations,
        "pair_validation": pair_validations,
        "planned_commands": [],
        "executed_commands": [],
        "repeat_outputs": [],
        "combined_across_repeats_csv": "",
    }


def _write_manifest(path: Path, manifest: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


def _join_summary_rows(
    summary_rows: Sequence[Dict[str, str]],
    validations: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    joined: list[Dict[str, Any]] = []
    for row in summary_rows:
        case_name = str(row.get("name", "")).strip()
        if case_name not in validations:
            joined.append(dict(row))
            continue
        merged = dict(row)
        validation = validations[case_name]
        for key in (
            "pattern_family",
            "overlap_class",
            "topology_shape",
            "connection_json",
            "placement_json",
            "ncr",
            "nts",
            "num_sources",
            "num_destinations",
            "num_flows",
            "avg_hop_count",
            "max_hop_count",
            "max_flows_on_any_resource",
            "fraction_of_route_resources_shared_by_2_or_more_flows",
            "top_shared_resource_id",
            "average_pairwise_route_overlap",
            "route_overlap_score",
        ):
            merged[key] = validation.get(key, "")
        joined.append(merged)
    return joined


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any, digits: int = 3) -> str:
    number = _as_float(value)
    if number is None:
        text = str(value).strip() if value is not None else ""
        return text or "n/a"
    return f"{number:.{digits}f}"


def _write_experiment_report(
    path: Path,
    rows: Sequence[Dict[str, Any]],
    pair_validations: Dict[str, Dict[str, Any]],
    baseline_case: str,
) -> None:
    by_name = {str(row.get("name", "")).strip(): row for row in rows}
    with path.open("w") as f:
        f.write("# Experiment 2 Report\n\n")
        f.write(
            "This report joins route-overlap metrics with topology-analysis metrics "
            f"for baseline `{baseline_case}`.\n\n"
        )
        for family in PATTERN_FAMILIES:
            validation = pair_validations[family]
            low = by_name.get(validation["low_case"])
            high = by_name.get(validation["high_case"])
            f.write(f"## {family.title()}\n\n")
            if low is None or high is None:
                f.write("Selected results did not include both low/high overlap cases.\n\n")
                continue
            p99_low = _as_float(low.get("worst_p99_cycles"))
            p99_high = _as_float(high.get("worst_p99_cycles"))
            jfi_low = _as_float(low.get("min_jfi"))
            jfi_high = _as_float(high.get("min_jfi"))
            hotspot_low = _as_float(low.get("hotspot_top1_share"))
            hotspot_high = _as_float(high.get("hotspot_top1_share"))
            f.write(
                f"- hop match: low={_fmt(validation['avg_hop_count_low'])}, "
                f"high={_fmt(validation['avg_hop_count_high'])}, "
                f"delta={_fmt(validation['hop_delta'])}\n"
            )
            f.write(
                f"- overlap: low={_fmt(validation['route_overlap_score_low'])}, "
                f"high={_fmt(validation['route_overlap_score_high'])}, "
                f"ratio={_fmt(validation['measured_overlap_ratio'])}\n"
            )
            f.write(
                f"- worst_p99_cycles: low={_fmt(p99_low)}, high={_fmt(p99_high)}, "
                f"delta={_fmt((p99_high - p99_low) if p99_low is not None and p99_high is not None else None)}\n"
            )
            f.write(
                f"- min_jfi: low={_fmt(jfi_low)}, high={_fmt(jfi_high)}, "
                f"delta={_fmt((jfi_high - jfi_low) if jfi_low is not None and jfi_high is not None else None)}\n"
            )
            f.write(
                f"- hotspot_top1_share: low={_fmt(hotspot_low)}, high={_fmt(hotspot_high)}, "
                f"delta={_fmt((hotspot_high - hotspot_low) if hotspot_low is not None and hotspot_high is not None else None)}\n"
            )
            f.write(
                f"- top_shared_resource_id: low=`{low.get('top_shared_resource_id', '') or 'n/a'}`, "
                f"high=`{high.get('top_shared_resource_id', '') or 'n/a'}`\n\n"
            )


def _postprocess_analysis(
    *,
    artifact_root: Path,
    repeat_index: int,
    validations: Dict[str, Dict[str, Any]],
    pair_validations: Dict[str, Dict[str, Any]],
    topology_analysis_outputs: Dict[str, str],
    route_metrics_paths: Dict[str, Dict[str, str]],
    baseline_case: str,
) -> Dict[str, str]:
    summary_path = Path(topology_analysis_outputs["summary_csv"])
    joined_rows = _join_summary_rows(_csv_rows(summary_path), validations)
    final_csv_path = artifact_root / "analysis" / f"{_repeat_slug(repeat_index)}_final.csv"
    _write_csv(final_csv_path, joined_rows)
    final_report_path = artifact_root / "analysis" / f"{_repeat_slug(repeat_index)}_final.md"
    _write_experiment_report(final_report_path, joined_rows, pair_validations, baseline_case)
    return {
        **topology_analysis_outputs,
        "final_summary_csv": str(final_csv_path),
        "final_report_md": str(final_report_path),
        "route_metrics_csv": str(
            artifact_root / "route_metrics" / "experiment2_route_metrics.csv"
        ),
        "route_metrics_json": str(
            artifact_root / "route_metrics" / "experiment2_route_metrics.json"
        ),
    }


def run_plan_only(
    *,
    args: argparse.Namespace,
    base_run_tag: str,
    artifact_root: Path,
    plan_path: Path,
    manifest_path: Path,
    selected_cases: Sequence[str],
    repeat_indices: Sequence[int],
    validations: Dict[str, Dict[str, Any]],
    pair_validations: Dict[str, Dict[str, Any]],
    preflight_command_log: List[Dict[str, Any]],
) -> int:
    route_metric_paths = _write_route_metric_artifacts(artifact_root, validations)
    manifest = _default_manifest(
        args=args,
        base_run_tag=base_run_tag,
        selected_cases=selected_cases,
        repeat_indices=repeat_indices,
        plan_path=plan_path,
        validations=validations,
        pair_validations=pair_validations,
    )
    manifest["executed_commands"].extend(preflight_command_log)
    for repeat_index in repeat_indices:
        repeat_cases = []
        for case_name in selected_cases:
            case = CASE_BY_NAME[case_name]
            repeat_cases.append(
                _planned_case_manifest(
                    case=case,
                    repeat_index=repeat_index,
                    plan_path=plan_path,
                    base_run_tag=manifest["run_tag"],
                    hotspot_profile=args.hotspot_profile,
                    validation=validations[case_name],
                    route_metric_paths=route_metric_paths[case_name],
                    analysis_included=False,
                )
            )
            manifest["planned_commands"].append(
                _stringify_cmd(
                    _build_noc_sweep_cmd(
                        plan_path=plan_path,
                        row_index=CASE_ROW_INDEX[case_name],
                        run_tag=_case_run_tag(manifest["run_tag"], repeat_index, case_name),
                        hotspot_mode=_hotspot_mode(args.hotspot_profile, case_name),
                    )
                )
            )
        manifest["repeat_outputs"].append({"repeat_index": repeat_index, "cases": repeat_cases})
    _write_manifest(manifest_path, manifest)
    print(f"Plan written to: {plan_path}")
    print(f"Manifest written to: {manifest_path}")
    return 0


def run_experiment(
    *,
    args: argparse.Namespace,
    base_run_tag: str,
    artifact_root: Path,
    plan_path: Path,
    manifest_path: Path,
    selected_cases: Sequence[str],
    repeat_indices: Sequence[int],
    validations: Dict[str, Dict[str, Any]],
    pair_validations: Dict[str, Dict[str, Any]],
    preflight_command_log: List[Dict[str, Any]],
) -> int:
    _validate_baseline_present(selected_cases, args.baseline_case)
    route_metric_paths = _write_route_metric_artifacts(artifact_root, validations)
    manifest = _default_manifest(
        args=args,
        base_run_tag=base_run_tag,
        selected_cases=selected_cases,
        repeat_indices=repeat_indices,
        plan_path=plan_path,
        validations=validations,
        pair_validations=pair_validations,
    )
    manifest["executed_commands"].extend(preflight_command_log)
    repeat_combined_csvs: list[Path] = []
    for repeat_index in repeat_indices:
        print(f"Running Experiment 2 repeat {repeat_index}/{args.repeats}")
        combined_rows: list[Dict[str, Any]] = []
        repeat_case_outputs: list[Dict[str, Any]] = []
        for case_name in selected_cases:
            case = CASE_BY_NAME[case_name]
            hotspot_mode = _hotspot_mode(args.hotspot_profile, case_name)
            case_tag = _case_run_tag(base_run_tag, repeat_index, case_name)
            cmd = _build_noc_sweep_cmd(
                plan_path=plan_path,
                row_index=CASE_ROW_INDEX[case_name],
                run_tag=case_tag,
                hotspot_mode=hotspot_mode,
            )
            manifest["planned_commands"].append(_stringify_cmd(cmd))
            print(f"  Running {case_name} with hotspot_mode={hotspot_mode}")
            _run_cmd(
                cmd,
                cwd=REPO_ROOT,
                command_log=manifest["executed_commands"],
                label=f"noc_sweep:{case_name}:repeat{repeat_index}",
            )
            paths = _per_case_paths(plan_path, base_run_tag, repeat_index, case)
            result_csv = paths["gem5_results_csv"]
            if not result_csv.exists():
                raise SystemExit(f"Expected gem5 results CSV was not produced: {result_csv}")
            raw_rows = _csv_rows(result_csv)
            _collect_case_outputs(
                artifact_root=artifact_root,
                repeat_index=repeat_index,
                case=case,
                source_paths=paths,
                validation=validations[case_name],
                route_metrics_json=Path(route_metric_paths[case_name]["route_metrics_json"]),
                route_metrics_csv=Path(route_metric_paths[case_name]["route_metrics_csv"]),
            )
            combined_rows.extend(
                _combine_case_rows(
                    raw_rows,
                    case=case,
                    repeat_index=repeat_index,
                    validation=validations[case_name],
                )
            )
            repeat_case_outputs.append(
                _planned_case_manifest(
                    case=case,
                    repeat_index=repeat_index,
                    plan_path=plan_path,
                    base_run_tag=base_run_tag,
                    hotspot_profile=args.hotspot_profile,
                    validation=validations[case_name],
                    route_metric_paths=route_metric_paths[case_name],
                    analysis_included=True,
                )
            )

        repeat_dir = artifact_root / "results"
        repeat_dir.mkdir(parents=True, exist_ok=True)
        joined_gem5_csv = repeat_dir / f"{_repeat_slug(repeat_index)}_joined_gem5.csv"
        _write_csv(joined_gem5_csv, combined_rows)
        repeat_combined_csvs.append(joined_gem5_csv)
        topology_outputs = _run_analysis(
            gem5_results=joined_gem5_csv,
            output_prefix=_analysis_prefix(artifact_root, repeat_index),
            baseline_row_index=_baseline_row_index(args.baseline_case),
            command_log=manifest["executed_commands"],
        )
        analysis_outputs = _postprocess_analysis(
            artifact_root=artifact_root,
            repeat_index=repeat_index,
            validations=validations,
            pair_validations=pair_validations,
            topology_analysis_outputs=topology_outputs,
            route_metrics_paths=route_metric_paths,
            baseline_case=args.baseline_case,
        )
        manifest["repeat_outputs"].append(
            {
                "repeat_index": repeat_index,
                "combined_gem5_csv": str(joined_gem5_csv),
                "analysis": analysis_outputs,
                "cases": repeat_case_outputs,
            }
        )

    if len(repeat_combined_csvs) > 1:
        across_rows: list[Dict[str, Any]] = []
        for path in repeat_combined_csvs:
            across_rows.extend(_csv_rows(path))
        across_path = artifact_root / "results" / "combined_across_repeats_gem5.csv"
        _write_csv(across_path, across_rows)
        manifest["combined_across_repeats_csv"] = str(across_path)

    _write_manifest(manifest_path, manifest)
    print(f"Manifest written to: {manifest_path}")
    return 0


def run_analyze_only(
    *,
    args: argparse.Namespace,
    base_run_tag: str,
    artifact_root: Path,
    manifest_path: Path,
    validations: Dict[str, Dict[str, Any]],
    pair_validations: Dict[str, Dict[str, Any]],
    preflight_command_log: List[Dict[str, Any]],
) -> int:
    if args.gem5_results is None:
        raise SystemExit("--gem5-results is required for --mode analyze-only.")
    gem5_results = args.gem5_results.resolve()
    if not gem5_results.exists():
        raise SystemExit(f"gem5 results CSV not found: {gem5_results}")
    _validate_baseline_in_csv(gem5_results, args.baseline_case)
    route_metric_paths = _write_route_metric_artifacts(artifact_root, validations)
    command_log: list[Dict[str, Any]] = list(preflight_command_log)
    copied_input_csv = artifact_root / "results" / "analyze_only_input_gem5.csv"
    _copy_file_if_exists(gem5_results, copied_input_csv)
    topology_outputs = _run_analysis(
        gem5_results=copied_input_csv if copied_input_csv.exists() else gem5_results,
        output_prefix=artifact_root / "analysis" / "analyze_only_topology",
        baseline_row_index=_baseline_row_index(args.baseline_case),
        command_log=command_log,
    )
    analysis_outputs = _postprocess_analysis(
        artifact_root=artifact_root,
        repeat_index=1,
        validations=validations,
        pair_validations=pair_validations,
        topology_analysis_outputs=topology_outputs,
        route_metrics_paths=route_metric_paths,
        baseline_case=args.baseline_case,
    )
    manifest = {
        "experiment": "experiment2",
        "mode": args.mode,
        "run_tag": base_run_tag,
        "artifact_root": str(artifact_root),
        "gem5_results": str(copied_input_csv if copied_input_csv.exists() else gem5_results),
        "baseline_case": args.baseline_case,
        "baseline_plan_row_index": _baseline_row_index(args.baseline_case),
        "hop_match_tolerance": args.hop_match_tolerance,
        "min_overlap_ratio": args.min_overlap_ratio,
        "pair_validation": pair_validations,
        "analysis": analysis_outputs,
        "executed_commands": command_log,
    }
    _write_manifest(manifest_path, manifest)
    print(f"Analysis manifest written to: {manifest_path}")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and collect Experiment 2 evaluation results."
    )
    parser.add_argument(
        "--mode",
        choices=["run", "plan-only", "analyze-only"],
        default="run",
    )
    parser.add_argument("--run-tag")
    parser.add_argument("--case", action="append")
    parser.add_argument("--cases")
    parser.add_argument(
        "--hotspot-profile",
        choices=[HOTSPOT_PROFILE_NONE, HOTSPOT_PROFILE_ALL, HOTSPOT_PROFILE_RECOMMENDED],
        default=HOTSPOT_PROFILE_ALL,
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--repeat-index", type=int)
    parser.add_argument(
        "--baseline-case",
        choices=sorted(CASE_BY_NAME),
        default="shift_low_overlap",
    )
    parser.add_argument("--bandwidth-mbps", type=int, default=DEFAULT_BANDWIDTH_MBPS)
    parser.add_argument("--num-transactions", type=int, default=DEFAULT_NUM_TRANSACTIONS)
    parser.add_argument("--beat-bytes", type=int, default=DEFAULT_BEAT_BYTES)
    parser.add_argument("--beat-count", type=int, default=DEFAULT_BEAT_COUNT)
    parser.add_argument("--data-width-bits", type=int, default=DEFAULT_DATA_WIDTH_BITS)
    parser.add_argument(
        "--bram-data-width-bits", type=int, default=DEFAULT_BRAM_DATA_WIDTH_BITS
    )
    parser.add_argument("--noc-clk-mhz", type=int, default=DEFAULT_NOC_CLK_MHZ)
    parser.add_argument("--abs-max-tick", type=int, default=DEFAULT_ABS_MAX_TICK)
    parser.add_argument("--tg-mode", default=DEFAULT_TG_MODE)
    parser.add_argument("--gem5-results", type=Path)
    parser.add_argument("--hop-match-tolerance", type=float, default=1.5)
    parser.add_argument("--min-overlap-ratio", type=float, default=1.5)
    parser.add_argument("--allow-validation-failures", action="store_true")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    base_run_tag = _run_tag(args)
    selected_cases = _case_list_from_args(args)
    repeat_indices = _repeat_indices(args)
    artifact_root = args.artifact_root.resolve() / base_run_tag
    preflight_command_log: list[Dict[str, Any]] = []
    validations = _build_validations(
        artifact_root=artifact_root,
        command_log=preflight_command_log,
    )
    pair_validations = _validate_pair_requirements(
        validations,
        hop_tolerance=args.hop_match_tolerance,
        min_overlap_ratio=args.min_overlap_ratio,
        allow_validation_failures=args.allow_validation_failures,
    )
    plan_path = artifact_root / "plan" / PLAN_FILENAME
    manifest_path = artifact_root / "manifest.json"
    plan_rows = build_plan_rows(_workload_settings(args), validations)
    write_plan_csv(plan_path, plan_rows)

    if args.mode == "plan-only":
        return run_plan_only(
            args=args,
            base_run_tag=base_run_tag,
            artifact_root=artifact_root,
            plan_path=plan_path,
            manifest_path=manifest_path,
            selected_cases=selected_cases,
            repeat_indices=repeat_indices,
            validations=validations,
            pair_validations=pair_validations,
            preflight_command_log=preflight_command_log,
        )
    if args.mode == "analyze-only":
        return run_analyze_only(
            args=args,
            base_run_tag=base_run_tag,
            artifact_root=artifact_root,
            manifest_path=manifest_path,
            validations=validations,
            pair_validations=pair_validations,
            preflight_command_log=preflight_command_log,
        )
    return run_experiment(
        args=args,
        base_run_tag=base_run_tag,
        artifact_root=artifact_root,
        plan_path=plan_path,
        manifest_path=manifest_path,
        selected_cases=selected_cases,
        repeat_indices=repeat_indices,
        validations=validations,
        pair_validations=pair_validations,
        preflight_command_log=preflight_command_log,
    )


if __name__ == "__main__":
    raise SystemExit(main())
