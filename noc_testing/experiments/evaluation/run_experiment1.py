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
from typing import Any, Dict, Iterable, List, Optional, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parents[1]
REPO_ROOT = WORKSPACE.parent
RESULTS_DIR = WORKSPACE / "artifacts" / "results"
DEFAULT_ARTIFACT_ROOT = SCRIPT_DIR / "artifacts"
NOC_DESC_DIR = WORKSPACE / "artifacts" / "noc_desc"
SIMLOGS_DIR = WORKSPACE / "artifacts" / "simlogs"
HOTSPOT_DIR = WORKSPACE / "artifacts" / "hotspot"

DEFAULT_RUN_TAG_PREFIX = "experiment1"
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
HOTSPOT_RECOMMENDED_CASES = {
    "exp1_4to4_compact",
    "exp1_4to4_far",
    "exp1_4to1_far",
}


@dataclass(frozen=True)
class CaseSpec:
    case_name: str
    connection_json: str
    placement_json: str
    pattern: str


CASE_SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        "exp1_4to4_compact",
        "topology_jsons/multi_endpoint/4nmu_to_4nsu_distributed_aximm.conn.json",
        "topology_jsons/multi_endpoint/4nmu_to_4nsu_distributed_compact.place.json",
        "distributed",
    ),
    CaseSpec(
        "exp1_4to4_far",
        "topology_jsons/multi_endpoint/4nmu_to_4nsu_distributed_aximm.conn.json",
        "topology_jsons/multi_endpoint/4nmu_to_4nsu_distributed_far.place.json",
        "distributed",
    ),
    CaseSpec(
        "exp1_4to1_compact",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm.conn.json",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_compact.place.json",
        "incast",
    ),
    CaseSpec(
        "exp1_4to1_far",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm.conn.json",
        "topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_spread.place.json",
        "incast",
    ),
)
CASE_BY_NAME = {case.case_name: case for case in CASE_SPECS}
CASE_ROW_INDEX = {case.case_name: index for index, case in enumerate(CASE_SPECS, 1)}
PLAN_FILENAME = "experiment1_plan.csv"


def _repo_rel(path: Path) -> str:
    resolved = path.resolve()
    for base in (REPO_ROOT.resolve(), WORKSPACE.resolve()):
        try:
            rel = resolved.relative_to(base)
            prefix = "" if base == REPO_ROOT.resolve() else ""
            return f"{prefix}{rel}"
        except ValueError:
            continue
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
            raise SystemExit(f"Unknown Experiment 1 case: {name}")
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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{DEFAULT_RUN_TAG_PREFIX}_{timestamp}"


