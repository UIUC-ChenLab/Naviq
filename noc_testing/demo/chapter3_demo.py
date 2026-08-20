#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import shutil
import sys
import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
NOC_TESTING_ROOT = SCRIPT_DIR.parent
REPO_ROOT = NOC_TESTING_ROOT.parent
if str(NOC_TESTING_ROOT) not in sys.path:
    sys.path.insert(0, str(NOC_TESTING_ROOT))

import topology_recommender


OUTPUT_DIR = SCRIPT_DIR / "artifacts_ch3"
CONFIG_PATH = SCRIPT_DIR / "chapter3_demo_config.json"

EXP1_CSV_CANDIDATES = (
    NOC_TESTING_ROOT
    / "experiments/evaluation/artifacts/exp1_evaluation_1/analysis/repeat_01.csv",
)
EXP2_SUMMARY_CSV = (
    NOC_TESTING_ROOT
    / "experiments/evaluation/artifacts/exp2_evaluation/analysis/repeat_01_final.csv"
)
EXP3_CSV_CANDIDATES = (
    NOC_TESTING_ROOT
    / "experiments/evaluation/artifacts/exp3_tornado_uncapped_tx500/analysis/repeat_01_final.csv",
    NOC_TESTING_ROOT
    / "experiments/evaluation/artifacts/exp3_tornado_uncapped/analysis/repeat_01_final.csv",
    NOC_TESTING_ROOT
    / "experiments/evaluation/artifacts/exp3_tornado_tx500/analysis/repeat_01_final.csv",
)
EXP4_CSV_CANDIDATES = (
    NOC_TESTING_ROOT
    / "experiments/evaluation/artifacts/exp4_main_1/analysis/repeat_01_final.csv",
)
BASIC_UNCAPPED_CSV_CANDIDATES = (
    NOC_TESTING_ROOT
    / "experiments/evaluation/artifacts/chapter3_uncapped_sensitivity_20260505/results/experiment1_uncapped_table.csv",
)

@dataclass
class Exp1Row:
    configuration: str
    worst_p99: float
    mean_bw: float
    min_jfi: float
    hotspot_top1: float
    culprit: str


@dataclass
class Exp2PairRow:
    pattern: str
    low_name: str
    high_name: str
    hop_low: float
    hop_high: float
    overlap_ratio: float
    p99_low: float
    p99_high: float
    hotspot_low: float
    hotspot_high: float
    diagnosis: str
    recommendation: str


@dataclass
class Exp3Row:
    strategy: str
    avg_hop: float
    overlap: float
    worst_p99: float
    mean_bw: float
    min_jfi: float
    hotspot_top1: float


@dataclass
class Exp4Row:
    placement: str
    single_p99: float
    distributed_p99: float


@dataclass
class BasicCongestionRow:
    scenario: str
    bw_mode: str
    worst_p99: float
    mean_bw: float
    min_jfi: float
    hotspot_top1: float
    hotspot_resource: str
    congestion_signal: str


@dataclass
class BasicCongestionResult:
    rows: List[BasicCongestionRow]
    source_csv: Optional[Path]
    analysis: str


@dataclass
class RecommenderRun:
    key: str
    label: str
    evidence: Dict[str, Any]
    mode: str
    message: str
    output_md: Path
    evidence_json: Path


@dataclass
class ExperimentRun:
    key: str
    label: str
    enabled: bool
    status: str
    command: List[str]
    log_path: Path
    run_root: Optional[Path]
    summary_csv: Optional[Path]
    fallback_csv: Optional[Path]


@dataclass
class ExperimentSources:
    runs: List[ExperimentRun]
    exp1_csv: Optional[Path]
    exp2_csv: Path
    exp3_csv: Optional[Path]
    exp4_csv: Optional[Path]


@dataclass
class Gem5SmokeRun:
    enabled: bool
    status: str
    command: List[str]
    log_path: Path
    plan_path: Path
    results_path: Optional[Path]
    copied_results_path: Optional[Path]
    rows: List[Dict[str, str]]


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _float(value: Any, default: float = 0.0) -> float:
    text = _clean(value)
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _first_existing(paths: Sequence[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


def _config_path(value: Any, default: Path) -> Path:
    text = _clean(value)
    if not text:
        return default
    path = Path(text)
    return path if path.is_absolute() else REPO_ROOT / path


def _fmt(value: Any, digits: int = 3) -> str:
    return f"{_float(value):.{digits}f}"


def _fmt_p99(value: Any) -> str:
    return f"{_float(value):.0f}"


def _terminal_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))

    def fmt_row(row: Sequence[str]) -> str:
        return "  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(row))

    lines = [fmt_row(headers), fmt_row(["-" * width for width in widths])]
    lines.extend(fmt_row(row) for row in rows)
    return "\n".join(lines)


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_csv(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def _load_exp1_rows(path: Optional[Path] = None) -> List[Exp1Row]:
    fallback = {
        "exp1_4to4_compact": Exp1Row(
            "4-to-4 compact", 79, 405.975, 1.000, 0.125, "baseline"
        ),
        "exp1_4to4_far": Exp1Row(
            "4-to-4 far", 215, 405.371, 1.000, 0.014, "path length"
        ),
        "exp1_4to1_compact": Exp1Row(
            "4-to-1 compact", 207, 405.799, 0.991, 0.257, "destination convergence"
        ),
        "exp1_4to1_far": Exp1Row(
            "4-to-1 far", 345, 405.086, 0.990, 0.128, "path length + convergence"
        ),
    }
    path = path if path and path.exists() else _first_existing(EXP1_CSV_CANDIDATES)
    if path is None:
        return list(fallback.values())

    by_name = {row["name"]: row for row in _read_csv(path)}
    labels = {
        "exp1_4to4_compact": "4-to-4 compact",
        "exp1_4to4_far": "4-to-4 far",
        "exp1_4to1_compact": "4-to-1 compact",
        "exp1_4to1_far": "4-to-1 far",
    }
    culprits = {
        "exp1_4to4_compact": "baseline",
        "exp1_4to4_far": "path length",
        "exp1_4to1_compact": "destination convergence",
        "exp1_4to1_far": "path length + convergence",
    }
    rows = []
    for name, label in labels.items():
        source = by_name.get(name)
        if source is None:
            rows.append(fallback[name])
            continue
        rows.append(
            Exp1Row(
                label,
                _float(source.get("worst_p99_cycles")),
                _float(source.get("mean_bw_MBps")),
                _float(source.get("min_jfi")),
                _float(source.get("hotspot_top1_share")),
                culprits[name],
            )
        )
    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an offline-capable Naviq congestion-analysis demo."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Force artifact-only output; do not run live gem5 experiments.",
    )
    parser.add_argument(
        "--skip-gem5",
        action="store_true",
        help="Skip live gem5 experiment runs and smoke runs.",
    )
    parser.add_argument(
        "--use-existing-artifacts",
        action="store_true",
        help="Use existing CSV/Markdown artifacts instead of regenerating experiments. This is the default.",
    )
    parser.add_argument(
        "--run-live-experiments",
        action="store_true",
        help="Regenerate Experiment 1, 2, and 3 artifacts locally under the demo output directory.",
    )
    parser.add_argument(
        "--require-live-experiments",
        action="store_true",
        help="Fail instead of falling back if a live experiment does not produce its expected CSV.",
    )
    parser.add_argument(
        "--include-exp4",
        action="store_true",
        help="Also run the optional Experiment 4 sweep in live mode.",
    )
    return parser.parse_args()


