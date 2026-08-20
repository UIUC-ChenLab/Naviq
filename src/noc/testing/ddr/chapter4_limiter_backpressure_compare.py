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

RUNS = [
    {
        "case": "none",
        "label": "smartnic_limiter_none_v2_pkt100",
        "script": THIS_DIR / "smartnic_limiter_none_pkt100.py",
    },
    {
        "case": "moderate",
        "label": "smartnic_limiter_moderate_v2_pkt100",
        "script": THIS_DIR / "smartnic_limiter_moderate_pkt100.py",
    },
    {
        "case": "strong",
        "label": "smartnic_limiter_strong_v2_pkt100",
        "script": THIS_DIR / "smartnic_limiter_strong_pkt100.py",
    },
]

TABLE_COLUMNS = [
    "case",
    "run_label",
    "limiter_config_name",
    "limiter_backpressure_period",
    "limiter_backpressure_allow",
    "packets_received",
    "checker_bytes_received",
    "dma_bytes_read",
    "limiter_input_bytes",
    "limiter_output_bytes",
    "limiter_input_packets",
    "limiter_output_packets",
    "dma_read_avg_latency_cycles",
    "dma_read_p99_cycles",
    "packet_throughput_gbps",
    "operation_window_duration_ns",
    "axis_stream_window_duration_ns",
    "cpu_ddr_read_bytes_overlap",
    "worst_endpoint_culprit",
    "dma_to_limiter_valid_only_pct",
    "limiter_to_checker_valid_only_pct",
    "limiter_fifo_max_occupancy",
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
        raise RuntimeError(f"{label}: invalid measurement: {data.get('invalid_reason', '')}")
    if data.get("invalid_reason"):
        raise RuntimeError(f"{label}: invalid_reason not empty: {data['invalid_reason']}")
    expected_packets = str(EXPECTED_PACKETS)
    if row.get("packets_expected") != expected_packets or row.get("packets_received") != expected_packets:
        raise RuntimeError(
            f"{label}: packet mismatch expected={row.get('packets_expected')} "
            f"received={row.get('packets_received')}"
        )
    if row.get("checker_bytes_received") != row.get("axis_bytes_emitted"):
        raise RuntimeError(
            f"{label}: checker bytes {row.get('checker_bytes_received')} "
            f"!= axis bytes {row.get('axis_bytes_emitted')}"
        )
    if _as_int(row, "dma_bytes_read") <= 0:
        raise RuntimeError(f"{label}: unexpected dma_bytes_read={row.get('dma_bytes_read')}")
    if row.get("dma_axis_bytes_emitted") != row.get("limiter_input_bytes"):
        raise RuntimeError(
            f"{label}: dma_axis_bytes_emitted={row.get('dma_axis_bytes_emitted')} "
            f"!= limiter_input_bytes={row.get('limiter_input_bytes')}"
        )
    if row.get("limiter_output_bytes") != row.get("checker_bytes_received"):
        raise RuntimeError(
            f"{label}: limiter_output_bytes={row.get('limiter_output_bytes')} "
            f"!= checker_bytes_received={row.get('checker_bytes_received')}"
        )
    if row.get("limiter_input_packets") != expected_packets or row.get("limiter_output_packets") != expected_packets:
        raise RuntimeError(
            f"{label}: limiter packet mismatch in={row.get('limiter_input_packets')} "
            f"out={row.get('limiter_output_packets')}"
        )
    if _as_int(row, "limiter_buffered_bytes") != 0:
        raise RuntimeError(f"{label}: limiter buffered bytes nonzero")
    if _as_int(row, "limiter_buffered_packets") != 0:
        raise RuntimeError(f"{label}: limiter buffered packets nonzero")
    if _as_int(row, "cpu_ddr_read_bytes_overlap") > 1024:
        raise RuntimeError(
            f"{label}: unexpected CPU DDR overlap bytes: "
            f"{row.get('cpu_ddr_read_bytes_overlap')}"
        )
    op = data.get("operation_window", {})
    axis = data.get("axis_stream_window", {})
    if op.get("start_tick") is None or op.get("end_tick") is None:
        raise RuntimeError(f"{label}: missing operation window")
    if axis.get("start_tick") is None or axis.get("end_tick") is None:
        raise RuntimeError(f"{label}: missing axis stream window")
    if int(op["start_tick"]) > int(axis["start_tick"]):
        raise RuntimeError(f"{label}: operation window starts after axis stream")
    if not data.get("endpoint_map"):
        raise RuntimeError(f"{label}: missing endpoint map")
    if not data.get("clock_metadata"):
        raise RuntimeError(f"{label}: missing clock metadata")


def _validate_comparison(row_by_label: dict) -> None:
    none = row_by_label["smartnic_limiter_none_v2_pkt100"]
    moderate = row_by_label["smartnic_limiter_moderate_v2_pkt100"]
    strong = row_by_label["smartnic_limiter_strong_v2_pkt100"]

    if not (_as_float(moderate, "packet_throughput_gbps") < _as_float(none, "packet_throughput_gbps")):
        raise RuntimeError("moderate throughput is not below none throughput")
    if not (_as_float(strong, "packet_throughput_gbps") < _as_float(moderate, "packet_throughput_gbps")):
        raise RuntimeError("strong throughput is not below moderate throughput")
    if not (_as_float(moderate, "axis_stream_window_duration_ns") > _as_float(none, "axis_stream_window_duration_ns")):
        raise RuntimeError("moderate AXIS stream duration is not above none duration")
    if not (_as_float(strong, "axis_stream_window_duration_ns") > _as_float(moderate, "axis_stream_window_duration_ns")):
        raise RuntimeError("strong AXIS stream duration is not above moderate duration")
    dma_bytes = {_as_int(row, "dma_bytes_read") for row in row_by_label.values()}
    if len(dma_bytes) != 1:
        raise RuntimeError(f"DMA bytes read not fixed across cases: {sorted(dma_bytes)}")

    none_tput = _as_float(none, "packet_throughput_gbps")
    strong_tput = _as_float(strong, "packet_throughput_gbps")
    throughput_drop_pct = 100.0 * (none_tput - strong_tput) / none_tput
    valid_only_increase = (
        _as_float(strong, "dma_to_limiter_valid_only_pct") >
        _as_float(none, "dma_to_limiter_valid_only_pct")
    )
    if throughput_drop_pct < 10.0 and not valid_only_increase:
        raise RuntimeError(
            "v2 limiter comparison is not useful: strong throughput drop is "
            f"{throughput_drop_pct:.3f}% and DMA-side valid_only did not increase"
        )


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
