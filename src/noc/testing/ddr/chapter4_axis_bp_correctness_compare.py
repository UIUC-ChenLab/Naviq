import csv
import json
import subprocess
import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[3]
GEM5_BIN = REPO_ROOT / "build" / "X86" / "gem5.opt"
METRICS_DIR = REPO_ROOT / "src" / "noc" / "out" / "csv"
EXPECTED_PACKETS = 100
EXPECTED_CHECKER_BYTES = 20200
EXPECTED_DMA_BYTES = 23400

RUNS = [
    {
        "case": "none",
        "label": "smartnic_axis_bp_correctness_none_pkt100",
        "script": THIS_DIR / "smartnic_axis_bp_correctness_none_pkt100.py",
    },
    {
        "case": "moderate",
        "label": "smartnic_axis_bp_correctness_moderate_pkt100",
        "script": THIS_DIR / "smartnic_axis_bp_correctness_moderate_pkt100.py",
    },
    {
        "case": "strong",
        "label": "smartnic_axis_bp_correctness_strong_pkt100",
        "script": THIS_DIR / "smartnic_axis_bp_correctness_strong_pkt100.py",
    },
]

TABLE_COLUMNS = [
    "case",
    "run_label",
    "backpressure_period",
    "backpressure_allow",
    "measurement_valid",
    "packets_received",
    "checker_bytes_received",
    "dma_bytes_read",
    "shim_input_bytes",
    "shim_output_bytes",
    "shim_input_packets",
    "shim_output_packets",
    "axis_stability_violation",
    "dma_to_shim_valid_only_pct",
    "shim_to_checker_valid_only_pct",
    "packet_throughput_gbps",
    "axis_stream_window_duration_ns",
    "dma_read_avg_latency_cycles",
    "dma_read_p99_cycles",
    "shim_fifo_max_occupancy",
    "invalid_reason",
]


def _artifact_path(label: str, suffix: str) -> Path:
    return METRICS_DIR / f"{label}{suffix}"


def _load_json(label: str):
    with _artifact_path(label, ".json").open() as f:
        return json.load(f)


def _load_csv_row(label: str):
    with _artifact_path(label, ".csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1:
        raise RuntimeError(f"expected exactly one CSV row for {label}")
    return rows[0]


def _csv_line(label: str) -> str:
    lines = _artifact_path(label, ".csv").read_text().splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"missing CSV row for {label}")
    return lines[1]


def _extract_pass_line(stdout: str, label: str) -> str:
    for line in reversed(stdout.splitlines()):
        if "PASS" in line:
            return line
    raise RuntimeError(f"missing pass line for {label}")


def _as_int(row: dict, key: str) -> int:
    return int(float(row.get(key) or 0))


def _as_float(row: dict, key: str) -> float:
    return float(row.get(key) or 0.0)


def _validate_run(label: str, data: dict, row: dict) -> None:
    if not data.get("measurement_valid"):
        bp = data.get("backpressure_summary", {})
        detail = (
            f" stability={bp.get('axis_stability_violation')} "
            f"tick={bp.get('axis_stability_violation_tick')} "
            f"signal={bp.get('axis_stability_violation_signal')} "
            f"side={bp.get('axis_stability_violation_side')}"
        )
        raise RuntimeError(
            f"{label}: invalid measurement: {data.get('invalid_reason', '')}{detail}"
        )
    if data.get("invalid_reason"):
        raise RuntimeError(f"{label}: invalid_reason not empty: {data['invalid_reason']}")
    if _as_int(row, "packets_expected") != EXPECTED_PACKETS:
        raise RuntimeError(f"{label}: packets_expected={row.get('packets_expected')}")
    if _as_int(row, "packets_received") != EXPECTED_PACKETS:
        raise RuntimeError(f"{label}: packets_received={row.get('packets_received')}")
    if _as_int(row, "checker_bytes_received") != EXPECTED_CHECKER_BYTES:
        raise RuntimeError(f"{label}: checker_bytes_received={row.get('checker_bytes_received')}")
    if _as_int(row, "axis_bytes_emitted") != EXPECTED_CHECKER_BYTES:
        raise RuntimeError(f"{label}: axis_bytes_emitted={row.get('axis_bytes_emitted')}")
    if _as_int(row, "dma_bytes_read") != EXPECTED_DMA_BYTES:
        raise RuntimeError(f"{label}: dma_bytes_read={row.get('dma_bytes_read')}")
    if _as_int(row, "cpu_ddr_read_bytes_overlap") > 1024:
        raise RuntimeError(f"{label}: cpu_ddr_read_bytes_overlap={row.get('cpu_ddr_read_bytes_overlap')}")
    if str(row.get("axis_stability_violation")).lower() == "true":
        raise RuntimeError(f"{label}: axis stability violation")
    if _as_int(row, "shim_input_bytes") != EXPECTED_CHECKER_BYTES:
        raise RuntimeError(f"{label}: shim_input_bytes={row.get('shim_input_bytes')}")
    if _as_int(row, "shim_output_bytes") != EXPECTED_CHECKER_BYTES:
        raise RuntimeError(f"{label}: shim_output_bytes={row.get('shim_output_bytes')}")
    if _as_int(row, "shim_input_packets") != EXPECTED_PACKETS:
        raise RuntimeError(f"{label}: shim_input_packets={row.get('shim_input_packets')}")
    if _as_int(row, "shim_output_packets") != EXPECTED_PACKETS:
        raise RuntimeError(f"{label}: shim_output_packets={row.get('shim_output_packets')}")
    if _as_int(row, "shim_input_tlast_count") != EXPECTED_PACKETS:
        raise RuntimeError(f"{label}: shim_input_tlast_count={row.get('shim_input_tlast_count')}")
    if _as_int(row, "shim_output_tlast_count") != EXPECTED_PACKETS:
        raise RuntimeError(f"{label}: shim_output_tlast_count={row.get('shim_output_tlast_count')}")
    if _as_int(row, "dma_to_shim_accepted_beats") != _as_int(row, "shim_to_checker_accepted_beats"):
        raise RuntimeError(
            f"{label}: accepted beat mismatch in={row.get('dma_to_shim_accepted_beats')} "
            f"out={row.get('shim_to_checker_accepted_beats')}"
        )
    op = data.get("operation_window", {})
    axis = data.get("axis_stream_window", {})
    if op.get("start_tick") is None or op.get("end_tick") is None:
        raise RuntimeError(f"{label}: missing operation window")
    if axis.get("start_tick") is None or axis.get("end_tick") is None:
        raise RuntimeError(f"{label}: missing axis stream window")


