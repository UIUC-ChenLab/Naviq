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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import route_metrics


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parents[1]
REPO_ROOT = WORKSPACE.parent
RESULTS_DIR = WORKSPACE / "artifacts" / "results"
DEFAULT_ARTIFACT_ROOT = SCRIPT_DIR / "artifacts"
NOC_DESC_DIR = WORKSPACE / "artifacts" / "noc_desc"
SIMLOGS_DIR = WORKSPACE / "artifacts" / "simlogs"
HOTSPOT_DIR = WORKSPACE / "artifacts" / "hotspot"

DEFAULT_RUN_TAG_PREFIX = "experiment4"
DEFAULT_TRAFFIC_MODE = "mixed_rw"
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

MEMORY_PATH_HOTSPOT_STATUS = "not_computed"
PLAN_FILENAME = "experiment4_plan.csv"


@dataclass(frozen=True)
class CaseSpec:
    case_name: str
    subexperiment: str
    target_class: str
    attachment_mode: str
    source_placement_class: str
    topology_shape: str
    source_count: int
    target_count: int
    connection_json: str
    placement_json: str
    ncr: str
    nts: str
    enabled_by_default: bool = True


def _asset_route(case_name: str, suffix: str) -> str:
    return f"experiments/evaluation/assets/experiment4/{case_name}/noc_subsystem.{suffix}"


CASE_SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        "exp4_near_single_target",
        "4A",
        "bram_like",
        "single_target",
        "near",
        "4x1",
        4,
        1,
        "topology_jsons/multi_endpoint/exp4_4nmu_to_1bram_single_target_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp4_near_single_target.place.json",
        _asset_route("exp4_near_single_target", "ncr"),
        _asset_route("exp4_near_single_target", "nts"),
    ),
    CaseSpec(
        "exp4_far_single_target",
        "4A",
        "bram_like",
        "single_target",
        "far",
        "4x1",
        4,
        1,
        "topology_jsons/multi_endpoint/exp4_4nmu_to_1bram_single_target_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp4_far_single_target.place.json",
        _asset_route("exp4_far_single_target", "ncr"),
        _asset_route("exp4_far_single_target", "nts"),
    ),
    CaseSpec(
        "exp4_spread_single_target",
        "4A",
        "bram_like",
        "single_target",
        "spread",
        "4x1",
        4,
        1,
        "topology_jsons/multi_endpoint/exp4_4nmu_to_1bram_single_target_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp4_spread_single_target.place.json",
        _asset_route("exp4_spread_single_target", "ncr"),
        _asset_route("exp4_spread_single_target", "nts"),
    ),
    CaseSpec(
        "exp4_near_distributed_targets",
        "4B",
        "bram_like",
        "distributed_targets",
        "near",
        "4x4",
        4,
        4,
        "topology_jsons/multi_endpoint/exp4_4nmu_to_4bram_distributed_targets_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp4_near_distributed_targets.place.json",
        _asset_route("exp4_near_distributed_targets", "ncr"),
        _asset_route("exp4_near_distributed_targets", "nts"),
    ),
    CaseSpec(
        "exp4_far_distributed_targets",
        "4B",
        "bram_like",
        "distributed_targets",
        "far",
        "4x4",
        4,
        4,
        "topology_jsons/multi_endpoint/exp4_4nmu_to_4bram_distributed_targets_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp4_far_distributed_targets.place.json",
        _asset_route("exp4_far_distributed_targets", "ncr"),
        _asset_route("exp4_far_distributed_targets", "nts"),
    ),
    CaseSpec(
        "exp4_spread_distributed_targets",
        "4B",
        "bram_like",
        "distributed_targets",
        "spread",
        "4x4",
        4,
        4,
        "topology_jsons/multi_endpoint/exp4_4nmu_to_4bram_distributed_targets_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp4_spread_distributed_targets.place.json",
        _asset_route("exp4_spread_distributed_targets", "ncr"),
        _asset_route("exp4_spread_distributed_targets", "nts"),
    ),
)
CASE_BY_NAME = {case.case_name: case for case in CASE_SPECS}
CASE_ROW_INDEX = {case.case_name: index for index, case in enumerate(CASE_SPECS, 1)}
OFFICIAL_CASES = [case.case_name for case in CASE_SPECS if case.enabled_by_default]
HOTSPOT_RECOMMENDED_CASES = {
    "exp4_near_single_target",
    "exp4_far_single_target",
    "exp4_far_distributed_targets",
}
SAME_PLACEMENT_SINGLE_CASE = {
    "exp4_near_distributed_targets": "exp4_near_single_target",
    "exp4_far_distributed_targets": "exp4_far_single_target",
    "exp4_spread_distributed_targets": "exp4_spread_single_target",
}


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
        return list(OFFICIAL_CASES)

    ordered: list[str] = []
    seen = set()
    for name in selected:
        if name not in CASE_BY_NAME:
            raise SystemExit(f"Unknown Experiment 4 case: {name}")
        if not CASE_BY_NAME[name].enabled_by_default and not args.enable_extension_cases:
            raise SystemExit(
                f"Case '{name}' is an extension case. Re-run with --enable-extension-cases."
            )
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