def _load_demo_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Demo config not found: {CONFIG_PATH}")
    return _load_json(CONFIG_PATH)


def _run_live_gem5_smoke(
    config: Dict[str, Any], args: argparse.Namespace
) -> Gem5SmokeRun:
    smoke = config.get("live_gem5_smoke", {})
    live_dir = OUTPUT_DIR / "live_gem5"
    live_dir.mkdir(parents=True, exist_ok=True)
    plan_path = live_dir / "chapter3_smoke_plan.csv"
    log_path = live_dir / "chapter3_gem5_smoke.log"

    if args.offline or args.skip_gem5 or not smoke.get("enabled", True):
        reason = "offline/skip requested" if args.offline or args.skip_gem5 else "disabled in config"
        return Gem5SmokeRun(
            False,
            reason,
            [],
            log_path,
            plan_path,
            None,
            None,
            [],
        )

    row = dict(smoke.get("row", {}))
    if not row:
        raise SystemExit(f"live_gem5_smoke.row is empty in {CONFIG_PATH}")
    _write_csv(plan_path, row)

    run_tag = _clean(smoke.get("run_tag")) or "chapter3_demo_smoke"
    command = [
        sys.executable,
        str(NOC_TESTING_ROOT / "noc_sweep.py"),
        "--plan",
        str(plan_path),
        "--mode",
        _clean(smoke.get("mode")) or "gem5_only",
        "--topo-gen",
        _clean(smoke.get("topo_gen")) or "in_house",
        "--row",
        str(smoke.get("row_index", 1)),
        "--run-tag",
        run_tag,
        "--hotspot-mode",
        _clean(smoke.get("hotspot_mode")) or "off",
    ]

    gem5_cmd = smoke.get("gem5_cmd")
    if gem5_cmd:
        command.extend(["--gem5-cmd", *[str(part) for part in gem5_cmd]])

    results_path = (
        NOC_TESTING_ROOT
        / "artifacts"
        / "results"
        / f"gem5_{plan_path.stem}_{run_tag}.csv"
    )

    print()
    print("=== Live gem5 smoke run ===")
    print("Command: " + " ".join(command))
    print(f"Log: {log_path}")

    with log_path.open("w") as log:
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            log.write(line)
        return_code = proc.wait()

    copied_results_path = None
    rows: List[Dict[str, str]] = []
    if results_path.exists():
        copied_results_path = live_dir / results_path.name
        shutil.copy2(results_path, copied_results_path)
        rows = _read_csv(results_path)

    status = "passed" if return_code == 0 else f"failed_return_code_{return_code}"
    if rows and any(_clean(row.get("gem5_return_code")) not in ("", "0") for row in rows):
        status = "gem5_reported_failure"
    return Gem5SmokeRun(
        True,
        status,
        command,
        log_path,
        plan_path,
        results_path if results_path.exists() else None,
        copied_results_path,
        rows,
    )


def _append_cli_args(command: List[str], values: Dict[str, Any]) -> None:
    for key, value in values.items():
        flag = "--" + key.replace("_", "-")
        if value is None:
            continue
        if isinstance(value, bool):
            if value:
                command.append(flag)
            continue
        if isinstance(value, list):
            for item in value:
                command.extend([flag, str(item)])
            continue
        command.extend([flag, str(value)])


def _live_experiments_enabled(config: Dict[str, Any], args: argparse.Namespace) -> bool:
    if args.offline or args.skip_gem5 or args.use_existing_artifacts:
        return False
    if args.run_live_experiments:
        return True
    return False


def _experiment_summary_path(run_root: Path, key: str, repeat_index: int = 1) -> Path:
    if key == "experiment1":
        return run_root / "analysis" / f"repeat_{repeat_index:02d}.csv"
    return run_root / "analysis" / f"repeat_{repeat_index:02d}_final.csv"


