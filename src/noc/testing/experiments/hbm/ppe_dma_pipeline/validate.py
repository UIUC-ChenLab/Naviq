import csv
import json
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "noc").is_dir() and (parent / "SConstruct").is_file():
            return parent
    raise RuntimeError("could not locate naviq repository root")


REPO_ROOT = _find_repo_root()
METRICS_DIR = REPO_ROOT / "src" / "noc" / "out" / "csv"
EXPECTED_PACKETS = 500


def artifact_path(label: str, suffix: str) -> Path:
    return METRICS_DIR / f"{label}{suffix}"


def load_json(label: str) -> dict:
    with artifact_path(label, ".json").open() as f:
        return json.load(f)


def load_csv_row(label: str) -> dict:
    with artifact_path(label, ".csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1:
        raise RuntimeError(f"expected exactly one CSV row for {label}")
    return rows[0]


def as_int(row: dict, key: str) -> int:
    return int(float(row.get(key) or 0))


def validate_pipeline_run(label: str, data: dict, row: dict) -> None:
    if data.get("memory_endpoint_type") != "hbm" or row.get("memory_endpoint_type") != "hbm":
        raise RuntimeError(f"{label}: memory_endpoint_type is not hbm")
    if not data.get("measurement_valid") or data.get("invalid_reason"):
        raise RuntimeError(f"{label}: invalid measurement: {data.get('invalid_reason', '')}")

    expected = str(EXPECTED_PACKETS)
    if row.get("packets_expected") != expected or row.get("packets_received") != expected:
        raise RuntimeError(
            f"{label}: packet mismatch expected={row.get('packets_expected')} "
            f"received={row.get('packets_received')}"
        )
    if row.get("checker_bytes_received") != row.get("axis_bytes_emitted"):
        raise RuntimeError(
            f"{label}: checker_bytes_received={row.get('checker_bytes_received')} "
            f"!= axis_bytes_emitted={row.get('axis_bytes_emitted')}"
        )
    if as_int(row, "dma_bytes_read") <= 0:
        raise RuntimeError(f"{label}: dma_bytes_read is not positive")

    op = data.get("operation_window", {})
    axis = data.get("axis_stream_window", {})
    if op.get("start_tick") is None or op.get("end_tick") is None:
        raise RuntimeError(f"{label}: missing operation_window")
    if axis.get("start_tick") is None or axis.get("end_tick") is None:
        raise RuntimeError(f"{label}: missing axis_stream_window")
