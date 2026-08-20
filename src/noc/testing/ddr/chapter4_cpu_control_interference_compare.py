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
        "label": "smartnic_data_plane_only_ppe_none_pkt100",
        "script": THIS_DIR / "smartnic_data_plane_only_ppe_none_pkt100.py",
    },
    {
        "label": "smartnic_control_heavy_ppe_none_pkt100",
        "script": THIS_DIR / "smartnic_control_heavy_ppe_none_pkt100.py",
    },
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
    path = _artifact_path(label, ".csv")
    lines = path.read_text().splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"missing CSV row in {path}")
    return lines[1]


def _extract_pass_line(stdout: str, label: str) -> str:
    for line in reversed(stdout.splitlines()):
        if "PASS" in line or "smoke]" in line:
            return line
    raise RuntimeError(f"missing pass/fail line for {label}")


def _validate_run(label: str, data: dict, row: dict) -> None:
    if not data.get("measurement_valid"):
        raise RuntimeError(f"{label}: invalid measurement: {data.get('invalid_reason', '')}")
    if data.get("invalid_reason"):
        raise RuntimeError(f"{label}: invalid_reason not empty: {data['invalid_reason']}")
    op = data.get("operation_window", {})
    axis = data.get("axis_stream_window", {})
    if op.get("start_tick") is None or op.get("end_tick") is None:
        raise RuntimeError(f"{label}: missing operation_window")
    if axis.get("start_tick") is None or axis.get("end_tick") is None:
        raise RuntimeError(f"{label}: missing axis_stream_window")
    if int(op["start_tick"]) > int(axis["start_tick"]):
        raise RuntimeError(f"{label}: operation_window starts after axis_stream_window")
    if float(axis.get("duration_ns") or 0.0) <= 0.0:
        raise RuntimeError(f"{label}: axis_stream_window duration is not positive")
    if not data.get("endpoint_map"):
        raise RuntimeError(f"{label}: missing endpoint labels")
    if not data.get("clock_metadata"):
        raise RuntimeError(f"{label}: missing clock metadata")
    packets_expected = row.get("packets_expected")
    packets_received = row.get("packets_received")
    checker_bytes = row.get("checker_bytes_received")
    axis_bytes = row.get("axis_bytes_emitted")
    if packets_expected != packets_received:
        raise RuntimeError(
            f"{label}: packets_expected ({packets_expected}) != packets_received ({packets_received})"
        )
    if checker_bytes != axis_bytes:
        raise RuntimeError(
            f"{label}: checker_bytes_received ({checker_bytes}) != axis_bytes_emitted ({axis_bytes})"
        )


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

    baseline_overlap = int(row_by_label[RUNS[0]["label"]]["cpu_mmio_overlap_count"])
    heavy_overlap = int(row_by_label[RUNS[1]["label"]]["cpu_mmio_overlap_count"])
    if not (heavy_overlap >= 20 or heavy_overlap >= (5 * baseline_overlap)):
        raise RuntimeError(
            "heavy-control overlap requirement failed: "
            f"baseline={baseline_overlap}, heavy={heavy_overlap}"
        )

    for run in RUNS:
        label = run["label"]
        print(_csv_line(label))
        print(_extract_pass_line(stdout_by_label[label], label))
        endpoint_metrics = json_by_label[label].get("endpoint_metrics")
        if endpoint_metrics is not None:
            print(json.dumps(endpoint_metrics, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
