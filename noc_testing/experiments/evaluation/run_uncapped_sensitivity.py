#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import shlex
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import route_metrics
import run_experiment1 as exp1
import run_experiment4 as exp4


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parents[1]
REPO_ROOT = WORKSPACE.parent
RESULTS_DIR = WORKSPACE / "artifacts" / "results"
DEFAULT_ARTIFACT_ROOT = SCRIPT_DIR / "artifacts"

DEFAULT_BASELINE_EXP1 = SCRIPT_DIR / "artifacts" / "exp1_evaluation_1"
DEFAULT_BASELINE_EXP4 = SCRIPT_DIR / "artifacts" / "exp4_main_1"

DEFAULT_RUN_TAG = "chapter3_uncapped_sensitivity"
DEFAULT_NUM_TRANSACTIONS = 64
DEFAULT_BEAT_BYTES = 32
DEFAULT_BEAT_COUNT = 16
DEFAULT_DATA_WIDTH_BITS = 512
DEFAULT_BRAM_DATA_WIDTH_BITS = 512
DEFAULT_NOC_CLK_MHZ = 1000
DEFAULT_ABS_MAX_TICK = 10000000000
DEFAULT_TG_MODE = "rw_interleaved"

CALIBRATION_CONCURRENCY = (1, 2, 4, 8, 16, 32)
PLATEAU_FRACTION = 0.95


@dataclass(frozen=True)
class StudyCase:
    study: str
    source_case: str
    name: str
    connection_json: str
    placement_json: str
    ncr: str
    nts: str
    avg_hop_count: str = ""
    route_overlap_score: str = ""


def _repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _float(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        text = str(row.get(key, "")).strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def _int(row: Dict[str, Any], key: str, default: int = 0) -> int:
    try:
        text = str(row.get(key, "")).strip()
        return int(float(text)) if text else default
    except (TypeError, ValueError):
        return default


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def _tg_component_ids(connection_json: str) -> List[str]:
    path = (WORKSPACE / connection_json).resolve()
    data = _load_json(path)
    components = data.get("components", {})
    return sorted(
        name
        for name, component in components.items()
        if component.get("node_type") == "AxiRandomTrafficGenerator"
    )


def _plan_row(case: StudyCase, *, max_concurrent: int, bandwidth_mbps: int) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "name": case.name,
        "topology_json": case.connection_json,
        "placement_json": case.placement_json,
        "ncr": case.ncr,
        "nts": case.nts,
        "tg_mode": DEFAULT_TG_MODE,
        "axi_write_len_beats": DEFAULT_BEAT_COUNT,
        "axi_write_size_bytes": DEFAULT_BEAT_BYTES,
        "axi_write_bandwidth_cfg_MBps": bandwidth_mbps,
        "num_write_transactions_cfg": DEFAULT_NUM_TRANSACTIONS,
        "tg_axi_data_width_bits": DEFAULT_DATA_WIDTH_BITS,
        "bram_data_width": DEFAULT_BRAM_DATA_WIDTH_BITS,
        "noc_axi_clk_mhz": DEFAULT_NOC_CLK_MHZ,
        "abs_max_tick": DEFAULT_ABS_MAX_TICK,
        "uncapped_requested": 1 if bandwidth_mbps == 0 else 0,
        "max_concurrent_transactions": max_concurrent,
        "source_case": case.source_case,
        "study": case.study,
    }
    for component_id in _tg_component_ids(case.connection_json):
        row[f"param.{component_id}.max_outstanding_writes"] = max_concurrent
    return row


def _write_plan(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        raise SystemExit("No plan rows to write.")
    _write_csv(path, rows)


def _run_cmd(cmd: Sequence[str], *, cwd: Path, log: List[Dict[str, Any]], label: str) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    log.append(
        {
            "label": label,
            "command": shlex.join([str(part) for part in cmd]),
            "cwd": str(cwd),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"{label} failed with exit code {proc.returncode}\n"
            f"Command: {shlex.join([str(part) for part in cmd])}\n"
            f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-4000:]}"
        )


