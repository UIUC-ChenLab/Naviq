#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
NULL_GEM5 = REPO_ROOT / "build" / "NULL" / "gem5.opt"
X86_GEM5 = REPO_ROOT / "build" / "X86" / "gem5.opt"
HELLO_X86 = REPO_ROOT / "tests" / "test-progs" / "hello" / "bin" / "x86" / "linux" / "hello"
CPU_DDR_WALK_X86 = REPO_ROOT / "src" / "noc" / "cpu" / "programs" / "cpu_ddr_walk_x86"

LOG_ROOT = REPO_ROOT / "noc_testing" / "artifacts" / "smoke"

REQUIRED_SMOKES = [
    "src/noc/testing/generic/aximm_1_to_1_close_smoke.py",
    "src/noc/testing/generic/aximm_1_to_1_far_smoke.py",
    "src/noc/testing/generic/axis_1_to_1_smoke.py",
    "src/noc/testing/generic/aximm_1_to_1_close_long_smoke.py",
    "src/noc/testing/generic/aximm_1_to_1_far_long_smoke.py",
    "src/noc/testing/generic/axis_1_to_1_long_smoke.py",
    "src/noc/testing/generic/aximm_2_to_2_smoke.py",
    "src/noc/testing/generic/aximm_1_to_4_smoke.py",
    "src/noc/testing/generic/axis_2_to_2_smoke.py",
    "src/noc/testing/generic/axis_2_to_2_long_smoke.py",
    "src/noc/testing/generic/axis_fifo_smoke.py",
    "src/noc/testing/ddr/ddr_direct_interleaved_smoke.py",
    "src/noc/testing/ddr/ddr_direct_contention_smoke.py",
    "src/noc/testing/ddr/ddr_dma_axis_sink_smoke.py",
    "src/noc/testing/ddr/ddr_dma_ppe_base_axis_sink_smoke.py",
    "src/noc/testing/hbm/hbm_shared_controller_smoke.py",
    "src/noc/testing/hbm/hbm_shared_controller_contention_smoke.py",
    "src/noc/testing/hbm/hbm_single_port_smoke.py",
    "src/noc/testing/hbm/hbm_single_port_unaligned_smoke.py",
    "src/noc/testing/hbm/hbm_multi_hbm_multi_nmu_smoke.py",
    "src/noc/testing/hbm/hbm_mixed_bram_hbm_smoke.py",
    "src/noc/testing/hbm/hbm_32tg_16mc_uncapped_bandwidth_smoke.py",
]

OPTIONAL_CPU_SMOKES = [
    "src/noc/testing/ddr/cpu_ddr_hello_smoke.py",
    "src/noc/testing/ddr/cpu_ddr_memory_smoke.py",
    "src/noc/testing/ddr/cpu_ddr_walk_smoke.py",
    "src/noc/testing/ddr/cpu_ddr_dma_axis_sink_smoke.py",
    "src/noc/testing/ddr/cpu_ddr_dma_ppe_base_axis_sink_smoke.py",
]

TIMEOUT_CAUSE_SUBSTRINGS = [
    "simulate() limit reached",
    "tick exit reached",
    "maxtick",
    "max tick",
    "completed simcycles",
]


@dataclass
class SmokeResult:
    path: str
    category: str
    returncode: int
    passed: bool
    skipped: bool
    reason: str
    exit_cause: str | None
    completed_reads: list[int]
    completed_writes: list[int]
    log_path: Path


def parse_skip_reason(text: str):
    match = re.search(r"SMOKE_SKIP:\s*(.+)", text)
    return match.group(1).strip() if match else None


def cpu_prereqs_available():
    return all(
        path.exists()
        for path in (
            X86_GEM5,
            HELLO_X86,
            CPU_DDR_WALK_X86,
        )
    )


def select_gem5_binary(smoke_path: str):
    if Path(smoke_path).name.startswith("cpu_"):
        return X86_GEM5
    return NULL_GEM5


def parse_exit_cause(text: str):
    match = re.search(r"Exiting @ tick \d+ because (.+)", text)
    return match.group(1).strip() if match else None


def parse_completion_counts(text: str):
    reads = [int(value) for value in re.findall(r"Completed Reads:\s*(\d+)", text)]
    writes = [int(value) for value in re.findall(r"Completed Writes:\s*(\d+)", text)]
    return reads, writes


def contains_failure_markers(text: str):
    lowered = text.lower()
    return "panic:" in lowered or "fatal:" in lowered or "m5.fatal" in lowered


def is_timeout_cause(cause: str | None):
    if cause is None:
        return False
    lowered = cause.lower()
    return any(token in lowered for token in TIMEOUT_CAUSE_SUBSTRINGS)


def has_completion_marker(text: str):
    return (
        "completed" in text.lower()
        or "started dma" in text.lower()
        or "reads and writes completed" in text.lower()
    )


def write_log(log_path: Path, cmd: list[str], proc: subprocess.CompletedProcess[str]):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                f"COMMAND: {' '.join(cmd)}",
                "",
                "--- STDOUT ---",
                proc.stdout,
                "",
                "--- STDERR ---",
                proc.stderr,
                "",
            ]
        )
    )


