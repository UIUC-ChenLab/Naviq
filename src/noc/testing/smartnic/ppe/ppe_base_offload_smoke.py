import os

from m5.objects import (
    PacketProcessingEngineBaseChecksumRtlNode,
    PacketProcessingEngineBaseNatRtlNode,
    PacketProcessingEngineBaseNoneRtlNode,
    PacketProcessingEngineBaseSegmentationRtlNode,
    PacketProcessingEngineBaseTelemetryRtlNode,
)

import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, make_stream_rtl_node, run_axis_test


TOPOLOGY = "src/noc/topology/topologies/smartnic_tests/axis_module_smoke"
OFFLOAD = os.environ.get("PPE_OFFLOAD", "none").lower()

OFFLOAD_CLASSES = {
    "none": PacketProcessingEngineBaseNoneRtlNode,
    "telemetry": PacketProcessingEngineBaseTelemetryRtlNode,
    "segmentation": PacketProcessingEngineBaseSegmentationRtlNode,
    "checksum": PacketProcessingEngineBaseChecksumRtlNode,
    "nat": PacketProcessingEngineBaseNatRtlNode,
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
            expected_packets=max(options.num_packets, 1),
            reset_cycles=reset_cycles,
        )
    return ppe_node


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        if OFFLOAD == "nat":
            return make_packet_checker(
                options,
                check_mode="nat_outbound",
                validate_ipv4_checksum=False,
                validate_l4_checksum=False,
            )
        return make_packet_checker(options, check_mode="exact")
    if tile_name == "M01_AXIS_nsu":
        return get_ppe_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        if OFFLOAD == "nat":
            return make_packet_source(
                options,
                profile="ipv4_tcp",
                min_gap_cycles=4096,
                max_gap_cycles=4096,
                initial_gap_cycles=2600,
            )
        return make_packet_source(options, initial_gap_cycles=64)
    if tile_name == "S01_AXIS_nmu":
        return get_ppe_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


print(f"[PPE base offload smoke] OFFLOAD={OFFLOAD}")
run_axis_test(TOPOLOGY, make_nsu, make_nmu)