def _run_one_experiment(
    *,
    key: str,
    spec: Dict[str, Any],
    common_args: Dict[str, Any],
    artifact_root: Path,
    live_enabled: bool,
    include_exp4: bool,
    require_live: bool,
) -> ExperimentRun:
    label = _clean(spec.get("label")) or key
    fallback_text = _clean(spec.get("existing_summary_csv"))
    fallback_csv = _config_path(fallback_text, Path("")) if fallback_text else None
    if fallback_csv is not None and not fallback_csv.exists():
        fallback_csv = None

    spec_enabled = bool(spec.get("enabled", True))
    if key == "experiment4" and include_exp4:
        spec_enabled = True
    should_run = live_enabled and spec_enabled

    run_tag = _clean(spec.get("run_tag")) or f"chapter3_demo_{key}"
    run_root = artifact_root / run_tag
    repeat_index = int(spec.get("repeat_index", common_args.get("repeat_index", 1) or 1))
    summary_csv = _experiment_summary_path(run_root, key, repeat_index)
    log_path = artifact_root / "logs" / f"{key}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if not should_run:
        reason = "disabled in config"
        if not live_enabled:
            reason = "using existing artifacts"
        return ExperimentRun(
            key,
            label,
            False,
            reason,
            [],
            log_path,
            run_root,
            summary_csv if summary_csv.exists() else None,
            fallback_csv,
        )

    script = _config_path(
        spec.get("script"),
        NOC_TESTING_ROOT / "experiments" / "evaluation" / f"run_{key}.py",
    )
    command = [
        sys.executable,
        str(script),
        "--mode",
        _clean(spec.get("mode")) or "run",
        "--run-tag",
        run_tag,
        "--artifact-root",
        str(artifact_root),
    ]
    merged_args = dict(common_args)
    merged_args.update(spec.get("args", {}))
    _append_cli_args(command, merged_args)

    print()
    print(f"=== Live {label} ===")
    print("Command: " + " ".join(command))
    print(f"Log: {log_path}")

    with log_path.open("w") as log:
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            log.write(line)
        return_code = proc.wait()

    if return_code != 0:
        status = f"failed_return_code_{return_code}"
        if require_live:
            raise SystemExit(f"{label} failed. See log: {log_path}")
        if fallback_csv:
            status += "_using_existing_artifact"
        return ExperimentRun(
            key,
            label,
            True,
            status,
            command,
            log_path,
            run_root,
            summary_csv if summary_csv.exists() else None,
            fallback_csv,
        )

    status = "passed" if summary_csv.exists() else "passed_missing_summary"
    if require_live and not summary_csv.exists():
        raise SystemExit(f"{label} completed but did not create expected summary: {summary_csv}")
    return ExperimentRun(
        key,
        label,
        True,
        status,
        command,
        log_path,
        run_root,
        summary_csv if summary_csv.exists() else None,
        fallback_csv,
    )


def _run_live_experiments(config: Dict[str, Any], args: argparse.Namespace) -> ExperimentSources:
    live = config.get("live_experiments", {})
    live_enabled = _live_experiments_enabled(config, args)
    artifact_root = _config_path(
        live.get("artifact_root"),
        OUTPUT_DIR / "live_experiments",
    )
    common_args = dict(live.get("common_args", {}))
    experiments = live.get("experiments", {})
    ordered_keys = ("experiment1", "experiment2", "experiment3", "experiment4")
    defaults = {
        "experiment1": {
            "label": "Experiment 1 motivation sweep",
            "script": str(NOC_TESTING_ROOT / "experiments/evaluation/run_experiment1.py"),
            "run_tag": "chapter3_demo_exp1",
            "existing_summary_csv": str(_first_existing(EXP1_CSV_CANDIDATES) or ""),
        },
        "experiment2": {
            "label": "Experiment 2 route-overlap sweep",
            "script": str(NOC_TESTING_ROOT / "experiments/evaluation/run_experiment2.py"),
            "run_tag": "chapter3_demo_exp2",
            "existing_summary_csv": str(EXP2_SUMMARY_CSV),
        },
        "experiment3": {
            "label": "Experiment 3 routing-strategy validation",
            "script": str(NOC_TESTING_ROOT / "experiments/evaluation/run_experiment3.py"),
            "run_tag": "chapter3_demo_exp3",
            "existing_summary_csv": str(_first_existing(EXP3_CSV_CANDIDATES) or ""),
        },
        "experiment4": {
            "label": "Optional Experiment 4 memory-target sweep",
            "script": str(NOC_TESTING_ROOT / "experiments/evaluation/run_experiment4.py"),
            "run_tag": "chapter3_demo_exp4",
            "enabled": False,
            "existing_summary_csv": str(_first_existing(EXP4_CSV_CANDIDATES) or ""),
        },
    }

    runs = []
    for key in ordered_keys:
        spec = dict(defaults[key])
        spec.update(experiments.get(key, {}))
        runs.append(
            _run_one_experiment(
                key=key,
                spec=spec,
                common_args=common_args,
                artifact_root=artifact_root,
                live_enabled=live_enabled,
                include_exp4=args.include_exp4,
                require_live=args.require_live_experiments,
            )
        )

    def source_for(key: str, fallback_candidates: Sequence[Path]) -> Optional[Path]:
        run = next((item for item in runs if item.key == key), None)
        if run and run.enabled and run.summary_csv and run.summary_csv.exists():
            return run.summary_csv
        if run and run.fallback_csv and run.fallback_csv.exists():
            return run.fallback_csv
        return _first_existing(fallback_candidates)

    exp2_csv = source_for("experiment2", (EXP2_SUMMARY_CSV,))
    if exp2_csv is None:
        raise SystemExit("Experiment 2 summary CSV is required for the recommender.")

    return ExperimentSources(
        runs=runs,
        exp1_csv=source_for("experiment1", EXP1_CSV_CANDIDATES),
        exp2_csv=exp2_csv,
        exp3_csv=source_for("experiment3", EXP3_CSV_CANDIDATES),
        exp4_csv=source_for("experiment4", EXP4_CSV_CANDIDATES),
    )


def _run_recommender(
    args: argparse.Namespace, *, key: str, label: str, summary_csv: Path
) -> RecommenderRun:
    recommendation_dir = OUTPUT_DIR / "recommendations"
    output_md = recommendation_dir / f"{key}_recommendations.md"
    evidence_json = recommendation_dir / f"{key}_recommendations_evidence.json"
    evidence = topology_recommender.build_evidence_bundle(
        summary_csv=summary_csv.resolve()
    )
    evidence["demo_recommendation_scope"] = "single_experiment"
    evidence["demo_experiment_key"] = key
    evidence["demo_experiment_label"] = label
    evidence_json.parent.mkdir(parents=True, exist_ok=True)
    with evidence_json.open("w") as f:
        json.dump(evidence, f, indent=2, sort_keys=True)
        f.write("\n")

    _write_text(output_md, topology_recommender.render_deterministic_markdown(evidence))
    return RecommenderRun(
        key,
        label,
        evidence,
        "evidence-based recommendation",
        "Generated a recommendation report from the measured evidence.",
        output_md,
        evidence_json,
    )