def run_one(smoke_path: str, category: str, log_dir: Path):
    gem5 = select_gem5_binary(smoke_path)
    cmd = [str(gem5), smoke_path]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    log_path = log_dir / f"{Path(smoke_path).stem}.log"
    write_log(log_path, cmd, proc)
    text = proc.stdout + "\n" + proc.stderr
    exit_cause = parse_exit_cause(text)
    completed_reads, completed_writes = parse_completion_counts(text)
    skip_reason = parse_skip_reason(text)

    if proc.returncode == 0 and skip_reason:
        return SmokeResult(
            smoke_path,
            category,
            proc.returncode,
            False,
            True,
            skip_reason,
            exit_cause,
            completed_reads,
            completed_writes,
            log_path,
        )

    if proc.returncode != 0:
        return SmokeResult(
            smoke_path,
            category,
            proc.returncode,
            False,
            False,
            f"nonzero return code {proc.returncode}",
            exit_cause,
            completed_reads,
            completed_writes,
            log_path,
        )

    if contains_failure_markers(text):
        return SmokeResult(
            smoke_path,
            category,
            proc.returncode,
            False,
            False,
            "panic/fatal marker found in output",
            exit_cause,
            completed_reads,
            completed_writes,
            log_path,
        )

    if is_timeout_cause(exit_cause):
        return SmokeResult(
            smoke_path,
            category,
            proc.returncode,
            False,
            False,
            f"timeout-like exit cause: {exit_cause}",
            exit_cause,
            completed_reads,
            completed_writes,
            log_path,
        )

    if (completed_reads or completed_writes) and (
        sum(completed_reads) + sum(completed_writes) == 0
    ):
        return SmokeResult(
            smoke_path,
            category,
            proc.returncode,
            False,
            False,
            "all completion counters were zero",
            exit_cause,
            completed_reads,
            completed_writes,
            log_path,
        )

    if not completed_reads and not completed_writes and not has_completion_marker(text):
        return SmokeResult(
            smoke_path,
            category,
            proc.returncode,
            False,
            False,
            "no completion evidence found in output",
            exit_cause,
            completed_reads,
            completed_writes,
            log_path,
        )

    return SmokeResult(
        smoke_path,
        category,
        proc.returncode,
        True,
        False,
        "ok",
        exit_cause,
        completed_reads,
        completed_writes,
        log_path,
    )


def filter_paths(paths: list[str], only_patterns: list[str]):
    if not only_patterns:
        return list(paths)
    filtered = []
    for path in paths:
        if any(pattern in path or pattern in Path(path).stem for pattern in only_patterns):
            filtered.append(path)
    return filtered


def print_result(result: SmokeResult):
    state = "SKIP" if result.skipped else ("PASS" if result.passed else "FAIL")
    print(f"[{state}] {result.path}")
    print(f"  reason: {result.reason}")
    if result.exit_cause:
        print(f"  exit: {result.exit_cause}")
    if result.completed_writes:
        print(f"  writes: {result.completed_writes}")
    if result.completed_reads:
        print(f"  reads: {result.completed_reads}")
    print(f"  log: {result.log_path}")


def main():
    parser = argparse.ArgumentParser(description="Run explicit NoC smoke tests.")
    parser.add_argument("--with-cpu", action="store_true", help="Include optional CPU smokes when prerequisites are available.")
    parser.add_argument("--skip-cpu", action="store_true", help="Disable CPU auto-detection and skip optional CPU smokes.")
    parser.add_argument("--only", action="append", default=[], help="Run only smokes whose path or stem contains this substring. May be repeated.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failing smoke.")
    args = parser.parse_args()

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = LOG_ROOT / run_tag
    log_dir.mkdir(parents=True, exist_ok=True)

    required = filter_paths(REQUIRED_SMOKES, args.only)
    cpu_requested = not args.skip_cpu and (args.with_cpu or cpu_prereqs_available())
    cpu_smokes = filter_paths(OPTIONAL_CPU_SMOKES, args.only) if cpu_requested else []

    results: list[SmokeResult] = []

    for smoke_path in required:
        result = run_one(smoke_path, "required", log_dir)
        results.append(result)
        print_result(result)
        if args.fail_fast and not result.passed:
            break

    if not args.fail_fast or all(result.passed for result in results):
        if cpu_requested and cpu_prereqs_available():
            for smoke_path in cpu_smokes:
                result = run_one(smoke_path, "cpu", log_dir)
                results.append(result)
                print_result(result)
                if args.fail_fast and not result.passed:
                    break
        elif not args.skip_cpu:
            results.append(
                SmokeResult(
                    path="optional_cpu_bucket",
                    category="cpu",
                    returncode=0,
                    passed=False,
                    skipped=True,
                    reason="CPU prerequisites missing; skipped optional CPU smokes",
                    exit_cause=None,
                    completed_reads=[],
                    completed_writes=[],
                    log_path=log_dir,
                )
            )
            print_result(results[-1])

    required_failures = [
        result
        for result in results
        if result.category == "required" and not result.passed and not result.skipped
    ]
    cpu_failures = [
        result
        for result in results
        if result.category == "cpu" and not result.passed and not result.skipped
    ]

    print("\nSummary")
    print(f"  required passed: {sum(1 for r in results if r.category == 'required' and r.passed)}")
    print(f"  required skipped: {sum(1 for r in results if r.category == 'required' and r.skipped)}")
    print(f"  required failed: {len(required_failures)}")
    print(f"  cpu passed: {sum(1 for r in results if r.category == 'cpu' and r.passed)}")
    print(f"  cpu failed: {len(cpu_failures)}")
    print(f"  cpu skipped: {sum(1 for r in results if r.category == 'cpu' and r.skipped)}")
    print(f"  logs: {log_dir}")

    if required_failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
