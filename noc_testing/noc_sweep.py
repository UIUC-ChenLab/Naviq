#!/usr/bin/env python3
"""
A unified orchestrator for running Vivado and gem5 simulations.

# NOTE: We might eventually want to implement in the TCL a way to load the .nts file into
# Vivado as well. Currently only the .ncr file is loaded for custom routes.

Supports five modes of operation:
1. vivado_then_gem5 (default): Runs Vivado then gem5, row-by-row, for comparison.
2. vivado_only: Runs the full Vivado Tcl sweep to generate all hardware artifacts.
3. gem5_old_topo: Runs gem5 using pre-existing topology artifacts (requires --reuse-tag).
4. topology_only: Generates NCR/NTS topology files without running simulation.
5. gem5_only: Generates topologies first, then runs gem5 on all rows.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from lib.noc_topology import get_topology_from_row

# --- Configuration ---
# Modify these paths if your project structure is different
WORKSPACE = Path(__file__).resolve().parent
REPO_ROOT = WORKSPACE.parent
ARTIFACTS_DIR = WORKSPACE / "artifacts"
GENERATED_ARTIFACTS_DIR = ARTIFACTS_DIR / "generated"
RESULTS_DIR = GENERATED_ARTIFACTS_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
NOC_DESC_DIR = ARTIFACTS_DIR / "noc_desc"
SIMLOGS_DIR = GENERATED_ARTIFACTS_DIR / "simlogs"
HOTSPOT_RESULTS_DIR = GENERATED_ARTIFACTS_DIR / "hotspot"
RUNTIME_TRACE_DIR = REPO_ROOT / "src/noc/out/csv"
RUNTIME_OCC_TRACE = RUNTIME_TRACE_DIR / "nps_occ_all.csv"
RUNTIME_QUEUE_TRACE = RUNTIME_TRACE_DIR / "nps_queue_trace.csv"

GEM5_HEADERS = [
    "finished_at_iso",
    "run_tag",
    "name",
    "plan_row_index",
    "config_id",
    "sim_time_s",
    "src_id",
    "tg_mode",
    "num_write_transactions_cfg",
    "axi_write_size_bytes",
    "axi_write_len_beats",
    "axi_write_bandwidth_cfg_MBps",
    # Key gem5 Results
    "gem5_min_write_lat_cycles",
    "gem5_avg_write_lat_cycles",
    "gem5_max_write_lat_cycles",
    "gem5_p50_write_lat_cycles",
    "gem5_p95_write_lat_cycles",
    "gem5_p99_write_lat_cycles",
    "gem5_p999_write_lat_cycles",
    "gem5_achieved_write_bw_MBps",
    "gem5_min_read_lat_cycles",
    "gem5_avg_read_lat_cycles",
    "gem5_max_read_lat_cycles",
    "gem5_p50_read_lat_cycles",
    "gem5_p95_read_lat_cycles",
    "gem5_p99_read_lat_cycles",
    "gem5_p999_read_lat_cycles",
    "gem5_achieved_read_bw_MBps",
    # Fairness Metrics
    "gem5_jfi_write_bw",
    "gem5_cv_write_bw",
    "gem5_maxmin_write_bw",
    "gem5_jfi_read_bw",
    "gem5_cv_read_bw",
    "gem5_maxmin_read_bw",
    "gem5_jfi_write_lat",
    "gem5_cv_write_lat",
    "gem5_maxmin_write_lat",
    "gem5_jfi_read_lat",
    "gem5_cv_read_lat",
    "gem5_maxmin_read_lat",
    # Input Parameters from CSV
    "noc_axi_clk_mhz",
    # NoC behavior knobs
    "buffers_per_data_vc",
    "buffers_per_ctrl_vc",
    "nsu_read_response_gap_cycles",
    "nsu_read_response_per_flit_gap_cycles",
    "nsu_read_response_half_rate",
    "rptr_credits",
    "vnoc_credits",
    "hnoc_credits",
    "ncrb_credits",
    "nidb_credits",
    # Instrumentation knobs
    "record_mode",
    "hotspot_occ_gap_cycles",
    # Metadata
    "hotspot_mode",
    "hotspot_artifact_dir",
    "hotspot_occ_trace_csv",
    "hotspot_queue_trace_csv",
    "hotspot_occ_status",
    "hotspot_queue_status",
    "hotspot_capture_status",
    "gem5_return_code",
]
NON_CONFIG_RESULT_KEYS = {
    "finished_at_iso",
    "run_tag",
    "plan_row_index",
    "config_id",
    "sim_time_s",
    "src_id",
}

# --- Tcl/gem5 Command Information ---
VIVADO_TCL_SCRIPT = WORKSPACE / "main.tcl"
DEFAULT_GEM5_CMD = [
    "build/NULL/gem5.opt",
    "src/noc/setup/noc_config.py",
]
V2_GEM5_CMD = [
    "build/NULL/gem5.opt",
    "src/noc/setup/noc_setup_config.py",
]
DEFAULT_VIVADO_CMD = "vivado"
DEFAULT_AXI_CLK_MHZ = 1000
DEFAULT_VIVADO_AXI_BEAT_BYTES = 16
VIVADO_TG_MAX_TRANSACTION_BYTES = 4096
VIVADO_TG_MAX_BANDWIDTH_MBPS = 19200

CONNECTION_JSON_KEYS = [
    "connections_json",
    "topology_json",
    "topology",
    "topology_file",
    "connection_json",
    "connection_file",
]
PLACEMENT_JSON_KEYS = ["placement_json", "placement", "placement_file"]
NCR_KEYS = ["ncr", "ncr_file"]
NTS_KEYS = ["nts", "nts_file"]

V2_CONNECTION_KIND = "naviq.connections"
V2_PLACEMENT_KIND = "naviq.placement"

AXIMM_TG_TYPES = {"AxiRandomTrafficGenerator"}
AXIS_TG_TYPES = {"AxisRandomTrafficGenerator", "AxisPacketTrafficGenerator"}
EXPECTED_PACKET_TYPES = {
    "AxisSinkNode",
    "AxisFifoNode",
    "AxisPacketCheckerSink",
    "ChecksumRtlNode",
    "TelemetryRtlNode",
    "OverloadedNatRtlNode",
}
DATA_WIDTH_TYPES = (
    AXIMM_TG_TYPES
    | AXIS_TG_TYPES
    | {
        "AxisSinkNode",
        "AxisFifoNode",
        "AxisPacketCheckerSink",
        "ChecksumRtlNode",
        "TelemetryRtlNode",
        "OverloadedNatRtlNode",
    }
)

CANONICAL_ALIASES = {
    "num_transactions": [
        "num_transactions",
        "num_write_transactions_cfg",
        "num_packets",
        "packet_count",
        "transactions",
    ],
    "num_read_transactions": [
        "num_read_transactions",
        "num_read_transactions_cfg",
        "read_transactions",
    ],
    "max_outstanding_writes": [
        "max_outstanding_writes",
        "outstanding_writes",
        "max_outstanding",
    ],
    "max_outstanding_reads": [
        "max_outstanding_reads",
        "outstanding_reads",
    ],
    "transaction_bytes": [
        "transaction_bytes",
        "transaction_size_bytes",
        "axi_transaction_size_bytes",
        "packet_bytes",
    ],
    "beat_bytes": [
        "beat_bytes",
        "axi_write_size_bytes",
        "write_size_bytes",
        "axi_beat_bytes",
        "USER_C_AXI_WRITE_SIZE",
    ],
    "beat_count": [
        "beat_count",
        "axi_write_len_beats",
        "write_len_beats",
        "num_beats",
        "USER_C_AXIS_PKT_LEN",
        "USER_C_AXI_WRITE_LEN",
    ],
    "bandwidth_MBps": [
        "bandwidth_MBps",
        "axi_write_bandwidth_cfg_MBps",
        "read_write_bandwidth_MBps",
        "USER_C_AXI_WRITE_BANDWIDTH",
    ],
    "write_bandwidth_MBps": [
        "write_bandwidth_MBps",
        "max_write_bandwidth_MBps",
    ],
    "read_bandwidth_MBps": ["read_bandwidth_MBps", "max_read_bandwidth_MBps"],
    "tg_mode": ["tg_mode", "direction", "read_write_mode", "mode"],
    "data_width_bits": [
        "data_width_bits",
        "tg_axi_data_width_bits",
        "axi_data_width_bits",
    ],
    "endpoint_data_width_bits": [
        "endpoint_data_width_bits",
        "bram_data_width",
    ],
    "noc_clk_mhz": [
        "noc_clk_mhz",
        "noc_axi_clk_mhz",
        "clock_mhz",
        "clock_domain_mhz",
    ],
    "buffers_per_data_vc": ["buffers_per_data_vc", "data_vc_buffers"],
    "buffers_per_ctrl_vc": ["buffers_per_ctrl_vc", "ctrl_vc_buffers"],
    "nsu_read_response_gap_cycles": [
        "nsu_read_response_gap_cycles",
        "nsu_read_gap_cycles",
    ],
    "nsu_read_response_per_flit_gap_cycles": [
        "nsu_read_response_per_flit_gap_cycles",
        "nsu_read_per_flit_gap_cycles",
    ],
    "nsu_read_response_half_rate": [
        "nsu_read_response_half_rate",
        "nsu_read_half_rate",
        "nsu_read_response_every_other_flit",
    ],
    "rptr_credits": ["rptr_credits"],
    "vnoc_credits": ["vnoc_credits"],
    "hnoc_credits": ["hnoc_credits"],
    "ncrb_credits": ["ncrb_credits"],
    "nidb_credits": ["nidb_credits"],
    "qos_read_bw_MBps": ["qos_read_bw_MBps", "read_qos_MBps"],
    "qos_write_bw_MBps": ["qos_write_bw_MBps", "write_qos_MBps"],
    "qos_avg_burst": ["qos_avg_burst", "avg_burst", "qos_burst"],
}


# --- ANSI Color Codes for Output ---
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    ENDC = "\033[0m"


# --- Helper Functions (for parsing and data conversion) ---
def _to_int_or_none(v):
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _to_bool_or_none(v):
    s = _clean(v).lower()
    if not s:
        return None
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return None


def _awsize_code_from_bytes(b):
    b = _to_int_or_none(b)
    return int(math.log2(b)) if b and b > 0 else None


def _awlen_from_beats(beats):
    """Passes through the 0-indexed AWLEN value from the CSV (0 = 1 beat, 15 = 16 beats)."""
    v = _to_int_or_none(beats)
    return v if v is not None else None


def _clean(v: Any) -> str:
    return str(v if v is not None else "").strip()


def _format_scalar(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _vivado_tg_max_bandwidth_mbps(
    beat_bytes: Optional[int], clock_mhz: Optional[int]
) -> int:
    beat_bytes = beat_bytes or DEFAULT_VIVADO_AXI_BEAT_BYTES
    clock_mhz = clock_mhz or DEFAULT_AXI_CLK_MHZ
    return min(VIVADO_TG_MAX_BANDWIDTH_MBPS, beat_bytes * clock_mhz)


def _normalize_vivado_tg_bandwidth(
    requested: float, beat_bytes: Optional[int], clock_mhz: Optional[int]
) -> int:
    max_bw = _vivado_tg_max_bandwidth_mbps(beat_bytes, clock_mhz)
    if requested <= 0 or requested > max_bw:
        return max_bw
    return max(1, int(math.ceil(requested)))


def _row_value(row: Dict, keys: List[str]) -> str:
    for key in keys:
        value = _clean(row.get(key))
        if value:
            return value
    return ""


def _resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path

    candidates = [
        WORKSPACE / path,
        REPO_ROOT / path,
        Path.cwd() / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (WORKSPACE / path).resolve()


def _load_json_file(path: Path) -> Dict:
    with path.open() as f:
        return json.load(f)


def _connection_path_from_row(row: Dict) -> Optional[Path]:
    value = _row_value(row, CONNECTION_JSON_KEYS)
    return _resolve_path(value) if value else None


def _placement_path_from_row(row: Dict) -> Optional[Path]:
    value = _row_value(row, PLACEMENT_JSON_KEYS)
    return _resolve_path(value) if value else None


def _is_v2_connection_path(path: Optional[Path]) -> bool:
    if path is None:
        return False
    if path.name.endswith(".conn.json"):
        return True
    if not path.exists():
        return False
    try:
        return _load_json_file(path).get("kind") == V2_CONNECTION_KIND
    except (OSError, json.JSONDecodeError):
        return False


def is_v2_row(row: Dict) -> bool:
    return _is_v2_connection_path(_connection_path_from_row(row))


def _stable_path_stem(path: Optional[Path], fallback: str) -> str:
    if path is None:
        return fallback
    name = path.name
    for suffix in (".conn.json", ".place.json", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _sanitize_name_token(name: str) -> str:
    token = re.sub(r"[\s,:/]+", "_", name).strip("_")
    return token or "unnamed_row"


def _path_to_repoish_string(path: Path) -> str:
    resolved = path.resolve()
    for base in (REPO_ROOT.resolve(), WORKSPACE.resolve()):
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            continue
    return str(resolved)


def _normalize_path_value_for_id(raw: str) -> str:
    return _path_to_repoish_string(_resolve_path(raw))


def _config_source_from_plan_row(plan_row: Dict[str, str]) -> Dict[str, Any]:
    source: Dict[str, Any] = {}
    name = _clean(plan_row.get("name"))
    if name:
        source["name"] = name

    try:
        settings = normalize_sweep_settings(plan_row)
    except ValueError:
        settings = {}

    for key in sorted(settings):
        value = settings[key]
        if key == "tg_mode":
            source[key] = _normalize_mode(str(value))
        else:
            source[key] = value

    for label, keys in (
        ("connections_path", CONNECTION_JSON_KEYS),
        ("placement_path", PLACEMENT_JSON_KEYS),
        ("ncr_path", NCR_KEYS),
        ("nts_path", NTS_KEYS),
    ):
        raw = _row_value(plan_row, keys)
        if raw:
            source[label] = _normalize_path_value_for_id(raw)

    canonical_raw_keys = {
        alias for aliases in CANONICAL_ALIASES.values() for alias in aliases
    }
    ignored_raw_keys = canonical_raw_keys | set(CONNECTION_JSON_KEYS) | set(
        PLACEMENT_JSON_KEYS
    ) | set(NCR_KEYS) | set(NTS_KEYS) | {"name"} | NON_CONFIG_RESULT_KEYS

    for key in sorted(plan_row):
        if (
            key.startswith("__")
            or key in ignored_raw_keys
            or key.startswith("gem5_")
            or key.startswith("hotspot_")
        ):
            continue
        value = _clean(plan_row.get(key))
        if value:
            source[f"raw.{key}"] = value

    return source


def _compute_config_id(plan_row: Dict[str, str]) -> str:
    payload = json.dumps(
        _config_source_from_plan_row(plan_row),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _topology_key_for_v2(
    row: Dict, conn_path: Path, place_path: Optional[Path]
) -> str:
    if place_path:
        return f"{_stable_path_stem(conn_path, 'connections')}__{_stable_path_stem(place_path, 'placement')}"
    return f"{_stable_path_stem(conn_path, 'connections')}__auto_place"


def _normalize_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode in ("write_only", "w_only", "write", "writes"):
        return "WRITE_ONLY"
    if mode in ("read_only", "r_only", "read", "reads"):
        return "READ_ONLY"
    if mode in ("wr_then_rd", "writes_then_reads", "sequential", "seq"):
        return "SEQUENTIAL"
    if mode in (
        "rw_parallel",
        "parallel",
        "interleaved",
        "rw_interleaved",
        "write_read_interleaved",
        "",
    ):
        return "INTERLEAVED"
    return value.upper()


def _parse_csv_scalar(value: str) -> Any:
    text = _clean(value)
    if text == "":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _first_value(row: Dict, canonical: str) -> Optional[str]:
    for key in CANONICAL_ALIASES[canonical]:
        value = _clean(row.get(key))
        if value:
            return value
    return None


def normalize_sweep_settings(
    row: Dict, *, synthesize_vivado_beats: bool = False
) -> Dict[str, Any]:
    settings: Dict[str, Any] = {}

    int_fields = {
        "num_transactions",
        "num_read_transactions",
        "max_outstanding_writes",
        "max_outstanding_reads",
        "transaction_bytes",
        "beat_bytes",
        "beat_count",
        "data_width_bits",
        "endpoint_data_width_bits",
        "noc_clk_mhz",
        "buffers_per_data_vc",
        "buffers_per_ctrl_vc",
        "nsu_read_response_gap_cycles",
        "nsu_read_response_per_flit_gap_cycles",
        "rptr_credits",
        "vnoc_credits",
        "hnoc_credits",
        "ncrb_credits",
        "nidb_credits",
        "qos_read_bw_MBps",
        "qos_write_bw_MBps",
        "qos_avg_burst",
    }
    float_fields = {
        "bandwidth_MBps",
        "write_bandwidth_MBps",
        "read_bandwidth_MBps",
    }
    bool_fields = {
        "nsu_read_response_half_rate",
    }

    for canonical in CANONICAL_ALIASES:
        raw = _first_value(row, canonical)
        if raw is None:
            continue
        if canonical in int_fields:
            parsed = _to_int_or_none(raw)
            if parsed is None:
                raise ValueError(
                    f"'{canonical}' must be an integer, got '{raw}'."
                )
            settings[canonical] = parsed
        elif canonical in float_fields:
            try:
                settings[canonical] = float(raw)
            except ValueError as exc:
                raise ValueError(
                    f"'{canonical}' must be numeric, got '{raw}'."
                ) from exc
        elif canonical in bool_fields:
            parsed = _to_bool_or_none(raw)
            if parsed is None:
                raise ValueError(
                    f"'{canonical}' must be boolean-like, got '{raw}'."
                )
            settings[canonical] = parsed
        else:
            settings[canonical] = raw

    beat_bytes = settings.get("beat_bytes")
    beat_count = settings.get("beat_count")
    direct_bytes = settings.get("transaction_bytes")
    beat_derived_bytes = None
    if beat_bytes is not None and beat_count is not None:
        if beat_count < 0:
            raise ValueError("beat_count is AWLEN-style and must be >= 0.")
        if beat_bytes <= 0:
            raise ValueError("beat_bytes must be > 0.")
        beat_derived_bytes = beat_bytes * (beat_count + 1)
        if beat_derived_bytes > VIVADO_TG_MAX_TRANSACTION_BYTES:
            raise ValueError(
                "Vivado AXI-MM traffic generator transactions must be <= "
                f"{VIVADO_TG_MAX_TRANSACTION_BYTES} bytes; beat_bytes={beat_bytes} "
                f"and beat_count={beat_count} imply {beat_derived_bytes}."
            )

    if direct_bytes is not None and beat_derived_bytes is not None:
        if direct_bytes != beat_derived_bytes:
            raise ValueError(
                "Conflicting transaction size settings: "
                f"transaction_bytes={direct_bytes}, but beat_bytes={beat_bytes} "
                f"and beat_count={beat_count} imply {beat_derived_bytes}."
            )
    elif direct_bytes is None and beat_derived_bytes is not None:
        settings["transaction_bytes"] = beat_derived_bytes
    elif (
        direct_bytes is not None
        and synthesize_vivado_beats
        and (beat_bytes is None or beat_count is None)
    ):
        if direct_bytes <= 0 or direct_bytes % 64 != 0:
            raise ValueError(
                "transaction_bytes must be a positive multiple of 64 when Vivado/Tcl "
                "beat fields need to be synthesized."
            )
        settings.setdefault("beat_bytes", 64)
        settings.setdefault("beat_count", direct_bytes // 64 - 1)

    if settings.get("transaction_bytes") is not None and settings[
        "transaction_bytes"
    ] <= 0:
        raise ValueError("transaction_bytes must be > 0.")
    if settings.get("transaction_bytes", 0) > VIVADO_TG_MAX_TRANSACTION_BYTES:
        raise ValueError(
            "Vivado AXI-MM traffic generator transactions must be <= "
            f"{VIVADO_TG_MAX_TRANSACTION_BYTES} bytes; transaction_bytes="
            f"{settings['transaction_bytes']}."
        )
    for key in (
        "buffers_per_data_vc",
        "buffers_per_ctrl_vc",
        "rptr_credits",
        "vnoc_credits",
        "hnoc_credits",
        "ncrb_credits",
        "nidb_credits",
    ):
        if settings.get(key) is not None and settings[key] <= 0:
            raise ValueError(f"{key} must be > 0.")
    for key in (
        "nsu_read_response_gap_cycles",
        "nsu_read_response_per_flit_gap_cycles",
    ):
        if settings.get(key) is not None and settings[key] < 0:
            raise ValueError(f"{key} must be >= 0.")
    if settings.get("nsu_read_response_half_rate"):
        settings["nsu_read_response_gap_cycles"] = 0
        settings["nsu_read_response_per_flit_gap_cycles"] = max(
            settings.get("nsu_read_response_per_flit_gap_cycles", 0), 1
        )

    clock_mhz = settings.get("noc_clk_mhz") or DEFAULT_AXI_CLK_MHZ
    bw_beat_bytes = settings.get("beat_bytes") or DEFAULT_VIVADO_AXI_BEAT_BYTES
    for key in (
        "bandwidth_MBps",
        "write_bandwidth_MBps",
        "read_bandwidth_MBps",
    ):
        if key in settings:
            settings[key] = _normalize_vivado_tg_bandwidth(
                float(settings[key]), bw_beat_bytes, clock_mhz
            )

    return settings


def apply_normalized_settings_to_row(
    row: Dict, settings: Dict[str, Any]
) -> None:
    """Populate legacy/Tcl-friendly CSV keys from normalized settings."""

    def put_if_blank(key: str, value: Any) -> None:
        if _clean(row.get(key)) == "":
            row[key] = _format_scalar(value)

    def put_normalized(key: str, value: Any) -> None:
        row[key] = _format_scalar(value)

    if "num_transactions" in settings:
        put_if_blank(
            "num_write_transactions_cfg", settings["num_transactions"]
        )
    if "num_read_transactions" in settings:
        put_if_blank(
            "num_read_transactions_cfg", settings["num_read_transactions"]
        )
    if "beat_bytes" in settings:
        put_normalized("axi_write_size_bytes", settings["beat_bytes"])
    if "beat_count" in settings:
        put_normalized("axi_write_len_beats", settings["beat_count"])
    write_bw = settings.get(
        "write_bandwidth_MBps", settings.get("bandwidth_MBps")
    )
    if write_bw is not None:
        put_normalized("axi_write_bandwidth_cfg_MBps", write_bw)
    if "data_width_bits" in settings:
        put_if_blank("tg_axi_data_width_bits", settings["data_width_bits"])
    if "endpoint_data_width_bits" in settings:
        put_if_blank("bram_data_width", settings["endpoint_data_width_bits"])
    if "noc_clk_mhz" in settings:
        put_if_blank("noc_axi_clk_mhz", settings["noc_clk_mhz"])
    if "tg_mode" in settings:
        put_if_blank("tg_mode", settings["tg_mode"])
        put_if_blank("direction", _normalize_mode(str(settings["tg_mode"])))
    for key in (
        "buffers_per_data_vc",
        "buffers_per_ctrl_vc",
        "nsu_read_response_gap_cycles",
        "nsu_read_response_per_flit_gap_cycles",
        "nsu_read_response_half_rate",
        "rptr_credits",
        "vnoc_credits",
        "hnoc_credits",
        "ncrb_credits",
        "nidb_credits",
    ):
        if key in settings:
            put_if_blank(key, settings[key])


def _component_params(component: Dict) -> Dict:
    params = component.get("params", {})
    return params if isinstance(params, dict) else {}


def _count_axis_destinations(connections_data: Dict) -> Dict[str, int]:
    """Count the number of AXIS destinations for each master component.

    Returns a dict mapping component_id -> number of AXIS connections
    originating from that component. This is used to set max_tdest so
    the traffic generator only emits valid tdest values.
    """
    components = connections_data.get("components", {})
    connections = connections_data.get("connections", [])
    dest_counts: Dict[str, int] = {}
    for conn in connections:
        src_ref = conn.get("from", "")
        src_component = src_ref.split(".", 1)[0] if "." in src_ref else src_ref
        if src_component in components:
            dest_counts[src_component] = dest_counts.get(src_component, 0) + 1
    return dest_counts


def build_v2_param_overrides(
    row: Dict, connections_data: Dict, settings: Dict[str, Any]
) -> List[str]:
    overrides: Dict[Tuple[str, str], Any] = {}
    components = connections_data.get("components", {})
    if not isinstance(components, dict):
        return []

    axis_dest_counts = _count_axis_destinations(connections_data)

    def add(component_id: str, param: str, value: Any) -> None:
        if value is not None:
            overrides[(component_id, param)] = value

    for component_id, component in components.items():
        node_type = component.get("node_type", "")
        params = _component_params(component)

        if node_type in AXIMM_TG_TYPES:
            add(
                component_id,
                "max_write_commands",
                settings.get("num_transactions"),
            )
            add(
                component_id,
                "max_outstanding_writes",
                settings.get("max_outstanding_writes"),
            )
            add(
                component_id,
                "max_outstanding_reads",
                settings.get("max_outstanding_reads"),
            )
            if "transaction_bytes" in settings:
                add(
                    component_id,
                    "min_transaction_size_bytes",
                    settings["transaction_bytes"],
                )
                add(
                    component_id,
                    "max_transaction_size_bytes",
                    settings["transaction_bytes"],
                )
                add(component_id, "transaction_size_distribution", "FIXED")
            bw = settings.get("bandwidth_MBps")
            add(
                component_id,
                "max_write_bandwidth_mbps",
                settings.get("write_bandwidth_MBps", bw),
            )
            add(
                component_id,
                "max_read_bandwidth_mbps",
                settings.get("read_bandwidth_MBps", bw),
            )
            if "tg_mode" in settings:
                add(
                    component_id,
                    "read_write_mode",
                    _normalize_mode(str(settings["tg_mode"])),
                )
            address_increment = settings.get("transaction_bytes")
            if address_increment is None:
                address_increment = settings.get("beat_bytes")
            add(component_id, "beat_size_bytes", settings.get("beat_bytes"))
            add(component_id, "address_distribution", "INCREMENT")
            add(component_id, "address_increment", address_increment)
            add(
                component_id,
                "align_addresses",
                address_increment is not None
                and address_increment != settings.get("beat_bytes"),
            )
            add(component_id, "data_width", settings.get("data_width_bits"))
            add(component_id, "clock_domain_mhz", settings.get("noc_clk_mhz"))

        elif node_type in AXIS_TG_TYPES:
            add(component_id, "max_packets", settings.get("num_transactions"))
            if "transaction_bytes" in settings:
                if node_type == "AxisPacketTrafficGenerator":
                    add(
                        component_id,
                        "min_payload_bytes",
                        settings["transaction_bytes"],
                    )
                    add(
                        component_id,
                        "max_payload_bytes",
                        settings["transaction_bytes"],
                    )
                else:
                    add(
                        component_id,
                        "min_packet_size_bytes",
                        settings["transaction_bytes"],
                    )
                    add(
                        component_id,
                        "max_packet_size_bytes",
                        settings["transaction_bytes"],
                    )
                    add(component_id, "packet_size_distribution", "FIXED")
            add(component_id, "data_width", settings.get("data_width_bits"))
            add(component_id, "clock_domain_mhz", settings.get("noc_clk_mhz"))
            # Set max_tdest from the number of AXIS destinations so the TG
            # only emits valid tdest values (default 0xFFF generates random
            # values that won't match the routing table).
            num_dests = axis_dest_counts.get(component_id, 1)
            add(component_id, "max_tdest", max(num_dests - 1, 0))

        if node_type in EXPECTED_PACKET_TYPES or "expected_packets" in params:
            add(
                component_id,
                "expected_packets",
                settings.get("num_transactions"),
            )
        if node_type in DATA_WIDTH_TYPES and node_type not in AXIMM_TG_TYPES:
            add(component_id, "data_width", settings.get("data_width_bits"))

    for key, value in row.items():
        if not key.startswith("param."):
            continue
        raw_value = _clean(value)
        if raw_value == "":
            continue
        _, rest = key.split("param.", 1)
        if "." not in rest:
            raise ValueError(
                f"Invalid param override column '{key}'. Expected param.component.param."
            )
        component_id, param = rest.split(".", 1)
        if not component_id or not param:
            raise ValueError(
                f"Invalid param override column '{key}'. Expected param.component.param."
            )
        overrides[(component_id, param)] = _parse_csv_scalar(raw_value)

    return [
        f"{component_id}.{param}={json.dumps(value)}"
        for (component_id, param), value in sorted(overrides.items())
    ]


def _clock_arg_from_mhz(mhz: Optional[int]) -> Optional[str]:
    if mhz is None:
        return None
    return f"{mhz}MHz"


def _append_network_behavior_args(
    gem5_args: List[str], settings: Dict[str, Any]
) -> None:
    for key in (
        "buffers_per_data_vc",
        "buffers_per_ctrl_vc",
        "nsu_read_response_gap_cycles",
        "nsu_read_response_per_flit_gap_cycles",
        "rptr_credits",
        "vnoc_credits",
        "hnoc_credits",
        "ncrb_credits",
        "nidb_credits",
    ):
        value = settings.get(key)
        if value is not None:
            gem5_args.extend([f"--{key.replace('_', '-')}", str(value)])


def _row_int_value(
    row: Dict[str, str], keys: Tuple[str, ...], default: Optional[int] = None
) -> Optional[int]:
    for key in keys:
        value = _clean(row.get(key))
        if value:
            parsed = _to_int_or_none(value)
            if parsed is None:
                raise ValueError(f"'{key}' must be an integer, got '{value}'.")
            return parsed
    return default


def _row_hotspot_mode(row: Dict[str, str], cli_default: str) -> str:
    if cli_default != "off":
        return cli_default
    value = _clean(row.get("hotspot_mode"))
    if value == "":
        return cli_default
    mode = value.lower()
    if mode not in ("off", "occ", "queue", "both"):
        raise ValueError(
            "hotspot_mode must be one of off, occ, queue, or both; "
            f"got '{value}'."
        )
    return mode


def _clk_period_ps_from_mhz(mhz: Optional[int]) -> int:
    mhz = mhz or 1000
    return int(1_000_000 / mhz)


def _clear_runtime_hotspot_traces(hotspot_mode: str) -> None:
    if hotspot_mode == "off":
        return
    for path in (RUNTIME_OCC_TRACE, RUNTIME_QUEUE_TRACE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _csv_data_row_count(path: Path) -> int:
    try:
        with path.open(newline="") as f:
            reader = csv.reader(f)
            next(reader, None)
            return sum(1 for row in reader if any(cell.strip() for cell in row))
    except (OSError, csv.Error):
        return 0


def _capture_single_hotspot_trace(
    requested: bool, source_path: Path, artifact_dir: Optional[Path]
) -> Tuple[str, str]:
    if not requested:
        return "disabled", ""
    if not source_path.exists():
        return "missing", ""

    if artifact_dir is None:
        copied_path = source_path
    else:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        copied_path = artifact_dir / source_path.name
        shutil.copy2(source_path, copied_path)

    status = "present" if _csv_data_row_count(copied_path) > 0 else "empty"
    return status, str(copied_path)


def _combined_hotspot_status(
    occ_status: str, queue_status: str, requested_occ: bool, requested_queue: bool
) -> str:
    statuses = []
    if requested_occ:
        statuses.append(occ_status)
    if requested_queue:
        statuses.append(queue_status)
    if not statuses:
        return "disabled"
    if all(status == "present" for status in statuses):
        return "present"
    if all(status == "empty" for status in statuses):
        return "empty"
    if all(status == "missing" for status in statuses):
        return "missing"
    if any(status == "present" for status in statuses):
        return "partial"
    if any(status == "empty" for status in statuses) and any(
        status == "missing" for status in statuses
    ):
        return "partial"
    return "missing"


def _hotspot_capture_metadata(
    hotspot_mode: str, run_tag: str, row_index: int, row_name: str
) -> Dict[str, str]:
    requested_occ = hotspot_mode in ("occ", "both")
    requested_queue = hotspot_mode in ("queue", "both")
    if hotspot_mode == "off":
        return {
            "hotspot_mode": hotspot_mode,
            "hotspot_artifact_dir": "",
            "hotspot_occ_trace_csv": "",
            "hotspot_queue_trace_csv": "",
            "hotspot_occ_status": "disabled",
            "hotspot_queue_status": "disabled",
            "hotspot_capture_status": "disabled",
        }

    artifact_dir = (
        HOTSPOT_RESULTS_DIR
        / run_tag
        / f"row_{row_index}_{_sanitize_name_token(row_name)}"
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    occ_status, occ_path = _capture_single_hotspot_trace(
        requested_occ, RUNTIME_OCC_TRACE, artifact_dir
    )
    queue_status, queue_path = _capture_single_hotspot_trace(
        requested_queue, RUNTIME_QUEUE_TRACE, artifact_dir
    )

    return {
        "hotspot_mode": hotspot_mode,
        "hotspot_artifact_dir": str(artifact_dir),
        "hotspot_occ_trace_csv": occ_path,
        "hotspot_queue_trace_csv": queue_path,
        "hotspot_occ_status": occ_status,
        "hotspot_queue_status": queue_status,
        "hotspot_capture_status": _combined_hotspot_status(
            occ_status, queue_status, requested_occ, requested_queue
        ),
    }


def read_plan_rows(plan_path: Path) -> List[Dict[str, str]]:
    with plan_path.open(newline="") as f:
        return [
            r
            for r in csv.DictReader(f)
            if not r.get("name", "#").strip().startswith("#")
        ]


def select_plan_rows(
    plan_rows: List[Dict[str, str]],
    row_number: Optional[int],
) -> List[Tuple[int, Dict[str, str]]]:
    """Return (1-based data row index, row) pairs, optionally narrowed to one row."""
    if row_number is None:
        return list(enumerate(plan_rows, 1))

    if row_number < 1 or row_number > len(plan_rows):
        sys.exit(
            f"{Colors.RED}[ERROR] --row {row_number} is out of range. "
            f"Plan has {len(plan_rows)} data rows.{Colors.ENDC}"
        )

    return [(row_number, plan_rows[row_number - 1])]


def print_selected_rows_summary(
    plan_rows: List[Dict[str, str]],
    selected_rows: List[Tuple[int, Dict[str, str]]],
) -> None:
    if len(selected_rows) == len(plan_rows):
        print(f"Processing {len(plan_rows)} rows...")
        return

    row_number, row = selected_rows[0]
    row_name = row.get("name", f"Row {row_number}")
    print(
        f"Processing 1 selected row out of {len(plan_rows)}: "
        f"row {row_number} ({row_name})"
    )


def _row_error(row_name: str, message: str) -> None:
    print(f"{Colors.RED}  [ERROR] Row '{row_name}': {message}{Colors.ENDC}")
    sys.exit(1)


def _gem5_cmd_for_row(args: argparse.Namespace, row: Dict) -> List[str]:
    if is_v2_row(row) and args.gem5_cmd == DEFAULT_GEM5_CMD:
        return V2_GEM5_CMD
    return args.gem5_cmd


def _mark_v2_row(
    row: Dict, conn_path: Path, placement_path: Optional[Path]
) -> None:
    row["__is_v2"] = "1"
    row["__v2_connections_json"] = str(conn_path)
    if placement_path is not None:
        row["__v2_placement_json"] = str(placement_path)


def _v2_paths_from_row(row: Dict) -> Tuple[Optional[Path], Optional[Path]]:
    conn_raw = row.get("__v2_connections_json")
    place_raw = row.get("__v2_placement_json")
    conn_path = Path(conn_raw) if conn_raw else _connection_path_from_row(row)
    placement_path = (
        Path(place_raw) if place_raw else _placement_path_from_row(row)
    )
    return conn_path, placement_path


def parse_gem5_output(text: str) -> List[Dict]:
    """Parses gem5 stdout for metrics, returning a list of dicts (one per TG/src_id)."""
    node_block_pattern = re.compile(
        r">>>>>> AXI Node ID:\s*(\d+)\s*Stats >>>>>>(.*?)(?=^>>>>>> AXI Node ID:|^=== Fairness Summary|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    node_blocks = node_block_pattern.findall(text)

    if node_blocks:
        rows = []
        for src_id_raw, block in node_blocks:
            row = {"src_id": int(src_id_raw)}

            metric_patterns = {
                "gem5_min_write_lat_cycles": r"Min Write Latency\s*=\s*([0-9.]+)",
                "gem5_max_write_lat_cycles": r"Max Write Latency\s*=\s*([0-9.]+)",
                "gem5_avg_write_lat_cycles": r"Avg Write Latency\s*=\s*([0-9.]+)",
                "gem5_p50_write_lat_cycles": r"P50 Write Latency\s*=\s*([0-9.]+)",
                "gem5_p95_write_lat_cycles": r"P95 Write Latency\s*=\s*([0-9.]+)",
                "gem5_p99_write_lat_cycles": r"P99 Write Latency\s*=\s*([0-9.]+)",
                "gem5_p999_write_lat_cycles": r"P99\.9 Write Latency\s*=\s*([0-9.]+)",
                "gem5_achieved_write_bw_MBps": r"Achieved Write BW\s*=\s*([0-9.]+)",
                "gem5_min_read_lat_cycles": r"Min Read\s+Latency\s*=\s*([0-9.]+)",
                "gem5_max_read_lat_cycles": r"Max Read\s+Latency\s*=\s*([0-9.]+)",
                "gem5_avg_read_lat_cycles": r"Avg Read\s+Latency\s*=\s*([0-9.]+)",
                "gem5_p50_read_lat_cycles": r"P50 Read\s+Latency\s*=\s*([0-9.]+)",
                "gem5_p95_read_lat_cycles": r"P95 Read\s+Latency\s*=\s*([0-9.]+)",
                "gem5_p99_read_lat_cycles": r"P99 Read\s+Latency\s*=\s*([0-9.]+)",
                "gem5_p999_read_lat_cycles": r"P99\.9 Read\s+Latency\s*=\s*([0-9.]+)",
                "gem5_achieved_read_bw_MBps": r"Achieved Read BW\s*=\s*([0-9.]+)",
            }

            for key, pattern in metric_patterns.items():
                match = re.search(pattern, block)
                if match:
                    row[key] = float(match.group(1))

            rows.append(row)
    else:
        wlat_min = re.findall(r"Min Write Latency\s*=\s*([0-9.]+)", text)
        wlat_max = re.findall(r"Max Write Latency\s*=\s*([0-9.]+)", text)
        wlat_avg = re.findall(r"Avg Write Latency\s*=\s*([0-9.]+)", text)
        wlat_p50 = re.findall(r"P50 Write Latency\s*=\s*([0-9.]+)", text)
        wlat_p95 = re.findall(r"P95 Write Latency\s*=\s*([0-9.]+)", text)
        wlat_p99 = re.findall(r"P99 Write Latency\s*=\s*([0-9.]+)", text)
        wlat_p999 = re.findall(r"P99\.9 Write Latency\s*=\s*([0-9.]+)", text)
        wbw = re.findall(r"Achieved Write BW\s*=\s*([0-9.]+)", text)

        rlat_min = re.findall(r"Min Read\s+Latency\s*=\s*([0-9.]+)", text)
        rlat_max = re.findall(r"Max Read\s+Latency\s*=\s*([0-9.]+)", text)
        rlat_avg = re.findall(r"Avg Read\s+Latency\s*=\s*([0-9.]+)", text)
        rlat_p50 = re.findall(r"P50 Read\s+Latency\s*=\s*([0-9.]+)", text)
        rlat_p95 = re.findall(r"P95 Read\s+Latency\s*=\s*([0-9.]+)", text)
        rlat_p99 = re.findall(r"P99 Read\s+Latency\s*=\s*([0-9.]+)", text)
        rlat_p999 = re.findall(r"P99\.9 Read\s+Latency\s*=\s*([0-9.]+)", text)
        rbw = re.findall(r"Achieved Read BW\s*=\s*([0-9.]+)", text)
        n = max(
            map(
                len,
                [
                    wlat_min,
                    wlat_max,
                    wlat_avg,
                    wlat_p50,
                    wlat_p95,
                    wlat_p99,
                    wlat_p999,
                    wbw,
                    rlat_min,
                    rlat_max,
                    rlat_avg,
                    rlat_p50,
                    rlat_p95,
                    rlat_p99,
                    rlat_p999,
                    rbw,
                ],
            ),
            default=0,
        )
        rows = []
        for i in range(n):
            row = {"src_id": i}
            if i < len(wlat_min):
                row["gem5_min_write_lat_cycles"] = float(wlat_min[i])
            if i < len(wlat_max):
                row["gem5_max_write_lat_cycles"] = float(wlat_max[i])
            if i < len(wlat_avg):
                row["gem5_avg_write_lat_cycles"] = float(wlat_avg[i])
            if i < len(wlat_p50):
                row["gem5_p50_write_lat_cycles"] = float(wlat_p50[i])
            if i < len(wlat_p95):
                row["gem5_p95_write_lat_cycles"] = float(wlat_p95[i])
            if i < len(wlat_p99):
                row["gem5_p99_write_lat_cycles"] = float(wlat_p99[i])
            if i < len(wlat_p999):
                row["gem5_p999_write_lat_cycles"] = float(wlat_p999[i])
            if i < len(wbw):
                row["gem5_achieved_write_bw_MBps"] = float(wbw[i])
            if i < len(rlat_min):
                row["gem5_min_read_lat_cycles"] = float(rlat_min[i])
            if i < len(rlat_max):
                row["gem5_max_read_lat_cycles"] = float(rlat_max[i])
            if i < len(rlat_avg):
                row["gem5_avg_read_lat_cycles"] = float(rlat_avg[i])
            if i < len(rlat_p50):
                row["gem5_p50_read_lat_cycles"] = float(rlat_p50[i])
            if i < len(rlat_p95):
                row["gem5_p95_read_lat_cycles"] = float(rlat_p95[i])
            if i < len(rlat_p99):
                row["gem5_p99_read_lat_cycles"] = float(rlat_p99[i])
            if i < len(rlat_p999):
                row["gem5_p999_read_lat_cycles"] = float(rlat_p999[i])
            if i < len(rbw):
                row["gem5_achieved_read_bw_MBps"] = float(rbw[i])
            rows.append(row)

    # Parse global fairness metrics
    fairness = {}
    for metric_name, tag in [
        ("Write BW", "write_bw"),
        ("Read BW", "read_bw"),
        ("Write Lat", "write_lat"),
        ("Read Lat", "read_lat"),
    ]:
        match = re.search(
            rf"{metric_name}\s+JFI = ([0-9.]+)\s+CV = ([0-9.]+)\s+Max/Min = ([0-9.]+)",
            text,
        )
        if match:
            fairness[f"gem5_jfi_{tag}"] = float(match.group(1))
            fairness[f"gem5_cv_{tag}"] = float(match.group(2))
            fairness[f"gem5_maxmin_{tag}"] = float(match.group(3))

    # Apply global fairness metrics to every row
    for row in rows:
        row.update(fairness)

    return rows if rows else [fairness] if fairness else [{}]


def save_gem5_log(run_time: str, name: str, proc: subprocess.CompletedProcess):
    """Saves the gem5 stdout log to the artifact directory."""
    log_dir = SIMLOGS_DIR / f"simlogs_{run_time}"
    log_dir.mkdir(parents=True, exist_ok=True)
    sanitized_row_name = _sanitize_name_token(name)
    log_path = log_dir / f"gem5_{sanitized_row_name}.log"
    with log_path.open("w") as f_log:
        f_log.write(f"--- STDOUT ---\n{proc.stdout}\n")
        if proc.stderr:
            f_log.write(f"\n--- STDERR ---\n{proc.stderr}\n")
    print(f"  gem5 log saved to: {log_path}")


def save_vivado_batch_log(
    run_time: str, name: str, proc: subprocess.CompletedProcess
) -> Path:
    """Saves Vivado batch stdout/stderr for route-forcing diagnostics."""
    log_dir = SIMLOGS_DIR / f"simlogs_{run_time}"
    log_dir.mkdir(parents=True, exist_ok=True)
    sanitized_row_name = _sanitize_name_token(name)
    log_path = log_dir / f"vivado_batch_{sanitized_row_name}.log"
    with log_path.open("w") as f_log:
        f_log.write(f"--- STDOUT ---\n{proc.stdout}\n")
        if proc.stderr:
            f_log.write(f"\n--- STDERR ---\n{proc.stderr}\n")
    print(f"  Vivado batch log saved to: {log_path}")
    return log_path


def _set_custom_topology_env(
    env: Dict[str, str],
    custom_ncr: Optional[Path],
    custom_nts: Optional[Path],
    is_custom: bool,
) -> None:
    env.pop("CUSTOM_NCR_FILE", None)
    env.pop("CUSTOM_NTS_FILE", None)
    if is_custom and custom_ncr:
        env["CUSTOM_NCR_FILE"] = str(custom_ncr)
    if is_custom and custom_nts:
        env["CUSTOM_NTS_FILE"] = str(custom_nts)


def run_gem5_and_get_results(
    row: Dict,
    plan_input_row: Dict[str, str],
    row_index: int,
    artifact_root: Path,
    args: argparse.Namespace,
    run_tag: str,
    custom_topo_base: Path = None,
) -> List[Dict]:
    """Runs gem5 for a row and returns a list of result dictionaries, ready for CSV writing."""
    row_name = row.get("name", "unnamed_row")
    config_id = _compute_config_id(plan_input_row)
    try:
        row_hotspot_mode = _row_hotspot_mode(row, args.hotspot_mode)
        if args.hotspot_mode != "off":
            row_hotspot_occ_gap_cycles = args.hotspot_occ_gap_cycles
        else:
            row_hotspot_occ_gap_cycles = _row_int_value(
                row,
                ("hotspot_occ_gap_cycles", "hotspot_occ_trace_gap_cycles"),
                args.hotspot_occ_gap_cycles,
            )
        row_record_mode = _row_int_value(
            row, ("record_mode", "monitor_record_mode"), None
        )
        if row_record_mode is not None and row_record_mode not in (0, 1, 2):
            raise ValueError(
                f"record_mode must be 0, 1, or 2; got {row_record_mode}."
            )
    except ValueError as exc:
        _row_error(row_name, str(exc))

    if row_record_mode is not None:
        row["record_mode"] = str(row_record_mode)
    if row_hotspot_mode in ("occ", "both"):
        row["hotspot_occ_gap_cycles"] = str(row_hotspot_occ_gap_cycles)

    if row.get("__is_v2") == "1" or is_v2_row(row):
        conn_path, placement_path = _v2_paths_from_row(row)
        if conn_path is None:
            _row_error(row_name, "v2 row is missing connections_json.")
        if placement_path is None:
            _row_error(
                row_name,
                "v2 gem5 runs need a placement_json. If placement is omitted, "
                "use --topo-gen in_house so the placer can emit one.",
            )

        try:
            settings = normalize_sweep_settings(row)
            apply_normalized_settings_to_row(row, settings)
            connections_data = _load_json_file(conn_path)
            param_overrides = build_v2_param_overrides(
                row, connections_data, settings
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _row_error(row_name, str(exc))

        if custom_topo_base:
            artifact_base = custom_topo_base
        else:
            topo_key = row.get("__topology_key") or _topology_key_for_v2(
                row, conn_path, placement_path
            )
            artifact_base = artifact_root / topo_key / "noc_subsystem"

        if not artifact_base.with_suffix(".ncr").exists():
            print(
                f"{Colors.YELLOW}  [WARN] Skipping row {row_name}. Artifact not found: {artifact_base}{Colors.ENDC}"
            )
            return []

        gem5_args = [
            "--noc-topology",
            str(artifact_base),
            "--connections-json",
            str(conn_path),
            "--placement-json",
            str(placement_path),
        ]

        clock = _clock_arg_from_mhz(settings.get("noc_clk_mhz"))
        if clock:
            gem5_args.extend(
                [
                    "--noc-clock",
                    clock,
                    "--ruby-clock",
                    clock,
                    "--sys-clock",
                    clock,
                ]
            )

        endpoint_data_width_bits = settings.get("endpoint_data_width_bits")
        if endpoint_data_width_bits is not None:
            gem5_args.extend(["--data-width", str(endpoint_data_width_bits)])

        abs_max_tick = _clean(row.get("abs_max_tick"))
        if abs_max_tick:
            gem5_args.extend(["--abs-max-tick", abs_max_tick])

        if row_record_mode is not None:
            gem5_args.extend(["--record-mode", str(row_record_mode)])

        _append_network_behavior_args(gem5_args, settings)

        if row_hotspot_mode in ("occ", "both"):
            gem5_args.extend(
                [
                    "--nps-occ-trace",
                    "1",
                    "--nps-occ-trace-gap-cycles",
                    str(row_hotspot_occ_gap_cycles),
                ]
            )
        if row_hotspot_mode in ("queue", "both"):
            gem5_args.extend(["--nps-queue-trace", "1"])

        for override in param_overrides:
            gem5_args.extend(["--param", override])

        gem5_cmd = _gem5_cmd_for_row(args, row) + gem5_args

    else:
        # topo_key = _topo_key_from_row(row, P_DEFAULTS)
        counts, topo_key = get_topology_from_row(row, WORKSPACE)
        row.update(counts)

        if custom_topo_base:
            artifact_base = custom_topo_base
        else:
            artifact_base = artifact_root / topo_key / "noc_subsystem"

        if not artifact_base.with_suffix(".ncr").exists():
            print(
                f"{Colors.YELLOW}  [WARN] Skipping row {row_name}. Artifact not found: {artifact_base}{Colors.ENDC}"
            )
            return []

        try:
            settings = normalize_sweep_settings(row)
            apply_normalized_settings_to_row(row, settings)
        except ValueError as exc:
            _row_error(row_name, str(exc))

        num_reads = (
            _to_int_or_none(row.get("num_write_transactions_cfg")) or 10
        )
        read_size = (
            _awsize_code_from_bytes(row.get("axi_write_size_bytes")) or 16
        )
        read_len_raw = _awlen_from_beats(row.get("axi_write_len_beats"))
        read_len = read_len_raw if read_len_raw is not None else 7
        bandwidth = (
            _to_int_or_none(row.get("axi_write_bandwidth_cfg_MBps")) or 300
        )
        clk_freq = _to_int_or_none(row.get("noc_axi_clk_mhz")) or 1000
        clk_period = int(1 / (clk_freq / 1000000))

        gem5_args = [
            "--noc-topology",
            str(artifact_base),
            "--num-packets",
            str(num_reads),
            "--write-size",
            str(read_size),
            "--write-length",
            str(read_len),
            "--bandwidth",
            str(bandwidth),
            "--clk-period",
            str(clk_period),
            "--direction",
            row.get("direction", "INTERLEAVED"),
        ]
        if row_record_mode is not None:
            gem5_args.extend(["--record-mode", str(row_record_mode)])

        _append_network_behavior_args(gem5_args, settings)

        if row_hotspot_mode in ("occ", "both"):
            gem5_args.extend(
                [
                    "--nps-occ-trace",
                    "1",
                    "--nps-occ-trace-gap-cycles",
                    str(row_hotspot_occ_gap_cycles),
                ]
            )
        if row_hotspot_mode in ("queue", "both"):
            gem5_args.extend(["--nps-queue-trace", "1"])
        gem5_cmd = args.gem5_cmd + gem5_args

    print(f"{Colors.BLUE}  Running gem5 simulation...{Colors.ENDC}")
    print(f"  Executing gem5 command: {' '.join(gem5_cmd)}")
    _clear_runtime_hotspot_traces(row_hotspot_mode)
    t0 = time.monotonic()
    proc = subprocess.run(
        gem5_cmd, cwd=REPO_ROOT, capture_output=True, text=True
    )
    wall_time = time.monotonic() - t0

    save_gem5_log(run_tag, row_name, proc)
    hotspot_meta = _hotspot_capture_metadata(
        row_hotspot_mode, run_tag, row_index, row_name
    )

    parsed_rows = parse_gem5_output(proc.stdout)
    if not parsed_rows:
        parsed_rows = [{}]
    final_results = []
    for parsed_data in parsed_rows:
        result_dict = {
            **row,
            "run_tag": run_tag,
            "plan_row_index": row_index,
            "config_id": config_id,
            "finished_at_iso": datetime.now().astimezone().isoformat(),
            "sim_time_s": round(wall_time, 2),
            "gem5_return_code": proc.returncode,
            **hotspot_meta,
            **parsed_data,
        }
        final_results.append(result_dict)

    return final_results


def prepare_topology_for_row(i, row, args, run_tag):
    """
    Returns (custom_ncr_path, custom_nts_path, is_custom) if explicitly provided in CSV or generated in_house.
    """
    row_name = row.get("name", f"Row {i}")
    row_topo_gen = _clean(row.get("topo_gen")) or _clean(
        row.get("topology_generator")
    )
    if row_topo_gen:
        row_topo_gen = row_topo_gen.lower()
        if row_topo_gen not in ("vivado", "in_house"):
            _row_error(
                row_name,
                f"topo_gen must be 'vivado' or 'in_house', got {row_topo_gen!r}.",
            )
    topo_gen = row_topo_gen or args.topo_gen

    needs_vivado_beat_fields = topo_gen == "vivado" or args.mode in (
        "vivado_only",
        "vivado_and_gem5",
        "vivado_then_gem5",
    )
    try:
        settings = normalize_sweep_settings(
            row,
            synthesize_vivado_beats=needs_vivado_beat_fields,
        )
        apply_normalized_settings_to_row(row, settings)
    except ValueError as exc:
        _row_error(row_name, str(exc))

    conn_path = _connection_path_from_row(row)
    placement_path = _placement_path_from_row(row)
    v2_row = _is_v2_connection_path(conn_path)
    if v2_row:
        if conn_path is None or not conn_path.exists():
            _row_error(row_name, f"v2 connections JSON not found: {conn_path}")
        _mark_v2_row(row, conn_path, placement_path)

    custom_ncr_raw = _row_value(row, NCR_KEYS)
    custom_nts_raw = _row_value(row, NTS_KEYS)

    if custom_ncr_raw and custom_nts_raw:
        ncr_path = _resolve_path(custom_ncr_raw)
        nts_path = _resolve_path(custom_nts_raw)

        if not ncr_path.exists():
            _row_error(row_name, f"Custom NCR file not found: {ncr_path}")
        if not nts_path.exists():
            _row_error(row_name, f"Custom NTS file not found: {nts_path}")

        # gem5 currently strictly expects both to share the same base name due to noc_config.py's implementation
        if ncr_path.with_suffix("") != nts_path.with_suffix(""):
            print(
                f"{Colors.RED}  [ERROR] Custom NCR and NTS files must share the same base name and directory path (e.g. topology.ncr, topology.nts). Found: {ncr_path} and {nts_path}{Colors.ENDC}"
            )
            sys.exit(1)
        if v2_row and placement_path is None:
            _row_error(
                row_name,
                "v2 rows with explicit ncr/nts also need placement_json.",
            )

        return ncr_path, nts_path, True
    elif custom_ncr_raw or custom_nts_raw:
        # gem5 requires BOTH an .ncr and an .nts file to work properly
        print(
            f"{Colors.RED}  [ERROR] Row {i} provided only one of NCR or NTS file. Both must be provided for a custom route to work in gem5.{Colors.ENDC}"
        )
        sys.exit(1)

    if topo_gen == "in_house":
        if v2_row:
            topo_key = _topology_key_for_v2(row, conn_path, placement_path)
            row["__topology_key"] = topo_key
        else:
            counts, topo_key = get_topology_from_row(row, WORKSPACE)
        out_dir = NOC_DESC_DIR / run_tag / topo_key / "noc_subsystem"
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        out_ncr = out_dir.with_suffix(".ncr")
        out_nts = out_dir.with_suffix(".nts")
        generated_place = out_dir.with_suffix(".place.json")

        cache_ready = (
            out_ncr.exists()
            and out_nts.exists()
            and (
                not v2_row
                or placement_path is not None
                or generated_place.exists()
            )
        )
        if cache_ready:
            if v2_row and placement_path is None and generated_place.exists():
                _mark_v2_row(row, conn_path, generated_place)
            return out_ncr, out_nts, True  # Already generated!

        cmd = [
            sys.executable,
            str(WORKSPACE / "topology_generation" / "generate_ncr.py"),
            "--ncr",
            str(out_ncr),
            "--nts",
            str(out_nts),
        ]
        if conn_path and conn_path.exists():
            cmd.extend(["--connections", str(conn_path)])
        if v2_row:
            if placement_path:
                cmd.extend(["--placement", str(placement_path)])
            else:
                cmd.extend(["--placement-out", str(generated_place)])

        print(f"  Generating in_house topology: {' '.join(cmd)}")
        proc = subprocess.run(
            cmd, cwd=WORKSPACE, capture_output=True, text=True
        )
        if proc.returncode != 0:
            print(
                f"{Colors.RED}  [ERROR] generate_ncr.py failed:{Colors.ENDC}\n{proc.stdout}\n{proc.stderr}"
            )
            sys.exit(1)
        print(f"{Colors.GREEN}  ✓ In-house topology generated.{Colors.ENDC}")
        if v2_row and placement_path is None:
            _mark_v2_row(row, conn_path, generated_place)

        return out_ncr, out_nts, True

    return None, None, False


# --- Main Workflow Functions for Each Mode ---
def run_vivado_only(args: argparse.Namespace, run_tag: str):
    """Mode 1: Runs Vivado Tcl sweep row-by-row to generate artifacts incrementally."""
    print(f"\n{Colors.BLUE}=== Running Mode: vivado_only ==={Colors.ENDC}")

    # Read CSV to get row count
    plan_rows = read_plan_rows(args.plan)

    if len(plan_rows) == 0:
        sys.exit(
            f"{Colors.RED}[ERROR] CSV is empty or has no valid rows.{Colors.ENDC}"
        )
    selected_rows = select_plan_rows(plan_rows, args.row)

    vivado_results_path = (
        RESULTS_DIR / f"vivado_results_{args.plan.stem}_{run_tag}.csv"
    )
    env = os.environ.copy()
    env["RUN_TAG"] = run_tag

    print(f"Vivado results will be saved to: {vivado_results_path}")
    print_selected_rows_summary(plan_rows, selected_rows)

    vivado_failed = False
    for i, row in selected_rows:
        row_name = row.get("name", f"Row {i}")
        print(
            f"\n--- Processing Plan Row {i}/{len(plan_rows)}: {row_name} ---"
        )

        tcl_args = [
            "csv_row",
            str(args.plan),
            str(i),
            str(vivado_results_path),
        ]

        cmd = [
            args.vivado_bin,
            "-mode",
            "batch",
            "-source",
            str(VIVADO_TCL_SCRIPT),
            "-tclargs",
            *tcl_args,
        ]
        print(f"Executing: {' '.join(cmd)}")

        # Check for custom topology first. Clear per row so a mixed plan cannot
        # accidentally reuse a prior in-house NCR in a Vivado-routed row.
        custom_ncr, custom_nts, is_custom = prepare_topology_for_row(
            i, row, args, run_tag
        )
        _set_custom_topology_env(env, custom_ncr, custom_nts, is_custom)

        print(
            f"{Colors.BLUE}  Running Vivado... this may take a few minutes.{Colors.ENDC}"
        )
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True
        )
        save_vivado_batch_log(run_tag, row_name, proc)
        if proc.returncode != 0:
            vivado_failed = True
            print(
                f"{Colors.RED}  [ERROR] Vivado run failed for row {i}. See log below:{Colors.ENDC}"
            )
            print(proc.stdout)
            # Continue to next row instead of exiting
            continue

        print(f"{Colors.GREEN}  ✓ Row {i} complete.{Colors.ENDC}")

    print(
        f"\n{Colors.GREEN}✅ Vivado artifact generation complete.{Colors.ENDC}"
    )
    print(f"Artifacts saved under: {NOC_DESC_DIR}/{run_tag}")
    if vivado_failed:
        sys.exit(1)


def run_topology_only(args: argparse.Namespace, run_tag: str):
    """Mode: Runs Vivado TCL topology mode to generate NCR/NTS files only (no simulation)."""
    print(f"\n{Colors.BLUE}=== Running Mode: topology_only ==={Colors.ENDC}")

    # Read CSV to validate it exists and has rows
    plan_rows = read_plan_rows(args.plan)

    if len(plan_rows) == 0:
        sys.exit(
            f"{Colors.RED}[ERROR] CSV is empty or has no valid rows.{Colors.ENDC}"
        )
    selected_rows = select_plan_rows(plan_rows, args.row)

    env = os.environ.copy()
    env["RUN_TAG"] = run_tag

    if args.row is None:
        print(f"Generating topologies for {len(plan_rows)} rows...")
    else:
        row_number, row = selected_rows[0]
        row_name = row.get("name", f"Row {row_number}")
        print(
            f"Generating topology for selected row {row_number} ({row_name})..."
        )
    print(
        f"Artifacts will be saved to: {NOC_DESC_DIR}/{run_tag}"
    )

    # Call Vivado in topology mode (generates all unique topologies at once)
    if args.row is None:
        tcl_args = [
            "topology",
            str(args.plan),
        ]
    else:
        tcl_args = [
            "topology_row",
            str(args.plan),
            str(args.row),
        ]

    cmd = [
        args.vivado_bin,
        "-mode",
        "batch",
        "-source",
        str(VIVADO_TCL_SCRIPT),
        "-tclargs",
        *tcl_args,
    ]
    print(f"Executing: {' '.join(cmd)}")

    # For topology_only mode, we still generate one by one if in_house, or let Vivado do it
    # But Vivado topology-only script mode tries to do *all* rows in one launch. We can't
    # easily interleave in_house generation per-row before Vivado in this mode.
    # We will just run prepare_topology_for_row for each row if needed.

    if args.topo_gen == "in_house":
        print("  Generating topologies in-house...")
        for i, row in selected_rows:
            prepare_topology_for_row(i, row, args, run_tag)
        print(f"\n{Colors.GREEN}✅ Topology generation complete.{Colors.ENDC}")
        return run_tag

    print(
        f"{Colors.BLUE}  Running Vivado topology export... this may take a few minutes.{Colors.ENDC}"
    )
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )
    wall_time = time.monotonic() - t0

    if proc.returncode != 0:
        print(
            f"{Colors.RED}[ERROR] Vivado topology generation failed. See log below:{Colors.ENDC}"
        )
        print(proc.stdout)
        print(proc.stderr)
        sys.exit(1)

    print(
        f"\n{Colors.GREEN}✅ Topology generation complete in {wall_time:.1f}s.{Colors.ENDC}"
    )
    print(
        f"NCR/NTS files saved under: {NOC_DESC_DIR}/{run_tag}"
    )
    return run_tag


def run_gem5_only(args: argparse.Namespace, run_tag: str):
    """Mode: Generates topology for each row, then runs gem5 on it immediately."""
    print(f"\n{Colors.BLUE}=== Running Mode: gem5_only ==={Colors.ENDC}")

    artifact_tag = args.reuse_tag or run_tag
    artifact_root = NOC_DESC_DIR / artifact_tag

    plan_rows = read_plan_rows(args.plan)

    if len(plan_rows) == 0:
        sys.exit(
            f"{Colors.RED}[ERROR] CSV is empty or has no valid rows.{Colors.ENDC}"
        )
    selected_rows = select_plan_rows(plan_rows, args.row)

    gem5_results_path = RESULTS_DIR / f"gem5_{args.plan.stem}_{run_tag}.csv"
    print(f"gem5 results will be saved to: {gem5_results_path}")
    if args.reuse_tag:
        print(f"Using existing topology artifacts from: {artifact_root}")
    if len(selected_rows) == len(plan_rows):
        print(f"Processing {len(plan_rows)} rows (topology + gem5 per row)...")
    else:
        row_number, row = selected_rows[0]
        row_name = row.get("name", f"Row {row_number}")
        print(
            f"Processing 1 selected row out of {len(plan_rows)}: "
            f"row {row_number} ({row_name})"
        )

    env = os.environ.copy()
    env["RUN_TAG"] = run_tag

    with gem5_results_path.open("w", newline="") as f_gem5:
        gem5_writer = csv.DictWriter(
            f_gem5, fieldnames=GEM5_HEADERS, extrasaction="ignore"
        )
        gem5_writer.writeheader()

        for i, row in selected_rows:
            row_name = row.get("name", f"Row {i}")
            plan_input_row = dict(row)
            print(
                f"\n--- Processing Plan Row {i}/{len(plan_rows)}: {row_name} ---"
            )

            if args.reuse_tag:
                custom_ncr, custom_nts, is_custom = None, None, False
                print(
                    f"{Colors.GREEN}  ✓ Reusing existing Vivado topology artifacts.{Colors.ENDC}"
                )
            else:
                custom_ncr, custom_nts, is_custom = prepare_topology_for_row(
                    i, row, args, run_tag
                )

            if not args.reuse_tag and not is_custom:
                # Step 1: Generate topology for this row via Vivado
                print(f"  Generating topology...")
                tcl_args = [
                    "topology_row",
                    str(args.plan),
                    str(i),
                ]

                cmd = [
                    args.vivado_bin,
                    "-mode",
                    "batch",
                    "-source",
                    str(VIVADO_TCL_SCRIPT),
                    "-tclargs",
                    *tcl_args,
                ]

                print(
                    f"{Colors.BLUE}  Running Vivado to generate topology... this may take a few minutes.{Colors.ENDC}"
                )
                t0 = time.monotonic()
                proc = subprocess.run(
                    cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True
                )
                topo_time = time.monotonic() - t0

                if proc.returncode != 0:
                    print(
                        f"{Colors.RED}  [ERROR] Topology generation failed for row {i}. See log:{Colors.ENDC}"
                    )
                    print(
                        proc.stdout[-2000:]
                        if len(proc.stdout) > 2000
                        else proc.stdout
                    )
                    continue

                print(
                    f"{Colors.GREEN}  ✓ Topology generated in {topo_time:.1f}s{Colors.ENDC}"
                )
            elif is_custom:
                print(
                    f"{Colors.GREEN}  ✓ Using custom/in-house topology.{Colors.ENDC}"
                )

            # Step 2: Run gem5 on this row
            print(f"  Running gem5...")
            custom_base = (
                custom_ncr.with_suffix("")
                if is_custom and custom_ncr
                else None
            )
            results_to_write = run_gem5_and_get_results(
                row,
                plan_input_row,
                i,
                artifact_root,
                args,
                run_tag,
                custom_topo_base=custom_base,
            )

            for result in results_to_write:
                gem5_writer.writerow(result)
            f_gem5.flush()
            gem5_ok = results_to_write and all(
                result.get("gem5_return_code", 1) == 0
                for result in results_to_write
            )
            if gem5_ok:
                print(f"{Colors.GREEN}  ✓ Row {i} complete.{Colors.ENDC}")
            else:
                print(
                    f"{Colors.RED}  [ERROR] gem5 failed for row {i}. "
                    f"See the saved gem5 log and gem5_return_code column.{Colors.ENDC}"
                )

    print(
        f"\n{Colors.GREEN}✅ Topology generation + gem5 simulation complete.{Colors.ENDC}"
    )


def run_vivado_and_gem5(args: argparse.Namespace, run_tag: str):
    """Mode 3: The main interleaved workflow. Runs Vivado then gem5, row-by-row."""
    print(f"\n{Colors.BLUE}=== Running Mode: vivado_and_gem5 ==={Colors.ENDC}")

    plan_rows = read_plan_rows(args.plan)
    if len(plan_rows) == 0:
        sys.exit(
            f"{Colors.RED}[ERROR] CSV is empty or has no valid rows.{Colors.ENDC}"
        )
    selected_rows = select_plan_rows(plan_rows, args.row)

    vivado_results_path = (
        RESULTS_DIR / f"vivado_results_{args.plan.stem}_{run_tag}.csv"
    )
    gem5_results_path = RESULTS_DIR / f"gem5_{args.plan.stem}_{run_tag}.csv"

    print(f"Vivado results will be saved to: {vivado_results_path}")
    print(f"gem5 results will be saved to: {gem5_results_path}")
    print_selected_rows_summary(plan_rows, selected_rows)

    workflow_failed = False
    with gem5_results_path.open("w", newline="") as f_gem5:
        gem5_writer = csv.DictWriter(
            f_gem5, fieldnames=GEM5_HEADERS, extrasaction="ignore"
        )
        gem5_writer.writeheader()

        for i, row in selected_rows:
            row_name = row.get("name", f"Row {i}")
            plan_input_row = dict(row)
            print(
                f"\n--- Processing Plan Row {i}/{len(plan_rows)}: {row_name} ---"
            )

            # --- 1. VIVADO STEP ---
            print(
                f"{Colors.BLUE}  Running Vivado simulation for row {i}...{Colors.ENDC}"
            )

            tcl_args = [
                "csv_row",
                str(args.plan),
                str(i),
                str(vivado_results_path),
            ]
            # if args.topology_json:
            #     print(f"  Forwarding global topology override: {args.topology_json.name}")
            #     tcl_args.extend(["--topology-json", str(args.topology_json)])

            vivado_cmd = [
                args.vivado_bin,
                "-mode",
                "batch",
                "-source",
                str(VIVADO_TCL_SCRIPT),
                "-tclargs",
                *tcl_args,
            ]
            custom_ncr, custom_nts, is_custom = prepare_topology_for_row(
                i, row, args, run_tag
            )
            env = os.environ.copy()
            env["RUN_TAG"] = run_tag
            _set_custom_topology_env(env, custom_ncr, custom_nts, is_custom)

            print(f"Executing command: {' '.join(vivado_cmd)}")
            print(
                f"{Colors.BLUE}  Running Vivado... this may take a few minutes.{Colors.ENDC}"
            )

            # proc = subprocess.run(vivado_cmd, cwd=REPO_ROOT, capture_output=True, text=True)
            proc = subprocess.run(
                vivado_cmd,
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            save_vivado_batch_log(run_tag, row_name, proc)

            if proc.returncode != 0:
                workflow_failed = True
                print(
                    f"{Colors.RED}  [ERROR] Vivado run failed for row {i}. See logs.{Colors.ENDC}"
                )
                print(proc.stdout)  # Print stdout on failure for debugging
                continue

            print(f"{Colors.GREEN}  Vivado step complete.{Colors.ENDC}")

            artifact_root = NOC_DESC_DIR / run_tag

            # --- 2. GEM5 STEP ---
            custom_base = (
                custom_ncr.with_suffix("")
                if is_custom and custom_ncr
                else None
            )
            results_to_write = run_gem5_and_get_results(
                row,
                plan_input_row,
                i,
                artifact_root,
                args,
                run_tag,
                custom_topo_base=custom_base,
            )

            for result in results_to_write:
                gem5_writer.writerow(result)
            f_gem5.flush()

            gem5_ok = results_to_write and all(
                result.get("gem5_return_code", 1) == 0
                for result in results_to_write
            )
            if gem5_ok:
                print(f"{Colors.GREEN}  gem5 step complete.{Colors.ENDC}")
            else:
                workflow_failed = True
                print(
                    f"{Colors.RED}  [ERROR] gem5 step failed for row {i}. "
                    f"See the saved gem5 log and gem5_return_code column.{Colors.ENDC}"
                )

    if workflow_failed:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Unified Vivado and gem5 sweep orchestrator."
    )
    parser.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="Path to the master CSV plan file.",
    )
    parser.add_argument(
        "--mode",
        choices=[
            "vivado_and_gem5",
            "vivado_only",
            "topology_only",
            "gem5_only",
            "vivado_then_gem5",
        ],
        default="vivado_and_gem5",
        help="The workflow to execute. gem5_only generates topology then runs gem5.",
    )
    parser.add_argument(
        "--row",
        type=int,
        help="Run only this 1-based data row from the CSV plan. The header is not counted.",
    )
    parser.add_argument(
        "--topo-gen",
        choices=["vivado", "in_house"],
        default="in_house",
        help="Which tool to use for topology generation if not provided in the CSV.",
    )
    parser.add_argument(
        "--vivado-bin",
        default=DEFAULT_VIVADO_CMD,
        help="Path to Vivado binary.",
    )
    parser.add_argument(
        "--gem5-cmd",
        nargs="+",
        default=DEFAULT_GEM5_CMD,
        help="gem5 binary and config script.",
    )
    parser.add_argument(
        "--reuse-tag",
        help="RUN_TAG of existing artifacts to use for gem5_only mode.",
    )
    parser.add_argument(
        "--run-tag",
        help="Override the auto-generated RUN_TAG used for output file and artifact naming.",
    )
    parser.add_argument(
        "--hotspot-mode",
        choices=["off", "occ", "queue", "both"],
        default="off",
        help="Enable hotspot tracing for gem5 rows and preserve per-row artifacts.",
    )
    parser.add_argument(
        "--hotspot-occ-gap-cycles",
        type=int,
        default=200,
        help="Sampling gap in NoC cycles for legacy occupancy hotspot tracing.",
    )
    args = parser.parse_args()

    if not args.plan.exists():
        sys.exit(
            f"{Colors.RED}[ERROR] Plan file not found: {args.plan}{Colors.ENDC}"
        )
    if args.row is not None and args.row < 1:
        sys.exit(
            f"{Colors.RED}[ERROR] --row must be 1 or greater.{Colors.ENDC}"
        )

    run_tag = args.run_tag or datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.mode == "vivado_only":
        run_vivado_only(args, run_tag)
    elif args.mode == "topology_only":
        run_topology_only(args, run_tag)
    elif args.mode == "gem5_only":
        run_gem5_only(args, run_tag)
    else:  # Default is vivado_and_gem5
        run_vivado_and_gem5(args, run_tag)

    print(f"\n{Colors.GREEN}✅ Sweep finished.{Colors.ENDC}")


if __name__ == "__main__":
    main()