def _sanitize_name_token(name: str) -> str:
    token = re.sub(r"[\s,:/]+", "_", name).strip("_")
    return token or "unnamed_row"


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _port_component(endpoint: str) -> str:
    return endpoint.split(".", 1)[0]


def _tg_mode_for_traffic_mode(traffic_mode: str) -> str:
    if traffic_mode == "mixed_rw":
        return "rw_interleaved"
    if traffic_mode == "read_only":
        return "read_only"
    if traffic_mode == "write_only":
        return "write_only"
    raise SystemExit(f"Unsupported traffic mode: {traffic_mode}")


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

    if len(masters) != case.source_count:
        raise SystemExit(
            f"{path} does not define exactly {case.source_count} AXI-MM masters."
        )
    if len(slaves) != case.target_count:
        raise SystemExit(
            f"{path} does not define exactly {case.target_count} AXI-MM slaves."
        )
    if num_sources != case.source_count:
        raise SystemExit(
            f"{path} references {num_sources} sources but expected {case.source_count}."
        )
    if num_destinations != case.target_count:
        raise SystemExit(
            f"{path} references {num_destinations} destinations but expected {case.target_count}."
        )
    if num_flows != case.source_count:
        raise SystemExit(
            f"{path} defines {num_flows} flows but expected {case.source_count}."
        )
    if referenced_sources != masters:
        raise SystemExit(f"{path} does not connect every AXI-MM master exactly once.")
    if referenced_dests != slaves:
        raise SystemExit(f"{path} does not connect every AXI-MM slave in the declared set.")
    if any(count != 1 for count in source_counts.values()):
        raise SystemExit(f"{path} has a source with fanout != 1.")

    if case.attachment_mode == "single_target":
        if case.topology_shape != "4x1":
            raise SystemExit(f"{case.case_name} has inconsistent topology shape metadata.")
        if sorted(dest_counts.values()) != [case.source_count]:
            raise SystemExit(
                f"{path} does not route all {case.source_count} sources into one target."
            )
    elif case.attachment_mode == "distributed_targets":
        if case.topology_shape != "4x4":
            raise SystemExit(f"{case.case_name} has inconsistent topology shape metadata.")
        if any(count != 1 for count in dest_counts.values()):
            raise SystemExit(f"{path} does not distribute one flow per target.")
    else:
        raise SystemExit(f"Unsupported attachment mode: {case.attachment_mode}")

    return {
        "case_name": case.case_name,
        "subexperiment": case.subexperiment,
        "target_class": case.target_class,
        "attachment_mode": case.attachment_mode,
        "source_placement_class": case.source_placement_class,
        "topology_shape": case.topology_shape,
        "source_count": case.source_count,
        "traffic_mode": DEFAULT_TRAFFIC_MODE,
        "connection_json": f"noc_testing/{case.connection_json}",
        "placement_json": f"noc_testing/{case.placement_json}",
        "routing_mode": "pinned_ncr_nts",
        "num_sources": num_sources,
        "num_destinations": num_destinations,
        "num_flows": num_flows,
    }