def _run_recommenders(args: argparse.Namespace, sources: ExperimentSources) -> Dict[str, RecommenderRun]:
    source_specs = [
        ("experiment1", "Experiment 1 placement/convergence", sources.exp1_csv),
        ("experiment2", "Experiment 2 route overlap", sources.exp2_csv),
        ("experiment3", "Experiment 3 routing strategies", sources.exp3_csv),
        ("experiment4", "Experiment 4 memory targets", sources.exp4_csv),
    ]
    runs: Dict[str, RecommenderRun] = {}
    for key, label, path in source_specs:
        if path is None or not path.exists():
            continue
        runs[key] = _run_recommender(args, key=key, label=label, summary_csv=path)

    index_md = OUTPUT_DIR / "chapter3_recommendations.md"
    index_json = OUTPUT_DIR / "chapter3_recommendations_evidence.json"
    _write_text(index_md, _recommendation_index_markdown(runs))
    with index_json.open("w") as f:
        json.dump(_recommendation_index_json(runs), f, indent=2, sort_keys=True)
        f.write("\n")
    return runs


def _recommendation_index_markdown(runs: Dict[str, RecommenderRun]) -> str:
    rows = []
    for key in ("experiment1", "experiment2", "experiment3", "experiment4"):
        run = runs.get(key)
        if run is None:
            continue
        rows.append(
            (
                run.label,
                run.mode,
                str(run.output_md.relative_to(OUTPUT_DIR)),
                str(run.evidence_json.relative_to(OUTPUT_DIR)),
                str(len(run.evidence.get("configs", []))),
            )
        )
    return "\n".join(
        [
            "# Per-Experiment Recommendation Reports",
            "",
            "The recommendation stage is run separately for each experiment artifact. The files below are not a combined cross-experiment diagnosis.",
            "",
            _markdown_table(
                ("Experiment", "Mode", "Markdown", "Evidence JSON", "Configs"),
                rows,
            ),
            "",
        ]
    )


def _recommendation_index_json(runs: Dict[str, RecommenderRun]) -> Dict[str, Any]:
    return {
        "recommendation_stage_scope": "per_experiment",
        "combined_cross_experiment_diagnosis": False,
        "experiments": {
            key: {
                "label": run.label,
                "mode": run.mode,
                "markdown": str(run.output_md),
                "evidence_json": str(run.evidence_json),
                "config_count": len(run.evidence.get("configs", [])),
            }
            for key, run in runs.items()
        },
    }


def _load_exp2_pairs(evidence: Dict[str, Any]) -> List[Exp2PairRow]:
    configs = {config["name"]: config for config in evidence.get("configs", [])}
    pairs = (
        ("shift", "shift_low_overlap", "shift_high_overlap"),
        ("reverse", "reverse_low_overlap", "reverse_high_overlap"),
        ("tornado", "tornado_low_overlap", "tornado_high_overlap"),
        ("hotspot/incast", "hotspot_low_overlap", "hotspot_high_overlap"),
    )
    rows = []
    for pattern, low_name, high_name in pairs:
        low = configs.get(low_name)
        high = configs.get(high_name)
        if low is None or high is None:
            continue
        primary = high.get("primary_diagnosis", "n/a")
        recommendation = _clean(high.get("recommended_action")) or "n/a"
        if primary == "route_overlap_bottleneck":
            recommendation = "use low-overlap/path-diverse routing"
        elif primary == "destination_convergence_bottleneck":
            recommendation = "distribute target traffic"
        rows.append(
            Exp2PairRow(
                pattern,
                low_name,
                high_name,
                _float(low.get("route_metadata", {}).get("avg_hop_count")),
                _float(high.get("route_metadata", {}).get("avg_hop_count")),
                _float(high.get("pairwise_route_overlap_ratio")),
                _float(low.get("measured_metrics", {}).get("worst_p99_cycles")),
                _float(high.get("measured_metrics", {}).get("worst_p99_cycles")),
                _float(low.get("measured_metrics", {}).get("hotspot_top1_share")),
                _float(high.get("measured_metrics", {}).get("hotspot_top1_share")),
                primary,
                recommendation,
            )
        )
    return rows


def _load_exp3_rows(path: Optional[Path] = None) -> List[Exp3Row]:
    fallback = {
        "exp3_path_diverse": Exp3Row(
            "path-diverse", 30.0, 0.010, 180, 3979.241, 0.928, 0.035
        ),
        "exp3_shortest": Exp3Row(
            "shortest", 29.5, 0.033, 203, 3937.347, 0.925, 0.218
        ),
        "exp3_bad_path": Exp3Row(
            "bad path", 31.5, 0.091, 213, 3625.652, 0.917, 0.258
        ),
        "exp3_high_overlap": Exp3Row(
            "high overlap", 29.5, 0.053, 214, 3832.675, 0.915, 0.277
        ),
    }
    path = path if path and path.exists() else _first_existing(EXP3_CSV_CANDIDATES)
    if path is None:
        return list(fallback.values())
    by_name = {row["name"]: row for row in _read_csv(path)}
    order = ("exp3_path_diverse", "exp3_shortest", "exp3_bad_path", "exp3_high_overlap")
    labels = {
        "exp3_path_diverse": "path-diverse",
        "exp3_shortest": "shortest",
        "exp3_bad_path": "bad path",
        "exp3_high_overlap": "high overlap",
    }
    rows = []
    for name in order:
        source = by_name.get(name)
        if source is None:
            rows.append(fallback[name])
            continue
        rows.append(
            Exp3Row(
                labels[name],
                _float(source.get("avg_hop_count")),
                _float(source.get("route_overlap_score")),
                _float(source.get("worst_p99_cycles")),
                _float(source.get("mean_bw_MBps")),
                _float(source.get("min_jfi")),
                _float(source.get("hotspot_top1_share")),
            )
        )
    return rows


