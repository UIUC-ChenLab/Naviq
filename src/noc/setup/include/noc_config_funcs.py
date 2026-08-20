import argparse
import csv
import json
import os
import re
from collections import defaultdict
from dataclasses import (
    dataclass,
    field,
)
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.objects.ClockedObject import ClockedObject
from m5.params import *
from m5.SimObject import SimObject
from m5.util import addToPath, warn
from m5.util.convert import toFrequency

# so it can find gem5 config helpers after the NoC tree reorg
REPO_ROOT = Path(__file__).resolve().parents[3]
addToPath(str(REPO_ROOT / "configs"))

from common import (
    FileSystemConfig,
    MemConfig,
    ObjectList,
)
from noc_network import *
from noc_trace_paths import (
    NPS_OCC_TRACE_FILENAME,
    NPS_QUEUE_TRACE_FILENAME,
    runtime_trace_artifact_path,
)
from ruby.Garnet_standalone import create_system as protocol_create_system
from ruby.Ruby import setup_memory_controllers

# for simplicity, for now use Mesh_XY topology
from topologies.Mesh_XY import Mesh_XY
from topologies.NoC_Topology import NoC_Topology


METRICS_ARTIFACT_DIR = Path("src/noc/out/csv")
METRICS_FRAGMENT_DIR = METRICS_ARTIFACT_DIR / "fragments"


# ---------------------------------------------------------------------------
# Runtime metrics artifacts and topology-derived summaries.
# ---------------------------------------------------------------------------

def _safe_metrics_name(label: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(label).strip())
    return text or "metrics"


def ensure_metrics_artifact_dirs() -> None:
    METRICS_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_FRAGMENT_DIR.mkdir(parents=True, exist_ok=True)


def metrics_artifact_path(label: str, suffix: str) -> str:
    ensure_metrics_artifact_dirs()
    return os.fspath(METRICS_ARTIFACT_DIR / f"{_safe_metrics_name(label)}{suffix}")


def metrics_fragment_path(label: str, component: str) -> str:
    ensure_metrics_artifact_dirs()
    return os.fspath(
        METRICS_FRAGMENT_DIR
        / f"{_safe_metrics_name(label)}__{_safe_metrics_name(component)}.json"
    )


def clear_metrics_artifacts(label: str, components: Iterable[str]) -> None:
    for path in [metrics_artifact_path(label, ".json"), metrics_artifact_path(label, ".csv")]:
        Path(path).unlink(missing_ok=True)
    for component in components:
        Path(metrics_fragment_path(label, component)).unlink(missing_ok=True)


def build_endpoint_metric_map(
    name_to_id: Dict[str, int],
    entries: Iterable[Dict[str, str]],
) -> List[Dict[str, Any]]:
    out = []
    for entry in entries:
        logical_name = entry.get("logical_name", "")
        raw_id = name_to_id.get(logical_name)
        out.append(
            {
                "logical_name": logical_name,
                "raw_id": raw_id,
                "endpoint_label": entry.get("endpoint_label", ""),
                "protocol": entry.get("protocol", ""),
                "role": entry.get("role", ""),
            }
        )
    return out


def _clock_hz(clock_str: str) -> int:
    return int(toFrequency(clock_str))


def _duration_ticks(start_tick: Optional[int], end_tick: Optional[int]) -> Optional[int]:
    if start_tick is None or end_tick is None or end_tick < start_tick:
        return None
    return int(end_tick - start_tick)


def _duration_ns(start_tick: Optional[int], end_tick: Optional[int]) -> Optional[float]:
    duration = _duration_ticks(start_tick, end_tick)
    if duration is None:
        return None
    return float(duration) / 1000.0