def validate_route_artifacts(case: CaseSpec, topology_meta: Dict[str, Any]) -> Dict[str, Any]:
    ncr_path = _workspace_path(case.ncr)
    nts_path = _workspace_path(case.nts)
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
        "ncr": f"noc_testing/{case.ncr}",
        "nts": f"noc_testing/{case.nts}",
        "route_source_path": f"noc_testing/{case.ncr}",
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
        "tg_mode": _tg_mode_for_traffic_mode(args.traffic_mode),
        "axi_write_len_beats": args.beat_count,
        "axi_write_size_bytes": args.beat_bytes,
        "axi_write_bandwidth_cfg_MBps": args.bandwidth_mbps,
        "num_write_transactions_cfg": args.num_transactions,
        "tg_axi_data_width_bits": args.data_width_bits,
        "bram_data_width": args.bram_data_width_bits,
        "noc_axi_clk_mhz": args.noc_clk_mhz,
        "abs_max_tick": args.abs_max_tick,
    }


def build_plan_rows(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for case in CASE_SPECS:
        if not case.enabled_by_default:
            continue
        row = {
            "name": case.case_name,
            "topology_json": case.connection_json,
            "placement_json": case.placement_json,
            "ncr": case.ncr,
            "nts": case.nts,
        }
        row.update(settings)
        rows.append(row)
    return rows


def write_plan_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        raise SystemExit("No Experiment 4 plan rows were generated.")
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
            _workspace_path(case.ncr),
            case_root / "routes" / "noc_subsystem.ncr",
        ),
        "collected_nts_path": _copy_file_if_exists(
            _workspace_path(case.nts),
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
    traffic_mode: str,
) -> List[Dict[str, Any]]:
    combined: list[Dict[str, Any]] = []
    for row in raw_rows:
        merged = dict(row)
        merged.update(
            {
                "experiment_case": case.case_name,
                "repeat_index": repeat_index,
                "subexperiment": case.subexperiment,
                "target_class": case.target_class,
                "attachment_mode": case.attachment_mode,
                "source_placement_class": case.source_placement_class,
                "source_count": case.source_count,
                "traffic_mode": traffic_mode,
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


def _write_route_metric_artifacts(
    artifact_root: Path,
    validations: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, str]]:
    metrics_dir = artifact_root / "route_metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    per_case_paths: Dict[str, Dict[str, str]] = {}
    aggregate_rows: List[Dict[str, Any]] = []
    for case in CASE_SPECS:
        if case.case_name not in validations:
            continue
        validation = validations[case.case_name]
        row = {
            key: validation[key]
            for key in (
                "case_name",
                "subexperiment",
                "target_class",
                "attachment_mode",
                "source_placement_class",
                "source_count",
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
    _write_csv(metrics_dir / "experiment4_route_metrics.csv", aggregate_rows)
    with (metrics_dir / "experiment4_route_metrics.json").open("w") as f:
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
    traffic_mode: str,
) -> Dict[str, Any]:
    paths = _per_case_paths(plan_path, base_run_tag, repeat_index, case)
    collected_case_root = plan_path.parent.parent / "collected" / _repeat_slug(repeat_index) / case.case_name
    return {
        **validation,
        "repeat_index": repeat_index,
        "traffic_mode": traffic_mode,
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
        "memory_path_hotspot_status": MEMORY_PATH_HOTSPOT_STATUS,
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
) -> Dict[str, Any]:
    return {
        "experiment": "experiment4",
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
        "enable_extension_cases": args.enable_extension_cases,
        "traffic_mode": args.traffic_mode,
        "workload": _workload_settings(args),
        "case_validation": validations,
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
    traffic_mode: str,
) -> List[Dict[str, Any]]:
    joined: list[Dict[str, Any]] = []
    for row in summary_rows:
        case_name = str(row.get("name", "")).strip()
        merged = dict(row)
        if case_name in validations:
            validation = validations[case_name]
            for key in (
                "subexperiment",
                "target_class",
                "attachment_mode",
                "source_placement_class",
                "source_count",
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
        merged["traffic_mode"] = traffic_mode
        merged["memory_path_hotspot_flag"] = ""
        merged["memory_path_hotspot_status"] = MEMORY_PATH_HOTSPOT_STATUS
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


def _apply_global_baseline_deltas(rows: List[Dict[str, Any]], baseline_case: str) -> None:
    baseline_row = None
    for row in rows:
        if str(row.get("name", "")).strip() == baseline_case:
            baseline_row = row
            break
    if baseline_row is None:
        raise SystemExit(f"Baseline case row '{baseline_case}' not present in joined summary.")

    baseline_hop = _as_float(baseline_row.get("avg_hop_count"))
    baseline_overlap = _as_float(baseline_row.get("route_overlap_score"))
    baseline_p99 = _as_float(baseline_row.get("worst_p99_cycles"))
    baseline_jfi = _as_float(baseline_row.get("min_jfi"))
    baseline_hotspot = _as_float(baseline_row.get("hotspot_top1_share"))
    baseline_bw = _as_float(baseline_row.get("mean_bw_MBps"))
    baseline_hotspot_loc = str(baseline_row.get("hotspot_primary_location", "")).strip()

    for row in rows:
        hop = _as_float(row.get("avg_hop_count"))
        overlap = _as_float(row.get("route_overlap_score"))
        p99 = _as_float(row.get("worst_p99_cycles"))
        jfi = _as_float(row.get("min_jfi"))
        hotspot = _as_float(row.get("hotspot_top1_share"))
        bw = _as_float(row.get("mean_bw_MBps"))
        hotspot_loc = str(row.get("hotspot_primary_location", "")).strip()

        row["avg_hop_delta_vs_baseline"] = (
            hop - baseline_hop if hop is not None and baseline_hop is not None else ""
        )
        row["route_overlap_delta_vs_baseline"] = (
            overlap - baseline_overlap
            if overlap is not None and baseline_overlap is not None
            else ""
        )
        row["worst_p99_delta_vs_baseline"] = (
            p99 - baseline_p99 if p99 is not None and baseline_p99 is not None else ""
        )
        row["min_jfi_delta_vs_baseline"] = (
            jfi - baseline_jfi if jfi is not None and baseline_jfi is not None else ""
        )
        row["hotspot_top1_share_delta_vs_baseline"] = (
            hotspot - baseline_hotspot
            if hotspot is not None and baseline_hotspot is not None
            else ""
        )
        row["mean_bw_delta_vs_baseline"] = (
            bw - baseline_bw if bw is not None and baseline_bw is not None else ""
        )
        row["primary_hotspot_changed_vs_baseline"] = hotspot_loc != baseline_hotspot_loc


def _apply_same_placement_pairwise_deltas(rows: List[Dict[str, Any]]) -> None:
    by_name = {str(row.get("name", "")).strip(): row for row in rows}
    for row in rows:
        case_name = str(row.get("name", "")).strip()
        pair_case = SAME_PLACEMENT_SINGLE_CASE.get(case_name, "")
        row["same_placement_single_case"] = pair_case
        if not pair_case:
            row["delta_worst_p99_vs_same_placement_single"] = ""
            row["delta_mean_bw_vs_same_placement_single"] = ""
            row["delta_hotspot_top1_share_vs_same_placement_single"] = ""
            row["delta_route_overlap_vs_same_placement_single"] = ""
            row["delta_avg_hop_vs_same_placement_single"] = ""
            row["primary_hotspot_changed_vs_same_placement_single"] = ""
            continue
        pair_row = by_name.get(pair_case)
        if pair_row is None:
            row["delta_worst_p99_vs_same_placement_single"] = ""
            row["delta_mean_bw_vs_same_placement_single"] = ""
            row["delta_hotspot_top1_share_vs_same_placement_single"] = ""
            row["delta_route_overlap_vs_same_placement_single"] = ""
            row["delta_avg_hop_vs_same_placement_single"] = ""
            row["primary_hotspot_changed_vs_same_placement_single"] = ""
            continue

        row_p99 = _as_float(row.get("worst_p99_cycles"))
        pair_p99 = _as_float(pair_row.get("worst_p99_cycles"))
        row_bw = _as_float(row.get("mean_bw_MBps"))
        pair_bw = _as_float(pair_row.get("mean_bw_MBps"))
        row_hotspot = _as_float(row.get("hotspot_top1_share"))
        pair_hotspot = _as_float(pair_row.get("hotspot_top1_share"))
        row_overlap = _as_float(row.get("route_overlap_score"))
        pair_overlap = _as_float(pair_row.get("route_overlap_score"))
        row_hop = _as_float(row.get("avg_hop_count"))
        pair_hop = _as_float(pair_row.get("avg_hop_count"))
        row_hotspot_loc = str(row.get("hotspot_primary_location", "")).strip()
        pair_hotspot_loc = str(pair_row.get("hotspot_primary_location", "")).strip()

        row["delta_worst_p99_vs_same_placement_single"] = (
            row_p99 - pair_p99 if row_p99 is not None and pair_p99 is not None else ""
        )
        row["delta_mean_bw_vs_same_placement_single"] = (
            row_bw - pair_bw if row_bw is not None and pair_bw is not None else ""
        )
        row["delta_hotspot_top1_share_vs_same_placement_single"] = (
            row_hotspot - pair_hotspot
            if row_hotspot is not None and pair_hotspot is not None
            else ""
        )
        row["delta_route_overlap_vs_same_placement_single"] = (
            row_overlap - pair_overlap
            if row_overlap is not None and pair_overlap is not None
            else ""
        )
        row["delta_avg_hop_vs_same_placement_single"] = (
            row_hop - pair_hop if row_hop is not None and pair_hop is not None else ""
        )
        row["primary_hotspot_changed_vs_same_placement_single"] = (
            row_hotspot_loc != pair_hotspot_loc
        )


def _write_experiment_report(
    path: Path,
    rows: Sequence[Dict[str, Any]],
    baseline_case: str,
) -> None:
    by_name = {str(row.get("name", "")).strip(): row for row in rows}
    with path.open("w") as f:
        f.write("# Experiment 4 Report\n\n")
        f.write(
            "This is a BRAM-like memory endpoint attachment study for AXI-MM memory-style traffic. "
            f"Global baseline: `{baseline_case}`.\n\n"
        )
        f.write(
            "Interpretation boundary: distributed targets in 4B change both NoC convergence and "
            "target-side distribution. Results should be read as attachment-path distribution effects, "
            "not as proof that distributed targets are always better.\n\n"
        )

        f.write("## 4A Near vs Far Placement\n\n")
        for case_name in (
            "exp4_near_single_target",
            "exp4_far_single_target",
            "exp4_spread_single_target",
        ):
            row = by_name.get(case_name)
            if row is None:
                continue
            f.write(f"### {row.get('source_placement_class', case_name)}\n\n")
            f.write(f"- worst_p99_cycles: {_fmt(row.get('worst_p99_cycles'))}\n")
            f.write(f"- mean_bw_MBps: {_fmt(row.get('mean_bw_MBps'))}\n")
            f.write(f"- min_jfi: {_fmt(row.get('min_jfi'))}\n")
            f.write(f"- hotspot_top1_share: {_fmt(row.get('hotspot_top1_share'))}\n")
            f.write(
                f"- hotspot_primary_location: `{row.get('hotspot_primary_location', '') or 'n/a'}`\n"
            )
            f.write(f"- avg_hop_count: {_fmt(row.get('avg_hop_count'))}\n")
            f.write(f"- route_overlap_score: {_fmt(row.get('route_overlap_score'))}\n")
            f.write(
                f"- worst_p99_delta_vs_baseline: {_fmt(row.get('worst_p99_delta_vs_baseline'))}\n"
            )
            f.write(
                f"- primary_hotspot_changed_vs_baseline: "
                f"{'yes' if row.get('primary_hotspot_changed_vs_baseline') else 'no'}\n\n"
            )

        f.write("## 4B Single vs Distributed Targets\n\n")
        for case_name in (
            "exp4_near_distributed_targets",
            "exp4_far_distributed_targets",
            "exp4_spread_distributed_targets",
        ):
            row = by_name.get(case_name)
            if row is None:
                continue
            f.write(
                f"### {row.get('source_placement_class', case_name)}: "
                f"`{row.get('same_placement_single_case', 'n/a')}` -> `{case_name}`\n\n"
            )
            f.write(f"- delta_worst_p99_vs_same_placement_single: {_fmt(row.get('delta_worst_p99_vs_same_placement_single'))}\n")
            f.write(f"- delta_mean_bw_vs_same_placement_single: {_fmt(row.get('delta_mean_bw_vs_same_placement_single'))}\n")
            f.write(
                f"- delta_hotspot_top1_share_vs_same_placement_single: "
                f"{_fmt(row.get('delta_hotspot_top1_share_vs_same_placement_single'))}\n"
            )
            f.write(
                f"- delta_route_overlap_vs_same_placement_single: "
                f"{_fmt(row.get('delta_route_overlap_vs_same_placement_single'))}\n"
            )
            f.write(
                f"- delta_avg_hop_vs_same_placement_single: "
                f"{_fmt(row.get('delta_avg_hop_vs_same_placement_single'))}\n"
            )
            f.write(
                f"- primary_hotspot_changed_vs_same_placement_single: "
                f"{'yes' if row.get('primary_hotspot_changed_vs_same_placement_single') else 'no'}\n"
            )
            f.write(
                f"- hotspot_primary_location: `{row.get('hotspot_primary_location', '') or 'n/a'}`\n\n"
            )

        f.write(
            "Final interpretation: changing placement and distribution of BRAM-like targets changes "
            "NoC paths, hotspot locations, and endpoint-level tail latency. Memory-style attachment "
            "should be analyzed as a NoC path and convergence problem, not only as an endpoint problem.\n"
        )


def _manifest_case_summaries(final_summary_csv: Path) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for row in _csv_rows(final_summary_csv):
        summaries.append(
            {
                "case_name": row.get("name", ""),
                "subexperiment": row.get("subexperiment", ""),
                "target_class": row.get("target_class", ""),
                "attachment_mode": row.get("attachment_mode", ""),
                "source_placement_class": row.get("source_placement_class", ""),
                "worst_p99_delta_vs_baseline": row.get("worst_p99_delta_vs_baseline", ""),
                "delta_worst_p99_vs_same_placement_single": row.get(
                    "delta_worst_p99_vs_same_placement_single", ""
                ),
                "primary_hotspot_changed_vs_baseline": row.get(
                    "primary_hotspot_changed_vs_baseline", ""
                ),
                "primary_hotspot_changed_vs_same_placement_single": row.get(
                    "primary_hotspot_changed_vs_same_placement_single", ""
                ),
            }
        )
    return summaries


def _postprocess_analysis(
    *,
    artifact_root: Path,
    repeat_index: int,
    validations: Dict[str, Dict[str, Any]],
    topology_analysis_outputs: Dict[str, str],
    baseline_case: str,
    traffic_mode: str,
) -> Dict[str, str]:
    summary_path = Path(topology_analysis_outputs["summary_csv"])
    joined_rows = _join_summary_rows(_csv_rows(summary_path), validations, traffic_mode)
    _apply_global_baseline_deltas(joined_rows, baseline_case)
    _apply_same_placement_pairwise_deltas(joined_rows)
    final_csv_path = artifact_root / "analysis" / f"{_repeat_slug(repeat_index)}_final.csv"
    _write_csv(final_csv_path, joined_rows)
    final_report_path = artifact_root / "analysis" / f"{_repeat_slug(repeat_index)}_final.md"
    _write_experiment_report(final_report_path, joined_rows, baseline_case)
    return {
        **topology_analysis_outputs,
        "final_summary_csv": str(final_csv_path),
        "final_report_md": str(final_report_path),
        "route_metrics_csv": str(
            artifact_root / "route_metrics" / "experiment4_route_metrics.csv"
        ),
        "route_metrics_json": str(
            artifact_root / "route_metrics" / "experiment4_route_metrics.json"
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
    )
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
                    traffic_mode=args.traffic_mode,
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
    )
    repeat_combined_csvs: list[Path] = []
    for repeat_index in repeat_indices:
        print(f"Running Experiment 4 repeat {repeat_index}/{args.repeats}")
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
                route_metrics_json=Path(route_metric_paths[case_name]["route_metrics_json"]),
                route_metrics_csv=Path(route_metric_paths[case_name]["route_metrics_csv"]),
            )
            combined_rows.extend(
                _combine_case_rows(
                    raw_rows,
                    case=case,
                    repeat_index=repeat_index,
                    validation=validations[case_name],
                    traffic_mode=args.traffic_mode,
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
                    traffic_mode=args.traffic_mode,
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
            topology_analysis_outputs=topology_outputs,
            baseline_case=args.baseline_case,
            traffic_mode=args.traffic_mode,
        )
        manifest["repeat_outputs"].append(
            {
                "repeat_index": repeat_index,
                "combined_gem5_csv": str(joined_gem5_csv),
                "analysis": analysis_outputs,
                "final_case_summaries": _manifest_case_summaries(
                    Path(analysis_outputs["final_summary_csv"])
                ),
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
) -> int:
    if args.gem5_results is None:
        raise SystemExit("--gem5-results is required for --mode analyze-only.")
    gem5_results = args.gem5_results.resolve()
    if not gem5_results.exists():
        raise SystemExit(f"gem5 results CSV not found: {gem5_results}")
    _validate_baseline_in_csv(gem5_results, args.baseline_case)
    _write_route_metric_artifacts(artifact_root, validations)
    command_log: list[Dict[str, Any]] = []
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
        topology_analysis_outputs=topology_outputs,
        baseline_case=args.baseline_case,
        traffic_mode=args.traffic_mode,
    )
    manifest = {
        "experiment": "experiment4",
        "mode": args.mode,
        "run_tag": base_run_tag,
        "artifact_root": str(artifact_root),
        "gem5_results": str(copied_input_csv if copied_input_csv.exists() else gem5_results),
        "baseline_case": args.baseline_case,
        "baseline_plan_row_index": _baseline_row_index(args.baseline_case),
        "traffic_mode": args.traffic_mode,
        "analysis": analysis_outputs,
        "final_case_summaries": _manifest_case_summaries(
            Path(analysis_outputs["final_summary_csv"])
        ),
        "executed_commands": command_log,
    }
    _write_manifest(manifest_path, manifest)
    print(f"Analysis manifest written to: {manifest_path}")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and collect Experiment 4 evaluation results."
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
        default="exp4_near_single_target",
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
    parser.add_argument(
        "--traffic-mode",
        choices=["mixed_rw", "read_only", "write_only"],
        default=DEFAULT_TRAFFIC_MODE,
    )
    parser.add_argument("--gem5-results", type=Path)
    parser.add_argument("--enable-extension-cases", action="store_true")
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
    validations = {
        case.case_name: validate_route_artifacts(case, validate_case_topology(case))
        for case in CASE_SPECS
        if case.enabled_by_default or args.enable_extension_cases
    }
    for validation in validations.values():
        validation["traffic_mode"] = args.traffic_mode
    artifact_root = args.artifact_root.resolve() / base_run_tag
    plan_path = artifact_root / "plan" / PLAN_FILENAME
    manifest_path = artifact_root / "manifest.json"
    plan_rows = build_plan_rows(_workload_settings(args))
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
        )
    if args.mode == "analyze-only":
        return run_analyze_only(
            args=args,
            base_run_tag=base_run_tag,
            artifact_root=artifact_root,
            manifest_path=manifest_path,
            validations=validations,
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
    )


if __name__ == "__main__":
    raise SystemExit(main())