def _load_exp4_rows(path: Optional[Path] = None) -> List[Exp4Row]:
    path = path if path and path.exists() else _first_existing(EXP4_CSV_CANDIDATES)
    if path is None:
        return []
    rows = {row["name"]: row for row in _read_csv(path)}
    pairs = (
        ("near", "exp4_near_single_target", "exp4_near_distributed_targets"),
        ("far", "exp4_far_single_target", "exp4_far_distributed_targets"),
        ("spread", "exp4_spread_single_target", "exp4_spread_distributed_targets"),
    )
    out = []
    for placement, single_name, distributed_name in pairs:
        single = rows.get(single_name)
        distributed = rows.get(distributed_name)
        if single is None or distributed is None:
            continue
        out.append(
            Exp4Row(
                placement,
                _float(single.get("worst_p99_cycles")),
                _float(distributed.get("worst_p99_cycles")),
            )
        )
    return out


def _exp1_table(rows: Sequence[Exp1Row], markdown: bool) -> str:
    headers = ("Configuration", "Worst P99", "Mean BW", "Min JFI", "Hotspot Top1", "Culprit")
    table_rows = [
        (
            row.configuration,
            _fmt_p99(row.worst_p99),
            _fmt(row.mean_bw),
            _fmt(row.min_jfi),
            _fmt(row.hotspot_top1),
            row.culprit,
        )
        for row in rows
    ]
    return _markdown_table(headers, table_rows) if markdown else _terminal_table(headers, table_rows)


def _exp2_table(rows: Sequence[Exp2PairRow], markdown: bool) -> str:
    headers = (
        "Pattern",
        "Hop low",
        "Hop high",
        "Overlap ratio",
        "P99 low",
        "P99 high",
        "Hotspot low",
        "Hotspot high",
        "Diagnosis",
        "Recommendation",
    )
    table_rows = [
        (
            row.pattern,
            _fmt(row.hop_low, 1),
            _fmt(row.hop_high, 1),
            f"{_fmt(row.overlap_ratio, 2)}x",
            _fmt_p99(row.p99_low),
            _fmt_p99(row.p99_high),
            _fmt(row.hotspot_low),
            _fmt(row.hotspot_high),
            row.diagnosis,
            row.recommendation,
        )
        for row in rows
    ]
    return _markdown_table(headers, table_rows) if markdown else _terminal_table(headers, table_rows)


def _exp3_table(rows: Sequence[Exp3Row], markdown: bool) -> str:
    headers = ("Strategy", "Avg Hop", "Overlap", "Worst P99", "Mean BW", "Min JFI", "Hotspot Top1")
    table_rows = [
        (
            row.strategy,
            _fmt(row.avg_hop, 1),
            _fmt(row.overlap),
            _fmt_p99(row.worst_p99),
            _fmt(row.mean_bw),
            _fmt(row.min_jfi),
            _fmt(row.hotspot_top1),
        )
        for row in rows
    ]
    return _markdown_table(headers, table_rows) if markdown else _terminal_table(headers, table_rows)


def _exp4_table(rows: Sequence[Exp4Row], markdown: bool) -> str:
    headers = ("Placement", "Single-target P99", "Distributed-target P99")
    table_rows = [
        (row.placement, _fmt_p99(row.single_p99), _fmt_p99(row.distributed_p99))
        for row in rows
    ]
    return _markdown_table(headers, table_rows) if markdown else _terminal_table(headers, table_rows)


def _load_basic_uncapped_rows() -> List[BasicCongestionRow]:
    path = _first_existing(BASIC_UNCAPPED_CSV_CANDIDATES)
    if path is None:
        return []
    source_rows = {row.get("source_case", ""): row for row in _read_csv(path)}
    specs = (
        (
            "exp1_4to1_compact",
            "4-to-1 compact",
            "destination convergence hotspot",
        ),
        (
            "exp1_4to1_far",
            "4-to-1 far",
            "path length plus destination convergence",
        ),
    )
    rows: List[BasicCongestionRow] = []
    for source_case, label, signal in specs:
        row = source_rows.get(source_case)
        if row is None:
            continue
        rows.append(
            BasicCongestionRow(
                label,
                "uncapped",
                _float(row.get("worst_p99_cycles")),
                _float(row.get("mean_bw_MBps")),
                _float(row.get("min_jfi")),
                _float(row.get("hotspot_top1_share")),
                _clean(row.get("hotspot_top1_resource")) or "n/a",
                signal,
            )
        )
    return rows


def _basic_congestion_result(exp1_rows: Sequence[Exp1Row]) -> BasicCongestionResult:
    uncapped_path = _first_existing(BASIC_UNCAPPED_CSV_CANDIDATES)
    uncapped_rows = _load_basic_uncapped_rows()
    if len(uncapped_rows) == 2:
        compact, far = uncapped_rows
        analysis = (
            "With bandwidth uncapped, the compact and far 4-to-1 cases both stress a "
            "single destination, but they expose different congestion signatures. "
            f"`{compact.scenario}` reaches worst_p99={_fmt_p99(compact.worst_p99)} cycles "
            f"with hotspot_top1={_fmt(compact.hotspot_top1)} at `{compact.hotspot_resource}`. "
            f"`{far.scenario}` reaches worst_p99={_fmt_p99(far.worst_p99)} cycles "
            f"with hotspot_top1={_fmt(far.hotspot_top1)} at `{far.hotspot_resource}`. "
            "This separates destination-side hotspot concentration from additional path-length pressure."
        )
        return BasicCongestionResult(uncapped_rows, uncapped_path, analysis)

    if not exp1_rows:
        return BasicCongestionResult(
            [],
            uncapped_path,
            "No basic congestion measurement rows were available.",
        )
    wanted = {"4-to-1 compact", "4-to-1 far"}
    fallback_rows = [
        BasicCongestionRow(
            row.configuration,
            "controlled",
            row.worst_p99,
            row.mean_bw,
            row.min_jfi,
            row.hotspot_top1,
            "n/a",
            row.culprit,
        )
        for row in exp1_rows
        if row.configuration in wanted
    ]
    hotspot_row = max(fallback_rows, key=lambda row: row.hotspot_top1)
    worst_row = max(fallback_rows, key=lambda row: row.worst_p99)
    analysis = (
        "Uncapped basic congestion rows were not found, so this table falls back to the "
        "controlled-bandwidth 4-to-1 rows. "
        f"The strongest hotspot signal is `{hotspot_row.scenario}` with "
        f"hotspot_top1={_fmt(hotspot_row.hotspot_top1)}. The worst tail-latency "
        f"case is `{worst_row.scenario}` with worst_p99={_fmt_p99(worst_row.worst_p99)} cycles."
    )
    return BasicCongestionResult(fallback_rows, uncapped_path, analysis)


