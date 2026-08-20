import os
import subprocess
import sys

from validate import (
    REPO_ROOT,
    THIS_DIR,
    as_float,
    csv_line,
    load_csv_row,
    load_json,
    validate_limiter_comparison,
    validate_limiter_run,
)


GEM5_BIN = REPO_ROOT / "build" / "X86" / "gem5.opt"
SETUP_INCLUDE_DIR = REPO_ROOT / "src" / "noc" / "setup" / "include"

RUNS = [
    ("none", "smartnic_hbm_rtl_limiter_none_pkt100", "case_none_pkt100.py"),
    ("moderate", "smartnic_hbm_rtl_limiter_moderate_pkt100", "case_moderate_pkt100.py"),
    ("strong", "smartnic_hbm_rtl_limiter_strong_pkt100", "case_strong_pkt100.py"),
]

TABLE_COLUMNS = (
    "case",
    "run_label",
    "limiter_config_name",
    "limiter_scope",
    "limiter_backpressure_period",
    "limiter_backpressure_allow",
    "packets_received",
    "checker_bytes_received",
    "dma_axis_bytes_emitted",
    "limiter_input_bytes",
    "limiter_output_bytes",
    "limiter_input_packets",
    "limiter_output_packets",
    "packet_throughput_gbps",
    "axis_stream_window_duration_ns",
    "dma_to_limiter_valid_only_cycles",
    "limiter_to_checker_valid_only_cycles",
    "dma_to_limiter_valid_only_pct",
    "limiter_to_checker_valid_only_pct",
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

    none = row_by_label["smartnic_hbm_rtl_limiter_none_pkt100"]
    strong = row_by_label["smartnic_hbm_rtl_limiter_strong_pkt100"]
    drop_pct = 100.0 * (
        as_float(none, "packet_throughput_gbps") -
        as_float(strong, "packet_throughput_gbps")
    ) / as_float(none, "packet_throughput_gbps")
    print(f"# Strong throughput drop vs none: {drop_pct:.3f}%")


def main() -> int:
    if not GEM5_BIN.exists():
        print(f"missing gem5 binary: {GEM5_BIN}", file=sys.stderr)
        return 2

    stdout_by_label = _run_cases()
    row_by_label = {}
    for _, label, _ in RUNS:
        data = load_json(label)
        row = load_csv_row(label)
        validate_limiter_run(label, data, row)
        row_by_label[label] = row
    validate_limiter_comparison(row_by_label)

    _print_table(row_by_label)
    print("# Pass lines")
    for _, label, _ in RUNS:
        print(_pass_line(stdout_by_label[label], label))
    print("# Raw flattened CSV rows")
    for _, label, _ in RUNS:
        print(csv_line(label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