def _validate_comparison(row_by_label: dict) -> None:
    none = row_by_label["smartnic_axis_bp_correctness_none_pkt100"]
    moderate = row_by_label["smartnic_axis_bp_correctness_moderate_pkt100"]
    strong = row_by_label["smartnic_axis_bp_correctness_strong_pkt100"]
    if not (_as_float(moderate, "axis_stream_window_duration_ns") > _as_float(none, "axis_stream_window_duration_ns")):
        raise RuntimeError("moderate AXIS stream duration is not above none duration")
    if not (_as_float(strong, "axis_stream_window_duration_ns") > _as_float(moderate, "axis_stream_window_duration_ns")):
        raise RuntimeError("strong AXIS stream duration is not above moderate duration")
    if not (_as_float(moderate, "packet_throughput_gbps") < _as_float(none, "packet_throughput_gbps")):
        raise RuntimeError("moderate throughput is not below none throughput")
    if not (_as_float(strong, "packet_throughput_gbps") < _as_float(moderate, "packet_throughput_gbps")):
        raise RuntimeError("strong throughput is not below moderate throughput")
    if _as_float(moderate, "dma_to_shim_valid_only_pct") <= _as_float(none, "dma_to_shim_valid_only_pct"):
        raise RuntimeError("moderate DMA-side valid_only did not increase")
    if _as_float(strong, "dma_to_shim_valid_only_pct") <= _as_float(moderate, "dma_to_shim_valid_only_pct"):
        raise RuntimeError("strong DMA-side valid_only did not increase")


def _print_table(row_by_label: dict) -> None:
    print(",".join(TABLE_COLUMNS))
    for run in RUNS:
        row = row_by_label[run["label"]]
        table_row = {"case": run["case"], "run_label": run["label"]}
        for key in TABLE_COLUMNS:
            table_row.setdefault(key, row.get(key, ""))
        print(",".join(str(table_row.get(key, "")) for key in TABLE_COLUMNS))


def main() -> int:
    if not GEM5_BIN.exists():
        print(f"missing gem5 binary: {GEM5_BIN}", file=sys.stderr)
        return 2

    stdout_by_label = {}
    for run in RUNS:
        proc = subprocess.run(
            [str(GEM5_BIN), str(run["script"])],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        stdout_by_label[run["label"]] = proc.stdout
        if proc.returncode != 0:
            sys.stdout.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            raise RuntimeError(f"{run['label']}: gem5 exited with code {proc.returncode}")

    json_by_label = {run["label"]: _load_json(run["label"]) for run in RUNS}
    row_by_label = {run["label"]: _load_csv_row(run["label"]) for run in RUNS}
    for run in RUNS:
        _validate_run(run["label"], json_by_label[run["label"]], row_by_label[run["label"]])
    _validate_comparison(row_by_label)

    print("# Comparison table")
    _print_table(row_by_label)
    print("# Pass lines")
    for run in RUNS:
        print(_extract_pass_line(stdout_by_label[run["label"]], run["label"]))
    print("# Raw flattened CSV rows")
    for run in RUNS:
        print(_csv_line(run["label"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