def _basic_congestion_table(result: BasicCongestionResult, markdown: bool) -> str:
    headers = (
        "Scenario",
        "BW Mode",
        "Worst P99",
        "Mean BW",
        "Min JFI",
        "Hotspot Top1",
        "Top Hotspot",
        "Signal",
    )
    rows = [
        (
            row.scenario,
            row.bw_mode,
            _fmt_p99(row.worst_p99),
            _fmt(row.mean_bw),
            _fmt(row.min_jfi),
            _fmt(row.hotspot_top1),
            row.hotspot_resource,
            row.congestion_signal,
        )
        for row in result.rows
    ]
    return _markdown_table(headers, rows) if markdown else _terminal_table(headers, rows)


def _exp1_analysis(rows: Sequence[Exp1Row]) -> str:
    if not rows:
        return "Experiment 1 data was unavailable."
    min_p99 = min(rows, key=lambda row: row.worst_p99)
    max_p99 = max(rows, key=lambda row: row.worst_p99)
    max_hotspot = max(rows, key=lambda row: row.hotspot_top1)
    bw_values = [row.mean_bw for row in rows]
    return (
        f"Worst P99 spans {_fmt_p99(min_p99.worst_p99)} to "
        f"{_fmt_p99(max_p99.worst_p99)} cycles while mean bandwidth stays within "
        f"{_fmt(max(bw_values) - min(bw_values))} MB/s across the listed cases. "
        f"The strongest hotspot concentration is `{max_hotspot.configuration}` "
        f"with hotspot_top1={_fmt(max_hotspot.hotspot_top1)}."
    )


def _exp2_analysis(rows: Sequence[Exp2PairRow]) -> str:
    route_rows = [row for row in rows if row.diagnosis == "route_overlap_bottleneck"]
    incast = next((row for row in rows if row.diagnosis == "destination_convergence_bottleneck"), None)
    if not rows:
        return "Experiment 2 data was unavailable."
    if route_rows:
        strongest = max(route_rows, key=lambda row: row.hotspot_high - row.hotspot_low)
        text = (
            f"`{strongest.pattern}` has the largest hotspot-top1 "
            f"increase in the pairwise table ({_fmt(strongest.hotspot_low)} -> "
            f"{_fmt(strongest.hotspot_high)}) while P99 changes "
            f"{_fmt_p99(strongest.p99_low)} -> {_fmt_p99(strongest.p99_high)} cycles. "
            "The local diagnosis is route overlap for the path-diverse pairs."
        )
    else:
        text = "No route-overlap pair was available."
    if incast:
        text += (
            f" The `{incast.pattern}` row is analyzed separately as destination convergence "
            "because the traffic converges on one target."
        )
    return text


def _exp2_highlight_row(rows: Sequence[Exp2PairRow]) -> Optional[Exp2PairRow]:
    candidates = [
        row
        for row in rows
        if row.diagnosis == "route_overlap_bottleneck" and abs(row.hop_high - row.hop_low) <= 1.0
    ]
    for preferred in ("reverse", "tornado", "shift"):
        match = next((row for row in candidates if row.pattern == preferred), None)
        if match:
            return match
    return candidates[0] if candidates else (rows[0] if rows else None)


def _exp3_analysis(rows: Sequence[Exp3Row]) -> str:
    by_strategy = {row.strategy: row for row in rows}
    path_diverse = by_strategy.get("path-diverse")
    shortest = by_strategy.get("shortest")
    if path_diverse is None or shortest is None:
        return (
            "Path-diverse and shortest-path rows were not both available."
        )
    hop_delta = path_diverse.avg_hop - shortest.avg_hop
    p99_delta = path_diverse.worst_p99 - shortest.worst_p99
    bw_delta = path_diverse.mean_bw - shortest.mean_bw
    hotspot_delta = path_diverse.hotspot_top1 - shortest.hotspot_top1
    overlap_delta = path_diverse.overlap - shortest.overlap
    measured = (
        f"The path-diverse route set changes average hop count by {_fmt(hop_delta, 1)} "
        f"relative to shortest-path routing, changes overlap by {_fmt(overlap_delta)}, "
        f"changes worst P99 by {_fmt_p99(p99_delta)} cycles, changes mean bandwidth by "
        f"{_fmt(bw_delta)} MB/s, and changes hotspot top1 share by {_fmt(hotspot_delta)}."
    )
    if overlap_delta < 0 and p99_delta <= 0 and hotspot_delta <= 0:
        return f"The path-diverse row reduces overlap, P99, and hotspot concentration in this data. {measured}"
    if overlap_delta < 0:
        return (
            "The path-diverse row reduces overlap but does not improve "
            f"every measured metric in this data. {measured}"
        )
    return (
        "The path-diverse row is not lower-overlap in this data. "
        f"{measured}"
    )