def _read_json_if_exists(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    with p.open() as f:
        return json.load(f)


def _percentile(values: List[int], pct: float) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(ordered[0])
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return int(ordered[idx])


def _mean(values: List[float]) -> Optional[float]:
    return (sum(values) / len(values)) if values else None


def _aligned_axi_memory_bytes(txn: Dict[str, Any], beat_bytes: int = 64) -> int:
    axi_bytes = txn.get("axi_bytes")
    if isinstance(axi_bytes, int) and axi_bytes > 0:
        return int(axi_bytes)
    addr = txn.get("addr")
    size = txn.get("size")
    if not isinstance(addr, int) or not isinstance(size, int) or size <= 0:
        return 0
    start = addr
    end = addr + size
    aligned_start = start & ~(beat_bytes - 1)
    aligned_end = (end + beat_bytes - 1) & ~(beat_bytes - 1)
    return int(aligned_end - aligned_start)


def _logical_name_matches(actual: str, expected: str) -> bool:
    actual = str(actual)
    expected = str(expected)
    return actual == expected or actual.endswith("/" + expected) or actual.endswith(expected)


def _nps_resources_from_net(net: Dict[str, Any]) -> List[str]:
    resources = []
    for item in net.get("Connections", []):
        if isinstance(item, str) and item.startswith("NOC_NPS"):
            resources.append(item)
    return resources


def _route_path_resources(path: Dict[str, Any]) -> Dict[str, List[str]]:
    by_comm = {}
    for net in path.get("Nets", []):
        comm = str(net.get("CommType", ""))
        if comm in ("READ_REQ", "READ"):
            by_comm[comm] = _nps_resources_from_net(net)
    return by_comm


def extract_cpu_dma_ddr_route_metadata(
    ncr_filename: Optional[str],
    *,
    cpu_ddr_from: str,
    dma_ddr_from: str,
    ddr_to: str,
) -> Dict[str, Any]:
    empty = {
        "cpu_ddr_hop_count": None,
        "dma_ddr_hop_count": None,
        "cpu_dma_ddr_path_overlap_score": None,
        "shared_resource_count": None,
        "top_shared_resource_id": "",
        "cpu_dma_ddr_read_req_overlap_score": None,
        "cpu_dma_ddr_read_resp_overlap_score": None,
        "route_metadata_scope": "empty_or_not_applicable",
    }
    if not ncr_filename:
        return empty
    path = Path(ncr_filename)
    if not path.exists():
        return empty
    with path.open() as f:
        ncr = json.load(f)

    def _find_path(from_name: str, to_name: str) -> Optional[Dict[str, Any]]:
        for entry in ncr.get("Paths", []):
            if _logical_name_matches(entry.get("From", ""), from_name) and _logical_name_matches(
                entry.get("To", ""), to_name
            ):
                return entry
        return None

    cpu_path = _find_path(cpu_ddr_from, ddr_to)
    dma_path = _find_path(dma_ddr_from, ddr_to)
    if cpu_path is None or dma_path is None:
        return empty

    cpu_by_comm = _route_path_resources(cpu_path)
    dma_by_comm = _route_path_resources(dma_path)
    cpu_all = cpu_by_comm.get("READ_REQ", []) + cpu_by_comm.get("READ", [])
    dma_all = dma_by_comm.get("READ_REQ", []) + dma_by_comm.get("READ", [])

    def _overlap(left: List[str], right: List[str]) -> int:
        left_counts = defaultdict(int)
        for resource in left:
            left_counts[resource] += 1
        total = 0
        for resource in right:
            if left_counts[resource] > 0:
                total += 1
                left_counts[resource] -= 1
        return total

    shared = sorted(set(cpu_all).intersection(dma_all))
    shared_counts = {
        resource: cpu_all.count(resource) + dma_all.count(resource)
        for resource in shared
    }
    top_shared = max(shared_counts.items(), key=lambda item: item[1])[0] if shared_counts else ""
    cpu_hop_count = max((len(set(v)) for v in cpu_by_comm.values()), default=None)
    dma_hop_count = max((len(set(v)) for v in dma_by_comm.values()), default=None)

    return {
        "cpu_ddr_hop_count": cpu_hop_count,
        "dma_ddr_hop_count": dma_hop_count,
        "cpu_dma_ddr_path_overlap_score": _overlap(cpu_all, dma_all),
        "shared_resource_count": len(shared),
        "top_shared_resource_id": top_shared,
        "cpu_dma_ddr_read_req_overlap_score": _overlap(
            cpu_by_comm.get("READ_REQ", []), dma_by_comm.get("READ_REQ", [])
        ),
        "cpu_dma_ddr_read_resp_overlap_score": _overlap(
            cpu_by_comm.get("READ", []), dma_by_comm.get("READ", [])
        ),
        "route_metadata_scope": "ncr_read_req_and_read",
    }


def _load_runtime_hotspot_metrics() -> Dict[str, Any]:
    occ_path = REPO_ROOT / runtime_trace_artifact_path(NPS_OCC_TRACE_FILENAME)
    queue_path = REPO_ROOT / runtime_trace_artifact_path(NPS_QUEUE_TRACE_FILENAME)

    occ_by_name: Dict[str, float] = defaultdict(float)
    queue_by_name: Dict[str, float] = defaultdict(float)

    if occ_path.exists():
        with occ_path.open(newline="") as f:
            for row in csv.DictReader(f):
                name = str(row.get("nps_name") or row.get("nocname") or "").strip()
                try:
                    occ = float(row.get("occupancy_sum", ""))
                except ValueError:
                    continue
                if name:
                    occ_by_name[name] += occ

    if queue_path.exists():
        with queue_path.open(newline="") as f:
            for row in csv.DictReader(f):
                name = str(row.get("nocname") or row.get("router_id") or "").strip()
                try:
                    depth = float(row.get("depth", ""))
                except ValueError:
                    continue
                if name:
                    queue_by_name[name] += depth

    def _top(metrics: Dict[str, float]) -> tuple[str, Optional[float]]:
        if not metrics:
            return "", None
        total = sum(metrics.values())
        if total <= 0:
            return "", None
        name, value = max(metrics.items(), key=lambda item: item[1])
        return name, value / total

    occ_name, occ_share = _top(occ_by_name)
    queue_name, queue_share = _top(queue_by_name)
    if occ_share is None and queue_share is None:
        return {
            "hotspot_top1_location": "",
            "hotspot_top1_share": None,
            "hotspot_scope": "empty_or_not_applicable",
        }
    if occ_share is not None and (queue_share is None or occ_share >= queue_share):
        return {
            "hotspot_top1_location": occ_name,
            "hotspot_top1_share": occ_share,
            "hotspot_scope": "inclusive_full_run",
        }
    return {
        "hotspot_top1_location": queue_name,
        "hotspot_top1_share": queue_share,
        "hotspot_scope": "inclusive_full_run",
    }


def write_windowed_metrics_artifact(
    *,
    label: str,
    options,
    clock_policy: Dict[str, int],
    endpoint_map: List[Dict[str, Any]],
    fragment_paths: Dict[str, str],
    required_windows: Iterable[str],
    route_metadata: Optional[Dict[str, Any]] = None,
    memory_endpoint_type: str = "ddr",
    scratch_base: int = 0x12000000,
    scratch_size: int = 1 << 16,
) -> Dict[str, str]:
    memory_endpoint_type = str(memory_endpoint_type).lower()
    scratch_limit = scratch_base + scratch_size
    ensure_metrics_artifact_dirs()
    dma = _read_json_if_exists(fragment_paths.get("dma"))
    checker = _read_json_if_exists(fragment_paths.get("checker"))
    cpu = _read_json_if_exists(fragment_paths.get("cpu"))
    limiter = _read_json_if_exists(fragment_paths.get("limiter"))
    backpressure = _read_json_if_exists(fragment_paths.get("backpressure"))

    op_start_candidates = []
    if dma.get("saw_dma_launch") is True and isinstance(dma.get("dma_launch_tick"), int):
        op_start_candidates.append(dma.get("dma_launch_tick"))
    if dma.get("saw_first_ddr_read_request") is True and isinstance(
        dma.get("first_ddr_read_request_tick"), int
    ):
        op_start_candidates.append(dma.get("first_ddr_read_request_tick"))
    operation_start_tick = min(
        [int(v) for v in op_start_candidates if isinstance(v, int) and v >= 0],
        default=None,
    )
    operation_end_tick = None
    if checker.get("saw_beat") is True and isinstance(checker.get("last_beat_tick"), int):
        operation_end_tick = checker.get("last_beat_tick")
    elif isinstance(dma.get("dma_done_tick"), int):
        operation_end_tick = dma.get("dma_done_tick")

    axis_start_candidates = []
    if backpressure and isinstance(backpressure.get("shim_output_first_tick"), int):
        axis_start_candidates.append(backpressure.get("shim_output_first_tick"))
    elif limiter and isinstance(limiter.get("limiter_output_first_tick"), int):
        axis_start_candidates.append(limiter.get("limiter_output_first_tick"))
    elif dma.get("saw_axis_beat") is True and isinstance(dma.get("first_axis_beat_tick"), int):
        axis_start_candidates.append(dma.get("first_axis_beat_tick"))
    if checker.get("saw_beat") is True and isinstance(checker.get("first_beat_tick"), int):
        axis_start_candidates.append(checker.get("first_beat_tick"))
    axis_stream_start_tick = min(
        [int(v) for v in axis_start_candidates if isinstance(v, int) and v >= 0],
        default=None,
    )
    axis_stream_end_tick = None
    if checker.get("saw_beat") is True and isinstance(checker.get("last_beat_tick"), int):
        axis_stream_end_tick = checker.get("last_beat_tick")
    elif backpressure and isinstance(backpressure.get("shim_output_last_tick"), int):
        axis_stream_end_tick = backpressure.get("shim_output_last_tick")
    elif limiter and isinstance(limiter.get("limiter_output_last_tick"), int):
        axis_stream_end_tick = limiter.get("limiter_output_last_tick")
    elif isinstance(dma.get("last_axis_beat_tick"), int):
        axis_stream_end_tick = dma.get("last_axis_beat_tick")

    operation_window = {
        "start_tick": operation_start_tick,
        "end_tick": operation_end_tick,
        "start_reason": dma.get("operation_window_start_reason", ""),
        "end_reason": "checker_last_expected_packet"
        if isinstance(checker.get("last_beat_tick"), int)
        else ("dma_done" if isinstance(dma.get("dma_done_tick"), int) else ""),
        "duration_ticks": _duration_ticks(operation_start_tick, operation_end_tick),
        "duration_ns": _duration_ns(operation_start_tick, operation_end_tick),
    }
    axis_stream_window = {
        "start_tick": axis_stream_start_tick,
        "end_tick": axis_stream_end_tick,
        "start_reason": dma.get("axis_stream_window_start_reason", ""),
        "end_reason": "checker_last_expected_packet"
        if isinstance(checker.get("last_beat_tick"), int)
        else ("dma_last_axis_beat" if isinstance(dma.get("last_axis_beat_tick"), int) else ""),
        "duration_ticks": _duration_ticks(axis_stream_start_tick, axis_stream_end_tick),
        "duration_ns": _duration_ns(axis_stream_start_tick, axis_stream_end_tick),
    }

    setup_mmio = []
    overlap_mmio = []
    cleanup_mmio = []
    mmio_all = cpu.get("mmio_transactions", []) if isinstance(cpu.get("mmio_transactions"), list) else []
    memory_all = cpu.get("memory_transactions", []) if isinstance(cpu.get("memory_transactions"), list) else []
    for txn in mmio_all:
        start_tick = txn.get("start_tick")
        end_tick = txn.get("end_tick")
        if not isinstance(start_tick, int) or not isinstance(end_tick, int):
            continue
        # Phase classification is driven by request start time, not interval
        # overlap. This keeps the DMA launch MMIO in setup/launch even if its
        # completion extends slightly into the operation window.
        if operation_window["start_tick"] is None or start_tick < operation_window["start_tick"]:
            setup_mmio.append(txn)
        elif operation_window["end_tick"] is not None and start_tick > operation_window["end_tick"]:
            cleanup_mmio.append(txn)
        else:
            overlap_mmio.append(txn)

    overlap_memory = []
    for txn in memory_all:
        start_tick = txn.get("start_tick")
        end_tick = txn.get("end_tick")
        if not isinstance(start_tick, int) or not isinstance(end_tick, int):
            continue
        if (
            operation_window["start_tick"] is not None
            and operation_window["end_tick"] is not None
            and start_tick >= operation_window["start_tick"]
            and start_tick <= operation_window["end_tick"]
        ):
            overlap_memory.append(txn)

    mmio_lat_ticks = [
        int(txn["latency_ticks"])
        for txn in mmio_all
        if isinstance(txn.get("latency_ticks"), int)
    ]
    cpu_mmio_avg_ticks = _mean([float(v) for v in mmio_lat_ticks])
    cpu_mmio_avg_ns = (cpu_mmio_avg_ticks / 1000.0) if cpu_mmio_avg_ticks is not None else None
    cpu_clock_hz = _clock_hz(options.sys_clock)
    overlap_memory_reads = [txn for txn in overlap_memory if txn.get("is_read") is True]
    overlap_scratch_reads = [
        txn
        for txn in overlap_memory_reads
        if isinstance(txn.get("addr"), int)
        and scratch_base <= int(txn["addr"]) < scratch_limit
    ]
    cpu_memory_overlap_count = len(overlap_memory)
    cpu_memory_overlap_bytes = sum(
        _aligned_axi_memory_bytes(txn)
        for txn in overlap_memory
    )
    cpu_memory_read_count_overlap = len(overlap_scratch_reads)
    cpu_memory_read_bytes_overlap = sum(
        _aligned_axi_memory_bytes(txn)
        for txn in overlap_scratch_reads
    )
    cpu_memory_read_lat_ticks = [
        int(txn["latency_ticks"])
        for txn in overlap_scratch_reads
        if isinstance(txn.get("latency_ticks"), int)
    ]
    cpu_memory_read_avg_ticks = _mean([float(v) for v in cpu_memory_read_lat_ticks])
    cpu_memory_read_p99_ticks = _percentile(cpu_memory_read_lat_ticks, 99.0)
    cpu_memory_read_avg_cycles = (
        cpu_memory_read_avg_ticks / (1.0e12 / float(cpu_clock_hz))
        if cpu_memory_read_avg_ticks is not None
        else None
    )
    cpu_memory_read_p99_cycles = (
        cpu_memory_read_p99_ticks / (1.0e12 / float(cpu_clock_hz))
        if cpu_memory_read_p99_ticks is not None
        else None
    )
    is_hbm_memory = memory_endpoint_type == "hbm"
    cpu_ddr_read_count_overlap = 0 if is_hbm_memory else cpu_memory_read_count_overlap
    cpu_ddr_read_bytes_overlap = 0 if is_hbm_memory else cpu_memory_read_bytes_overlap
    cpu_ddr_read_avg_ticks = None if is_hbm_memory else cpu_memory_read_avg_ticks
    cpu_ddr_read_p99_ticks = None if is_hbm_memory else cpu_memory_read_p99_ticks
    cpu_ddr_read_avg_cycles = None if is_hbm_memory else cpu_memory_read_avg_cycles
    cpu_ddr_read_p99_cycles = None if is_hbm_memory else cpu_memory_read_p99_cycles
    cpu_hbm_read_count_overlap = cpu_memory_read_count_overlap if is_hbm_memory else 0
    cpu_hbm_read_bytes_overlap = cpu_memory_read_bytes_overlap if is_hbm_memory else 0
    cpu_hbm_read_avg_ticks = cpu_memory_read_avg_ticks if is_hbm_memory else None
    cpu_hbm_read_p99_ticks = cpu_memory_read_p99_ticks if is_hbm_memory else None
    cpu_hbm_read_avg_cycles = cpu_memory_read_avg_cycles if is_hbm_memory else None
    cpu_hbm_read_p99_cycles = cpu_memory_read_p99_cycles if is_hbm_memory else None

    dma_read_latencies = [
        int(v)
        for v in dma.get("read_latency_ticks", [])
        if isinstance(v, int)
    ]
    dma_read_avg_ticks = _mean([float(v) for v in dma_read_latencies])
    dma_read_p99_ticks = _percentile(dma_read_latencies, 99.0)
    ddr_clock_hz = _clock_hz(options.ddr_endpoint_clock)
    dma_read_avg_cycles = (
        dma_read_avg_ticks / (1.0e12 / float(ddr_clock_hz))
        if dma_read_avg_ticks is not None
        else None
    )
    dma_read_p99_cycles = (
        dma_read_p99_ticks / (1.0e12 / float(ddr_clock_hz))
        if dma_read_p99_ticks is not None
        else None
    )

    dma_axis_bytes_emitted = dma.get("axis_bytes_emitted")
    axis_bytes_emitted = dma_axis_bytes_emitted
    if axis_bytes_emitted is None:
        axis_bytes_emitted = checker.get("bytes_received")
    throughput_bytes = checker.get("bytes_received")
    if backpressure and isinstance(backpressure.get("shim_output_bytes"), int):
        throughput_bytes = backpressure.get("shim_output_bytes")
    elif limiter and isinstance(limiter.get("limiter_output_bytes"), int):
        throughput_bytes = limiter.get("limiter_output_bytes")
    if throughput_bytes is None:
        throughput_bytes = axis_bytes_emitted
    packet_count = checker.get("packets_received", dma.get("packets_completed"))
    axis_duration_ns = axis_stream_window["duration_ns"]
    packet_throughput_gbps = None
    if isinstance(throughput_bytes, int) and axis_duration_ns and axis_duration_ns > 0:
        packet_throughput_gbps = (float(throughput_bytes) * 8.0) / axis_duration_ns

    required = set(required_windows)
    measurement_valid = True
    invalid_reasons = []
    if "operation_window" in required:
        if operation_window["start_tick"] is None:
            invalid_reasons.append("operation_window did not start")
        if operation_window["end_tick"] is None:
            invalid_reasons.append("operation_window did not end")
    if "axis_stream_window" in required:
        if axis_stream_window["start_tick"] is None:
            invalid_reasons.append("axis_stream_window did not start")
        if axis_stream_window["end_tick"] is None:
            invalid_reasons.append("axis_stream_window did not end")
    if (
        operation_window["start_tick"] is not None
        and axis_stream_window["start_tick"] is not None
        and operation_window["end_tick"] is not None
        and axis_stream_window["start_tick"] is not None
        and operation_window["end_tick"] < axis_stream_window["start_tick"]
    ):
        invalid_reasons.append("operation_window ended before axis_stream_window started")
    expected_packets = checker.get("expected_packets")
    received_packets = checker.get("packets_received")
    checker_bytes_received = checker.get("bytes_received")
    if isinstance(expected_packets, int) and isinstance(received_packets, int):
        if received_packets != expected_packets:
            invalid_reasons.append("checker did not receive expected packets")
    if (
        isinstance(axis_bytes_emitted, int)
        and isinstance(checker_bytes_received, int)
        and axis_bytes_emitted != checker_bytes_received
    ):
        invalid_reasons.append("checker bytes do not match axis bytes emitted")
    if limiter:
        limiter_input_bytes = limiter.get("limiter_input_bytes")
        limiter_output_bytes = limiter.get("limiter_output_bytes")
        limiter_input_packets = limiter.get("limiter_input_packets")
        limiter_output_packets = limiter.get("limiter_output_packets")
        limiter_buffered_bytes = limiter.get("limiter_buffered_bytes")
        limiter_buffered_packets = limiter.get("limiter_buffered_packets")
        if (
            isinstance(dma_axis_bytes_emitted, int)
            and isinstance(limiter_input_bytes, int)
            and dma_axis_bytes_emitted != limiter_input_bytes
        ):
            invalid_reasons.append("dma axis bytes do not match limiter input bytes")
        if (
            isinstance(limiter_output_bytes, int)
            and isinstance(checker_bytes_received, int)
            and limiter_output_bytes != checker_bytes_received
        ):
            invalid_reasons.append("limiter output bytes do not match checker bytes")
        if (
            isinstance(limiter_input_packets, int)
            and isinstance(limiter_output_packets, int)
            and limiter_input_packets != limiter_output_packets
        ):
            invalid_reasons.append("limiter input packets do not match limiter output packets")
        if (
            isinstance(limiter_output_packets, int)
            and isinstance(received_packets, int)
            and limiter_output_packets != received_packets
        ):
            invalid_reasons.append("limiter output packets do not match checker packets")
        if isinstance(limiter_buffered_bytes, int) and limiter_buffered_bytes != 0:
            invalid_reasons.append("limiter buffered bytes nonzero at completion")
        if isinstance(limiter_buffered_packets, int) and limiter_buffered_packets != 0:
            invalid_reasons.append("limiter buffered packets nonzero at completion")
    if backpressure:
        shim_input_bytes = backpressure.get("shim_input_bytes")
        shim_output_bytes = backpressure.get("shim_output_bytes")
        shim_input_packets = backpressure.get("shim_input_packets")
        shim_output_packets = backpressure.get("shim_output_packets")
        shim_input_tlast_count = backpressure.get("shim_input_tlast_count")
        shim_output_tlast_count = backpressure.get("shim_output_tlast_count")
        if backpressure.get("axis_stability_violation") is True:
            invalid_reasons.append("axis stability violation")
        if (
            isinstance(dma_axis_bytes_emitted, int)
            and isinstance(shim_input_bytes, int)
            and dma_axis_bytes_emitted != shim_input_bytes
        ):
            invalid_reasons.append("dma axis bytes do not match shim input bytes")
        if (
            isinstance(shim_output_bytes, int)
            and isinstance(checker_bytes_received, int)
            and shim_output_bytes != checker_bytes_received
        ):
            invalid_reasons.append("shim output bytes do not match checker bytes")
        if (
            isinstance(shim_input_bytes, int)
            and isinstance(shim_output_bytes, int)
            and shim_input_bytes != shim_output_bytes
        ):
            invalid_reasons.append("shim input bytes do not match shim output bytes")
        if (
            isinstance(shim_input_packets, int)
            and isinstance(shim_output_packets, int)
            and shim_input_packets != shim_output_packets
        ):
            invalid_reasons.append("shim input packets do not match shim output packets")
        if (
            isinstance(shim_output_packets, int)
            and isinstance(received_packets, int)
            and shim_output_packets != received_packets
        ):
            invalid_reasons.append("shim output packets do not match checker packets")
        if isinstance(expected_packets, int):
            if isinstance(shim_input_tlast_count, int) and shim_input_tlast_count != expected_packets:
                invalid_reasons.append("shim input TLAST count does not match expected packets")
            if isinstance(shim_output_tlast_count, int) and shim_output_tlast_count != expected_packets:
                invalid_reasons.append("shim output TLAST count does not match expected packets")
        if (
            isinstance(backpressure.get("dma_to_shim_accepted_beats"), int)
            and isinstance(backpressure.get("shim_to_checker_accepted_beats"), int)
            and backpressure.get("dma_to_shim_accepted_beats") != backpressure.get("shim_to_checker_accepted_beats")
        ):
            invalid_reasons.append("shim accepted beat counts do not match")
    measurement_valid = len(invalid_reasons) == 0

    hotspot = _load_runtime_hotspot_metrics()
    route_metadata = route_metadata or {
        "cpu_ddr_hop_count": None,
        "dma_ddr_hop_count": None,
        "cpu_dma_ddr_path_overlap_score": None,
        "shared_resource_count": None,
        "top_shared_resource_id": "",
        "cpu_dma_ddr_read_req_overlap_score": None,
        "cpu_dma_ddr_read_resp_overlap_score": None,
        "route_metadata_scope": "empty_or_not_applicable",
    }

    endpoint_metric_rows = []
    label_to_row = {entry["endpoint_label"]: dict(entry) for entry in endpoint_map}

    def _append_endpoint(label_key: str, metrics: Dict[str, Any]) -> None:
        base = dict(label_to_row.get(label_key, {
            "endpoint_label": label_key,
            "raw_id": None,
            "protocol": "",
            "role": "",
            "logical_name": "",
        }))
        base.update(metrics)
        endpoint_metric_rows.append(base)

    if dma:
        _append_endpoint(
            "dma_ddr_read",
            {
                "bytes": dma.get("total_ddr_bytes_read"),
                "avg_latency_ticks": dma_read_avg_ticks,
                "p99_latency_ticks": dma_read_p99_ticks,
                "metric_scope": "windowed_operation",
            },
        )
        _append_endpoint(
            "dma_axis_source",
            {
                "bytes": axis_bytes_emitted,
                "throughput_gbps": packet_throughput_gbps,
                "metric_scope": "windowed_axis_stream",
            },
        )
    if checker:
        _append_endpoint(
            "axis_checker_sink",
            {
                "bytes": checker.get("bytes_received"),
                "packets": checker.get("packets_received"),
                "metric_scope": "windowed_axis_stream",
            },
        )
    if limiter:
        _append_endpoint(
            "limiter_axis_input",
            {
                "bytes": limiter.get("limiter_input_bytes"),
                "packets": limiter.get("limiter_input_packets"),
                "valid_only_pct": limiter.get("dma_to_limiter_valid_only_pct"),
                "metric_scope": "windowed_axis_stream",
            },
        )
    if backpressure:
        _append_endpoint(
            "backpressure_axis_input",
            {
                "bytes": backpressure.get("shim_input_bytes"),
                "packets": backpressure.get("shim_input_packets"),
                "valid_only_pct": backpressure.get("dma_to_shim_valid_only_pct"),
                "metric_scope": "windowed_axis_stream",
            },
        )
        _append_endpoint(
            "backpressure_axis_output",
            {
                "bytes": backpressure.get("shim_output_bytes"),
                "packets": backpressure.get("shim_output_packets"),
                "valid_only_pct": backpressure.get("shim_to_checker_valid_only_pct"),
                "metric_scope": "windowed_axis_stream",
            },
        )
        _append_endpoint(
            "limiter_axis_output",
            {
                "bytes": limiter.get("limiter_output_bytes"),
                "packets": limiter.get("limiter_output_packets"),
                "valid_only_pct": limiter.get("limiter_to_checker_valid_only_pct"),
                "metric_scope": "windowed_axis_stream",
            },
        )
    if cpu:
        _append_endpoint(
            "cpu_mmio",
            {
                "transactions": len(mmio_all),
                "avg_latency_ticks": cpu_mmio_avg_ticks,
                "metric_scope": "control_only",
            },
        )
        memory_read_endpoint_label = "cpu_hbm_read" if is_hbm_memory else "cpu_ddr_read"
        _append_endpoint(
            memory_read_endpoint_label,
            {
                "transactions": cpu_memory_read_count_overlap,
                "bytes": cpu_memory_read_bytes_overlap,
                "avg_latency_ticks": cpu_memory_read_avg_ticks,
                "p99_latency_ticks": cpu_memory_read_p99_ticks,
                "metric_scope": "windowed_operation"
                if cpu_memory_read_count_overlap > 0
                else "empty_or_not_applicable",
            },
        )

    culprit_candidates = []
    for row in endpoint_metric_rows:
        if isinstance(row.get("p99_latency_ticks"), (int, float)):
            culprit_candidates.append((float(row["p99_latency_ticks"]), row["endpoint_label"]))
        elif isinstance(row.get("avg_latency_ticks"), (int, float)):
            culprit_candidates.append((float(row["avg_latency_ticks"]), row["endpoint_label"]))
    worst_endpoint_culprit = max(culprit_candidates)[1] if culprit_candidates else ""

    noc_clock_hz = _clock_hz(options.noc_clock)
    rtl_clock_hz = _clock_hz(options.rtl_endpoint_clock)

    artifact = {
        "run_label": label,
        "measurement_valid": measurement_valid,
        "invalid_reason": "; ".join(invalid_reasons),
        "memory_endpoint_type": memory_endpoint_type,
        "operation_window_duration_ticks": operation_window["duration_ticks"],
        "operation_window_duration_ns": operation_window["duration_ns"],
        "axis_stream_window_duration_ticks": axis_stream_window["duration_ticks"],
        "axis_stream_window_duration_ns": axis_stream_window["duration_ns"],
        "clock_metadata": {
            "cpu_clock_hz": cpu_clock_hz,
            "noc_clock_hz": noc_clock_hz,
            "ddr_clock_hz": ddr_clock_hz,
            "rtl_clock_hz": rtl_clock_hz,
            "axis_clock_hz": rtl_clock_hz,
            "latency_cycle_domain": f"ddr_endpoint_{clock_policy['ddr_endpoint_mhz']}mhz_cycles",
        },
        "endpoint_map": endpoint_map,
        "setup_phase": {
            "cpu_mmio_count": len(setup_mmio),
            "included_in_data_plane_metrics": False,
        },
        "operation_window": operation_window,
        "axis_stream_window": axis_stream_window,
        "cleanup_phase": {
            "cpu_poll_count": len(cleanup_mmio),
            "included_in_data_plane_metrics": False,
        },
        "control_plane_overlap": {
            "cpu_mmio_overlap_count": len(overlap_mmio),
            "cpu_mmio_total_count": len(mmio_all),
            "cpu_mmio_avg_latency_ticks": cpu_mmio_avg_ticks,
            "cpu_mmio_avg_latency_ns": cpu_mmio_avg_ns,
            "scope": "control_only",
        },
        "cpu_memory_overlap": {
            "memory_endpoint_type": memory_endpoint_type,
            "cpu_memory_overlap_count": cpu_memory_overlap_count,
            "cpu_memory_overlap_bytes": cpu_memory_overlap_bytes,
            "cpu_memory_read_count_overlap": cpu_memory_read_count_overlap,
            "cpu_memory_read_bytes_overlap": cpu_memory_read_bytes_overlap,
            "cpu_memory_read_avg_latency_ticks": cpu_memory_read_avg_ticks,
            "cpu_memory_read_avg_latency_cycles": cpu_memory_read_avg_cycles,
            "cpu_memory_read_p99_ticks": cpu_memory_read_p99_ticks,
            "cpu_memory_read_p99_cycles": cpu_memory_read_p99_cycles,
            "cpu_ddr_read_count_overlap": cpu_ddr_read_count_overlap,
            "cpu_ddr_read_bytes_overlap": cpu_ddr_read_bytes_overlap,
            "cpu_ddr_read_avg_latency_ticks": cpu_ddr_read_avg_ticks,
            "cpu_ddr_read_avg_latency_cycles": cpu_ddr_read_avg_cycles,
            "cpu_ddr_read_p99_ticks": cpu_ddr_read_p99_ticks,
            "cpu_ddr_read_p99_cycles": cpu_ddr_read_p99_cycles,
            "cpu_hbm_read_count_overlap": cpu_hbm_read_count_overlap,
            "cpu_hbm_read_bytes_overlap": cpu_hbm_read_bytes_overlap,
            "cpu_hbm_read_avg_latency_ticks": cpu_hbm_read_avg_ticks,
            "cpu_hbm_read_avg_latency_cycles": cpu_hbm_read_avg_cycles,
            "cpu_hbm_read_p99_ticks": cpu_hbm_read_p99_ticks,
            "cpu_hbm_read_p99_cycles": cpu_hbm_read_p99_cycles,
            "scope": "windowed_operation"
            if cpu_memory_read_count_overlap > 0
            else "empty_or_not_applicable",
        },
        "metrics": {
            "dma_bytes_read": {
                "value": dma.get("total_ddr_bytes_read"),
                "scope": "windowed_operation" if dma else "empty_or_not_applicable",
            },
            "dma_read_avg_latency_ticks": {
                "value": dma_read_avg_ticks,
                "scope": "windowed_operation" if dma_read_avg_ticks is not None else "empty_or_not_applicable",
            },
            "dma_read_avg_latency_cycles": {
                "value": dma_read_avg_cycles,
                "scope": "windowed_operation" if dma_read_avg_cycles is not None else "empty_or_not_applicable",
            },
            "dma_read_p99_ticks": {
                "value": dma_read_p99_ticks,
                "scope": "windowed_operation" if dma_read_p99_ticks is not None else "empty_or_not_applicable",
            },
            "dma_read_p99_cycles": {
                "value": dma_read_p99_cycles,
                "scope": "windowed_operation" if dma_read_p99_cycles is not None else "empty_or_not_applicable",
            },
            "dma_reads_issued": {
                "value": dma.get("reads_issued"),
                "scope": "windowed_operation" if dma.get("reads_issued") is not None else "empty_or_not_applicable",
            },
            "dma_max_inflight_reads_observed": {
                "value": dma.get("max_inflight_reads_observed"),
                "scope": "windowed_operation" if dma.get("max_inflight_reads_observed") is not None else "empty_or_not_applicable",
            },
            "dma_descriptor_reads_completed": {
                "value": dma.get("descriptor_reads_completed"),
                "scope": "windowed_operation" if dma.get("descriptor_reads_completed") is not None else "empty_or_not_applicable",
            },
            "dma_packet_reads_completed": {
                "value": dma.get("packet_reads_completed"),
                "scope": "windowed_operation" if dma.get("packet_reads_completed") is not None else "empty_or_not_applicable",
            },
            "dma_read_issue_stall_inflight_full_cycles": {
                "value": dma.get("read_issue_stall_inflight_full_cycles"),
                "scope": "windowed_operation" if dma.get("read_issue_stall_inflight_full_cycles") is not None else "empty_or_not_applicable",
            },
            "dma_axis_wait_packet_cycles": {
                "value": dma.get("axis_wait_packet_cycles"),
                "scope": "windowed_operation" if dma.get("axis_wait_packet_cycles") is not None else "empty_or_not_applicable",
            },
            "axis_bytes_emitted": {
                "value": axis_bytes_emitted,
                "scope": "windowed_axis_stream" if axis_bytes_emitted is not None else "empty_or_not_applicable",
            },
            "dma_axis_bytes_emitted": {
                "value": dma_axis_bytes_emitted,
                "scope": "windowed_axis_stream" if dma_axis_bytes_emitted is not None else "empty_or_not_applicable",
            },
            "packet_throughput_gbps": {
                "value": packet_throughput_gbps,
                "scope": "windowed_axis_stream" if packet_throughput_gbps is not None else "empty_or_not_applicable",
            },
            "ppe_ready_percentage": {
                "value": None,
                "scope": "empty_or_not_applicable",
            },
            "ppe_valid_percentage": {
                "value": None,
                "scope": "empty_or_not_applicable",
            },
            "hotspot_top1_location": {
                "value": hotspot["hotspot_top1_location"],
                "scope": hotspot["hotspot_scope"],
            },
            "hotspot_top1_share": {
                "value": hotspot["hotspot_top1_share"],
                "scope": hotspot["hotspot_scope"],
            },
            "worst_endpoint_culprit": {
                "value": worst_endpoint_culprit,
                "scope": "windowed_operation" if worst_endpoint_culprit else "empty_or_not_applicable",
            },
        },
        "checker_summary": {
            "packets_expected": expected_packets,
            "packets_received": received_packets,
            "bytes_received": checker_bytes_received,
            "axis_bytes_emitted": axis_bytes_emitted,
            "dma_axis_bytes_emitted": dma_axis_bytes_emitted,
        },
        "limiter_summary": {
            "limiter_enabled": limiter.get("limiter_enabled") if limiter else False,
            "limiter_config_name": limiter.get("limiter_config_name", "") if limiter else "",
            "limiter_rate_setting": limiter.get("limiter_rate_setting", "") if limiter else "",
            "limiter_scope": limiter.get("limiter_scope", "empty_or_not_applicable")
            if limiter else "empty_or_not_applicable",
            "limiter_flow_bucket": limiter.get("limiter_flow_bucket") if limiter else None,
            "limiter_tokens_per_cycle": limiter.get("limiter_tokens_per_cycle") if limiter else None,
            "limiter_bucket_capacity": limiter.get("limiter_bucket_capacity") if limiter else None,
            "limiter_backpressure_period": limiter.get("limiter_backpressure_period") if limiter else None,
            "limiter_backpressure_allow": limiter.get("limiter_backpressure_allow") if limiter else None,
            "limiter_fifo_depth": limiter.get("limiter_fifo_depth") if limiter else None,
            "limiter_fifo_max_occupancy": limiter.get("limiter_fifo_max_occupancy") if limiter else None,
            "limiter_input_bytes": limiter.get("limiter_input_bytes") if limiter else None,
            "limiter_output_bytes": limiter.get("limiter_output_bytes") if limiter else None,
            "limiter_input_packets": limiter.get("limiter_input_packets") if limiter else None,
            "limiter_output_packets": limiter.get("limiter_output_packets") if limiter else None,
            "limiter_input_first_tick": limiter.get("limiter_input_first_tick") if limiter else None,
            "limiter_input_last_tick": limiter.get("limiter_input_last_tick") if limiter else None,
            "limiter_output_first_tick": limiter.get("limiter_output_first_tick") if limiter else None,
            "limiter_output_last_tick": limiter.get("limiter_output_last_tick") if limiter else None,
            "limiter_buffered_bytes": limiter.get("limiter_buffered_bytes") if limiter else None,
            "limiter_buffered_packets": limiter.get("limiter_buffered_packets") if limiter else None,
            "dma_to_limiter_ready_valid_cycles": limiter.get("dma_to_limiter_ready_valid_cycles") if limiter else None,
            "dma_to_limiter_valid_only_cycles": limiter.get("dma_to_limiter_valid_only_cycles") if limiter else None,
            "dma_to_limiter_ready_only_cycles": limiter.get("dma_to_limiter_ready_only_cycles") if limiter else None,
            "dma_to_limiter_idle_cycles": limiter.get("dma_to_limiter_idle_cycles") if limiter else None,
            "limiter_to_checker_ready_valid_cycles": limiter.get("limiter_to_checker_ready_valid_cycles") if limiter else None,
            "limiter_to_checker_valid_only_cycles": limiter.get("limiter_to_checker_valid_only_cycles") if limiter else None,
            "limiter_to_checker_ready_only_cycles": limiter.get("limiter_to_checker_ready_only_cycles") if limiter else None,
            "limiter_to_checker_idle_cycles": limiter.get("limiter_to_checker_idle_cycles") if limiter else None,
            "dma_to_limiter_valid_only_pct": limiter.get("dma_to_limiter_valid_only_pct") if limiter else None,
            "limiter_to_checker_valid_only_pct": limiter.get("limiter_to_checker_valid_only_pct") if limiter else None,
        },
        "backpressure_summary": {
            "backpressure_enabled": backpressure.get("backpressure_enabled") if backpressure else False,
            "backpressure_config_name": backpressure.get("backpressure_config_name", "") if backpressure else "",
            "backpressure_period": backpressure.get("backpressure_period") if backpressure else None,
            "backpressure_allow": backpressure.get("backpressure_allow") if backpressure else None,
            "backpressure_scope": backpressure.get("backpressure_scope", "empty_or_not_applicable")
            if backpressure else "empty_or_not_applicable",
            "axis_stability_violation": backpressure.get("axis_stability_violation") if backpressure else False,
            "axis_stability_violation_tick": backpressure.get("axis_stability_violation_tick") if backpressure else None,
            "axis_stability_violation_signal": backpressure.get("axis_stability_violation_signal", "") if backpressure else "",
            "axis_stability_violation_side": backpressure.get("axis_stability_violation_side", "") if backpressure else "",
            "dma_to_shim_ready_valid_cycles": backpressure.get("dma_to_shim_ready_valid_cycles") if backpressure else None,
            "dma_to_shim_valid_only_cycles": backpressure.get("dma_to_shim_valid_only_cycles") if backpressure else None,
            "dma_to_shim_ready_only_cycles": backpressure.get("dma_to_shim_ready_only_cycles") if backpressure else None,
            "dma_to_shim_idle_cycles": backpressure.get("dma_to_shim_idle_cycles") if backpressure else None,
            "dma_to_shim_valid_only_pct": backpressure.get("dma_to_shim_valid_only_pct") if backpressure else None,
            "shim_to_checker_ready_valid_cycles": backpressure.get("shim_to_checker_ready_valid_cycles") if backpressure else None,
            "shim_to_checker_valid_only_cycles": backpressure.get("shim_to_checker_valid_only_cycles") if backpressure else None,
            "shim_to_checker_ready_only_cycles": backpressure.get("shim_to_checker_ready_only_cycles") if backpressure else None,
            "shim_to_checker_idle_cycles": backpressure.get("shim_to_checker_idle_cycles") if backpressure else None,
            "shim_to_checker_valid_only_pct": backpressure.get("shim_to_checker_valid_only_pct") if backpressure else None,
            "dma_to_shim_accepted_beats": backpressure.get("dma_to_shim_accepted_beats") if backpressure else None,
            "shim_to_checker_accepted_beats": backpressure.get("shim_to_checker_accepted_beats") if backpressure else None,
            "shim_input_bytes": backpressure.get("shim_input_bytes") if backpressure else None,
            "shim_output_bytes": backpressure.get("shim_output_bytes") if backpressure else None,
            "shim_input_packets": backpressure.get("shim_input_packets") if backpressure else None,
            "shim_output_packets": backpressure.get("shim_output_packets") if backpressure else None,
            "shim_input_tlast_count": backpressure.get("shim_input_tlast_count") if backpressure else None,
            "shim_output_tlast_count": backpressure.get("shim_output_tlast_count") if backpressure else None,
            "shim_fifo_depth": backpressure.get("shim_fifo_depth") if backpressure else None,
            "shim_fifo_max_occupancy": backpressure.get("shim_fifo_max_occupancy") if backpressure else None,
        },
        "endpoint_metrics": endpoint_metric_rows,
        "route_metadata": route_metadata,
        "raw_fragments": {
            "dma": dma,
            "checker": checker,
            "cpu": cpu,
            "limiter": limiter,
            "backpressure": backpressure,
        },
    }

    json_path = Path(metrics_artifact_path(label, ".json"))
    csv_path = Path(metrics_artifact_path(label, ".csv"))
    with json_path.open("w") as f:
        json.dump(artifact, f, indent=2, sort_keys=True)
    csv_row = {
        "run_label": label,
        "measurement_valid": measurement_valid,
        "invalid_reason": artifact["invalid_reason"],
        "memory_endpoint_type": memory_endpoint_type,
        "operation_window_start_tick": operation_window["start_tick"],
        "operation_window_end_tick": operation_window["end_tick"],
        "operation_window_duration_ticks": operation_window["duration_ticks"],
        "operation_window_duration_ns": operation_window["duration_ns"],
        "axis_stream_window_start_tick": axis_stream_window["start_tick"],
        "axis_stream_window_end_tick": axis_stream_window["end_tick"],
        "axis_stream_window_duration_ticks": axis_stream_window["duration_ticks"],
        "axis_stream_window_duration_ns": axis_stream_window["duration_ns"],
        "cpu_clock_hz": cpu_clock_hz,
        "noc_clock_hz": noc_clock_hz,
        "ddr_clock_hz": ddr_clock_hz,
        "rtl_clock_hz": rtl_clock_hz,
        "axis_clock_hz": rtl_clock_hz,
        "latency_cycle_domain": artifact["clock_metadata"]["latency_cycle_domain"],
        "packets_expected": expected_packets,
        "packets_received": received_packets,
        "checker_packets_received": received_packets,
        "checker_bytes_received": checker_bytes_received,
        "dma_bytes_read": artifact["metrics"]["dma_bytes_read"]["value"],
        "dma_bytes_read_scope": artifact["metrics"]["dma_bytes_read"]["scope"],
        "dma_read_avg_latency_ticks": artifact["metrics"]["dma_read_avg_latency_ticks"]["value"],
        "dma_read_avg_latency_cycles": artifact["metrics"]["dma_read_avg_latency_cycles"]["value"],
        "dma_read_p99_ticks": artifact["metrics"]["dma_read_p99_ticks"]["value"],
        "dma_read_p99_cycles": artifact["metrics"]["dma_read_p99_cycles"]["value"],
        "dma_read_p99_scope": artifact["metrics"]["dma_read_p99_ticks"]["scope"],
        "dma_reads_issued": artifact["metrics"]["dma_reads_issued"]["value"],
        "dma_max_inflight_reads_observed": artifact["metrics"]["dma_max_inflight_reads_observed"]["value"],
        "dma_descriptor_reads_completed": artifact["metrics"]["dma_descriptor_reads_completed"]["value"],
        "dma_packet_reads_completed": artifact["metrics"]["dma_packet_reads_completed"]["value"],
        "dma_read_issue_stall_inflight_full_cycles": artifact["metrics"]["dma_read_issue_stall_inflight_full_cycles"]["value"],
        "dma_axis_wait_packet_cycles": artifact["metrics"]["dma_axis_wait_packet_cycles"]["value"],
        "axis_bytes_emitted": artifact["metrics"]["axis_bytes_emitted"]["value"],
        "dma_axis_bytes_emitted": artifact["metrics"]["dma_axis_bytes_emitted"]["value"],
        "axis_bytes_emitted_scope": artifact["metrics"]["axis_bytes_emitted"]["scope"],
        "packet_throughput_gbps": artifact["metrics"]["packet_throughput_gbps"]["value"],
        "packet_throughput_scope": artifact["metrics"]["packet_throughput_gbps"]["scope"],
        "limiter_enabled": artifact["limiter_summary"]["limiter_enabled"],
        "limiter_config_name": artifact["limiter_summary"]["limiter_config_name"],
        "limiter_rate_setting": artifact["limiter_summary"]["limiter_rate_setting"],
        "limiter_scope": artifact["limiter_summary"]["limiter_scope"],
        "limiter_flow_bucket": artifact["limiter_summary"]["limiter_flow_bucket"],
        "limiter_tokens_per_cycle": artifact["limiter_summary"]["limiter_tokens_per_cycle"],
        "limiter_bucket_capacity": artifact["limiter_summary"]["limiter_bucket_capacity"],
        "limiter_backpressure_period": artifact["limiter_summary"]["limiter_backpressure_period"],
        "limiter_backpressure_allow": artifact["limiter_summary"]["limiter_backpressure_allow"],
        "limiter_fifo_depth": artifact["limiter_summary"]["limiter_fifo_depth"],
        "limiter_fifo_max_occupancy": artifact["limiter_summary"]["limiter_fifo_max_occupancy"],
        "limiter_input_bytes": artifact["limiter_summary"]["limiter_input_bytes"],
        "limiter_output_bytes": artifact["limiter_summary"]["limiter_output_bytes"],
        "limiter_input_packets": artifact["limiter_summary"]["limiter_input_packets"],
        "limiter_output_packets": artifact["limiter_summary"]["limiter_output_packets"],
        "limiter_input_first_tick": artifact["limiter_summary"]["limiter_input_first_tick"],
        "limiter_input_last_tick": artifact["limiter_summary"]["limiter_input_last_tick"],
        "limiter_output_first_tick": artifact["limiter_summary"]["limiter_output_first_tick"],
        "limiter_output_last_tick": artifact["limiter_summary"]["limiter_output_last_tick"],
        "limiter_buffered_bytes": artifact["limiter_summary"]["limiter_buffered_bytes"],
        "limiter_buffered_packets": artifact["limiter_summary"]["limiter_buffered_packets"],
        "dma_to_limiter_ready_valid_cycles": artifact["limiter_summary"]["dma_to_limiter_ready_valid_cycles"],
        "dma_to_limiter_valid_only_cycles": artifact["limiter_summary"]["dma_to_limiter_valid_only_cycles"],
        "dma_to_limiter_ready_only_cycles": artifact["limiter_summary"]["dma_to_limiter_ready_only_cycles"],
        "dma_to_limiter_idle_cycles": artifact["limiter_summary"]["dma_to_limiter_idle_cycles"],
        "limiter_to_checker_ready_valid_cycles": artifact["limiter_summary"]["limiter_to_checker_ready_valid_cycles"],
        "limiter_to_checker_valid_only_cycles": artifact["limiter_summary"]["limiter_to_checker_valid_only_cycles"],
        "limiter_to_checker_ready_only_cycles": artifact["limiter_summary"]["limiter_to_checker_ready_only_cycles"],
        "limiter_to_checker_idle_cycles": artifact["limiter_summary"]["limiter_to_checker_idle_cycles"],
        "dma_to_limiter_valid_only_pct": artifact["limiter_summary"]["dma_to_limiter_valid_only_pct"],
        "limiter_to_checker_valid_only_pct": artifact["limiter_summary"]["limiter_to_checker_valid_only_pct"],
        "backpressure_enabled": artifact["backpressure_summary"]["backpressure_enabled"],
        "backpressure_config_name": artifact["backpressure_summary"]["backpressure_config_name"],
        "backpressure_period": artifact["backpressure_summary"]["backpressure_period"],
        "backpressure_allow": artifact["backpressure_summary"]["backpressure_allow"],
        "backpressure_scope": artifact["backpressure_summary"]["backpressure_scope"],
        "axis_stability_violation": artifact["backpressure_summary"]["axis_stability_violation"],
        "axis_stability_violation_tick": artifact["backpressure_summary"]["axis_stability_violation_tick"],
        "axis_stability_violation_signal": artifact["backpressure_summary"]["axis_stability_violation_signal"],
        "axis_stability_violation_side": artifact["backpressure_summary"]["axis_stability_violation_side"],
        "dma_to_shim_ready_valid_cycles": artifact["backpressure_summary"]["dma_to_shim_ready_valid_cycles"],
        "dma_to_shim_valid_only_cycles": artifact["backpressure_summary"]["dma_to_shim_valid_only_cycles"],
        "dma_to_shim_ready_only_cycles": artifact["backpressure_summary"]["dma_to_shim_ready_only_cycles"],
        "dma_to_shim_idle_cycles": artifact["backpressure_summary"]["dma_to_shim_idle_cycles"],
        "dma_to_shim_valid_only_pct": artifact["backpressure_summary"]["dma_to_shim_valid_only_pct"],
        "shim_to_checker_ready_valid_cycles": artifact["backpressure_summary"]["shim_to_checker_ready_valid_cycles"],
        "shim_to_checker_valid_only_cycles": artifact["backpressure_summary"]["shim_to_checker_valid_only_cycles"],
        "shim_to_checker_ready_only_cycles": artifact["backpressure_summary"]["shim_to_checker_ready_only_cycles"],
        "shim_to_checker_idle_cycles": artifact["backpressure_summary"]["shim_to_checker_idle_cycles"],
        "shim_to_checker_valid_only_pct": artifact["backpressure_summary"]["shim_to_checker_valid_only_pct"],
        "dma_to_shim_accepted_beats": artifact["backpressure_summary"]["dma_to_shim_accepted_beats"],
        "shim_to_checker_accepted_beats": artifact["backpressure_summary"]["shim_to_checker_accepted_beats"],
        "shim_input_bytes": artifact["backpressure_summary"]["shim_input_bytes"],
        "shim_output_bytes": artifact["backpressure_summary"]["shim_output_bytes"],
        "shim_input_packets": artifact["backpressure_summary"]["shim_input_packets"],
        "shim_output_packets": artifact["backpressure_summary"]["shim_output_packets"],
        "shim_input_tlast_count": artifact["backpressure_summary"]["shim_input_tlast_count"],
        "shim_output_tlast_count": artifact["backpressure_summary"]["shim_output_tlast_count"],
        "shim_fifo_depth": artifact["backpressure_summary"]["shim_fifo_depth"],
        "shim_fifo_max_occupancy": artifact["backpressure_summary"]["shim_fifo_max_occupancy"],
        "cpu_mmio_count": len(mmio_all),
        "cpu_mmio_avg_latency_ticks": cpu_mmio_avg_ticks,
        "cpu_mmio_avg_latency_ns": cpu_mmio_avg_ns,
        "cpu_mmio_overlap_count": len(overlap_mmio),
        "cpu_memory_overlap_count": cpu_memory_overlap_count,
        "cpu_memory_overlap_bytes": cpu_memory_overlap_bytes,
        "cpu_memory_read_count_overlap": cpu_memory_read_count_overlap,
        "cpu_memory_read_bytes_overlap": cpu_memory_read_bytes_overlap,
        "cpu_memory_read_avg_latency_cycles": cpu_memory_read_avg_cycles,
        "cpu_memory_read_p99_cycles": cpu_memory_read_p99_cycles,
        "cpu_ddr_read_count_overlap": cpu_ddr_read_count_overlap,
        "cpu_ddr_read_bytes_overlap": cpu_ddr_read_bytes_overlap,
        "cpu_ddr_read_avg_latency_cycles": cpu_ddr_read_avg_cycles,
        "cpu_ddr_read_p99_cycles": cpu_ddr_read_p99_cycles,
        "cpu_hbm_read_count_overlap": cpu_hbm_read_count_overlap,
        "cpu_hbm_read_bytes_overlap": cpu_hbm_read_bytes_overlap,
        "cpu_hbm_read_avg_latency_cycles": cpu_hbm_read_avg_cycles,
        "cpu_hbm_read_p99_cycles": cpu_hbm_read_p99_cycles,
        "hotspot_top1_location": hotspot["hotspot_top1_location"],
        "hotspot_top1_share": hotspot["hotspot_top1_share"],
        "hotspot_scope": hotspot["hotspot_scope"],
        "worst_endpoint_culprit": worst_endpoint_culprit,
        "endpoint_label": worst_endpoint_culprit,
        "cpu_ddr_hop_count": route_metadata.get("cpu_ddr_hop_count"),
        "dma_ddr_hop_count": route_metadata.get("dma_ddr_hop_count"),
        "cpu_dma_ddr_path_overlap_score": route_metadata.get("cpu_dma_ddr_path_overlap_score"),
        "shared_resource_count": route_metadata.get("shared_resource_count"),
        "top_shared_resource_id": route_metadata.get("top_shared_resource_id"),
        "cpu_dma_ddr_read_req_overlap_score": route_metadata.get("cpu_dma_ddr_read_req_overlap_score"),
        "cpu_dma_ddr_read_resp_overlap_score": route_metadata.get("cpu_dma_ddr_read_resp_overlap_score"),
        "route_metadata_scope": route_metadata.get("route_metadata_scope"),
    }
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_row.keys()))
        writer.writeheader()
        writer.writerow(csv_row)
    return {"json_path": os.fspath(json_path), "csv_path": os.fspath(csv_path)}


