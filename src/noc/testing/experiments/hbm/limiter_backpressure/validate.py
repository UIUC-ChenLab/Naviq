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

EXPECTED_PACKETS = 100
EXPECTED_SCOPE = "csr_programmed_plus_axis_backpressure_v1"
EXPECTED_NODE = "PacketRateLimiterThrottleRtlNode"


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


def csv_line(label: str) -> str:
    lines = artifact_path(label, ".csv").read_text().splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"missing CSV row for {label}")
    return lines[1]


def as_int(row: dict, key: str) -> int:
    return int(float(row.get(key) or 0))


def as_float(row: dict, key: str) -> float:
    return float(row.get(key) or 0.0)


def limiter_fragment(data: dict) -> dict:
    return data.get("raw_fragments", {}).get("limiter", {}) or {}


def validate_limiter_run(label: str, data: dict, row: dict) -> None:
    if data.get("memory_endpoint_type") != "hbm" or row.get("memory_endpoint_type") != "hbm":
        raise RuntimeError(f"{label}: memory_endpoint_type is not hbm")
    if not data.get("measurement_valid") or data.get("invalid_reason"):
        raise RuntimeError(f"{label}: invalid measurement: {data.get('invalid_reason', '')}")

    limiter = limiter_fragment(data)
    if limiter.get("type") != "axis_rtl_stream_node":
        raise RuntimeError(f"{label}: limiter fragment type is {limiter.get('type')}")
    if limiter.get("node_name") != EXPECTED_NODE:
        raise RuntimeError(f"{label}: limiter node is {limiter.get('node_name')}")
    if row.get("limiter_scope") != EXPECTED_SCOPE or limiter.get("limiter_scope") != EXPECTED_SCOPE:
        raise RuntimeError(
            f"{label}: limiter scope row={row.get('limiter_scope')} "
            f"fragment={limiter.get('limiter_scope')}"
        )
    if row.get("limiter_enabled") not in ("True", "true", "1"):
        raise RuntimeError(f"{label}: limiter_enabled is {row.get('limiter_enabled')}")

    expected_packets = str(EXPECTED_PACKETS)
    packet_fields = (
        ("packets_expected", expected_packets),
        ("packets_received", expected_packets),
        ("limiter_input_packets", expected_packets),
        ("limiter_output_packets", expected_packets),
    )
    for key, expected in packet_fields:
        if row.get(key) != expected:
            raise RuntimeError(f"{label}: {key}={row.get(key)} expected={expected}")

    byte_pairs = (
        ("checker_bytes_received", "axis_bytes_emitted"),
        ("dma_axis_bytes_emitted", "limiter_input_bytes"),
        ("limiter_output_bytes", "checker_bytes_received"),
    )
    for lhs, rhs in byte_pairs:
        if row.get(lhs) != row.get(rhs):
            raise RuntimeError(f"{label}: {lhs}={row.get(lhs)} != {rhs}={row.get(rhs)}")

    if as_int(row, "limiter_buffered_bytes") != 0:
        raise RuntimeError(f"{label}: limiter buffered bytes nonzero")
    if as_int(row, "limiter_buffered_packets") != 0:
        raise RuntimeError(f"{label}: limiter buffered packets nonzero")


def validate_limiter_comparison(row_by_label: dict) -> None:
    none = row_by_label["smartnic_hbm_rtl_limiter_none_pkt100"]
    moderate = row_by_label["smartnic_hbm_rtl_limiter_moderate_pkt100"]
    strong = row_by_label["smartnic_hbm_rtl_limiter_strong_pkt100"]

    if not as_float(moderate, "axis_stream_window_duration_ns") > as_float(none, "axis_stream_window_duration_ns"):
        raise RuntimeError("moderate AXIS stream duration is not above none duration")
    if not as_float(strong, "axis_stream_window_duration_ns") > as_float(moderate, "axis_stream_window_duration_ns"):
        raise RuntimeError("strong AXIS stream duration is not above moderate duration")
    if not as_int(moderate, "limiter_to_checker_valid_only_cycles") > as_int(none, "limiter_to_checker_valid_only_cycles"):
        raise RuntimeError("moderate limiter-to-checker valid-only cycles did not increase")
    if not as_int(strong, "limiter_to_checker_valid_only_cycles") > as_int(moderate, "limiter_to_checker_valid_only_cycles"):
        raise RuntimeError("strong limiter-to-checker valid-only cycles did not increase over moderate")

    dma_axis_bytes = {as_int(row, "dma_axis_bytes_emitted") for row in row_by_label.values()}
    if len(dma_axis_bytes) != 1:
        raise RuntimeError(f"DMA AXIS bytes not fixed across cases: {sorted(dma_axis_bytes)}")

    none_tput = as_float(none, "packet_throughput_gbps")
    strong_tput = as_float(strong, "packet_throughput_gbps")
    if none_tput <= 0.0:
        raise RuntimeError("none throughput is not positive")
    throughput_drop_pct = 100.0 * (none_tput - strong_tput) / none_tput
    axis_increase_pct = 100.0 * (
        as_float(strong, "axis_stream_window_duration_ns") -
        as_float(none, "axis_stream_window_duration_ns")
    ) / as_float(none, "axis_stream_window_duration_ns")
    if throughput_drop_pct < 10.0 and axis_increase_pct < 10.0:
        raise RuntimeError(
            "real RTL limiter comparison is not useful: strong throughput drop is "
            f"{throughput_drop_pct:.3f}% and AXIS window increase is {axis_increase_pct:.3f}%"
        )