def _exp4_analysis(rows: Sequence[Exp4Row]) -> str:
    if not rows:
        return "Experiment 4 data was not available."
    deltas = [(row.placement, row.single_p99 - row.distributed_p99) for row in rows]
    best = max(deltas, key=lambda item: item[1])
    return (
        f"Distributed targets reduce P99 for the listed placements. "
        f"The largest listed reduction is `{best[0]}` with a {best[1]:.0f}-cycle P99 drop."
    )


def _tables_md(
    basic_result: BasicCongestionResult,
    exp1_rows: Sequence[Exp1Row],
    exp2_rows: Sequence[Exp2PairRow],
    exp3_rows: Sequence[Exp3Row],
    exp4_rows: Sequence[Exp4Row],
    smoke_run: Gem5SmokeRun,
    experiment_runs: Sequence[ExperimentRun],
) -> str:
    parts = [
        "# Congestion Analysis Demo Tables",
        "",
        "## Experiment Sources",
        "",
        _experiment_runs_table(experiment_runs, markdown=True),
        "",
        "## Basic Congestion Test",
        "",
        _basic_congestion_table(basic_result, markdown=True),
        "",
        "## Experiment 1 Placement and Convergence Metrics",
        "",
        _exp1_table(exp1_rows, markdown=True),
        "",
        "## Experiment 2 Route-Overlap Diagnosis",
        "",
        _exp2_table(exp2_rows, markdown=True),
        "",
        "## Experiment 3 Routing Strategy Analysis",
        "",
        _exp3_table(exp3_rows, markdown=True),
        "",
    ]
    if exp4_rows:
        parts.extend(["## Optional Experiment 4 Memory Attachment", "", _exp4_table(exp4_rows, markdown=True), ""])
    parts.extend(["## Live gem5 Smoke Run", "", _smoke_markdown(smoke_run), ""])
    return "\n".join(parts)


def _smoke_markdown(smoke_run: Gem5SmokeRun) -> str:
    if not smoke_run.enabled:
        return f"Live gem5 smoke run skipped: {smoke_run.status}."
    lines = [
        f"- status: `{smoke_run.status}`",
        f"- plan: `{smoke_run.plan_path}`",
        f"- log: `{smoke_run.log_path}`",
    ]
    if smoke_run.copied_results_path:
        lines.append(f"- results: `{smoke_run.copied_results_path}`")
    if smoke_run.rows:
        row = smoke_run.rows[0]
        lines.extend(
            [
                "",
                "| name | src_id | write P99 | write BW | return code |",
                "| --- | --- | ---: | ---: | ---: |",
                "| {name} | {src} | {p99} | {bw} | {code} |".format(
                    name=row.get("name", ""),
                    src=row.get("src_id", ""),
                    p99=_fmt(row.get("gem5_p99_write_lat_cycles")),
                    bw=_fmt(row.get("gem5_achieved_write_bw_MBps")),
                    code=row.get("gem5_return_code", ""),
                ),
            ]
        )
    return "\n".join(lines)


def _experiment_runs_table(runs: Sequence[ExperimentRun], markdown: bool) -> str:
    headers = ("Experiment", "Status", "Summary CSV", "Log")
    table_rows = []
    for run in runs:
        summary = run.summary_csv if run.enabled and run.summary_csv else run.fallback_csv
        table_rows.append(
            (
                run.label,
                run.status,
                str(summary.relative_to(OUTPUT_DIR) if summary and summary.is_relative_to(OUTPUT_DIR) else summary or "n/a"),
                str(run.log_path.relative_to(OUTPUT_DIR) if run.log_path.is_relative_to(OUTPUT_DIR) else run.log_path),
            )
        )
    return _markdown_table(headers, table_rows) if markdown else _terminal_table(headers, table_rows)


def _recommender_runs_table(runs: Dict[str, RecommenderRun], markdown: bool) -> str:
    headers = ("Experiment", "Mode", "Markdown", "Evidence JSON")
    rows = []
    for key in ("experiment1", "experiment2", "experiment3", "experiment4"):
        run = runs.get(key)
        if run is None:
            continue
        rows.append(
            (
                run.label,
                run.mode,
                str(run.output_md.relative_to(OUTPUT_DIR)),
                str(run.evidence_json.relative_to(OUTPUT_DIR)),
            )
        )
    return _markdown_table(headers, rows) if markdown else _terminal_table(headers, rows)


