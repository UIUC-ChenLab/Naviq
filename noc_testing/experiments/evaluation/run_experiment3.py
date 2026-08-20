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

DEFAULT_RUN_TAG_PREFIX = "experiment3"
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
class WorkloadSpec:
    workload_case: str
    connection_json: str
    placement_json: str
    topology_shape: str


@dataclass(frozen=True)
class StrategySpec:
    case_name: str
    strategy_class: str
    route_origin: str
    router_name: str


@dataclass(frozen=True)
class CaseSpec:
    workload_case: str
    case_name: str
    strategy_class: str
    route_origin: str
    router_name: str
    connection_json: str
    placement_json: str
    topology_shape: str


WORKLOAD_SPECS: tuple[WorkloadSpec, ...] = (
    WorkloadSpec(
        "exp1_4to1_far",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm.conn.json",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_spread.place.json",
        "4x1",
    ),
    WorkloadSpec(
        "exp2_shift",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_shift_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_shift.place.json",
        "4x4",
    ),
    WorkloadSpec(
        "exp2_reverse",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_reverse_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_reverse.place.json",
        "4x4",
    ),
    WorkloadSpec(
        "exp2_reverse_high_overlap",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_reverse_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_reverse.place.json",
        "4x4",
    ),
    WorkloadSpec(
        "exp2_tornado",
        "topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_tornado_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_tornado.place.json",
        "4x4",
    ),
    WorkloadSpec(
        "exp2_hotspot",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm.conn.json",
        "topology_jsons/multi_endpoint/exp2_hotspot.place.json",
        "4x1",
    ),
)
WORKLOAD_BY_NAME = {workload.workload_case: workload for workload in WORKLOAD_SPECS}

STRATEGY_SPECS: tuple[StrategySpec, ...] = (
    StrategySpec("exp3_shortest", "shortest", "generated_shortest", "shortest_path"),
    StrategySpec("exp3_bad_path", "bad_path", "generated_bad", "bad_path"),
    StrategySpec("exp3_high_overlap", "high_overlap", "generated_high_overlap", "high_overlap"),
    StrategySpec("exp3_path_diverse", "path_diverse", "generated_low_overlap", "low_overlap"),
)
STRATEGY_BY_NAME = {strategy.case_name: strategy for strategy in STRATEGY_SPECS}
CASE_ROW_INDEX = {strategy.case_name: index for index, strategy in enumerate(STRATEGY_SPECS, 1)}
PLAN_FILENAME = "experiment3_plan.csv"


def _repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(REPO_ROOT.resolve())
        return str(rel)
    except ValueError:
        return str(resolved)


def _workspace_path(rel_path: str) -> Path:
    return (WORKSPACE / rel_path).resolve()


def _runtime_cases(workload_case: str) -> tuple[CaseSpec, ...]:
    workload = WORKLOAD_BY_NAME[workload_case]
    return tuple(
        CaseSpec(
            workload_case=workload.workload_case,
            case_name=strategy.case_name,
            strategy_class=strategy.strategy_class,
            route_origin=strategy.route_origin,
            router_name=strategy.router_name,
            connection_json=workload.connection_json,
            placement_json=workload.placement_json,
            topology_shape=workload.topology_shape,
        )
        for strategy in STRATEGY_SPECS
    )


def _strategy_list_from_args(args: argparse.Namespace) -> list[str]:
    selected: list[str] = []
    if args.strategy:
        selected.extend(args.strategy)
    if args.strategies:
        for chunk in args.strategies.split(","):
            token = chunk.strip()
            if token:
                selected.append(token)
    if not selected:
        return [
            "exp3_shortest",
            "exp3_high_overlap",
            "exp3_path_diverse",
        ]

    ordered: list[str] = []
    seen = set()
    for name in selected:
        if name not in STRATEGY_BY_NAME:
            raise SystemExit(f"Unknown Experiment 3 strategy: {name}")
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
        "workload_case": case.workload_case,
        "strategy_class": case.strategy_class,
        "route_origin": case.route_origin,
        "router_name": case.router_name,
        "topology_shape": case.topology_shape,
        "connection_json": f"noc_testing/{case.connection_json}",
        "placement_json": f"noc_testing/{case.placement_json}",
        "routing_mode": case.router_name,
        "num_sources": num_sources,
        "num_destinations": num_destinations,
        "num_flows": num_flows,
    }