def _run_noc_sweep(plan_path: Path, run_tag: str, command_log: List[Dict[str, Any]]) -> Path:
    result_csv = RESULTS_DIR / f"gem5_{plan_path.stem}_{run_tag}.csv"
    if result_csv.exists():
        result_csv.unlink()
    cmd = [
        sys.executable,
        str(WORKSPACE / "noc_sweep.py"),
        "--plan",
        str(plan_path),
        "--mode",
        "gem5_only",
        "--run-tag",
        run_tag,
        "--hotspot-mode",
        "both",
    ]
    _run_cmd(cmd, cwd=REPO_ROOT, log=command_log, label=f"noc_sweep:{run_tag}")
    if not result_csv.exists():
        raise SystemExit(f"Expected gem5 results CSV was not produced: {result_csv}")
    return result_csv


def _copy_hotspot_outputs(rows: Sequence[Dict[str, str]], dst_root: Path) -> None:
    for row in rows:
        src_dir = Path(row.get("hotspot_artifact_dir", ""))
        name = row.get("name", "unnamed")
        if not src_dir.exists():
            continue
        dst = dst_root / name
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, dst)


def _hotspot_top1(path_text: str) -> tuple[float, str]:
    path = Path(path_text)
    if not path.exists():
        return 0.0, ""
    totals: Dict[str, float] = defaultdict(float)
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("nps_name") or row.get("nocname") or ""
            if not name:
                continue
            value = _float(row, "occupancy_sum", _float(row, "depth"))
            totals[name] += value
    total = sum(totals.values())
    if total <= 0 or not totals:
        return 0.0, ""
    culprit = max(totals, key=lambda key: (totals[key], key))
    return totals[culprit] / total, culprit