def get_parser():
    parser = argparse.ArgumentParser(
        description="Versal NoC Garnet Standalone Test"
    )

    # --- Topology ---
    parser.add_argument(
        "--noc-topology",
        type=str,
        default="src/noc/topology/topologies/aximm_1to1_close",
        help=(
            "Path to a topology bundle directory containing "
            "<basename>.conn.json, <basename>.place.json, <basename>.nts, "
            "and <basename>.ncr (basename = directory name). "
            "Optional <basename>.opts.json supplies record_nps, "
            "record_nps_gap_cycles, record_mode_interfaces, and noc_probes."
        ),
    )
    parser.add_argument(
        "--nts-file",
        type=str,
        default=None,
        help="Override the topology .nts filepath (bypasses --noc-topology + '.nts').",
    )
    parser.add_argument(
        "--ncr-file",
        type=str,
        default=None,
        help="Override the topology .ncr filepath (bypasses --noc-topology + '.ncr').",
    )
    parser.add_argument(
        "--noc-names",
        type=lambda x: (str(x).lower() in ["true", "1", "yes"]),
        default=True,
        help="True to parse specific Router/NPS types from NCR files, False for generic.",
    )
    parser.add_argument(
        "--nps-queue-trace",
        type=int,
        default=0,
        help="Non-zero enables sparse CSV trace of NPS input VC/credit queues "
        f"({runtime_trace_artifact_path('nps_queue_trace.csv')} by default).",
    )
    parser.add_argument(
        "--nsu-read-drain-trace",
        type=int,
        default=0,
        help="Non-zero enables CSV trace of AXI-MM NSU read-response drain "
        "selection and flit injection order "
        f"({runtime_trace_artifact_path('nsu_read_drain_trace.csv')} by default).",
    )
    parser.add_argument(
        "--nps-occ-trace",
        type=int,
        default=None,
        help="NPS trace bundle: 0=off, non-zero enables nps_occ_all.csv and "
        "nps_flit_trace.csv. When omitted, falls back to legacy topology "
        "JSON keys if present.",
    )
    parser.add_argument(
        "--nps-occ-trace-gap-cycles",
        type=int,
        default=None,
        help="NoC clock cycles between occupancy samples for --nps-occ-trace. "
        "When omitted, falls back to the legacy topology JSON value if present.",
    )

    # --- Traffic Generation Parameters ---
    parser.add_argument(
        "--num-packets",
        type=int,
        default=100,
        help="Number of read transactions per NMU.",
    )
    parser.add_argument(
        "--write-size",
        type=int,
        default=6,
        help="Log2 of write request size in bytes (e.g., 6 -> 2^6 = 64 bytes).",
    )
    parser.add_argument(
        "--write-length",
        type=int,
        default=15,
        help="AXI burst length for writes (e.g., 15 -> 16 beats).",
    )
    parser.add_argument(
        "--bandwidth",
        type=int,
        default=800,
        help="Read/write bandwidth in MBps.",
    )
    parser.add_argument(
        "--aximm-max-outstanding-writes",
        type=int,
        default=1,
        help="Maximum outstanding AXI-MM write commands per synthesized traffic generator.",
    )
    parser.add_argument(
        "--clk-period",
        type=int,
        default=1000,
        help="Clock period in ps.",
    )
    parser.add_argument(
        "--interleaved",
        type=int,
        choices=[0, 1],
        default=1,
        help="1 for interleaved r/ws, 0 for parallel r/ws.",
    )
    parser.add_argument(
        "--do-writes",
        type=int,
        choices=[0, 1],
        default=1,
        help="1 to enable write traffic, 0 to disable.",
    )
    parser.add_argument(
        "--do-reads",
        type=int,
        choices=[0, 1],
        default=1,
        help="1 to enable read traffic, 0 to disable.",
    )

    # --- Network Configuration ---
    parser.add_argument(
        "--network",
        type=str,
        default="nocgarnet",
        help="Network type ('nocgarnet' or other).",
    )
    parser.add_argument(
        "--router-latency",
        type=int,
        default=2,
        help="Latency of each router in cycles.",
    )
    parser.add_argument(
        "--link-latency",
        type=int,
        default=0,
        help="Latency of each link in cycles.",
    )
    parser.add_argument(
        "--vcs-per-vnet",
        type=int,
        default=4,
        help="Virtual channels per virtual network.",
    )
    parser.add_argument(
        "--ni-flit-size",
        type=int,
        default=16,
        help="Network interface flit size in bytes.",
    )
    parser.add_argument(
        "--data-width",
        type=int,
        default=512,
        help="Data width for Master and Slave tiles in bits.",
    )
    parser.add_argument(
        "--nsu-read-response-gap-cycles",
        type=int,
        default=1,
        help="Extra idle cycles inserted by AXI-MM NSUs after read-response flit groups; 0 disables response bubbles.",
    )
    parser.add_argument(
        "--nsu-read-response-per-flit-gap-cycles",
        type=int,
        default=0,
        help="Extra idle cycles inserted by AXI-MM NSUs after each read-response flit; 0 disables per-flit response bubbles.",
    )
    parser.add_argument(
        "--nsu-read-response-half-rate",
        action="store_true",
        default=False,
        help=(
            "Diagnostic override: pace AXI-MM NSU read-response flits every "
            "other cycle by forcing per-flit gap=1 and disabling the 4-flit "
            "burst gap."
        ),
    )
    parser.add_argument(
        "--nmu-read-response-delay-cycles",
        type=int,
        default=-1,
        help="Override AXI-MM NMU read-response enqueue delay; -1 preserves the built-in formula.",
    )
    parser.add_argument(
        "--aximm-master-rrob-max-entries",
        type=int,
        default=0,
        help="Override AXI-MM master RROB entries; 0 preserves per-endpoint defaults.",
    )
    parser.add_argument(
        "--axis-print-data",
        action="store_true",
        default=False,
        help="Print AXIS beat data for debug-oriented configs.",
    )
    parser.add_argument(
        "--record-mode",
        type=int,
        choices=[0, 1, 2],
        default=0,
        help="NocInterface monitor CSV logging: 0=off, 1=CSV, 2=CSV plus ready/valid.",
    )
    parser.add_argument(
        "--buffers-per-data-vc",
        type=int,
        default=None,
        help="Override NocGarnetNetwork data VC buffer depth.",
    )
    parser.add_argument(
        "--buffers-per-ctrl-vc",
        type=int,
        default=None,
        help="Override NocGarnetNetwork control VC buffer depth.",
    )
    parser.add_argument(
        "--rptr-credits",
        type=int,
        default=None,
        help="Override RPTR NPS credit depth.",
    )
    parser.add_argument(
        "--vnoc-credits",
        type=int,
        default=None,
        help="Override VNOC NPS credit depth.",
    )
    parser.add_argument(
        "--hnoc-credits",
        type=int,
        default=None,
        help="Override HNOC NPS credit depth.",
    )
    parser.add_argument(
        "--ncrb-credits",
        type=int,
        default=None,
        help="Override NCRB NPS credit depth.",
    )
    parser.add_argument(
        "--nidb-credits",
        type=int,
        default=None,
        help="Override NIDB NPS credit depth.",
    )
    parser.add_argument(
        "--disable-detailed-metrics",
        action="store_true",
        default=False,
        help="Disable detailed percentiles and fairness calculation to save memory and time.",
    )
    parser.add_argument(
        "--hbm-read-latency-cycles",
        type=int,
        default=None,
        help="Override HBM front-end read admission latency in cycles.",
    )
    parser.add_argument(
        "--hbm-write-latency-cycles",
        type=int,
        default=None,
        help="Override HBM front-end write admission latency in cycles.",
    )
    parser.add_argument(
        "--hbm-resp-latency-cycles",
        type=int,
        default=None,
        help="Override HBM front-end response latency in cycles.",
    )
    parser.add_argument(
        "--hbm-port-queue-depth",
        type=int,
        default=None,
        help="Override HBM front-end per-port queue depth.",
    )
    parser.add_argument(
        "--hbm-max-outstanding-reads",
        type=int,
        default=None,
        help="Override HBM front-end per-port outstanding read limit.",
    )
    parser.add_argument(
        "--hbm-max-outstanding-writes",
        type=int,
        default=None,
        help="Override HBM front-end per-port outstanding write limit.",
    )
    parser.add_argument(
        "--hbm-issue-interval-cycles",
        type=int,
        default=None,
        help="Override the shared HBM controller frontend issue interval in cycles; set to 0 to rely on the bandwidth cap.",
    )
    parser.add_argument(
        "--hbm-shared-bw-mbps",
        type=int,
        default=None,
        help="Override the shared HBM controller frontend bandwidth cap in MB/s.",
    )
    parser.add_argument(
        "--hbm-nmu-bw-mbps",
        type=int,
        default=None,
        help="Override the per-HBM-NMU AXI link bandwidth cap in MB/s.",
    )
    parser.add_argument(
        "--hbm-banks-per-pseudo-channel",
        type=int,
        default=None,
        help="Override the number of modeled banks per HBM pseudo channel.",
    )
    parser.add_argument(
        "--hbm-row-hit-latency-cycles",
        type=int,
        default=None,
        help="Override additional scheduler delay for an HBM row hit.",
    )
    parser.add_argument(
        "--hbm-row-miss-latency-cycles",
        type=int,
        default=None,
        help="Override additional scheduler delay for an HBM row miss.",
    )
    parser.add_argument(
        "--hbm-bank-busy-cycles",
        type=int,
        default=None,
        help="Override modeled bank busy time after an HBM command issues.",
    )
    parser.add_argument(
        "--hbm-cmd-bus-cycles",
        type=int,
        default=None,
        help="Override modeled shared HBM controller command-path occupancy in cycles.",
    )
    parser.add_argument(
        "--hbm-page-policy",
        type=str,
        default=None,
        help="Override HBM page policy (open_page or closed_page).",
    )
    parser.add_argument(
        "--routing-algorithm",
        type=int,
        default=2,
        help="Routing algorithm (0, 1, or 2).",
    )
    parser.add_argument(
        "--smartnic-connections-json",
        type=str,
        default="",
        help="SmartNIC logical topology JSON with smartnic_sim metadata.",
    )
    parser.add_argument(
        "--smartnic-placement-json",
        type=str,
        default="",
        help="SmartNIC logical-to-physical placement JSON used to generate NTS/NCR.",
    )
    parser.add_argument(
        "--connections-json",
        type=str,
        default="",
        help="Naviq v2 setup connections JSON (*.conn.json).",
    )
    parser.add_argument(
        "--placement-json",
        type=str,
        default="",
        help="Naviq v2 setup placement JSON (*.place.json).",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Override a v2 setup component parameter as component.param=value. May be repeated.",
    )
    parser.add_argument(
        "--topology",
        type=str,
        default="NoC_Topology",
        help="Topology type ('Mesh_XY' or other).",
    )

    # --- System & Simulation Control ---
    parser.add_argument(
        "--sys-clock", type=str, default="1GHz", help="System clock frequency."
    )
    parser.add_argument(
        "--noc-clock",
        type=str,
        default="1GHz",
        help="NoC (Garnet) clock frequency.",
    )
    parser.add_argument(
        "--ruby-clock", type=str, default="1GHz", help="Ruby clock frequency."
    )
    parser.add_argument(
        "--rtl-endpoint-clock",
        type=str,
        default="400MHz",
        help="Clock for RTL/dma/checker endpoint logic in targeted RTL/DDR config families.",
    )
    parser.add_argument(
        "--ddr-endpoint-clock",
        type=str,
        default="400MHz",
        help="Clock for DDR-facing endpoint/tile logic in targeted RTL/DDR config families.",
    )
    parser.add_argument(
        "--ddr-memctrl-clock",
        type=str,
        default="400MHz",
        help="Clock for DDR MemCtrl and DDR-side bus in targeted RTL/DDR config families.",
    )
    parser.add_argument(
        "--sim-cycles",
        type=int,
        default=10000000000000000,
        help="Maximum simulation cycles.",
    )
    parser.add_argument(
        "--abs-max-tick",
        type=int,
        default=10000000000000000,
        help="Absolute maximum simulation tick.",
    )

    # --- Workload Configs ---
    parser.add_argument(
        "--binary",
        type=str,
        default="tests/test-progs/hello/bin/arm/linux/hello",
        help="Path to the binary executable to run on the CPU.",
    )

    parser.add_argument(
        "--options",
        type=str,
        default="",
        help="Space-separated options for the binary executable.",
    )

    # --- FS Mode Configs ---
    parser.add_argument(
        "--kernel",
        type=str,
        default="",
        help="Path to the kernel binary (required for FS mode).",
    )

    parser.add_argument(
        "--disk-image",
        type=str,
        default="",
        help="Path to the disk image file (optional for FS mode).",
    )

    parser.add_argument(
        "--script",
        type=str,
        default="",
        help="Path to rcS script to run inside the OS",
    )

    parser.add_argument(
        "--dtb-filename",
        type=str,
        default="",
        help="Path to DTB file (auto-generated if not specified).",
    )
    parser.add_argument(
        "--cpu-type",
        type=str,
        default="TimingSimple",
        choices=["TimingSimple", "AtomicSimple", "O3"],
        help="CPU model to use (TimingSimple, AtomicSimple, O3).",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=str,
        default="",
        help="Path to a checkpoint directory to restore from (e.g. m5out/cpt.12345). "
        "Boot Linux fast with fs_linux_simple.py --checkpoint-at-end, then "
        "restore here with the NoC config.",
    )
    parser.add_argument(
        "--checkpoint-interval-noc-cycles",
        type=int,
        default=0,
        help="When > 0, periodically checkpoint every N NoC clock cycles.",
    )
    parser.add_argument(
        "--checkpoint-write-dir",
        type=str,
        default="",
        help="Directory where periodic NoC checkpoints are written as cpt_<tick>.",
    )
    parser.add_argument(
        "--checkpoint-verbose",
        type=int,
        choices=[0, 1],
        default=0,
        help="1 prints verbose checkpoint creation messages, 0 keeps periodic checkpoint logging quiet.",
    )

    # --- Other Configs ---
    parser.add_argument(
        "--num-cpus", type=int, default=2, help="number of cpus in network."
    )
    parser.add_argument(
        "--garnet-deadlock-threshold",
        type=int,
        default=50000,
        help="Garnet deadlock threshold.",
    )
    parser.add_argument(
        "--mem-size", type=str, default="32GiB", help="Memory size."
    )
    parser.add_argument(
        "--mesh-rows",
        type=int,
        default=2,
        help="Number of rows in Mesh_XY topology.",
    )
    parser.add_argument(
        "--direction",
        type=str,
        default="INTERLEAVED",
        choices=["WRITE_ONLY", "INTERLEAVED"],
        help="Direction for traffic generator (WRITE_ONLY, INTERLEAVED).",
    )
    parser.add_argument(
        "--num-packets-max",
        type=int,
        default=-1,
        help="Stop injecting after --num-packets-max. Set to -1 to disable.",
    )
    parser.add_argument(
        "--single-sender-id",
        type=int,
        default=-1,
        help="Only inject from this sender. Set to -1 to disable.",
    )
    parser.add_argument(
        "--single-dest-id",
        type=int,
        default=-1,
        help="Only send to this destination. Set to -1 to disable.",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=3,
        help="Number of digits of precision after decimal point for injection rate.",
    )
    parser.add_argument(
        "--synthetic",
        type=str,
        default="uniform_random",
        choices=[
            "uniform_random",
            "tornado",
            "bit_complement",
            "bit_reverse",
            "bit_rotation",
            "neighbor",
            "shuffle",
            "transpose",
        ],
        help="Synthetic traffic type.",
    )
    parser.add_argument(
        "--injectionrate",
        type=float,
        default=0.1,
        help="Injection rate in packets per cycle per node.",
    )
    parser.add_argument(
        "--inj-vnet",
        type=int,
        default=-1,
        choices=[-1, 0, 1, 2],
        help="Only inject in this vnet (0, 1 or 2). 0 and 1 are 1-flit, 2 is 5-flit. Set to -1 to inject randomly in all vnets.",
    )
    parser.add_argument(
        "--num-dirs",
        type=int,
        default=0,
        help="Number of directories (destinations).",
    )
    parser.add_argument(
        "--sys-voltage", type=str, default="1V", help="System voltage."
    )  # Changed default from "1" to "1V" for consistency
    parser.add_argument(
        "--l1d-size", type=str, default="64KiB", help="L1 data cache size."
    )
    parser.add_argument(
        "--l1d-assoc", type=int, default=2, help="L1 data cache associativity."
    )
    parser.add_argument(
        "--link-width-bits",
        type=int,
        default=128,
        help="Width in bits for all links inside garnet.",
    )
    parser.add_argument(
        "--network-fault-model",
        action="store_true",
        default=False,
        help="Enable network fault model.",
    )
    parser.add_argument(
        "--numa-high-bit",
        type=int,
        default=0,
        help="NUMA high bit for address interleaving.",
    )
    parser.add_argument(
        "--cacheline-size",
        type=int,
        default=64,
        help="Cacheline size in bytes.",
    )
    parser.add_argument(
        "--mem-type", type=str, default="DDR3_1600_8x8", help="Memory type."
    )
    parser.add_argument(
        "--xor-low-bit",
        type=int,
        default=20,
        help="XOR low bit for address hashing.",
    )
    parser.add_argument(
        "--access-backing-store",
        action="store_true",
        default=False,
        help="Use functional store and Ruby for timing only.",
    )  # Changed default from "store_true" string to False boolean
    parser.add_argument(
        "--enable-dram-powerdown",
        action="store_true",
        default=False,
        help="Enable DRAM powerdown states.",
    )
    parser.add_argument(
        "--number-of-virtual-networks",
        type=int,
        default=5,
        help="Number of virtual networks for the NoC.",
    )

    parser.add_argument(
        "--print-paths",
        action="store_true",
        default=False,
        dest="print_paths",
        help=(
            "Build the topology, validate noc_probes from the opts JSON, print "
            "NocProbe snooper field help, and print endpoint flow paths; then exit "
            "before m5.instantiate()."
        ),
    )
    parser.add_argument(
        "--print-noc-probe-help",
        action="store_true",
        default=False,
        dest="print_noc_probe_help",
        help=(
            "Print supported NocProbe snooper hook_ids and field IDs, then exit "
            "without building the topology or running simulation."
        ),
    )

    # Parse and return the options
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Endpoint clock policy and topology construction.
# ---------------------------------------------------------------------------