def _generated_route_paths(route_root: Path, case: CaseSpec) -> Dict[str, Path]:
    case_root = route_root / case.workload_case / case.case_name
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
        "ncr": _repo_rel(ncr_path),
        "nts": _repo_rel(nts_path),
        "route_source_path": _repo_rel(ncr_path),
        "route_to_vc_path": "",
        "hop_summary_status": "computed",
        "selection_rule_id": "",
        "k_shortest_paths_considered_per_direction": "",
        **metrics,
    }


def _build_validations(
    *,
    workload_case: str,
    artifact_root: Path,
    command_log: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    route_root = artifact_root / "generated_routes"
    validations: Dict[str, Dict[str, Any]] = {}
    for case in _runtime_cases(workload_case):
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


def _hotspot_mode(profile: str, case_name: str) -> str:
    if profile == HOTSPOT_PROFILE_NONE:
        return "off"
    if profile == HOTSPOT_PROFILE_ALL:
        return "both"
    if profile == HOTSPOT_PROFILE_RECOMMENDED:
        return "both"
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
    workload_case: str,
    settings: Dict[str, Any],
    validations: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for case in _runtime_cases(workload_case):
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
        raise SystemExit("No Experiment 3 plan rows were generated.")
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
                "workload_case": case.workload_case,
                "strategy_class": case.strategy_class,
                "route_origin": case.route_origin,
                "router_name": case.router_name,
                "selection_rule_id": validation["selection_rule_id"],
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


def _baseline_row_index(baseline_strategy: str) -> int:
    if baseline_strategy not in CASE_ROW_INDEX:
        raise SystemExit(f"Unknown baseline strategy: {baseline_strategy}")
    return CASE_ROW_INDEX[baseline_strategy]


def _validate_baseline_present(selected_strategies: Sequence[str], baseline_strategy: str) -> None:
    if baseline_strategy not in selected_strategies:
        raise SystemExit(
            f"Baseline strategy '{baseline_strategy}' is not included in the selected strategy set."
        )


def _validate_baseline_in_csv(path: Path, baseline_strategy: str) -> None:
    baseline_index = str(_baseline_row_index(baseline_strategy))
    rows = _csv_rows(path)
    if not any(str(row.get("plan_row_index", "")).strip() == baseline_index for row in rows):
        raise SystemExit(
            f"Baseline strategy '{baseline_strategy}' (plan_row_index {baseline_index}) "
            f"is not present in {path}."
        )


def _write_route_metric_artifacts(
    artifact_root: Path,
    validations: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, str]]:
    metrics_dir = artifact_root / "route_metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    per_case_paths: Dict[str, Dict[str, str]] = {}
    aggregate_rows: List[Dict[str, Any]] = []
    for strategy in STRATEGY_SPECS:
        validation = validations[strategy.case_name]
        row = {
            key: validation[key]
            for key in (
                "case_name",
                "workload_case",
                "strategy_class",
                "route_origin",
                "router_name",
                "selection_rule_id",
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
                "k_shortest_paths_considered_per_direction",
            )
        }
        aggregate_rows.append(row)
        json_path = metrics_dir / f"{strategy.case_name}.json"
        csv_path = metrics_dir / f"{strategy.case_name}.csv"
        with json_path.open("w") as f:
            json.dump(row, f, indent=2, sort_keys=True)
            f.write("\n")
        _write_csv(csv_path, [row])
        per_case_paths[strategy.case_name] = {
            "route_metrics_json": str(json_path),
            "route_metrics_csv": str(csv_path),
        }
    _write_csv(metrics_dir / "experiment3_route_metrics.csv", aggregate_rows)
    with (metrics_dir / "experiment3_route_metrics.json").open("w") as f:
        json.dump(aggregate_rows, f, indent=2, sort_keys=True)
        f.write("\n")
    return per_case_paths