def _clean_stem(path_text: str) -> str:
    name = Path(path_text).name
    for suffix in (".conn.json", ".place.json", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def _sanitize_name_token(name: str) -> str:
    token = re.sub(r"[\s,:/]+", "_", name).strip("_")
    return token or "unnamed_row"


def _topology_key(case: CaseSpec) -> str:
    return f"{_clean_stem(case.connection_json)}__{_clean_stem(case.placement_json)}"


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

    if case.pattern == "distributed":
        if len(masters) != 4 or len(slaves) != 4:
            raise SystemExit(
                f"{path} does not define exactly four AXI-MM masters and four AXI-MM slaves."
            )
        if referenced_sources != masters or referenced_dests != slaves:
            raise SystemExit(
                f"{path} does not connect every defined distributed endpoint exactly once."
            )
        if num_sources != 4 or num_destinations != 4 or num_flows != 4:
            raise SystemExit(
                f"{path} is not a valid distributed 4x4 mapping: "
                f"sources={num_sources}, destinations={num_destinations}, flows={num_flows}."
            )
        if any(count != 1 for count in source_counts.values()):
            raise SystemExit(f"{path} has a source with fanout != 1.")
        if any(count != 1 for count in dest_counts.values()):
            raise SystemExit(f"{path} has a destination with fanin != 1.")
    elif case.pattern == "incast":
        if len(masters) != 4 or len(slaves) != 1:
            raise SystemExit(
                f"{path} does not define exactly four AXI-MM masters and one AXI-MM slave."
            )
        if referenced_sources != masters or referenced_dests != slaves:
            raise SystemExit(
                f"{path} does not connect every defined incast endpoint as expected."
            )
        if num_sources != 4 or num_destinations != 1 or num_flows != 4:
            raise SystemExit(
                f"{path} is not a valid 4-to-1 incast mapping: "
                f"sources={num_sources}, destinations={num_destinations}, flows={num_flows}."
            )
        if any(count != 1 for count in source_counts.values()):
            raise SystemExit(f"{path} has a source with fanout != 1.")
        if sorted(dest_counts.values()) != [4]:
            raise SystemExit(f"{path} does not route all four sources into one destination.")
    else:
        raise SystemExit(f"Unsupported Experiment 1 pattern: {case.pattern}")

    return {
        "case_name": case.case_name,
        "connection_json": f"noc_testing/{case.connection_json}",
        "placement_json": f"noc_testing/{case.placement_json}",
        "routing_mode": "generated_in_house_v2",
        "num_sources": num_sources,
        "num_destinations": num_destinations,
        "num_flows": num_flows,
        "hop_summary_status": "not_computed",
        "avg_hop_count": "",
        "max_hop_count": "",
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


def build_plan_rows(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for case in CASE_SPECS:
        row = {"name": case.case_name, "topology_json": case.connection_json, "placement_json": case.placement_json}
        row.update(settings)
        rows.append(row)
    return rows


def write_plan_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        raise SystemExit("No Experiment 1 plan rows were generated.")
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
    topo_key = _topology_key(case)
    topo_dir = NOC_DESC_DIR / case_tag / topo_key
    sanitized_name = _sanitize_name_token(case.case_name)
    return {
        "case_run_tag": Path(case_tag),
        "gem5_results_csv": RESULTS_DIR / f"gem5_{plan_path.stem}_{case_tag}.csv",
        "topology_artifact_dir": topo_dir,
        "ncr_path": topo_dir / "noc_subsystem.ncr",
        "nts_path": topo_dir / "noc_subsystem.nts",
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
) -> Dict[str, str]:
    case_root = artifact_root / "collected" / _repeat_slug(repeat_index) / case.case_name
    collected = {
        "collected_case_dir": str(case_root),
        "collected_gem5_results_csv": _copy_file_if_exists(
            source_paths["gem5_results_csv"], case_root / "results" / source_paths["gem5_results_csv"].name
        ),
        "collected_topology_artifact_dir": _copy_tree_if_exists(
            source_paths["topology_artifact_dir"], case_root / "noc_desc"
        ),
        "collected_simlog_path": _copy_file_if_exists(
            source_paths["simlog_path"], case_root / "simlogs" / source_paths["simlog_path"].name
        ),
        "collected_hotspot_artifact_dir": _copy_tree_if_exists(
            source_paths["hotspot_artifact_dir"], case_root / "hotspot"
        ),
    }
    return collected


def _remove_path_if_exists(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _clear_case_runtime_artifacts(
    *,
    artifact_root: Path,
    repeat_index: int,
    case: CaseSpec,
    source_paths: Dict[str, Path],
) -> None:
    _remove_path_if_exists(source_paths["gem5_results_csv"])
    _remove_path_if_exists(source_paths["topology_artifact_dir"])
    _remove_path_if_exists(source_paths["simlog_dir"])
    _remove_path_if_exists(source_paths["hotspot_artifact_dir"])
    _remove_path_if_exists(
        artifact_root / "collected" / _repeat_slug(repeat_index) / case.case_name
    )


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
        merged["experiment_case"] = case.case_name
        merged["repeat_index"] = repeat_index
        merged["connection_json"] = validation["connection_json"]
        merged["placement_json"] = validation["placement_json"]
        combined.append(merged)
    return combined


def _analysis_prefix(artifact_root: Path, repeat_index: int) -> Path:
    return artifact_root / "analysis" / f"{_repeat_slug(repeat_index)}"


def _run_analysis(
    *,
    gem5_results: Path,
    output_prefix: Path,
    baseline_row_index: int,
    command_log: List[Dict[str, Any]],
) -> Dict[str, str]:
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
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
        "endpoint_csv": str(output_prefix.with_name(f"{output_prefix.name}_endpoints").with_suffix(".csv")),
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


def _planned_case_manifest(
    *,
    case: CaseSpec,
    repeat_index: int,
    plan_path: Path,
    base_run_tag: str,
    hotspot_profile: str,
    validation: Dict[str, Any],
    analysis_included: bool,
) -> Dict[str, Any]:
    paths = _per_case_paths(plan_path, base_run_tag, repeat_index, case)
    ncr_path = paths["ncr_path"]
    collected_case_root = plan_path.parent.parent / "collected" / _repeat_slug(repeat_index) / case.case_name
    return {
        **validation,
        "repeat_index": repeat_index,
        "hotspot_mode": _hotspot_mode(hotspot_profile, case.case_name),
        "analysis_included": analysis_included,
        "gem5_results_csv": str(collected_case_root / "results" / paths["gem5_results_csv"].name),
        "route_source_path": str(collected_case_root / "noc_desc" / "noc_subsystem.ncr") if ncr_path.exists() else "",
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
) -> Dict[str, Any]:
    workload = _workload_settings(args)
    return {
        "experiment": "experiment1",
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
        "workload": workload,
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
        manifest["repeat_outputs"].append(
            {
                "repeat_index": repeat_index,
                "cases": repeat_cases,
            }
        )
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
        print(f"Running Experiment 1 repeat {repeat_index}/{args.repeats}")
        combined_rows: list[Dict[str, Any]] = []
        repeat_case_outputs: list[Dict[str, Any]] = []
        for case_name in selected_cases:
            case = CASE_BY_NAME[case_name]
            hotspot_mode = _hotspot_mode(args.hotspot_profile, case_name)
            case_tag = _case_run_tag(base_run_tag, repeat_index, case_name)
            paths = _per_case_paths(plan_path, base_run_tag, repeat_index, case)
            _clear_case_runtime_artifacts(
                artifact_root=artifact_root,
                repeat_index=repeat_index,
                case=case,
                source_paths=paths,
            )
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
            result_csv = paths["gem5_results_csv"]
            if not result_csv.exists():
                raise SystemExit(f"Expected gem5 results CSV was not produced: {result_csv}")
            raw_rows = _csv_rows(result_csv)
            _collect_case_outputs(
                artifact_root=artifact_root,
                repeat_index=repeat_index,
                case=case,
                source_paths=paths,
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
                    analysis_included=True,
                )
            )

        repeat_dir = artifact_root / "results"
        repeat_dir.mkdir(parents=True, exist_ok=True)
        repeat_combined_csv = repeat_dir / f"{_repeat_slug(repeat_index)}_combined_gem5.csv"
        _write_csv(repeat_combined_csv, combined_rows)
        repeat_combined_csvs.append(repeat_combined_csv)
        analysis_outputs = _run_analysis(
            gem5_results=repeat_combined_csv,
            output_prefix=_analysis_prefix(artifact_root, repeat_index),
            baseline_row_index=_baseline_row_index(args.baseline_case),
            command_log=manifest["executed_commands"],
        )
        manifest["repeat_outputs"].append(
            {
                "repeat_index": repeat_index,
                "combined_gem5_csv": str(repeat_combined_csv),
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
) -> int:
    if args.gem5_results is None:
        raise SystemExit("--gem5-results is required for --mode analyze-only.")
    gem5_results = args.gem5_results.resolve()
    if not gem5_results.exists():
        raise SystemExit(f"gem5 results CSV not found: {gem5_results}")
    _validate_baseline_in_csv(gem5_results, args.baseline_case)
    command_log: list[Dict[str, Any]] = []
    copied_input_csv = artifact_root / "results" / "analyze_only_input_gem5.csv"
    _copy_file_if_exists(gem5_results, copied_input_csv)
    analysis_outputs = _run_analysis(
        gem5_results=copied_input_csv if copied_input_csv.exists() else gem5_results,
        output_prefix=artifact_root / "analysis" / "analyze_only",
        baseline_row_index=_baseline_row_index(args.baseline_case),
        command_log=command_log,
    )
    manifest = {
        "experiment": "experiment1",
        "mode": args.mode,
        "run_tag": base_run_tag,
        "artifact_root": str(artifact_root),
        "gem5_results": str(copied_input_csv if copied_input_csv.exists() else gem5_results),
        "baseline_case": args.baseline_case,
        "baseline_plan_row_index": _baseline_row_index(args.baseline_case),
        "analysis": analysis_outputs,
        "executed_commands": command_log,
    }
    _write_manifest(manifest_path, manifest)
    print(f"Analysis manifest written to: {manifest_path}")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and collect Experiment 1 evaluation results."
    )
    parser.add_argument(
        "--mode",
        choices=["run", "plan-only", "analyze-only"],
        default="run",
    )
    parser.add_argument(
        "--run-tag",
        help="Base run tag used to name Experiment 1 artifacts.",
    )
    parser.add_argument(
        "--case",
        action="append",
        help="Run a single Experiment 1 case. May be passed multiple times.",
    )
    parser.add_argument(
        "--cases",
        help="Comma-separated list of Experiment 1 cases to run.",
    )
    parser.add_argument(
        "--hotspot-profile",
        choices=[HOTSPOT_PROFILE_NONE, HOTSPOT_PROFILE_ALL, HOTSPOT_PROFILE_RECOMMENDED],
        default=HOTSPOT_PROFILE_NONE,
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--repeat-index", type=int)
    parser.add_argument(
        "--baseline-case",
        choices=sorted(CASE_BY_NAME),
        default="exp1_4to4_compact",
    )
    parser.add_argument(
        "--bandwidth-mbps",
        type=int,
        default=DEFAULT_BANDWIDTH_MBPS,
    )
    parser.add_argument(
        "--num-transactions",
        type=int,
        default=DEFAULT_NUM_TRANSACTIONS,
    )
    parser.add_argument(
        "--beat-bytes",
        type=int,
        default=DEFAULT_BEAT_BYTES,
    )
    parser.add_argument(
        "--beat-count",
        type=int,
        default=DEFAULT_BEAT_COUNT,
    )
    parser.add_argument(
        "--data-width-bits",
        type=int,
        default=DEFAULT_DATA_WIDTH_BITS,
    )
    parser.add_argument(
        "--bram-data-width-bits",
        type=int,
        default=DEFAULT_BRAM_DATA_WIDTH_BITS,
    )
    parser.add_argument(
        "--noc-clk-mhz",
        type=int,
        default=DEFAULT_NOC_CLK_MHZ,
    )
    parser.add_argument(
        "--abs-max-tick",
        type=int,
        default=DEFAULT_ABS_MAX_TICK,
    )
    parser.add_argument(
        "--tg-mode",
        default=DEFAULT_TG_MODE,
    )
    parser.add_argument(
        "--gem5-results",
        type=Path,
        help="Combined gem5 CSV to analyze in analyze-only mode.",
    )
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
        case_name: validate_case_topology(CASE_BY_NAME[case_name])
        for case_name in [case.case_name for case in CASE_SPECS]
    }
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