def clock_to_mhz(clock_str):
    freq_hz = int(toFrequency(clock_str))
    if freq_hz <= 0:
        m5.fatal(f"Invalid clock frequency: {clock_str}")
    return int(freq_hz / 1e6)


def create_targeted_clock_domains(system, options):
    if not hasattr(system, "voltage_domain"):
        system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)
    if not hasattr(system, "clk_domain"):
        system.clk_domain = SrcClockDomain(
            clock=options.sys_clock, voltage_domain=system.voltage_domain
        )
    system.rtl_endpoint_clk_domain = SrcClockDomain(
        clock=options.rtl_endpoint_clock, voltage_domain=system.voltage_domain
    )
    system.ddr_endpoint_clk_domain = SrcClockDomain(
        clock=options.ddr_endpoint_clock, voltage_domain=system.voltage_domain
    )
    system.ddr_memctrl_clk_domain = SrcClockDomain(
        clock=options.ddr_memctrl_clock, voltage_domain=system.voltage_domain
    )
    return {
        "sys_mhz": clock_to_mhz(options.sys_clock),
        "noc_mhz": clock_to_mhz(options.noc_clock),
        "rtl_endpoint_mhz": clock_to_mhz(options.rtl_endpoint_clock),
        "ddr_endpoint_mhz": clock_to_mhz(options.ddr_endpoint_clock),
        "ddr_memctrl_mhz": clock_to_mhz(options.ddr_memctrl_clock),
    }