def _summarize_case(rows: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    if not rows:
        return {}
    read_bw = [_float(row, "gem5_achieved_read_bw_MBps") for row in rows]
    write_bw = [_float(row, "gem5_achieved_write_bw_MBps") for row in rows]
    p99_candidates = []
    for row in rows:
        src_id = str(row.get("src_id", ""))
        read_p99 = _float(row, "gem5_p99_read_lat_cycles")
        write_p99 = _float(row, "gem5_p99_write_lat_cycles")
        p99_candidates.append((read_p99, src_id, "read"))
        p99_candidates.append((write_p99, src_id, "write"))
    worst_p99, worst_src, worst_kind = max(p99_candidates, key=lambda item: item[0])
    jfis = [
        _float(rows[0], "gem5_jfi_read_bw", 1.0),
        _float(rows[0], "gem5_jfi_write_bw", 1.0),
    ]
    occ_path = rows[0].get("hotspot_occ_trace_csv") or ""
    if not Path(occ_path).exists():
        occ_path = str(Path(rows[0].get("hotspot_artifact_dir", "")) / "nps_occ_all.csv")
    hotspot_share, hotspot_name = _hotspot_top1(occ_path)
    return {
        "rows": len(rows),
        "valid": all(_int(row, "gem5_return_code", -1) == 0 for row in rows)
        and all("gem5_achieved_read_bw_MBps" in row for row in rows),
        "read_bw_MBps": round(_mean(read_bw), 6),
        "write_bw_MBps": round(_mean(write_bw), 6),
        "mean_bw_MBps": round(_mean([*read_bw, *write_bw]), 6),
        "mean_endpoint_total_bw_MBps": round(
            _mean([r + w for r, w in zip(read_bw, write_bw)]), 6
        ),
        "aggregate_read_bw_MBps": round(sum(read_bw), 6),
        "aggregate_write_bw_MBps": round(sum(write_bw), 6),
        "aggregate_total_bw_MBps": round(sum(read_bw) + sum(write_bw), 6),
        "worst_p99_cycles": round(worst_p99, 6),
        "min_jfi": round(min(jfis), 6),
        "hotspot_top1_share": round(hotspot_share, 6),
        "hotspot_top1_resource": hotspot_name,
        "worst_endpoint_culprit": f"src_id={worst_src}:{worst_kind}_p99",
    }


def _summaries_by_case(rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("name", "")].append(row)
    return {name: _summarize_case(case_rows) for name, case_rows in grouped.items()}


def _load_controlled_means(path: Path) -> Dict[str, float]:
    if not path.exists():
        return {}
    out: Dict[str, float] = {}
    for name, summary in _summaries_by_case(_read_csv(path)).items():
        out[name] = float(summary.get("mean_bw_MBps", 0.0))
    return out


def _exp1_original_route(case_name: str, baseline_root: Path) -> tuple[str, str]:
    root = baseline_root / "collected" / "repeat_01" / case_name / "noc_desc" / "noc_subsystem"
    ncr = root.with_suffix(".ncr")
    nts = root.with_suffix(".nts")
    if not ncr.exists() or not nts.exists():
        raise SystemExit(
            f"Missing original Exp1 route artifacts for {case_name}: {ncr}, {nts}"
        )
    return _repo_rel(ncr), _repo_rel(nts)


def _exp1_cases(baseline_root: Path) -> List[StudyCase]:
    out = []
    for case in exp1.CASE_SPECS:
        ncr, nts = _exp1_original_route(case.case_name, baseline_root)
        out.append(
            StudyCase(
                study="exp1_uncapped",
                source_case=case.case_name,
                name=f"{case.case_name}_uncapped",
                connection_json=case.connection_json,
                placement_json=case.placement_json,
                ncr=ncr,
                nts=nts,
            )
        )
    return out


def _calibration_cases(baseline_root: Path) -> List[StudyCase]:
    source = exp1.CASE_BY_NAME["exp1_4to4_compact"]
    ncr, nts = _exp1_original_route(source.case_name, baseline_root)
    return [
        StudyCase(
            study="calibration",
            source_case=source.case_name,
            name=f"exp1_4to4_compact_uncapped_mc{mc}",
            connection_json=source.connection_json,
            placement_json=source.placement_json,
            ncr=ncr,
            nts=nts,
        )
        for mc in CALIBRATION_CONCURRENCY
    ]


def _exp4_cases() -> List[StudyCase]:
    name_map = {
        "exp4_near_single_target": "exp4_near_single_uncapped",
        "exp4_far_single_target": "exp4_far_single_uncapped",
        "exp4_spread_single_target": "exp4_spread_single_uncapped",
        "exp4_near_distributed_targets": "exp4_near_distributed_uncapped",
        "exp4_far_distributed_targets": "exp4_far_distributed_uncapped",
        "exp4_spread_distributed_targets": "exp4_spread_distributed_uncapped",
    }
    out = []
    for case in exp4.CASE_SPECS:
        metrics = route_metrics.compute_route_metrics(WORKSPACE / case.ncr)
        out.append(
            StudyCase(
                study="exp4_uncapped",
                source_case=case.case_name,
                name=name_map[case.case_name],
                connection_json=case.connection_json,
                placement_json=case.placement_json,
                ncr=case.ncr,
                nts=case.nts,
                avg_hop_count=str(metrics["avg_hop_count"]),
                route_overlap_score=str(metrics["route_overlap_score"]),
            )
        )
    return out


def _choose_calibrated(summary_rows: Sequence[Dict[str, Any]]) -> tuple[int, bool]:
    max_bw = max(float(row["aggregate_total_bw_MBps"]) for row in summary_rows)
    threshold = max_bw * PLATEAU_FRACTION
    for row in summary_rows:
        if float(row["aggregate_total_bw_MBps"]) >= threshold:
            return int(row["max_concurrent_transactions"]), True
    return int(summary_rows[-1]["max_concurrent_transactions"]), False


def _rows_for_table(
    cases: Sequence[StudyCase],
    summaries: Dict[str, Dict[str, Any]],
    controlled_means: Dict[str, float],
) -> List[Dict[str, Any]]:
    rows = []
    for case in cases:
        summary = dict(summaries.get(case.name, {}))
        controlled = controlled_means.get(case.source_case, 0.0)
        ratio = (
            float(summary.get("mean_bw_MBps", 0.0)) / controlled
            if controlled > 0
            else 0.0
        )
        rows.append(
            {
                "case": case.name,
                "source_case": case.source_case,
                **summary,
                "avg_hop_count": case.avg_hop_count,
                "route_overlap_score": case.route_overlap_score,
                "controlled_mean_bw_MBps": round(controlled, 6) if controlled else "",
                "bw_ratio_vs_controlled": round(ratio, 6) if controlled else "",
            }
        )
    return rows


def _write_markdown_table(f, title: str, rows: Sequence[Dict[str, Any]], columns: Sequence[str]) -> None:
    f.write(f"## {title}\n\n")
    f.write("| " + " | ".join(columns) + " |\n")
    f.write("| " + " | ".join(["---"] * len(columns)) + " |\n")
    for row in rows:
        f.write("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |\n")
    f.write("\n")


def _write_report(
    path: Path,
    *,
    calibrated: int,
    calibration_rows: Sequence[Dict[str, Any]],
    exp1_rows: Sequence[Dict[str, Any]],
    exp4_rows: Sequence[Dict[str, Any]],
    validation_notes: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("# Chapter 3 Uncapped Offered-Load Sensitivity\n\n")
        f.write(f"Calibrated max_concurrent_transactions: `{calibrated}`\n\n")
        _write_markdown_table(
            f,
            "Calibration",
            calibration_rows,
            [
                "max_concurrent_transactions",
                "read_bw_MBps",
                "write_bw_MBps",
                "mean_bw_MBps",
                "mean_endpoint_total_bw_MBps",
                "aggregate_total_bw_MBps",
                "worst_p99_cycles",
                "plateau",
            ],
        )
        _write_markdown_table(
            f,
            "Experiment 1 Uncapped",
            exp1_rows,
            [
                "case",
                "mean_bw_MBps",
                "mean_endpoint_total_bw_MBps",
                "read_bw_MBps",
                "write_bw_MBps",
                "worst_p99_cycles",
                "min_jfi",
                "hotspot_top1_share",
                "worst_endpoint_culprit",
                "bw_ratio_vs_controlled",
            ],
        )
        _write_markdown_table(
            f,
            "Experiment 4 Uncapped",
            exp4_rows,
            [
                "case",
                "mean_bw_MBps",
                "mean_endpoint_total_bw_MBps",
                "worst_p99_cycles",
                "min_jfi",
                "hotspot_top1_share",
                "avg_hop_count",
                "route_overlap_score",
                "worst_endpoint_culprit",
            ],
        )
        f.write("## Validation Notes\n\n")
        for note in validation_notes:
            f.write(f"- {note}\n")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run additive uncapped offered-load sensitivity runs for Chapter 3."
    )
    parser.add_argument("--run-tag", default=DEFAULT_RUN_TAG)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--baseline-exp1-root", type=Path, default=DEFAULT_BASELINE_EXP1)
    parser.add_argument("--baseline-exp4-root", type=Path, default=DEFAULT_BASELINE_EXP4)
    parser.add_argument(
        "--skip-exp4",
        action="store_true",
        help="Run only calibration and Experiment 1.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    run_root = args.artifact_root.resolve() / args.run_tag
    run_root.mkdir(parents=True, exist_ok=True)
    command_log: List[Dict[str, Any]] = []

    calibration_cases = _calibration_cases(args.baseline_exp1_root.resolve())
    cal_plan_rows = [
        _plan_row(case, max_concurrent=mc, bandwidth_mbps=0)
        for case, mc in zip(calibration_cases, CALIBRATION_CONCURRENCY)
    ]
    cal_plan = run_root / "plan" / "calibration_uncapped_plan.csv"
    _write_plan(cal_plan, cal_plan_rows)
    cal_result_csv = _run_noc_sweep(cal_plan, f"{args.run_tag}_calibration", command_log)
    cal_rows = _read_csv(cal_result_csv)
    _copy_hotspot_outputs(cal_rows, run_root / "hotspot" / "calibration")
    cal_summaries = _summaries_by_case(cal_rows)
    calibration_table = []
    for case, mc in zip(calibration_cases, CALIBRATION_CONCURRENCY):
        row = {
            "case": case.name,
            "max_concurrent_transactions": mc,
            **cal_summaries[case.name],
        }
        calibration_table.append(row)
    calibrated, plateau_found = _choose_calibrated(calibration_table)
    max_cal_bw = max(float(row["aggregate_total_bw_MBps"]) for row in calibration_table)
    for row in calibration_table:
        row["plateau"] = (
            "yes"
            if float(row["aggregate_total_bw_MBps"]) >= max_cal_bw * PLATEAU_FRACTION
            else "no"
        )

    exp1_cases = _exp1_cases(args.baseline_exp1_root.resolve())
    exp1_plan_rows = [
        _plan_row(case, max_concurrent=calibrated, bandwidth_mbps=0)
        for case in exp1_cases
    ]
    exp1_plan = run_root / "plan" / "experiment1_uncapped_plan.csv"
    _write_plan(exp1_plan, exp1_plan_rows)
    exp1_result_csv = _run_noc_sweep(exp1_plan, f"{args.run_tag}_exp1", command_log)
    exp1_raw = _read_csv(exp1_result_csv)
    _copy_hotspot_outputs(exp1_raw, run_root / "hotspot" / "exp1")

    exp4_raw: List[Dict[str, str]] = []
    exp4_cases: List[StudyCase] = []
    exp4_result_csv = ""
    if not args.skip_exp4:
        exp4_cases = _exp4_cases()
        exp4_plan_rows = [
            _plan_row(case, max_concurrent=calibrated, bandwidth_mbps=0)
            for case in exp4_cases
        ]
        exp4_plan = run_root / "plan" / "experiment4_uncapped_plan.csv"
        _write_plan(exp4_plan, exp4_plan_rows)
        exp4_result_path = _run_noc_sweep(exp4_plan, f"{args.run_tag}_exp4", command_log)
        exp4_result_csv = str(exp4_result_path)
        exp4_raw = _read_csv(exp4_result_path)
        _copy_hotspot_outputs(exp4_raw, run_root / "hotspot" / "exp4")

    controlled_exp1 = _load_controlled_means(
        args.baseline_exp1_root.resolve() / "results" / "repeat_01_combined_gem5.csv"
    )
    controlled_exp4 = _load_controlled_means(
        args.baseline_exp4_root.resolve() / "results" / "repeat_01_joined_gem5.csv"
    )
    exp1_table = _rows_for_table(exp1_cases, _summaries_by_case(exp1_raw), controlled_exp1)
    exp4_table = _rows_for_table(exp4_cases, _summaries_by_case(exp4_raw), controlled_exp4)

    validation_notes = []
    all_tables = [*calibration_table, *exp1_table, *exp4_table]
    invalid = [row.get("case", "") for row in all_tables if not row.get("valid", False)]
    if invalid:
        validation_notes.append(f"Invalid or incomplete metrics for: {', '.join(invalid)}.")
    else:
        validation_notes.append("All completed rows returned gem5_return_code=0 and bandwidth metrics.")
    if plateau_found:
        validation_notes.append(
            f"Plateau criterion: selected smallest concurrency reaching {int(PLATEAU_FRACTION * 100)}% of maximum calibrated aggregate throughput."
        )
    else:
        validation_notes.append("No plateau found within the calibration sweep.")
    low_bw = [
        row.get("case", "")
        for row in [*exp1_table, *exp4_table]
        if float(row.get("read_bw_MBps", 0.0) or 0.0) <= 450.0
        and float(row.get("write_bw_MBps", 0.0) or 0.0) <= 450.0
    ]
    if low_bw:
        validation_notes.append(
            "Bandwidth did not rise materially above the controlled-load ~405 MB/s level for: "
            + ", ".join(low_bw)
            + ". Check whether endpoint acceptance or another outstanding limit dominates; the plan requested max_read/write_bandwidth_mbps=0."
        )
    else:
        validation_notes.append("Uncapped bandwidth is materially above the ~405 MB/s controlled-load level.")

    results_dir = run_root / "results"
    _write_csv(results_dir / "calibration_table.csv", calibration_table)
    _write_csv(results_dir / "experiment1_uncapped_table.csv", exp1_table)
    if exp4_table:
        _write_csv(results_dir / "experiment4_uncapped_table.csv", exp4_table)
    _write_csv(results_dir / "raw_calibration_rows.csv", cal_rows)
    _write_csv(results_dir / "raw_exp1_rows.csv", exp1_raw)
    if exp4_raw:
        _write_csv(results_dir / "raw_exp4_rows.csv", exp4_raw)
    _write_csv(results_dir / "raw_all_rows.csv", [*cal_rows, *exp1_raw, *exp4_raw])

    manifest = {
        "run_tag": args.run_tag,
        "artifact_root": str(run_root),
        "calibrated_max_concurrent_transactions": calibrated,
        "plateau_fraction": PLATEAU_FRACTION,
        "calibration_result_csv": str(cal_result_csv),
        "exp1_result_csv": str(exp1_result_csv),
        "exp4_result_csv": exp4_result_csv,
        "baseline_exp1_root": str(args.baseline_exp1_root.resolve()),
        "baseline_exp4_root": str(args.baseline_exp4_root.resolve()),
        "command_log": command_log,
        "validation_notes": validation_notes,
    }
    with (run_root / "manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    _write_report(
        run_root / "report.md",
        calibrated=calibrated,
        calibration_rows=calibration_table,
        exp1_rows=exp1_table,
        exp4_rows=exp4_table,
        validation_notes=validation_notes,
    )

    print(f"Uncapped sensitivity artifacts written to: {run_root}")
    print(f"Calibrated max_concurrent_transactions: {calibrated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