def _strategy_validation_results(
    validations: Dict[str, Dict[str, Any]],
    *,
    selected_strategies: Sequence[str],
    min_bad_overlap_ratio: float,
    min_diverse_overlap_reduction_ratio: float,
    max_diverse_hop_increase: float,
    allow_validation_failures: bool,
) -> Dict[str, Dict[str, Any]]:
    shortest = validations["exp3_shortest"]
    shortest_score = float(shortest["route_overlap_score"])
    shortest_hop = float(shortest["avg_hop_count"])
    results: Dict[str, Dict[str, Any]] = {
        "exp3_shortest": {
            "case_name": "exp3_shortest",
            "passes": True,
        }
    }

    for strategy in STRATEGY_SPECS:
        if strategy.case_name == "exp3_shortest":
            continue
        validation = validations[strategy.case_name]
        score = float(validation["route_overlap_score"])
        hop = float(validation["avg_hop_count"])
        overlap_ratio_vs_shortest = None
        overlap_reduction_ratio_vs_shortest = None
        if shortest_score > 0.0:
            overlap_ratio_vs_shortest = score / shortest_score
            overlap_reduction_ratio_vs_shortest = shortest_score / score if score > 0.0 else float("inf")
        hop_increase = hop - shortest_hop
        result = {
            "case_name": strategy.case_name,
            "route_overlap_ratio_vs_shortest": round(overlap_ratio_vs_shortest, 6)
            if overlap_ratio_vs_shortest is not None
            else None,
            "route_overlap_reduction_ratio_vs_shortest": round(
                overlap_reduction_ratio_vs_shortest, 6
            )
            if overlap_reduction_ratio_vs_shortest is not None
            and overlap_reduction_ratio_vs_shortest != float("inf")
            else ("inf" if overlap_reduction_ratio_vs_shortest == float("inf") else None),
            "hop_increase_vs_shortest": round(hop_increase, 6),
            "passes": True,
            "candidate_strength": "",
        }

        if strategy.strategy_class in {"high_overlap", "bad_path"}:
            passes = (
                overlap_ratio_vs_shortest is not None
                and overlap_ratio_vs_shortest >= min_bad_overlap_ratio
            )
            result["passes"] = passes
            result["min_bad_overlap_ratio"] = min_bad_overlap_ratio
            if (
                strategy.case_name in selected_strategies
                and not passes
                and not allow_validation_failures
            ):
                raise SystemExit(
                    f"Experiment 3 {strategy.case_name} validation failed: "
                    f"overlap ratio={overlap_ratio_vs_shortest} minimum={min_bad_overlap_ratio}"
                )
        elif strategy.strategy_class == "path_diverse":
            passes = (
                overlap_reduction_ratio_vs_shortest is not None
                and overlap_reduction_ratio_vs_shortest >= min_diverse_overlap_reduction_ratio
                and hop >= shortest_hop
                and hop_increase <= max_diverse_hop_increase
            )
            candidate_strength = (
                "strong"
                if overlap_reduction_ratio_vs_shortest is not None
                and overlap_reduction_ratio_vs_shortest >= min_diverse_overlap_reduction_ratio
                else "weak"
            )
            result["passes"] = passes
            result["candidate_strength"] = candidate_strength
            result["min_diverse_overlap_reduction_ratio"] = min_diverse_overlap_reduction_ratio
            result["max_diverse_hop_increase"] = max_diverse_hop_increase
            if (
                strategy.case_name in selected_strategies
                and not passes
                and not allow_validation_failures
            ):
                raise SystemExit(
                    f"Experiment 3 {strategy.case_name} validation failed: "
                    f"overlap reduction ratio={overlap_reduction_ratio_vs_shortest}, "
                    f"hop increase={hop_increase}, minimum reduction={min_diverse_overlap_reduction_ratio}, "
                    f"max hop increase={max_diverse_hop_increase}"
                )
        results[strategy.case_name] = result
    return results