def apply_targeted_endpoint_clock_policy(
    system,
    options,
    tiles,
    node_conn_names,
    *,
    ddr_endpoint_names=(),
    sys_endpoint_names=(),
):
    policy = create_targeted_clock_domains(system, options)
    ddr_names = set(ddr_endpoint_names)
    sys_names = set(sys_endpoint_names)

    for tile_obj, conn_names in zip(tiles, node_conn_names):
        conn_clocks = []
        for conn_name in conn_names:
            if conn_name in sys_names:
                conn_clocks.append(policy["sys_mhz"])
            elif conn_name in ddr_names:
                conn_clocks.append(policy["ddr_endpoint_mhz"])
            else:
                conn_clocks.append(policy["rtl_endpoint_mhz"])
        tile_obj.clockDomains = conn_clocks
        tile_obj.port_endpoint_names = list(conn_names)

        if "clk_domain" in getattr(tile_obj, "_params", {}):
            if any(conn_name in sys_names for conn_name in conn_names):
                tile_obj.clk_domain = system.clk_domain
            elif any(conn_name in ddr_names for conn_name in conn_names):
                tile_obj.clk_domain = system.ddr_endpoint_clk_domain
            else:
                tile_obj.clk_domain = system.rtl_endpoint_clk_domain

    return policy


def print_targeted_clock_policy(
    label,
    system,
    tiles,
    node_conn_names,
    policy,
    *,
    ddr_endpoint_names=(),
    sys_endpoint_names=(),
):
    ddr_names = set(ddr_endpoint_names)
    sys_names = set(sys_endpoint_names)
    print(
        f"[ClockPolicy:{label}] "
        f"sys={policy['sys_mhz']}MHz "
        f"noc={policy['noc_mhz']}MHz "
        f"rtl_endpoint={policy['rtl_endpoint_mhz']}MHz "
        f"ddr_endpoint={policy['ddr_endpoint_mhz']}MHz "
        f"ddr_memctrl={policy['ddr_memctrl_mhz']}MHz"
    )
    for tile_obj, conn_names in zip(tiles, node_conn_names):
        conn_clock_mhz = []
        for conn_name in conn_names:
            if conn_name in sys_names:
                conn_clock_mhz.append(policy["sys_mhz"])
            elif conn_name in ddr_names:
                conn_clock_mhz.append(policy["ddr_endpoint_mhz"])
            else:
                conn_clock_mhz.append(policy["rtl_endpoint_mhz"])
        tile_clock = getattr(getattr(tile_obj, "clk_domain", None), "clock", "unset")
        print(
            f"  tile={type(tile_obj).__name__} endpoints={conn_names} "
            f"clockDomains={conn_clock_mhz} clk_domain={tile_clock}"
        )


def create_topology(controllers):
    return NoC_Topology(controllers)
    # return Mesh_XY(controllers)  # For now, using Mesh_XY as default topology


def configure_topology_tracing(
    topology_helper,
    options,
    *,
    legacy_record_nps=0,
    legacy_record_nps_gap_cycles=200,
):
    record_nps = getattr(options, "nps_occ_trace", None)
    if record_nps is None:
        record_nps = legacy_record_nps

    record_nps_gap_cycles = getattr(options, "nps_occ_trace_gap_cycles", None)
    if record_nps_gap_cycles is None:
        record_nps_gap_cycles = legacy_record_nps_gap_cycles

    topology_helper.set_record_nps(int(record_nps))
    topology_helper.set_record_nps_gap_cycles(
        max(1, int(record_nps_gap_cycles))
    )


@dataclass
# ---------------------------------------------------------------------------
# Parsed topology model and endpoint construction helpers.
# ---------------------------------------------------------------------------

class EndpointInfo:
    """Info for a single NMU/NSU endpoint from the topology (NTS + NCR)."""

    logical_name: str  # e.g. "S00_AXIS_nmu"
    comp_type: str  # PL_NMU, PL_NSU, HBM_NMU, HBMMC, DDRC
    protocol: str  # AXI_MM, AXI_STRM
    role: str  # "Master" (NMU) or "Slave" (NSU)
    physical_name: str | None = None  # From NCR e.g. NOC_NMU512_X0Y0
    addresses: list = field(default_factory=list)  # (start, size) for NSU
    port_name: str | None = None  # For HBM/DDR: "PORT0", etc.
    controller_name: str | None = None
    controller_index: int | None = None
    pseudo_channel: int | None = None
    model_params: dict = field(default_factory=dict)

    @property
    def start_address(self):
        return self.addresses[0][0] if self.addresses else None

    @property
    def address_space(self):
        return self.addresses[0][1] if self.addresses else None


@dataclass
class HbmControllerInfo:
    logical_name: str
    controller_name: str
    controller_index: int
    stack_index: int
    channel_index: int
    ports: list = field(default_factory=list)
    addresses: list = field(default_factory=list)
    memory_params: dict = field(default_factory=dict)


