import os

from m5.objects import (
    PacketProcessingEngineBaseFiveTupleHashRtlNode,
    PacketProcessingEngineBaseFlowPrefixRtlNode,
    PacketProcessingEngineBaseNoneRtlNode,
)

import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, make_stream_rtl_node, run_axis_test


TOPOLOGY = "src/noc/topology/topologies/smartnic_tests/axis_module_smoke"
STEERING = os.environ.get("PPE_STEERING", "none").lower()

STEERING_CLASSES = {
    "none": PacketProcessingEngineBaseNoneRtlNode,
    "flow_prefix": PacketProcessingEngineBaseFlowPrefixRtlNode,
    "five_tuple_hash": PacketProcessingEngineBaseFiveTupleHashRtlNode,
}

FLOW_ID = 0x35
FLOW_TDEST = 7
HASH_PREFIX_BYTES = 1
FLOW_PREFIX_BYTES = 2

ppe_node = None


def selected_class():
    if STEERING not in STEERING_CLASSES:
        raise RuntimeError(f"Unsupported PPE_STEERING={STEERING}")
    return STEERING_CLASSES[STEERING]


def get_ppe_node(options):
    global ppe_node
    if ppe_node is None:
        ppe_node = make_stream_rtl_node(
            selected_class(),
            options,
            expected_packets=max(options.num_packets, 1),
            reset_cycles=16,
        )
    return ppe_node


def source_initial_gap():
    if STEERING == "five_tuple_hash":
        return 800
    if STEERING == "flow_prefix":
        return 64
    return 16


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        if STEERING == "flow_prefix":
            return make_packet_checker(
                options,
                check_mode="exact",
                tdest=FLOW_TDEST,
                validation_skip_bytes=FLOW_PREFIX_BYTES,
                prefix_bytes=FLOW_PREFIX_BYTES,
                prefix_value=FLOW_ID,
            )
        if STEERING == "five_tuple_hash":
            return make_packet_checker(
                options,
                check_mode="ipv4",
                tdest=FLOW_TDEST,
                check_tdest=True,
                validation_skip_bytes=HASH_PREFIX_BYTES,
            )
        return make_packet_checker(options, check_mode="exact")
    if tile_name == "M01_AXIS_nsu":
        return get_ppe_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        if STEERING == "flow_prefix":
            return make_packet_source(
                options,
                initial_gap_cycles=source_initial_gap(),
                prefix_bytes=FLOW_PREFIX_BYTES,
                prefix_value=FLOW_ID,
            )
        return make_packet_source(options, initial_gap_cycles=source_initial_gap())
    if tile_name == "S01_AXIS_nmu":
        return get_ppe_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


def aliases():
    if STEERING in ("flow_prefix", "five_tuple_hash"):
        return [("S01_AXIS_nmu", FLOW_TDEST, "M00_AXIS_nsu")]
    return None


print(f"[PPE base steering smoke] STEERING={STEERING}")
run_axis_test(TOPOLOGY, make_nsu, make_nmu, axis_tdest_aliases=aliases())
