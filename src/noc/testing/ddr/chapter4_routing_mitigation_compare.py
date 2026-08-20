import csv
import json
import subprocess
import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[3]
GEM5_BIN = REPO_ROOT / "build" / "X86" / "gem5.opt"
METRICS_DIR = REPO_ROOT / "src" / "noc" / "out" / "csv"

RUNS = [
    {
        "case": "baseline",
        "label": "smartnic_ddr_contention_baseline_pkt100",
        "script": THIS_DIR / "smartnic_ddr_contention_baseline_pkt100.py",
    },
    {
        "case": "high_overlap",
        "label": "smartnic_ddr_contention_high_overlap_pkt100",
        "script": THIS_DIR / "smartnic_ddr_contention_high_overlap_pkt100.py",
    },
    {
        "case": "separated",
        "label": "smartnic_ddr_contention_separated_pkt100",
        "script": THIS_DIR / "smartnic_ddr_contention_separated_pkt100.py",
    },
]

TABLE_COLUMNS = [
    "case",
    "run_label",
    "cpu_ddr_read_bytes_overlap",
    "dma_read_avg_latency_cycles",
    "dma_read_p99_cycles",
    "packet_throughput_gbps",
    "operation_window_duration_ns",
    "axis_stream_window_duration_ns",
    "cpu_ddr_hop_count",
    "dma_ddr_hop_count",
    "cpu_dma_ddr_path_overlap_score",
    "shared_resource_count",
    "top_shared_resource_id",
    "hotspot_top1_share",
    "worst_endpoint_culprit",
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
    return int(row.get(key) or 0)


def _validate_run(label: str, data: dict, row: dict) -> None:
    if not data.get("measurement_valid"):
        raise RuntimeError(f"{label}: invalid measurement: {data.get('invalid_reason', '')}")
    if data.get("invalid_reason"):
        raise RuntimeError(f"{label}: invalid_reason not empty: {data['invalid_reason']}")
    if row.get("packets_expected") != "100" or row.get("packets_received") != "100":
        raise RuntimeError(
            f"{label}: packet mismatch expected={row.get('packets_expected')} "
            f"received={row.get('packets_received')}"
        )
    if row.get("checker_bytes_received") != row.get("axis_bytes_emitted"):
        raise RuntimeError(
            f"{label}: checker bytes {row.get('checker_bytes_received')} "
            f"!= axis bytes {row.get('axis_bytes_emitted')}"
        )
    if row.get("dma_bytes_read") != "23400":
        raise RuntimeError(f"{label}: unexpected dma_bytes_read={row.get('dma_bytes_read')}")
    if _as_int(row, "cpu_ddr_read_bytes_overlap") < 45056:
        raise RuntimeError(
            f"{label}: cpu_ddr_read_bytes_overlap below target: "
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
    route = data.get("route_metadata", {})
    required_route_fields = [
        "cpu_ddr_hop_count",
        "dma_ddr_hop_count",
        "cpu_dma_ddr_path_overlap_score",
        "shared_resource_count",
        "top_shared_resource_id",
    ]
    missing = [
        key for key in required_route_fields
        if route.get(key) in (None, "") and key != "top_shared_resource_id"
    ]
    if missing:
        raise RuntimeError(f"{label}: missing route metadata fields: {missing}")


def _validate_overlap_consistency(rows: dict) -> None:
    values = [
        _as_int(row, "cpu_ddr_read_bytes_overlap")
        for row in rows.values()
    ]
    low = min(values)
    high = max(values)
    midpoint = sum(values) / len(values)
    if midpoint <= 0:
        raise RuntimeError("cpu DDR overlap midpoint is zero")
    if (high - low) / midpoint > 0.20:
        raise RuntimeError(
            "CPU DDR overlap bytes are not within +/-10% across cases: "
            + ", ".join(str(v) for v in values)
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
    _validate_overlap_consistency(row_by_label)

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