@dataclass
class TopologyInfo:
    """
    Unified topology info from NTS and NCR files.
    Replaces the previous 10+ return values from get_address_map.
    """

    endpoints: dict = field(
        default_factory=dict
    )  # logical_name -> EndpointInfo
    address_name_map: list = field(
        default_factory=list
    )  # (start, end, name) sorted
    hbm_channels: dict = field(default_factory=dict)
    ddr_channels: dict = field(default_factory=dict)
    src_addr_options: dict = field(
        default_factory=dict
    )  # nmu_name -> [addr, size, ...]
    axis_nmu_to_dest_names: dict = field(default_factory=dict)
    logical_to_physical: dict = field(
        default_factory=dict
    )  # logical -> physical name
    physical_in_ncr: set = field(
        default_factory=set
    )  # physical names used in NCR Paths
    physical_to_logical: dict = field(
        default_factory=dict
    )  # physical -> logical (for connectLoc lookup)
    hbm_controllers: dict = field(
        default_factory=dict
    )  # controller_name -> HbmControllerInfo
    hbm_model: dict = field(default_factory=dict)
    source_address_routes: dict = field(
        default_factory=dict
    )  # src logical -> [(start, end, dest logical), ...]

    def has_physical_endpoint(self, physical_name: str) -> bool:
        """Check if physical name (e.g. NOC_NMU512_X0Y0) exists in topology. connectLoc must use physical names."""
        return (
            physical_name in self.physical_to_logical
            or physical_name in self.physical_in_ncr
        )

    def get_endpoint_by_physical(
        self, physical_name: str
    ) -> EndpointInfo | None:
        """Get EndpointInfo by physical name (e.g. NOC_NMU512_X0Y0). connectLoc must be physical."""
        logical = self.physical_to_logical.get(physical_name)
        if logical and logical in self.endpoints:
            return self.endpoints[logical]
        # Fallback: search endpoints by physical_name
        for ep in self.endpoints.values():
            if ep.physical_name == physical_name:
                return ep
        return None

    def get_hbm_endpoint(
        self, physical_name: str, controller_index: int, port_name: str
    ) -> EndpointInfo | None:
        for ep in self.endpoints.values():
            if (
                ep.comp_type == "HBMMC"
                and ep.physical_name == physical_name
                and ep.controller_index == controller_index
                and ep.port_name == port_name
            ):
                return ep
        return None

    @property
    def aximm_nsu(self) -> list:
        return [
            e.logical_name
            for e in self.endpoints.values()
            if e.comp_type == "PL_NSU" and e.protocol == "AXI_MM"
        ]

    @property
    def aximm_nmu(self) -> list:
        return [
            e.logical_name
            for e in self.endpoints.values()
            if e.comp_type == "PL_NMU" and e.protocol == "AXI_MM"
        ]

    @property
    def axis_nsu(self) -> list:
        return [
            e.logical_name
            for e in self.endpoints.values()
            if e.comp_type == "PL_NSU" and e.protocol == "AXI_STRM"
        ]

    @property
    def axis_nmu(self) -> list:
        return [
            e.logical_name
            for e in self.endpoints.values()
            if e.comp_type == "PL_NMU" and e.protocol == "AXI_STRM"
        ]

    @property
    def hbm_nsu(self) -> list:
        return [
            e.logical_name
            for e in self.endpoints.values()
            if e.comp_type == "HBMMC"
        ]

    @property
    def hbm_nmu(self) -> list:
        return [
            e.logical_name
            for e in self.endpoints.values()
            if e.comp_type == "HBM_NMU"
        ]

    @property
    def ddr_nsu(self) -> list:
        return [
            e.logical_name
            for e in self.endpoints.values()
            if e.comp_type == "DDRC"
        ]

    @property
    def endpoints_in_order(self) -> list:
        """All endpoints in standard order: aximm_nsu, hbm_nsu, ddr_nsu, axis_nsu, aximm_nmu, hbm_nmu, axis_nmu."""
        return (
            [self.endpoints[n] for n in self.aximm_nsu]
            + [self.endpoints[n] for n in self.hbm_nsu]
            + [self.endpoints[n] for n in self.ddr_nsu]
            + [self.endpoints[n] for n in self.axis_nsu]
            + [self.endpoints[n] for n in self.aximm_nmu]
            + [self.endpoints[n] for n in self.hbm_nmu]
            + [self.endpoints[n] for n in self.axis_nmu]
        )


HBM_CHANNELS_PER_STACK = 8


def _parse_hbm_controller_name(channel_name):
    match = re.search(r"hbm_st(\d+)/I_hbm_chnl(\d+)$", channel_name)
    if not match:
        return None
    stack_index = int(match.group(1))
    channel_index = int(match.group(2))
    controller_index = stack_index * HBM_CHANNELS_PER_STACK + channel_index
    return stack_index, channel_index, controller_index


