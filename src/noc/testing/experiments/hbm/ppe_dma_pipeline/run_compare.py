import os
import subprocess
import sys

from validate import (
    REPO_ROOT,
    THIS_DIR,
    load_csv_row,
    load_json,
    validate_pipeline_run,
)


GEM5_BIN = REPO_ROOT / "build" / "X86" / "gem5.opt"
SETUP_INCLUDE_DIR = REPO_ROOT / "src" / "noc" / "setup" / "include"

RUNS = [
    ("direct", "smartnic_hbm_direct_dma_pkt500_hbmclk1600_buf128_mo32_rrob128_funcpreload", "case_direct_pkt500.py"),
    ("ppe", "smartnic_hbm_ppe_dma_pkt500_hbmclk1600_buf128_mo32_rrob128_funcpreload", "case_ppe_pkt500.py"),
]

TABLE_COLUMNS = (
    "case",
    "run_label",
    "packets_received",
    "checker_bytes_received",
    "dma_bytes_read",
    "axis_bytes_emitted",
    "packet_throughput_gbps",
    "operation_window_duration_ns",
    "axis_stream_window_duration_ns",
    "dma_read_avg_latency_cycles",
    "dma_read_p99_cycles",
    "memory_endpoint_type",
)


def _gem5_env() -> dict:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SETUP_INCLUDE_DIR)
        if not existing_pythonpath
        else f"{SETUP_INCLUDE_DIR}{os.pathsep}{existing_pythonpath}"
    )
    return env


def _pass_line(stdout: str, label: str) -> str:
    for line in reversed(stdout.splitlines()):
        if "PASS" in line:
            return line
    raise RuntimeError(f"missing pass line for {label}")


def _run_cases() -> dict:
    stdout_by_label = {}
    for _, label, script_name in RUNS:
        proc = subprocess.run(
            [str(GEM5_BIN), str(THIS_DIR / script_name)],
            cwd=str(REPO_ROOT),
            env=_gem5_env(),
            capture_output=True,
            text=True,
        )
        stdout_by_label[label] = proc.stdout
        if proc.returncode != 0:
            sys.stdout.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            raise RuntimeError(f"{label}: gem5 exited with code {proc.returncode}")
    return stdout_by_label


def _print_table(row_by_label: dict) -> None:
    print("# Comparison table")
    print(",".join(TABLE_COLUMNS))
    for case, label, _ in RUNS:
        row = row_by_label[label]
        values = {"case": case, "run_label": label, **row}
        print(",".join(str(values.get(key, "")) for key in TABLE_COLUMNS))


def main() -> int:
    if not GEM5_BIN.exists():
        print(f"missing gem5 binary: {GEM5_BIN}", file=sys.stderr)
        return 2

    stdout_by_label = _run_cases()
    row_by_label = {}
    for _, label, _ in RUNS:
        data = load_json(label)
        row = load_csv_row(label)
        validate_pipeline_run(label, data, row)
        row_by_label[label] = row

    _print_table(row_by_label)
    print("# Pass lines")
    for _, label, _ in RUNS:
        print(_pass_line(stdout_by_label[label], label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
