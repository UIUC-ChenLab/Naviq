import os

from m5.objects import (
    PacketProcessingEngine2xChecksumRtlNode,
    PacketProcessingEngine2xNatRtlNode,
    PacketProcessingEngine2xNoneRtlNode,
    PacketProcessingEngine2xSegmentationRtlNode,
    PacketProcessingEngine2xTelemetryRtlNode,
)

import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, make_stream_rtl_node, run_axis_test


TOPOLOGY = "src/noc/topology/topologies/smartnic_tests/axis_module_2x_smoke"
OFFLOAD = os.environ.get("PPE_OFFLOAD", "none").lower()

OFFLOAD_CLASSES = {
    "none": PacketProcessingEngine2xNoneRtlNode,
    "telemetry": PacketProcessingEngine2xTelemetryRtlNode,
    "segmentation": PacketProcessingEngine2xSegmentationRtlNode,
    "checksum": PacketProcessingEngine2xChecksumRtlNode,
    "nat": PacketProcessingEngine2xNatRtlNode,
}

ppe_node = None


def selected_class():
    if OFFLOAD not in OFFLOAD_CLASSES:
        raise RuntimeError(f"Unsupported PPE_OFFLOAD={OFFLOAD}")
    return OFFLOAD_CLASSES[OFFLOAD]


def get_ppe_node(options):
    global ppe_node
    if ppe_node is None:
        reset_cycles = 2500 if OFFLOAD == "nat" else 16
        ppe_node = make_stream_rtl_node(
            selected_class(),
            options,
            expected_packets=max(options.num_packets, 1) * 2,
            reset_cycles=reset_cycles,
        )
    return ppe_node


def make_checker(options, seed):
    if OFFLOAD == "nat":
        return make_packet_checker(
            options,
            check_mode="nat_outbound",
            packet_count=max(options.num_packets, 1),
            min_payload_bytes=16,
            max_payload_bytes=16,
            validate_ipv4_checksum=False,
            validate_l4_checksum=False,
        )
    return make_packet_checker(
        options,
        check_mode="ipv4",
        check_seed=seed,
        min_payload_bytes=16,
        max_payload_bytes=16,
    )


def make_source(options, seed):
    if OFFLOAD == "nat":
        return make_packet_source(
            options,
            profile="ipv4_tcp",
            check_seed=seed,
            min_payload_bytes=16,
            max_payload_bytes=16,
            min_gap_cycles=4096,
            max_gap_cycles=4096,
            initial_gap_cycles=2600,
        )
    return make_packet_source(
        options,
        check_seed=seed,
        min_payload_bytes=16,
        max_payload_bytes=16,
        initial_gap_cycles=64,
    )


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        return make_checker(options, 1)
    if tile_name == "M01_AXIS_nsu":
        return make_checker(options, 2)
    if tile_name in ("M02_AXIS_nsu", "M03_AXIS_nsu"):
        return get_ppe_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        return make_source(options, 1)
    if tile_name == "S01_AXIS_nmu":
        return make_source(options, 2)
    if tile_name in ("S02_AXIS_nmu", "S03_AXIS_nmu"):
        return get_ppe_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


print(f"[PPE 2x offload smoke] OFFLOAD={OFFLOAD}")
run_axis_test(TOPOLOGY, make_nsu, make_nmu)