def _normalize_hbm_ports_and_addresses(channel_name, ports, addresses):
    normalized_ports = list(ports or [])
    normalized_addrs = list(addresses or [])

    if not normalized_ports:
        normalized_ports = ["PORT0", "PORT1", "PORT2", "PORT3"]
    else:
        valid_ports = {"PORT0", "PORT1", "PORT2", "PORT3"}
        if any(port not in valid_ports for port in normalized_ports):
            m5.fatal(
                "HBM controller '%s' uses unsupported ports %s. Expected a subset of %s.",
                channel_name,
                normalized_ports,
                sorted(valid_ports),
            )
        if len(set(normalized_ports)) != len(normalized_ports):
            m5.fatal(
                "HBM controller '%s' repeats port names: %s.",
                channel_name,
                normalized_ports,
            )
        if len(normalized_ports) > 4:
            m5.fatal(
                "HBM controller '%s' exposes too many ports: %s.",
                channel_name,
                normalized_ports,
            )

    used_pseudo_channels = sorted(
        {int(port.replace("PORT", "")) // 2 for port in normalized_ports}
    )

    if len(normalized_addrs) == 1 and used_pseudo_channels == [0, 1]:
        m5.fatal(
            "HBM controller '%s' spans both pseudo channels via ports %s but only provides one address range.",
            channel_name,
            normalized_ports,
        )
    if len(normalized_addrs) not in (1, 2):
        m5.fatal(
            "HBM controller '%s' must expose 1 or 2 pseudo-channel address ranges; got %d.",
            channel_name,
            len(normalized_addrs),
        )

    return normalized_ports, normalized_addrs


def _default_hbm_model(hbm_settings=None):
    settings = dict(hbm_settings or {})
    arb_policy = str(settings.get("arb_policy", "round_robin")).lower()
    if arb_policy != "round_robin":
        m5.fatal(
            "Unsupported HBM arb_policy '%s'. Only 'round_robin' is currently implemented.",
            arb_policy,
        )
    page_policy = str(settings.get("page_policy", "open_page")).lower()
    if page_policy not in ("open_page", "closed_page"):
        m5.fatal(
            "Unsupported HBM page_policy '%s'. Expected 'open_page' or 'closed_page'.",
            page_policy,
        )
    return {
        "num_pc": int(settings.get("num_pc", 2)),
        "read_latency_cycles": int(settings.get("read_latency_cycles", 30)),
        "write_latency_cycles": int(settings.get("write_latency_cycles", 20)),
        "resp_latency_cycles": int(settings.get("resp_latency_cycles", 8)),
        "port_queue_depth": int(settings.get("port_queue_depth", 96)),
        "max_outstanding_reads": int(
            settings.get("max_outstanding_reads", 64)
        ),
        "max_outstanding_writes": int(
            settings.get("max_outstanding_writes", 32)
        ),
        "issue_interval_cycles": int(settings.get("issue_interval_cycles", 0)),
        "shared_bw_MBps": int(settings.get("shared_bw_MBps", 51200)),
        "nmu_bw_MBps": int(settings.get("nmu_bw_MBps", 12000)),
        "banks_per_pseudo_channel": int(
            settings.get("banks_per_pseudo_channel", 16)
        ),
        "row_hit_latency_cycles": int(
            settings.get("row_hit_latency_cycles", 4)
        ),
        "row_miss_latency_cycles": int(
            settings.get("row_miss_latency_cycles", 18)
        ),
        "bank_busy_cycles": int(settings.get("bank_busy_cycles", 12)),
        "cmd_bus_cycles": int(settings.get("cmd_bus_cycles", 2)),
        "page_policy": page_policy,
        "arb_policy": arb_policy,
    }


def build_hbm_settings_from_options(options, base_settings=None):
    settings = dict(base_settings or {})
    overrides = {
        "read_latency_cycles": getattr(
            options, "hbm_read_latency_cycles", None
        ),
        "write_latency_cycles": getattr(
            options, "hbm_write_latency_cycles", None
        ),
        "resp_latency_cycles": getattr(
            options, "hbm_resp_latency_cycles", None
        ),
        "port_queue_depth": getattr(options, "hbm_port_queue_depth", None),
        "max_outstanding_reads": getattr(
            options, "hbm_max_outstanding_reads", None
        ),
        "max_outstanding_writes": getattr(
            options, "hbm_max_outstanding_writes", None
        ),
        "issue_interval_cycles": getattr(
            options, "hbm_issue_interval_cycles", None
        ),
        "shared_bw_MBps": getattr(options, "hbm_shared_bw_mbps", None),
        "nmu_bw_MBps": getattr(options, "hbm_nmu_bw_mbps", None),
        "banks_per_pseudo_channel": getattr(
            options, "hbm_banks_per_pseudo_channel", None
        ),
        "row_hit_latency_cycles": getattr(
            options, "hbm_row_hit_latency_cycles", None
        ),
        "row_miss_latency_cycles": getattr(
            options, "hbm_row_miss_latency_cycles", None
        ),
        "bank_busy_cycles": getattr(options, "hbm_bank_busy_cycles", None),
        "cmd_bus_cycles": getattr(options, "hbm_cmd_bus_cycles", None),
        "page_policy": getattr(options, "hbm_page_policy", None),
    }
    for key, value in overrides.items():
        if value is not None:
            settings[key] = value
    return settings or None


def get_address_map(nts_filename, ncr_filename=None, hbm_settings=None):
    address_name_map = []
    aximm_nsu = []
    aximm_nmu = []
    axis_nsu = []
    axis_nmu = []
    hbm_nsu = []
    hbm_nmu = []
    hbm_channels = (
        {}
    )  # Dict: channel_name -> {"addresses": [(start, size), ...]}
    ddr_nsu = []
    ddr_channels = (
        {}
    )  # Dict: channel_name -> {"addresses": [...], "memory_params": {...}}
    src_addr_options = {}
    temp_name_addr_dict = {}

    # AXIS routing: map (nmu_name) -> [dest_nsu_name, dest_nsu_name, ...]
    # The index in the list is the local tdest value
    axis_nmu_to_dest_names = {}  # Will be converted to IDs later
    hbm_controllers = {}
    hbm_model = _default_hbm_model(hbm_settings)
    source_address_routes = {}

    with open(nts_filename) as file:
        data = json.load(file)

    # First pass: parse all LogicalInstances
    for instance in data.get("LogicalInstances", []):
        name = instance["Name"].split("/")[-1]
        comp_type = instance.get("CompType", "")
        protocol = instance.get("Protocol", "")

        # hbm nsu/mc
        if comp_type == "HBMMC":
            channel_name = "/".join(instance["Name"].split("/")[-2:])
            ports, addresses = _normalize_hbm_ports_and_addresses(
                channel_name,
                instance.get("Ports", []),
                instance.get("SysAddresses", []),
            )
            controller_info = _parse_hbm_controller_name(channel_name)
            if controller_info is None:
                m5.fatal(
                    "Could not derive HBM controller identity from logical name '%s'.",
                    channel_name,
                )
            stack_index, channel_index, controller_index = controller_info
            controller_name = f"hbm{controller_index}"

            # Store channel-level address info (for HBM controller creation)
            hbm_channels[channel_name] = {
                "addresses": [
                    (int(a["Base"], 16), int(a["Size"], 16)) for a in addresses
                ],
                "controller_name": controller_name,
                "controller_index": controller_index,
                "stack_index": stack_index,
                "channel_index": channel_index,
                "ports": list(ports),
                "model": dict(hbm_model),
            }
            hbm_controllers[controller_name] = HbmControllerInfo(
                logical_name=channel_name,
                controller_name=controller_name,
                controller_index=controller_index,
                stack_index=stack_index,
                channel_index=channel_index,
                ports=list(ports),
                addresses=[
                    (int(a["Base"], 16), int(a["Size"], 16)) for a in addresses
                ],
                memory_params=dict(instance.get("MemoryParams", {})),
            )

            # Map each port to its address based on port number:
            # PORT0, PORT1 -> addresses[0] (pseudo-channel 0)
            # PORT2, PORT3 -> addresses[1] (pseudo-channel 1)

            for port in ports:
                # Create a unique name for each port: e.g., "I_hbm_chnl0_PORT0"
                port_name = f"{channel_name}_{port}"
                hbm_nsu.append(port_name)

                # Extract port number from port name (e.g., "PORT2" -> 2)
                port_num = int(port.replace("PORT", ""))
                # Map port number to address index: PORT0,1 -> 0 and PORT2,3 -> 1
                addr_idx = port_num // 2
                num_addr = len(addresses) - 1

                addr_idx = addr_idx if addr_idx <= num_addr else num_addr

                addr_block = addresses[addr_idx]
                base_str = addr_block.get("Base", "0x0")
                size_str = addr_block.get("Size", "0x0")
                start_address = int(base_str, 16)
                size = int(size_str, 16)
                end_address = start_address + size

                print(
                    f"HBM {port_name}: start_address={hex(start_address)}, size={hex(size)} (pseudo-channel {addr_idx})"
                )
                address_name_map.append(
                    (start_address, end_address, port_name)
                )
                temp_name_addr_dict[port_name] = (start_address, size)

        # DDR Memory Controller
        elif comp_type == "DDRC":
            # DDR Memory Controller - create one entry per PORT
            channel_name = "/".join(instance["Name"].split("/")[-2:])
            ports = instance.get("Ports", [])
            addresses = instance.get("SysAddresses", [])
            memory_params = instance.get("MemoryParams", {})

            # Extract key DDR parameters from MemoryParams
            base_addr_str = memory_params.get(
                "MC_CHAN_REGION0_BASEADDR", "0x0"
            )
            range_str = memory_params.get(
                "MC_CHAN_REGION0_RANGE", "0x80000000"
            )
            controller_type = memory_params.get("CONTROLLERTYPE", "DDR4_SDRAM")
            speed_grade = memory_params.get(
                "MC_MEMORY_SPEEDGRADE", "DDR4-3200AC(24-24-24)"
            )
            data_width = int(memory_params.get("MC_DATAWIDTH", "64"))
            num_mc = int(memory_params.get("NUM_MC", "1"))

            # Parse address from MemoryParams (fallback to SysAddresses)
            if addresses:
                start_address = int(
                    addresses[0].get("Base", base_addr_str), 16
                )
                size = int(addresses[0].get("Size", range_str), 16)
            else:
                start_address = int(base_addr_str, 16)
                size = int(range_str, 16)

            # Store channel-level info for DDR controller creation
            ddr_channels[channel_name] = {
                "addresses": [(start_address, size)],
                "memory_params": {
                    "controller_type": controller_type,
                    "speed_grade": speed_grade,
                    "data_width": data_width,
                    "num_mc": num_mc,
                },
            }

            # Create entry for each port
            for port in ports:
                port_name = f"{channel_name}_{port}"
                ddr_nsu.append(port_name)
                end_address = start_address + size

                print(
                    f"DDR {port_name}: start_address={hex(start_address)}, size={hex(size)} (type={controller_type})"
                )
                address_name_map.append(
                    (start_address, end_address, port_name)
                )
                temp_name_addr_dict[port_name] = (start_address, size)

        elif comp_type == "HBM_NMU":
            hbm_nmu.append(name)
            src_addr_options[name] = []

        elif comp_type == "PL_NSU":
            if protocol == "AXI_STRM":
                # print(f"[AXIS PLACEHOLDER] Found AXIS NSU: {name} - TODO: implement axis slave tile")
                axis_nsu.append(name)
            elif protocol == "AXI_MM":
                aximm_nsu.append(name)
                for addr_block in instance.get("SysAddresses", []):
                    if "Base" not in addr_block or "Size" not in addr_block:
                        continue
                    base_str = addr_block["Base"]
                    size_str = addr_block["Size"]
                    start_address = int(base_str, 16)
                    size = int(size_str, 16)
                    end_address = start_address + size

                    address_name_map.append((start_address, end_address, name))
                    temp_name_addr_dict[name] = (start_address, size)

        elif comp_type == "PL_NMU":
            if protocol == "AXI_STRM":
                # print(f"[AXIS PLACEHOLDER] Found AXIS NMU: {name} - TODO: implement axis master tile")
                axis_nmu.append(name)
                # Initialize empty destination list for this AXIS NMU
                axis_nmu_to_dest_names[name] = []
            elif protocol == "AXI_MM":
                aximm_nmu.append(name)
                src_addr_options[name] = []

    # Second pass: parse paths to build src_addr_options and AXIS routing
    for path in data.get("Paths", []):
        src_name = path["From"].split("/")[-1]
        dst_full = path["To"]
        dst_short = dst_full.split("/")[-1]
        port = path.get("Port", "")
        comm_type = path.get("CommType", "")

        # Handle AXIS paths - build tdest mapping
        if comm_type == "STRM" or src_name in axis_nmu_to_dest_names:
            if src_name in axis_nmu_to_dest_names:
                # Add destination to this NMU's list (tdest = index in list)
                if dst_short not in axis_nmu_to_dest_names[src_name]:
                    axis_nmu_to_dest_names[src_name].append(dst_short)
                    print(
                        f"[AXIS Routing] {src_name} tdest={len(axis_nmu_to_dest_names[src_name])-1} -> {dst_short}"
                    )
        # Handle HBM paths - need to map to port-specific name
        elif "hbm_chnl" in dst_full:
            # The destination is an HBM channel, but we need the port-specific name
            dst_short = "/".join(dst_full.split("/")[-2:])
            port_name = f"{dst_short}_{port}"
            if port_name in temp_name_addr_dict:
                start_address, size = temp_name_addr_dict[port_name]
                if src_name in src_addr_options:
                    src_addr_options[src_name].append(start_address)
                    src_addr_options[src_name].append(size)
                route = (start_address, start_address + size, port_name)
                routes = source_address_routes.setdefault(src_name, [])
                if route not in routes:
                    routes.append(route)
        # Handle DDR paths - need to map to port-specific name
        elif "ddrc" in dst_full.lower() or "MC" in dst_short:
            # The destination is a DDR controller, need the port-specific name
            dst_short = "/".join(dst_full.split("/")[-2:])
            port_name = f"{dst_short}_{port}"
            if port_name in temp_name_addr_dict:
                start_address, size = temp_name_addr_dict[port_name]
                if src_name in src_addr_options:
                    src_addr_options[src_name].append(start_address)
                    src_addr_options[src_name].append(size)
        elif dst_short in temp_name_addr_dict:
            # Standard NSU
            start_address, size = temp_name_addr_dict[dst_short]
            if src_name in src_addr_options:
                src_addr_options[src_name].append(start_address)
                src_addr_options[src_name].append(size)
        else:
            pass

    address_name_map.sort(key=lambda item: item[0])

    # Build logical_to_physical and physical_in_ncr from NCR if provided
    logical_to_physical = {}
    physical_in_ncr = set()
    if ncr_filename and os.path.exists(ncr_filename):
        with open(ncr_filename) as ncr_file:
            ncr_data = json.load(ncr_file)
        for path in ncr_data.get("Paths", []):
            path_from = path.get("From", "")
            path_to = path.get("To", "")
            port = path.get("Port", "")
            nmu_short = path_from.split("/")[-1]
            dst_full = path_to
            if "hbm_chnl" in dst_full:
                nsu_short = "/".join(dst_full.split("/")[-2:]) + (
                    f"_{port}" if port else ""
                )
            elif "ddrc" in dst_full.lower() or "MC" in path_to.split("/")[-1]:
                nsu_short = "/".join(dst_full.split("/")[-2:]) + (
                    f"_{port}" if port else ""
                )
            else:
                nsu_short = dst_full.split("/")[-1]
            for net in path.get("Nets", []):
                phy_src = net.get("PhyInstanceStart", "")
                phy_dst = net.get("PhyInstanceEnd", "")
                comm_type = net.get("CommType", "")

                if phy_src:
                    physical_in_ncr.add(phy_src)
                if phy_dst:
                    physical_in_ncr.add(phy_dst)

                if comm_type in ("READ", "WRITE_RESP"):
                    # These AXI-MM response nets run slave -> master.
                    if phy_src:
                        logical_to_physical[nsu_short] = phy_src
                    if phy_dst:
                        logical_to_physical[nmu_short] = phy_dst
                else:
                    # WRITE, READ_REQ, and AXIS STRM/WRITE nets run master -> slave.
                    if phy_src:
                        logical_to_physical[nmu_short] = phy_src
                    if phy_dst:
                        logical_to_physical[nsu_short] = phy_dst

    # Build endpoints dict from parsed data
    endpoints = {}
    for name in aximm_nsu:
        addrs = (
            [(temp_name_addr_dict[name][0], temp_name_addr_dict[name][1])]
            if name in temp_name_addr_dict
            else []
        )
        endpoints[name] = EndpointInfo(
            logical_name=name,
            comp_type="PL_NSU",
            protocol="AXI_MM",
            role="Slave",
            physical_name=logical_to_physical.get(name),
            addresses=addrs,
        )
    for name in aximm_nmu:
        endpoints[name] = EndpointInfo(
            logical_name=name,
            comp_type="PL_NMU",
            protocol="AXI_MM",
            role="Master",
            physical_name=logical_to_physical.get(name),
        )
    for name in axis_nsu:
        endpoints[name] = EndpointInfo(
            logical_name=name,
            comp_type="PL_NSU",
            protocol="AXI_STRM",
            role="Slave",
            physical_name=logical_to_physical.get(name),
        )
    for name in axis_nmu:
        endpoints[name] = EndpointInfo(
            logical_name=name,
            comp_type="PL_NMU",
            protocol="AXI_STRM",
            role="Master",
            physical_name=logical_to_physical.get(name),
        )
    for name in hbm_nsu:
        addrs = (
            [(temp_name_addr_dict[name][0], temp_name_addr_dict[name][1])]
            if name in temp_name_addr_dict
            else []
        )
        channel_name, port_name = name.rsplit("_", 1)
        controller_data = None
        for info in hbm_controllers.values():
            if info.logical_name == channel_name:
                controller_data = info
                break
        port_num = int(port_name.replace("PORT", ""))
        endpoints[name] = EndpointInfo(
            logical_name=name,
            comp_type="HBMMC",
            protocol="AXI_MM",
            role="Slave",
            physical_name=logical_to_physical.get(name),
            addresses=addrs,
            port_name=port_name,
            controller_name=(
                controller_data.controller_name if controller_data else None
            ),
            controller_index=(
                controller_data.controller_index if controller_data else None
            ),
            pseudo_channel=port_num // 2,
            model_params=dict(hbm_model),
        )
    for name in hbm_nmu:
        endpoints[name] = EndpointInfo(
            logical_name=name,
            comp_type="HBM_NMU",
            protocol="AXI_MM",
            role="Master",
            physical_name=logical_to_physical.get(name),
        )
    for name in ddr_nsu:
        addrs = (
            [(temp_name_addr_dict[name][0], temp_name_addr_dict[name][1])]
            if name in temp_name_addr_dict
            else []
        )
        endpoints[name] = EndpointInfo(
            logical_name=name,
            comp_type="DDRC",
            protocol="AXI_MM",
            role="Slave",
            physical_name=logical_to_physical.get(name),
            addresses=addrs,
        )

    physical_to_logical = {v: k for k, v in logical_to_physical.items()}
    return TopologyInfo(
        endpoints=endpoints,
        address_name_map=address_name_map,
        hbm_channels=hbm_channels,
        ddr_channels=ddr_channels,
        src_addr_options=src_addr_options,
        axis_nmu_to_dest_names=axis_nmu_to_dest_names,
        logical_to_physical=logical_to_physical,
        physical_in_ncr=physical_in_ncr,
        physical_to_logical=physical_to_logical,
        hbm_controllers=hbm_controllers,
        hbm_model=hbm_model,
        source_address_routes=source_address_routes,
    )


def lookup_component_by_address(address_name_map, address):
    for start_address, end_address, nameOrID in address_name_map:
        if start_address <= address < end_address:
            return nameOrID
    return None


def address_to_id(address_map, nameToID):
    """Translate (start, end, logical_name) tuples to NI controller ids.

    Rows whose logical name has no instantiated NocInterface (subset topologies:
    filtered ``*.conn.json`` leaving some HBM ports unused) are dropped. Same
    contract as ``noc_setup_config.py`` filtering before calling this helper.
    """
    rows = []
    dropped = 0
    for start, end, name in address_map:
        nid = nameToID.get(name)
        if nid is None:
            dropped += 1
            continue
        rows.append((start, end, nid))
    if dropped:
        warn(
            "address_to_id: omitted %d address map row(s) with no instantiated "
            "endpoint (subset topology)." % dropped
        )
    return rows


def source_address_to_id(source_address_routes, nameToID):
    route_id_map = []
    for src_name, routes in source_address_routes.items():
        if src_name not in nameToID:
            continue
        src_id = nameToID[src_name]
        for start, end, dest_name in routes:
            if dest_name not in nameToID:
                continue
            route_id_map.append((src_id, start, end, nameToID[dest_name]))
    return route_id_map


def get_hbm_endpoint_kwargs(ep, topology):
    model = topology.hbm_model
    return {
        "sim_cycles": getattr(ep, "sim_cycles", None) or 0,
        "requestorId": 0,
        "hbm_controller_id": (
            ep.controller_index if ep.controller_index is not None else 0
        ),
        "hbm_port_id": (
            int(ep.port_name.replace("PORT", "")) if ep.port_name else 0
        ),
        "hbm_pseudo_channel_id": (
            ep.pseudo_channel if ep.pseudo_channel is not None else 0
        ),
        "hbm_pseudo_channel_base_addr": (
            ep.start_address if ep.start_address is not None else 0
        ),
        "hbm_pseudo_channel_size": (
            ep.address_space if ep.address_space is not None else 0
        ),
        "read_latency_cycles": model["read_latency_cycles"],
        "write_latency_cycles": model["write_latency_cycles"],
        "resp_latency_cycles": model["resp_latency_cycles"],
        "port_queue_depth": model["port_queue_depth"],
        "max_outstanding_reads": model["max_outstanding_reads"],
        "max_outstanding_writes": model["max_outstanding_writes"],
        "issue_interval_cycles": model["issue_interval_cycles"],
        "shared_bw_MBps": model["shared_bw_MBps"],
        "nmu_bw_MBps": model["nmu_bw_MBps"],
        "banks_per_pseudo_channel": model["banks_per_pseudo_channel"],
        "row_hit_latency_cycles": model["row_hit_latency_cycles"],
        "row_miss_latency_cycles": model["row_miss_latency_cycles"],
        "bank_busy_cycles": model["bank_busy_cycles"],
        "cmd_bus_cycles": model["cmd_bus_cycles"],
        "page_policy": model["page_policy"],
    }


def _get_aximm_master_kwargs(ep, options, topology):
    addr_info = topology.src_addr_options.get(ep.logical_name, [])
    if len(addr_info) < 2 or len(addr_info) % 2 != 0:
        m5.fatal(
            "AXI-MM master endpoint %s has invalid address space info %s.",
            ep.logical_name,
            addr_info,
        )

    beat_size_bytes = 2**options.write_size
    transaction_size = beat_size_bytes * (options.write_length + 1)
    nsu_min_addrs = addr_info[::2]
    nsu_address_spaces = addr_info[1::2]
    base_addr = min(nsu_min_addrs)
    max_addr = max(
        start + size for start, size in zip(nsu_min_addrs, nsu_address_spaces)
    )

    direction = getattr(options, "direction", "INTERLEAVED")

    if direction == "WRITE_ONLY":
        read_write_mode = "WRITE_ONLY"
        max_write_commands = options.num_packets
    elif options.do_reads and options.do_writes:
        read_write_mode = (
            "INTERLEAVED" if options.interleaved else "SEQUENTIAL"
        )
        max_write_commands = options.num_packets
    elif options.do_reads:
        read_write_mode = "READ_ONLY"
        max_write_commands = 0
    else:
        read_write_mode = "WRITE_ONLY"
        max_write_commands = options.num_packets

    return {
        "addr_width": 64,
        "data_width": beat_size_bytes * 8,
        "id_width": 16,
        "base_addr": base_addr,
        "max_addr": max_addr,
        "nsu_min_addrs": nsu_min_addrs,
        "nsu_address_spaces": nsu_address_spaces,
        "min_transaction_size_bytes": transaction_size,
        "max_transaction_size_bytes": transaction_size,
        "min_gap_cycles": 0,
        "max_gap_cycles": 0,
        "read_write_mode": read_write_mode,
        "max_write_commands": max_write_commands,
        "max_write_bandwidth_mbps": float(options.bandwidth),
        "max_read_bandwidth_mbps": float(options.bandwidth),
        "clock_period_ns": float(options.clk_period) / 1000.0,
        "max_outstanding_writes": max(
            1, int(options.aximm_max_outstanding_writes)
        ),
        "beat_size_bytes": beat_size_bytes,
        "address_distribution": "INCREMENT",
        "address_increment": transaction_size,
        # Keep AXI-MM traffic aligned during current testing. The NMU-side
        # 256B packetizer is still fragile for some unaligned 64B bursts.
        "align_addresses": True,
    }


def _get_endpoint_kwargs(ep, options, topology, hbm_idx, ddr_idx):
    """Return kwargs needed to construct a node for this endpoint type. Errors if endpoint type is unsupported."""
    numAxisPackets = 100
    data_width = getattr(options, "data_width", 512)
    if ep.comp_type == "PL_NSU" and ep.protocol == "AXI_MM":
        return {"sim_cycles": options.sim_cycles}
    if ep.comp_type == "HBMMC":
        idx = hbm_idx[0]
        hbm_idx[0] += 1
        kwargs = get_hbm_endpoint_kwargs(ep, topology)
        kwargs["sim_cycles"] = options.sim_cycles
        kwargs["requestorId"] = idx
        return kwargs
    if ep.comp_type == "DDRC":
        idx = ddr_idx[0]
        ddr_idx[0] += 1
        return {
            "sim_cycles": options.sim_cycles,
            "requestorId": hbm_idx[0] + idx,
        }
    if ep.comp_type == "PL_NSU" and ep.protocol == "AXI_STRM":
        return {
            "sim_cycles": options.sim_cycles,
            "ready_percent": 100,
            "expected_packets": numAxisPackets - 1,
            "print_data": False,
            "data_width": data_width,
            "id_width": 16,
            "dest_width": 12,
        }
    if ep.comp_type == "PL_NMU" and ep.protocol == "AXI_MM":
        return _get_aximm_master_kwargs(ep, options, topology)
    if ep.comp_type == "HBM_NMU":
        return _get_aximm_master_kwargs(ep, options, topology)
    if ep.comp_type == "PL_NMU" and ep.protocol == "AXI_STRM":
        return {
            "max_gap_cycles": 0,
            "data_width": 512,
            "max_tid": 0,
            "max_tdest": 0,
            "max_packets": numAxisPackets,
        }
    m5.fatal(
        "Unsupported endpoint type: %s protocol %s for %s. "
        "No known constructor kwargs for this endpoint.",
        ep.comp_type,
        ep.protocol,
        ep.logical_name,
    )


def axis_tdest_name_to_id(axis_nmu_to_dest_names, nameToID):
    """
    Convert AXIS tdest name mapping to ID mapping.

    Input: {nmu_name: [dest_nsu_name_0, dest_nsu_name_1, ...]}
    Output: {nmu_id: {tdest_0: dest_ni_0, tdest_1: dest_ni_1, ...}}

    Where tdest is the local index (0, 1, 2...) and dest_ni is the global node ID.
    """
    axis_tdest_map = {}
    for nmu_name, dest_list in axis_nmu_to_dest_names.items():
        if nmu_name not in nameToID:
            print(f"Warning: AXIS NMU {nmu_name} not found in nameToID")
            continue
        nmu_id = nameToID[nmu_name]
        axis_tdest_map[nmu_id] = {}
        for tdest, dest_name in enumerate(dest_list):
            if dest_name not in nameToID:
                print(f"Warning: AXIS dest {dest_name} not found in nameToID")
                continue
            dest_ni = nameToID[dest_name]
            axis_tdest_map[nmu_id][tdest] = dest_ni
            print(
                f"[AXIS ID Map] NMU {nmu_id} tdest={tdest} -> dest_ni={dest_ni}"
            )
    return axis_tdest_map


# ---------------------------------------------------------------------------
# Optional NocProbe parsing and wiring.
# ---------------------------------------------------------------------------

def _noc_if_snooper_hook_ids() -> frozenset[str]:
    """Hook IDs allowed when probe_mode=snooper (NocInterface beat snapshots only)."""
    return frozenset({"noc_if.state.node_side", "noc_if.state.noc_side"})


def print_noc_interface_snooper_help() -> None:
    """Print snooper hooks with grouped field IDs (see --print-noc-probe-help)."""
    ids = sorted(_noc_probe_supported_snooper_field_ids())
    common = [x for x in ids if x in ("state.debug_id", "cdc.enqueue_ready")]
    axis_f = sorted(x for x in ids if x.startswith("axis."))
    aximm_f = sorted(x for x in ids if x.startswith("aximm."))

    def subbullets(title, fields):
        print(f"      – {title}")
        for f in fields:
            print(f"          • {f}")

    print("\n=== Supported NocProbe snooper field IDs with hooks ===")
    print("  currently, connectLoc must target nocinterface<N> (NocInterface).")
    print("  hook_id must be exactly noc_if.state.node_side or noc_if.state.noc_side.")
    print("\n  • noc_if.state.node_side — node-facing beat snapshot")
    subbullets("Common / CDC handshake:", common)
    subbullets("AXIS nocinterface (use when interface protocol is AXIS):", axis_f)
    subbullets("AXIMM nocinterface (use when interface protocol is AXIMM):", aximm_f)
    print("\n  • noc_if.state.noc_side — NoC-facing beat snapshot snapshot")
    print(
        "      – Same snoop_fields ids as node_side; interpretation follows the beat "
        "direction of that hook."
    )
    print(
        "\n  Comparator mode still supports other hook ids (flit, msg, State on "
        "noc_if.state.* / cdc / net, etc.); snooper mode is NocInterface-only."
    )


def _noc_probe_supported_snooper_field_ids() -> set[str]:
    """
    Supported snooper field IDs (NocInterface hooks only). Must match
    `snooperFieldRegistry()` in `src/noc/debug/NocProbe.cc`.
    """
    return {
        "state.debug_id",
        "axis.tvalid",
        "axis.tready",
        "axis.ni_tready",
        "axis.cdc_enqueue_ready",
        "cdc.enqueue_ready",
        "axis.tlast",
        "axis.tid",
        "axis.tdest",
        "axis.tkeep",
        "axis.tuser",
        "axis.nbytes_valid",
        "axis.tdata[0:15]",
        "aximm.ar.addr",
        "aximm.ar.len",
        "aximm.ar.size",
        "aximm.ar.burst",
        "aximm.ar.id",
        "aximm.ar.valid",
        "aximm.ar.ready",
        "aximm.aw.addr",
        "aximm.aw.len",
        "aximm.aw.size",
        "aximm.aw.burst",
        "aximm.aw.id",
        "aximm.aw.valid",
        "aximm.aw.ready",
        "aximm.w.last",
        "aximm.w.strb",
        "aximm.w.valid",
        "aximm.w.ready",
        "aximm.r.ready",
        "aximm.r.valid",
        "aximm.b.ready",
        "aximm.b.valid",
        "aximm.b.resp",
        "aximm.beat_bytes",
        "aximm.total_bytes",
    }


def _noc_probe_parse_snooper_fields(hp, probe_idx: int, hp_field_name: str) -> list[str]:
    raw = hp.get("fields", [])
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        out = []
        for j, v in enumerate(raw):
            if not isinstance(v, str):
                m5.fatal(
                    "noc_probes[%d]: %s.fields[%d] must be a string, got %r"
                    % (probe_idx, hp_field_name, j, v)
                )
            s = v.strip()
            if s:
                out.append(s)
        return out
    m5.fatal(
        "noc_probes[%d]: %s.fields must be a string or list of strings, got %r"
        % (probe_idx, hp_field_name, raw)
    )


def _noc_probe_parse_snooper_print_cycles(hp, probe_idx: int, hp_field_name: str) -> int:
    raw = hp.get("print_cycles", 0)
    if raw is None:
        return 0
    try:
        v = int(raw)
    except Exception:
        m5.fatal(
            "noc_probes[%d]: %s.print_cycles must be an int, got %r"
            % (probe_idx, hp_field_name, raw)
        )
    if v < 0:
        m5.fatal(
            "noc_probes[%d]: %s.print_cycles must be >= 0, got %d"
            % (probe_idx, hp_field_name, v)
        )
    return v


def _noc_probe_hook_id_syntax_message(hook_id: str):
    """
    Return None if hook_id is structurally valid, else a short error sentence.

    This does not enforce the full set of hook ids implemented in C++
    (see --print-noc-probe-help); it only rejects obvious typos such as a
    trailing '.' or empty segments ('noc_if.state.', 'a..b').
    """
    s = hook_id.strip()
    if not s:
        return "hook_id is empty"
    if s.endswith("."):
        return (
            "hook_id must not end with '.' "
            "(for NocInterface beat taps use e.g. noc_if.state.node_side or "
            "noc_if.state.noc_side)"
        )
    parts = s.split(".")
    if any(not p for p in parts):
        return "hook_id has an empty path segment (check stray '..'/trailing dots)"
    return None


def _noc_probe_parse_hook_point(hp, field_name):
    """Return (connectLoc, hook_id) from a hook_point_* object."""
    if not isinstance(hp, dict):
        m5.fatal("noc_probes: %s must be a JSON object." % field_name)
    loc = hp.get("connectLoc")
    hid = hp.get("hook_id")
    if loc is None or str(loc).strip() == "":
        m5.fatal("noc_probes: %s.connectLoc is required." % field_name)
    if hid is None or str(hid).strip() == "":
        m5.fatal("noc_probes: %s.hook_id is required." % field_name)
    hid_s = str(hid).strip()
    syn = _noc_probe_hook_id_syntax_message(hid_s)
    if syn:
        m5.fatal("noc_probes: %s %s (got hook_id=%r)" % (field_name, syn, hid_s))
    return str(loc).strip(), hid_s


def _resolve_probe_index_or_id(objects, n, id_attr, connect_loc, kind_label):
    """
    Pick objects[n] or the unique element whose id_attr == n.

    Path printing (noc_config.print_noc_paths) labels nocinterface/router/netif/
    intlink/extlink using each object's id field (e.g. link_id, router_id), not
    the object's position in the network's Python list. connectLoc must follow
    the same rule so 'intlink1' matches a link with link_id=1 even when it is
    int_links[0] in construction order.
    """
    matches = [
        o
        for o in objects
        if getattr(o, id_attr, None) is not None and int(getattr(o, id_attr)) == n
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        m5.fatal(
            "noc_probes: %r: %s %s=%d is ambiguous (%d matches)"
            % (connect_loc, kind_label, id_attr, n, len(matches))
        )
    if n < len(objects):
        return objects[n]
    avail = sorted(
        int(getattr(o, id_attr))
        for o in objects
        if getattr(o, id_attr, None) is not None
    )
    extra = ""
    if avail:
        extra = "; objects with %s: %s" % (id_attr, avail)
    m5.fatal(
        "noc_probes: %r: %s index %d out of range (len=%d)%s"
        % (connect_loc, kind_label, n, len(objects), extra)
    )


def resolve_noc_probe_connect_loc(system, connect_loc):
    """
    Map short names from node_config JSON to SimObjects that expose noc_probe:

    - nocinterface<N> -> tile controller with id N, else tile_controllers[N]
    - router<N> -> router with router_id N, else routers[N]
    - netif<N> -> NI with id N, else netifs[N]
    - intlink<N> -> internal link with link_id N, else int_links[N].network_link
    - extlink<N> -> external link with link_id N, else ext_links[N].network_links
    """
    s = str(connect_loc).strip()
    noc = getattr(system, "noc", None)
    if noc is None:
        m5.fatal("resolve_noc_probe_connect_loc: system has no .noc")
    net = getattr(noc, "network", None)
    if net is None:
        m5.fatal("resolve_noc_probe_connect_loc: system.noc has no .network")

    m = re.match(r"(?i)^nocinterface(\d+)$", s)
    if m:
        n = int(m.group(1))
        ctrls = list(getattr(noc, "tile_controllers", []) or [])
        return _resolve_probe_index_or_id(ctrls, n, "id", connect_loc, "tile_controllers")

    m = re.match(r"(?i)^router(\d+)$", s)
    if m:
        n = int(m.group(1))
        rts = list(getattr(net, "routers", []) or [])
        return _resolve_probe_index_or_id(rts, n, "router_id", connect_loc, "routers")

    m = re.match(r"(?i)^netif(\d+)$", s)
    if m:
        n = int(m.group(1))
        nis = list(getattr(net, "netifs", []) or [])
        return _resolve_probe_index_or_id(nis, n, "id", connect_loc, "netifs")

    m = re.match(r"(?i)^intlink(\d+)$", s)
    if m:
        n = int(m.group(1))
        ils = list(getattr(net, "int_links", []) or [])
        il = _resolve_probe_index_or_id(ils, n, "link_id", connect_loc, "int_links")
        link_obj = getattr(il, "network_link", None)
        if link_obj is None:
            m5.fatal(
                "noc_probes: %r resolved to int_links object but no network_link found."
                % (connect_loc,)
            )
        return link_obj

    m = re.match(r"(?i)^extlink(\d+)$", s)
    if m:
        n = int(m.group(1))
        els = list(getattr(net, "ext_links", []) or [])
        el = _resolve_probe_index_or_id(els, n, "link_id", connect_loc, "ext_links")
        links = list(getattr(el, "network_links", []) or [])
        if not links:
            m5.fatal(
                "noc_probes: %r resolved to ext_links but no network_links found."
                % (connect_loc,)
            )
        return links

    m5.fatal(
        "noc_probes: unknown connectLoc %r. Use nocinterface<N>, router<N>, "
        "netif<N>, intlink<N>, or extlink<N>."
        % (connect_loc,)
    )


def _assign_noc_probe_to_target(probe_idx, probe, target_obj, prev_owner_desc):
    """Assign probe to target_obj.noc_probe if unset or same probe."""
    if isinstance(target_obj, (list, tuple)):
        for idx, obj in enumerate(target_obj):
            _assign_noc_probe_to_target(
                probe_idx, probe, obj, f"{prev_owner_desc}[{idx}]"
            )
        return

    prev = getattr(target_obj, "noc_probe", None)
    if prev is not None and prev != NULL and prev != probe:
        m5.fatal(
            "noc_probes[%d]: cannot attach probe %s to %s: already has noc_probe "
            "(from %s)."
            % (probe_idx, probe.path(), target_obj.path(), prev_owner_desc)
        )
    target_obj.noc_probe = probe


def _noc_probe_bool_01(spec, idx, field_name, default):
    """Parse a bool param; JSON may use 0/1 as int or string."""
    raw = spec.get(field_name, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        if raw in (0, 1):
            return bool(raw)
        m5.fatal(
            "noc_probes[%d]: %s must be 0 or 1, got %r"
            % (idx, field_name, raw)
        )
    if isinstance(raw, str):
        s = raw.strip()
        if s == "1":
            return True
        if s == "0":
            return False
        m5.fatal(
            "noc_probes[%d]: %s string must be \"0\" or \"1\", got %r"
            % (idx, field_name, raw)
        )
    m5.fatal(
        "noc_probes[%d]: %s must be bool or 0/1, got %r"
        % (idx, field_name, raw)
    )


def _noc_probe_parse_enabled(spec, idx):
    """Default: enabled (1)."""
    return _noc_probe_bool_01(spec, idx, "enabled", 1)


def instantiate_and_wire_noc_probes(noc_probes, system, noc):
    """
    For each entry in node_config JSON ``noc_probes``, create one NocProbe and
    set ``noc_probe`` on each hook_point target (same probe may attach to multiple
    objects, e.g. two NocInterfaces for a snooper).

    Expected shape per item::

        probe_mode, hook_point_0: { connectLoc, hook_id }, optional hook_point_1,
        optional enabled (0 or 1), optional path_match_trace (0 or 1), ...
    """
    if not noc_probes:
        return

    for i, spec in enumerate(noc_probes):
        if not isinstance(spec, dict):
            m5.fatal("noc_probes[%d]: must be a JSON object." % i)

        probe_id = str(spec.get("probe_id", "") or "").strip()
        mode = spec.get("probe_mode", "snooper")
        comp_op = spec.get("comparator_op", "latency")

        if "hook_point_0" not in spec:
            m5.fatal("noc_probes[%d]: hook_point_0 is required." % i)
        loc0, hid0 = _noc_probe_parse_hook_point(spec["hook_point_0"], "hook_point_0")
        hp0 = spec["hook_point_0"]

        hid1 = ""
        loc1 = None
        hp1 = spec.get("hook_point_1")
        if hp1 is not None:
            loc1, hid1 = _noc_probe_parse_hook_point(hp1, "hook_point_1")

        if mode == "comparator" and not hid1:
            m5.fatal(
                "noc_probes[%d]: probe_mode comparator requires hook_point_1." % i
            )

        probe_enabled = _noc_probe_parse_enabled(spec, i)
        path_match_trace = _noc_probe_bool_01(spec, i, "path_match_trace", 0)

        # Disabled probes should not be wired at all. This avoids disabled entries
        # "claiming" target_obj.noc_probe and blocking enabled probes later.
        if not probe_enabled:
            continue

        snoop_fields = []
        snoop_print_cycles = 0
        if mode == "snooper":
            ni_hooks = _noc_if_snooper_hook_ids()
            if hid0 not in ni_hooks:
                m5.fatal(
                    "noc_probes[%d]: probe_mode=snooper requires hook_point_0.hook_id "
                    "to be one of %s (got %r)."
                    % (i, sorted(ni_hooks), hid0)
                )
            if hid1 and hid1 not in ni_hooks:
                m5.fatal(
                    "noc_probes[%d]: probe_mode=snooper requires hook_point_1.hook_id "
                    "to be one of %s (got %r)."
                    % (i, sorted(ni_hooks), hid1)
                )
            snoop_fields = _noc_probe_parse_snooper_fields(hp0, i, "hook_point_0")
            snoop_print_cycles = _noc_probe_parse_snooper_print_cycles(hp0, i, "hook_point_0")
            supported = _noc_probe_supported_snooper_field_ids()
            bad = [f for f in snoop_fields if f not in supported]
            if bad:
                m5.fatal(
                    "noc_probes[%d]: hook_point_0.fields contains unsupported field id(s): %s. "
                    "Run --print-noc-probe-help to see supported ids."
                    % (i, ", ".join(repr(x) for x in bad))
                )

        probe = NocProbe(
            noc_system=noc,
            probe_id=probe_id,
            probe_mode=mode,
            comparator_op=comp_op,
            hook_id_0=hid0,
            hook_id_1=hid1,
            enabled=probe_enabled,
            path_match_trace=path_match_trace,
            snoop_fields=snoop_fields,
            snoop_print_cycles=snoop_print_cycles,
        )

        t0 = resolve_noc_probe_connect_loc(system, loc0)
        _assign_noc_probe_to_target(i, probe, t0, "hook_point_0")

        if loc1 is not None:
            t1 = resolve_noc_probe_connect_loc(system, loc1)
            _assign_noc_probe_to_target(i, probe, t1, "hook_point_1")


def validate_noc_probes(noc_probes, system, noc):
    """
    Best-effort, non-fatal validator for node_config JSON `noc_probes`.

    Note: helpers such as _noc_probe_parse_hook_point use m5.fatal() (sys.exit),
    so paths that would fatal must be checked here first (e.g. hook_id syntax).

    Returns:
        (ok: bool, errors: list[str])
    """
    errors = []
    if noc_probes is None:
        return True, errors
    if not isinstance(noc_probes, list):
        return False, [f"'noc_probes' must be a list when present (got {type(noc_probes).__name__})."]
    if not noc_probes:
        return True, errors

    for i, spec in enumerate(noc_probes):
        try:
            if not isinstance(spec, dict):
                raise ValueError("must be a JSON object")

            mode = spec.get("probe_mode", "snooper")
            if "hook_point_0" not in spec:
                raise ValueError("hook_point_0 is required")

            # Hook id structural checks must run before _noc_probe_parse_hook_point:
            # that helper calls m5.fatal() -> sys.exit on invalid syntax, which this
            # validator cannot catch (see comment on validate_noc_probes).
            hook_id_syntax_errors = []
            for hp_key in ("hook_point_0", "hook_point_1"):
                if hp_key not in spec:
                    continue
                hp = spec[hp_key]
                if not isinstance(hp, dict) or hp.get("hook_id") is None:
                    continue
                hs = str(hp.get("hook_id")).strip()
                syn = _noc_probe_hook_id_syntax_message(hs)
                if syn:
                    hook_id_syntax_errors.append(
                        "noc_probes[%d]: %s %s (got hook_id=%r)"
                        % (i, hp_key, syn, hs)
                    )
            errors.extend(hook_id_syntax_errors)
            if hook_id_syntax_errors:
                continue

            loc0, hid0 = _noc_probe_parse_hook_point(spec["hook_point_0"], "hook_point_0")
            hp0 = spec["hook_point_0"]

            hid1 = ""
            loc1 = None
            hp1 = spec.get("hook_point_1")
            if hp1 is not None:
                loc1, hid1 = _noc_probe_parse_hook_point(hp1, "hook_point_1")

            if mode == "comparator" and not hid1:
                raise ValueError("probe_mode comparator requires hook_point_1")

            if mode == "snooper":
                ni_hooks = _noc_if_snooper_hook_ids()
                if hid0 not in ni_hooks:
                    errors.append(
                        "noc_probes[%d]: probe_mode=snooper requires hook_point_0.hook_id "
                        "to be one of %s (got %r)"
                        % (i, sorted(ni_hooks), hid0)
                    )
                if hid1 and hid1 not in ni_hooks:
                    errors.append(
                        "noc_probes[%d]: probe_mode=snooper requires hook_point_1.hook_id "
                        "to be one of %s (got %r)"
                        % (i, sorted(ni_hooks), hid1)
                    )

            # Validate bool-ish fields.
            _noc_probe_parse_enabled(spec, i)
            _noc_probe_bool_01(spec, i, "path_match_trace", 0)

            # Validate connectLoc resolution (index bounds, link presence, etc.).
            resolve_noc_probe_connect_loc(system, loc0)
            if loc1 is not None:
                resolve_noc_probe_connect_loc(system, loc1)

            # Snooper-only: validate fields without aborting print-noc-probe-help.
            if mode == "snooper":
                snoop_fields = _noc_probe_parse_snooper_fields(hp0, i, "hook_point_0")
                _noc_probe_parse_snooper_print_cycles(hp0, i, "hook_point_0")
                supported = _noc_probe_supported_snooper_field_ids()
                for f in snoop_fields:
                    if f not in supported:
                        errors.append(
                            "noc_probes[%d]: hook_point_0.fields contains unsupported field id %r; "
                            "run --print-noc-probe-help to see supported ids"
                            % (i, f)
                        )
        except BaseException as e:
            # m5.fatal raises SystemExit; treat it as a validation error.
            msg = str(e).strip() or repr(e)
            errors.append(f"noc_probes[{i}]: {msg}")

    return len(errors) == 0, errors