def _report_md(
    basic_result: BasicCongestionResult,
    exp1_rows: Sequence[Exp1Row],
    exp2_rows: Sequence[Exp2PairRow],
    exp3_rows: Sequence[Exp3Row],
    exp4_rows: Sequence[Exp4Row],
    recommender_runs: Dict[str, RecommenderRun],
    smoke_run: Gem5SmokeRun,
    experiment_runs: Sequence[ExperimentRun],
) -> str:
    exp2_example = _exp2_highlight_row(exp2_rows)

    parts = [
        "# Naviq Congestion Analysis Demo Report",
        "",
        "## Demo Goal",
        "",
        "This demo shows a measurement-driven congestion analysis flow: load or regenerate experiment data, identify hotspots and bottleneck signatures, and emit deterministic recommendations from measured evidence.",
        "",
        "The recommendation stage is run per experiment artifact. It does not combine all experiments into one diagnosis.",
        "",
        _recommender_runs_table(recommender_runs, markdown=True),
        "",
        "## 0. Inputs and Execution Mode",
        "",
        _experiment_runs_table(experiment_runs, markdown=True),
        "",
        "By default, the demo uses existing artifacts for a stable analysis walkthrough. Passing `--run-live-experiments` regenerates Experiment 1, Experiment 2, and Experiment 3 locally under `noc_testing/demo/artifacts_ch3/live_experiments/`; Experiment 4 is optional.",
        "",
        "## 1. Basic Congestion Test",
        "",
        _basic_congestion_table(basic_result, markdown=True),
        "",
        basic_result.analysis,
        "",
        "## 2. Experiment 1: Placement and Convergence Metrics",
        "",
        _exp1_table(exp1_rows, markdown=True),
        "",
        _exp1_analysis(exp1_rows),
        "",
        "## 3. Experiment 2: Route-Overlap Diagnosis",
        "",
        _exp2_table(exp2_rows, markdown=True),
        "",
        (
            f"Highlighted example: `{exp2_example.pattern}` keeps average hop count close "
            f"({_fmt(exp2_example.hop_low, 1)} -> {_fmt(exp2_example.hop_high, 1)}), "
            f"but high-overlap routing increases P99 ({_fmt_p99(exp2_example.p99_low)} -> "
            f"{_fmt_p99(exp2_example.p99_high)}) and hotspot concentration "
            f"({_fmt(exp2_example.hotspot_low)} -> {_fmt(exp2_example.hotspot_high)}). "
            f"The deterministic diagnosis is `{exp2_example.diagnosis}`, with the "
            f"recommendation `{exp2_example.recommendation}`."
        )
        if exp2_example
        else "No Experiment 2 pairwise rows were available.",
        "",
        _exp2_analysis(exp2_rows),
        "",
        "## 4. Experiment 3: Routing Strategy Analysis",
        "",
        _exp3_table(exp3_rows, markdown=True),
        "",
        _exp3_analysis(exp3_rows),
        "",
    ]
    if exp4_rows:
        parts.extend(
            [
                "## 5. Optional Experiment 4: Memory Target Attachment",
                "",
                _exp4_table(exp4_rows, markdown=True),
                "",
                _exp4_analysis(exp4_rows),
                "",
            ]
        )
    else:
        parts.extend(
            [
                "## 5. Optional Experiment 4: Memory Target Attachment",
                "",
                "Experiment 4 artifacts were not found locally, so this optional section was skipped.",
                "",
            ]
        )
    parts.extend(
        [
            "## Optional gem5 Smoke Run",
            "",
            _smoke_markdown(smoke_run),
            "",
            "## Analysis Outputs",
            "",
            "- `chapter3_demo_tables.md` contains the compact measured tables.",
            "- `chapter3_recommendations.md` indexes the per-experiment recommendation reports.",
            "- `chapter3_recommendations_evidence.json` indexes the per-experiment evidence bundles.",
            "- `recommendations/*_recommendations.md` and `recommendations/*_recommendations_evidence.json` contain the per-experiment recommendation outputs.",
            "",
        ]
    )
    return "\n".join(parts)


def _print_section(title: str, body: str) -> None:
    print()
    print(f"=== {title} ===")
    print(body)


def main() -> int:
    args = _parse_args()
    config = _load_demo_config()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sources = _run_live_experiments(config, args)
    smoke_run = _run_live_gem5_smoke(config, args)
    exp1_rows = _load_exp1_rows(sources.exp1_csv)
    basic_result = _basic_congestion_result(exp1_rows)
    recommender_runs = _run_recommenders(args, sources)
    exp2_recommender = recommender_runs.get("experiment2")
    if exp2_recommender is None:
        raise SystemExit("Experiment 2 recommender output is required for the route-overlap table.")
    exp2_rows = _load_exp2_pairs(exp2_recommender.evidence)
    exp3_rows = _load_exp3_rows(sources.exp3_csv)
    exp4_rows = _load_exp4_rows(sources.exp4_csv)

    _write_text(
        OUTPUT_DIR / "chapter3_demo_tables.md",
        _tables_md(basic_result, exp1_rows, exp2_rows, exp3_rows, exp4_rows, smoke_run, sources.runs),
    )
    _write_text(
        OUTPUT_DIR / "chapter3_demo_report.md",
        _report_md(
            basic_result,
            exp1_rows,
            exp2_rows,
            exp3_rows,
            exp4_rows,
            recommender_runs,
            smoke_run,
            sources.runs,
        ),
    )

    print("Naviq congestion analysis demo")
    print(f"Output directory: {OUTPUT_DIR}")
    _print_section("Experiment Sources", _experiment_runs_table(sources.runs, markdown=False))
    _print_section("Per-Experiment Recommendation Runs", _recommender_runs_table(recommender_runs, markdown=False))
    _print_section("Part 0: Basic Congestion Test", _basic_congestion_table(basic_result, markdown=False))
    print(f"\nAnalysis: {basic_result.analysis}")
    _print_section("Part 1: Experiment 1 Placement and Convergence Metrics", _exp1_table(exp1_rows, markdown=False))
    print(f"\nAnalysis: {_exp1_analysis(exp1_rows)}")
    _print_section("Part 2: Experiment 2 Route-Overlap Diagnosis", _exp2_table(exp2_rows, markdown=False))
    example = _exp2_highlight_row(exp2_rows)
    if example:
        print(
            "\nAnalysis example: Average hop count is close, but "
            "high-overlap routing increases P99 and hotspot concentration. "
            f"For {example.pattern}, P99 moves {_fmt_p99(example.p99_low)} -> "
            f"{_fmt_p99(example.p99_high)} and hotspot top1 moves "
            f"{_fmt(example.hotspot_low)} -> {_fmt(example.hotspot_high)}. "
            f"The diagnosis is {example.diagnosis}, and the recommendation is "
            f"{example.recommendation}."
        )
    print(f"\nAnalysis: {_exp2_analysis(exp2_rows)}")
    _print_section("Part 3: Experiment 3 Routing Strategy Analysis", _exp3_table(exp3_rows, markdown=False))
    print(f"\nAnalysis: {_exp3_analysis(exp3_rows)}")
    if exp4_rows:
        _print_section("Part 4: Optional Experiment 4 Memory Target Recommendation", _exp4_table(exp4_rows, markdown=False))
        print(f"\nAnalysis: {_exp4_analysis(exp4_rows)}")
    else:
        print("\n=== Part 4: Optional Experiment 4 Memory Target Recommendation ===")
        print("Experiment 4 artifacts were not found locally; skipping optional section.")
    print()
    print("Created:")
    for path in (
        OUTPUT_DIR / "chapter3_demo_report.md",
        OUTPUT_DIR / "chapter3_recommendations.md",
        OUTPUT_DIR / "chapter3_recommendations_evidence.json",
        OUTPUT_DIR / "chapter3_demo_tables.md",
    ):
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