def _planned_case_manifest(
    *,
    case: CaseSpec,
    repeat_index: int,
    plan_path: Path,
    base_run_tag: str,
    hotspot_profile: str,
    validation: Dict[str, Any],
    strategy_validation: Dict[str, Any],
    route_metric_paths: Dict[str, str],
    analysis_included: bool,
) -> Dict[str, Any]:
    paths = _per_case_paths(plan_path, base_run_tag, repeat_index, case)
    collected_case_root = plan_path.parent.parent / "collected" / _repeat_slug(repeat_index) / case.case_name
    return {
        **validation,
        **strategy_validation,
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
    selected_strategies: Sequence[str],
    repeat_indices: Sequence[int],
    plan_path: Path,
    validations: Dict[str, Dict[str, Any]],
    strategy_validations: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "experiment": "experiment3",
        "mode": args.mode,
        "run_tag": base_run_tag,
        "artifact_root": str(plan_path.parent.parent),
        "plan_csv": str(plan_path),
        "workload_case": args.workload_case,
        "selected_strategies": list(selected_strategies),
        "hotspot_profile": args.hotspot_profile,
        "repeats": args.repeats,
        "selected_repeat_indices": list(repeat_indices),
        "baseline_strategy": args.baseline_strategy,
        "baseline_plan_row_index": _baseline_row_index(args.baseline_strategy),
        "min_bad_overlap_ratio": args.min_bad_overlap_ratio,
        "min_diverse_overlap_reduction_ratio": args.min_diverse_overlap_reduction_ratio,
        "max_diverse_hop_increase": args.max_diverse_hop_increase,
        "allow_validation_failures": args.allow_validation_failures,
        "workload": _workload_settings(args),
        "case_validation": validations,
        "strategy_validation": strategy_validations,
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
    strategy_validations: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    joined: list[Dict[str, Any]] = []
    for row in summary_rows:
        case_name = str(row.get("name", "")).strip()
        merged = dict(row)
        if case_name in validations:
            validation = validations[case_name]
            strategy_validation = strategy_validations[case_name]
            for key in (
                "workload_case",
                "strategy_class",
                "route_origin",
                "router_name",
                "selection_rule_id",
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
                "k_shortest_paths_considered_per_direction",
            ):
                merged[key] = validation.get(key, "")
            merged["validation_passed"] = strategy_validation.get("passes", True)
            merged["candidate_strength"] = strategy_validation.get("candidate_strength", "")
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


def _apply_shortest_deltas(rows: List[Dict[str, Any]], baseline_strategy: str) -> None:
    shortest_row = None
    for row in rows:
        if str(row.get("name", "")).strip() == baseline_strategy:
            shortest_row = row
            break
    if shortest_row is None:
        raise SystemExit(f"Baseline strategy row '{baseline_strategy}' not present in joined summary.")

    shortest_hop = _as_float(shortest_row.get("avg_hop_count"))
    shortest_overlap = _as_float(shortest_row.get("route_overlap_score"))
    shortest_p99 = _as_float(shortest_row.get("worst_p99_cycles"))
    shortest_jfi = _as_float(shortest_row.get("min_jfi"))
    shortest_hotspot = _as_float(shortest_row.get("hotspot_top1_share"))
    shortest_bw = _as_float(shortest_row.get("mean_bw_MBps"))
    shortest_hotspot_loc = str(shortest_row.get("hotspot_primary_location", "")).strip()

    for row in rows:
        hop = _as_float(row.get("avg_hop_count"))
        overlap = _as_float(row.get("route_overlap_score"))
        p99 = _as_float(row.get("worst_p99_cycles"))
        jfi = _as_float(row.get("min_jfi"))
        hotspot = _as_float(row.get("hotspot_top1_share"))
        bw = _as_float(row.get("mean_bw_MBps"))
        hotspot_loc = str(row.get("hotspot_primary_location", "")).strip()

        row["hop_delta_vs_shortest"] = (hop - shortest_hop) if hop is not None and shortest_hop is not None else ""
        row["hop_increase_vs_shortest"] = row["hop_delta_vs_shortest"]
        row["route_overlap_delta_vs_shortest"] = (
            overlap - shortest_overlap if overlap is not None and shortest_overlap is not None else ""
        )
        row["route_overlap_ratio_vs_shortest"] = (
            overlap / shortest_overlap
            if overlap is not None and shortest_overlap not in (None, 0.0)
            else ""
        )
        row["route_overlap_reduction_vs_shortest"] = (
            shortest_overlap - overlap if overlap is not None and shortest_overlap is not None else ""
        )
        row["worst_p99_delta_vs_shortest"] = (
            p99 - shortest_p99 if p99 is not None and shortest_p99 is not None else ""
        )
        row["min_jfi_delta_vs_shortest"] = (
            jfi - shortest_jfi if jfi is not None and shortest_jfi is not None else ""
        )
        row["hotspot_top1_share_delta_vs_shortest"] = (
            hotspot - shortest_hotspot
            if hotspot is not None and shortest_hotspot is not None
            else ""
        )
        row["mean_bw_delta_vs_shortest"] = (
            bw - shortest_bw if bw is not None and shortest_bw is not None else ""
        )
        row["primary_hotspot_changed_vs_shortest"] = hotspot_loc != shortest_hotspot_loc

        hop_delta = _as_float(row.get("hop_delta_vs_shortest"))
        overlap_reduction = _as_float(row.get("route_overlap_reduction_vs_shortest"))
        if p99 is not None and shortest_p99 is not None and hop_delta is not None and hop_delta > 0:
            row["p99_improvement_per_added_hop"] = (shortest_p99 - p99) / hop_delta
        else:
            row["p99_improvement_per_added_hop"] = ""
        if (
            p99 is not None
            and shortest_p99 is not None
            and overlap_reduction is not None
            and overlap_reduction > 0
        ):
            row["p99_improvement_per_overlap_reduction"] = (
                shortest_p99 - p99
            ) / overlap_reduction
        else:
            row["p99_improvement_per_overlap_reduction"] = ""


def _write_experiment_report(
    path: Path,
    rows: Sequence[Dict[str, Any]],
    baseline_strategy: str,
    workload_case: str,
) -> None:
    by_name = {str(row.get("name", "")).strip(): row for row in rows}
    shortest = by_name[baseline_strategy]
    with path.open("w") as f:
        f.write("# Experiment 3 Report\n\n")
        f.write(
            f"This is a routing-strategy study on workload `{workload_case}`, not a pattern-family sweep. "
            f"Baseline strategy: `{baseline_strategy}`.\n\n"
        )
        f.write(
            f"Baseline shortest route overlap score: {_fmt(shortest.get('route_overlap_score'))}, "
            f"worst_p99={_fmt(shortest.get('worst_p99_cycles'))}, "
            f"top_hotspot=`{shortest.get('hotspot_primary_location', '') or 'n/a'}`.\n\n"
        )
        for row in rows:
            strategy_name = str(row.get("name", "")).strip()
            if strategy_name == baseline_strategy:
                continue
            strategy_label = str(row.get("strategy_class", strategy_name))
            f.write(f"## {strategy_label}\n\n")
            if strategy_name == "exp3_path_diverse" and row.get("candidate_strength"):
                f.write(f"- candidate_strength: `{row.get('candidate_strength')}`\n")
            f.write(f"- route_origin: `{row.get('route_origin')}`\n")
            f.write(f"- router_name: `{row.get('router_name')}`\n")
            if row.get("selection_rule_id"):
                f.write(f"- selection_rule_id: `{row.get('selection_rule_id')}`\n")
            f.write(f"- hop_delta_vs_shortest: {_fmt(row.get('hop_delta_vs_shortest'))}\n")
            f.write(
                f"- route_overlap_score: shortest={_fmt(shortest.get('route_overlap_score'))}, "
                f"strategy={_fmt(row.get('route_overlap_score'))}, "
                f"ratio={_fmt(row.get('route_overlap_ratio_vs_shortest'))}\n"
            )
            f.write(
                f"- worst_p99_delta_vs_shortest: {_fmt(row.get('worst_p99_delta_vs_shortest'))}\n"
            )
            f.write(
                f"- min_jfi_delta_vs_shortest: {_fmt(row.get('min_jfi_delta_vs_shortest'))}\n"
            )
            f.write(
                f"- hotspot_top1_share_delta_vs_shortest: "
                f"{_fmt(row.get('hotspot_top1_share_delta_vs_shortest'))}\n"
            )
            f.write(
                f"- mean_bw_delta_vs_shortest: {_fmt(row.get('mean_bw_delta_vs_shortest'))}\n"
            )
            f.write(
                f"- primary_hotspot_changed_vs_shortest: "
                f"{'yes' if row.get('primary_hotspot_changed_vs_shortest') else 'no'}\n"
            )
            hotspot_delta = _as_float(row.get("hotspot_top1_share_delta_vs_shortest"))
            if hotspot_delta is not None and hotspot_delta < 0:
                relocation = "reduced hotspot concentration"
            elif row.get("primary_hotspot_changed_vs_shortest"):
                relocation = "hotspot moved without clear concentration reduction"
            else:
                relocation = "congestion appears concentrated similarly to shortest"
            f.write(f"- interpretation: {relocation}\n\n")


def _manifest_case_summaries(final_summary_csv: Path) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for row in _csv_rows(final_summary_csv):
        summaries.append(
            {
                "case_name": row.get("name", ""),
                "strategy_class": row.get("strategy_class", ""),
                "route_origin": row.get("route_origin", ""),
                "router_name": row.get("router_name", ""),
                "selection_rule_id": row.get("selection_rule_id", ""),
                "route_overlap_reduction_vs_shortest": row.get(
                    "route_overlap_reduction_vs_shortest", ""
                ),
                "hop_increase_vs_shortest": row.get("hop_increase_vs_shortest", ""),
                "primary_hotspot_changed_vs_shortest": row.get(
                    "primary_hotspot_changed_vs_shortest", ""
                ),
                "worst_p99_delta_vs_shortest": row.get("worst_p99_delta_vs_shortest", ""),
            }
        )
    return summaries


def _postprocess_analysis(
    *,
    artifact_root: Path,
    repeat_index: int,
    validations: Dict[str, Dict[str, Any]],
    strategy_validations: Dict[str, Dict[str, Any]],
    topology_analysis_outputs: Dict[str, str],
    workload_case: str,
    baseline_strategy: str,
) -> Dict[str, str]:
    summary_path = Path(topology_analysis_outputs["summary_csv"])
    joined_rows = _join_summary_rows(
        _csv_rows(summary_path),
        validations,
        strategy_validations,
    )
    _apply_shortest_deltas(joined_rows, baseline_strategy)
    final_csv_path = artifact_root / "analysis" / f"{_repeat_slug(repeat_index)}_final.csv"
    _write_csv(final_csv_path, joined_rows)
    final_report_path = artifact_root / "analysis" / f"{_repeat_slug(repeat_index)}_final.md"
    _write_experiment_report(final_report_path, joined_rows, baseline_strategy, workload_case)
    return {
        **topology_analysis_outputs,
        "final_summary_csv": str(final_csv_path),
        "final_report_md": str(final_report_path),
        "route_metrics_csv": str(
            artifact_root / "route_metrics" / "experiment3_route_metrics.csv"
        ),
        "route_metrics_json": str(
            artifact_root / "route_metrics" / "experiment3_route_metrics.json"
        ),
    }


def run_plan_only(
    *,
    args: argparse.Namespace,
    base_run_tag: str,
    artifact_root: Path,
    plan_path: Path,
    manifest_path: Path,
    selected_strategies: Sequence[str],
    repeat_indices: Sequence[int],
    validations: Dict[str, Dict[str, Any]],
    strategy_validations: Dict[str, Dict[str, Any]],
) -> int:
    route_metric_paths = _write_route_metric_artifacts(artifact_root, validations)
    cases_by_name = {case.case_name: case for case in _runtime_cases(args.workload_case)}
    manifest = _default_manifest(
        args=args,
        base_run_tag=base_run_tag,
        selected_strategies=selected_strategies,
        repeat_indices=repeat_indices,
        plan_path=plan_path,
        validations=validations,
        strategy_validations=strategy_validations,
    )
    for repeat_index in repeat_indices:
        repeat_cases = []
        for case_name in selected_strategies:
            case = cases_by_name[case_name]
            repeat_cases.append(
                _planned_case_manifest(
                    case=case,
                    repeat_index=repeat_index,
                    plan_path=plan_path,
                    base_run_tag=manifest["run_tag"],
                    hotspot_profile=args.hotspot_profile,
                    validation=validations[case_name],
                    strategy_validation=strategy_validations[case_name],
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
    selected_strategies: Sequence[str],
    repeat_indices: Sequence[int],
    validations: Dict[str, Dict[str, Any]],
    strategy_validations: Dict[str, Dict[str, Any]],
) -> int:
    _validate_baseline_present(selected_strategies, args.baseline_strategy)
    route_metric_paths = _write_route_metric_artifacts(artifact_root, validations)
    cases_by_name = {case.case_name: case for case in _runtime_cases(args.workload_case)}
    manifest = _default_manifest(
        args=args,
        base_run_tag=base_run_tag,
        selected_strategies=selected_strategies,
        repeat_indices=repeat_indices,
        plan_path=plan_path,
        validations=validations,
        strategy_validations=strategy_validations,
    )
    repeat_combined_csvs: list[Path] = []
    for repeat_index in repeat_indices:
        print(f"Running Experiment 3 repeat {repeat_index}/{args.repeats}")
        combined_rows: list[Dict[str, Any]] = []
        repeat_case_outputs: list[Dict[str, Any]] = []
        for case_name in selected_strategies:
            case = cases_by_name[case_name]
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
                    strategy_validation=strategy_validations[case_name],
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
            baseline_row_index=_baseline_row_index(args.baseline_strategy),
            command_log=manifest["executed_commands"],
        )
        analysis_outputs = _postprocess_analysis(
            artifact_root=artifact_root,
            repeat_index=repeat_index,
            validations=validations,
            strategy_validations=strategy_validations,
            topology_analysis_outputs=topology_outputs,
            workload_case=args.workload_case,
            baseline_strategy=args.baseline_strategy,
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
    strategy_validations: Dict[str, Dict[str, Any]],
) -> int:
    if args.gem5_results is None:
        raise SystemExit("--gem5-results is required for --mode analyze-only.")
    gem5_results = args.gem5_results.resolve()
    if not gem5_results.exists():
        raise SystemExit(f"gem5 results CSV not found: {gem5_results}")
    _validate_baseline_in_csv(gem5_results, args.baseline_strategy)
    _write_route_metric_artifacts(artifact_root, validations)
    command_log: list[Dict[str, Any]] = []
    copied_input_csv = artifact_root / "results" / "analyze_only_input_gem5.csv"
    _copy_file_if_exists(gem5_results, copied_input_csv)
    topology_outputs = _run_analysis(
        gem5_results=copied_input_csv if copied_input_csv.exists() else gem5_results,
        output_prefix=artifact_root / "analysis" / "analyze_only_topology",
        baseline_row_index=_baseline_row_index(args.baseline_strategy),
        command_log=command_log,
    )
    analysis_outputs = _postprocess_analysis(
        artifact_root=artifact_root,
        repeat_index=1,
        validations=validations,
        strategy_validations=strategy_validations,
        topology_analysis_outputs=topology_outputs,
        workload_case=args.workload_case,
        baseline_strategy=args.baseline_strategy,
    )
    manifest = {
        "experiment": "experiment3",
        "mode": args.mode,
        "run_tag": base_run_tag,
        "artifact_root": str(artifact_root),
        "gem5_results": str(copied_input_csv if copied_input_csv.exists() else gem5_results),
        "workload_case": args.workload_case,
        "baseline_strategy": args.baseline_strategy,
        "baseline_plan_row_index": _baseline_row_index(args.baseline_strategy),
        "min_bad_overlap_ratio": args.min_bad_overlap_ratio,
        "min_diverse_overlap_reduction_ratio": args.min_diverse_overlap_reduction_ratio,
        "max_diverse_hop_increase": args.max_diverse_hop_increase,
        "strategy_validation": strategy_validations,
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
        description="Run and collect Experiment 3 evaluation results."
    )
    parser.add_argument(
        "--mode",
        choices=["run", "plan-only", "analyze-only"],
        default="run",
    )
    parser.add_argument("--run-tag")
    parser.add_argument(
        "--workload-case",
        choices=sorted(WORKLOAD_BY_NAME),
        default="exp1_4to1_far",
    )
    parser.add_argument("--strategy", action="append")
    parser.add_argument("--strategies")
    parser.add_argument(
        "--hotspot-profile",
        choices=[HOTSPOT_PROFILE_NONE, HOTSPOT_PROFILE_ALL, HOTSPOT_PROFILE_RECOMMENDED],
        default=HOTSPOT_PROFILE_ALL,
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--repeat-index", type=int)
    parser.add_argument(
        "--baseline-strategy",
        choices=sorted(STRATEGY_BY_NAME),
        default="exp3_shortest",
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
    parser.add_argument("--min-bad-overlap-ratio", type=float, default=1.25)
    parser.add_argument("--min-diverse-overlap-reduction-ratio", type=float, default=1.25)
    parser.add_argument("--max-diverse-hop-increase", type=float, default=2.0)
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
    selected_strategies = _strategy_list_from_args(args)
    repeat_indices = _repeat_indices(args)
    artifact_root = args.artifact_root.resolve() / base_run_tag
    validations = _build_validations(
        workload_case=args.workload_case,
        artifact_root=artifact_root,
        command_log=[],
    )
    strategy_validations = _strategy_validation_results(
        validations,
        selected_strategies=selected_strategies,
        min_bad_overlap_ratio=args.min_bad_overlap_ratio,
        min_diverse_overlap_reduction_ratio=args.min_diverse_overlap_reduction_ratio,
        max_diverse_hop_increase=args.max_diverse_hop_increase,
        allow_validation_failures=args.allow_validation_failures,
    )
    plan_path = artifact_root / "plan" / PLAN_FILENAME
    manifest_path = artifact_root / "manifest.json"
    plan_rows = build_plan_rows(args.workload_case, _workload_settings(args), validations)
    write_plan_csv(plan_path, plan_rows)

    if args.mode == "plan-only":
        return run_plan_only(
            args=args,
            base_run_tag=base_run_tag,
            artifact_root=artifact_root,
            plan_path=plan_path,
            manifest_path=manifest_path,
            selected_strategies=selected_strategies,
            repeat_indices=repeat_indices,
            validations=validations,
            strategy_validations=strategy_validations,
        )
    if args.mode == "analyze-only":
        return run_analyze_only(
            args=args,
            base_run_tag=base_run_tag,
            artifact_root=artifact_root,
            manifest_path=manifest_path,
            validations=validations,
            strategy_validations=strategy_validations,
        )
    return run_experiment(
        args=args,
        base_run_tag=base_run_tag,
        artifact_root=artifact_root,
        plan_path=plan_path,
        manifest_path=manifest_path,
        selected_strategies=selected_strategies,
        repeat_indices=repeat_indices,
        validations=validations,
        strategy_validations=strategy_validations,
    )


if __name__ == "__main__":
    raise SystemExit(main())
