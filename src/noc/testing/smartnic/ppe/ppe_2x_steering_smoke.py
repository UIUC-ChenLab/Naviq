import os

from m5.objects import (
    AxisPacketCheckerSink,
    PacketProcessingEngine2xFiveTupleHashRtlNode,
    PacketProcessingEngine2xFlowPrefixRtlNode,
    PacketProcessingEngine2xNoneRtlNode,
)

import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import (
    AXIS_DATA_WIDTH,
    AXIS_TDEST_WIDTH,
    AXIS_TID_WIDTH,
    AXIS_TUSER_WIDTH,
    make_packet_checker,
    make_packet_source,
    make_stream_rtl_node,
    run_axis_test,
)


TOPOLOGY = "src/noc/topology/topologies/smartnic_tests/axis_module_2x_smoke"
STEERING = os.environ.get("PPE_STEERING", "none").lower()

STEERING_CLASSES = {
    "none": PacketProcessingEngine2xNoneRtlNode,
    "flow_prefix": PacketProcessingEngine2xFlowPrefixRtlNode,
    "five_tuple_hash": PacketProcessingEngine2xFiveTupleHashRtlNode,
}

if STEERING != "none":
    raise RuntimeError(
        "2x PPE steering rewrite is not a valid physical-output steering "
        "test with the current RTL: packet_processing_engine_2x rewrites "
        "tdest in the base engine, then a round-robin distributor chooses "
        "m_axis_0/m_axis_1 without looking at tdest. Use the base PPE "
        "steering smoke for flow-prefix/hash tdest verification."
    )

FLOW0_ID = 0x35
FLOW1_ID = 0xA4
FLOW0_TDEST = 7
FLOW1_TDEST = 8
FLOW_PREFIX_BYTES = 2
HASH_PREFIX_BYTES = 1

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
            expected_packets=max(options.num_packets, 1) * 2,
            reset_cycles=16,
        )
    return ppe_node


def zero_packet_checker(options):
    return AxisPacketCheckerSink(
        data_width=AXIS_DATA_WIDTH,
        tid_width=AXIS_TID_WIDTH,
        tdest_width=AXIS_TDEST_WIDTH,
        tuser_width=AXIS_TUSER_WIDTH,
        expected_packets=0,
        print_summary=True,
    )


def make_nsu(tile_name, options):
    packets = max(options.num_packets, 1)
    if tile_name == "M00_AXIS_nsu":
        if STEERING == "flow_prefix":
            return make_packet_checker(
                options,
                check_mode="exact",
                check_seed=1,
                tdest=FLOW0_TDEST,
                validation_skip_bytes=FLOW_PREFIX_BYTES,
                prefix_bytes=FLOW_PREFIX_BYTES,
                prefix_value=FLOW0_ID,
            )
        if STEERING == "five_tuple_hash":
            return make_packet_checker(
                options,
                check_mode="ipv4",
                packet_count=packets * 2,
                tdest=FLOW0_TDEST,
                check_tdest=True,
                validation_skip_bytes=HASH_PREFIX_BYTES,
            )
        return make_packet_checker(
            options,
            check_mode="ipv4",
            check_seed=1,
            min_payload_bytes=16,
            max_payload_bytes=16,
        )
    if tile_name == "M01_AXIS_nsu":
        if STEERING == "flow_prefix":
            return make_packet_checker(
                options,
                check_mode="exact",
                check_seed=2,
                tdest=FLOW1_TDEST,
                validation_skip_bytes=FLOW_PREFIX_BYTES,
                prefix_bytes=FLOW_PREFIX_BYTES,
                prefix_value=FLOW1_ID,
            )
        if STEERING == "five_tuple_hash":
            return zero_packet_checker(options)
        return make_packet_checker(
            options,
            check_mode="ipv4",
            check_seed=2,
            min_payload_bytes=16,
            max_payload_bytes=16,
        )
    if tile_name in ("M02_AXIS_nsu", "M03_AXIS_nsu"):
        return get_ppe_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    initial_gap = 800 if STEERING == "five_tuple_hash" else 64
    if tile_name == "S00_AXIS_nmu":
        if STEERING == "flow_prefix":
            return make_packet_source(
                options,
                check_seed=1,
                initial_gap_cycles=initial_gap,
                prefix_bytes=FLOW_PREFIX_BYTES,
                prefix_value=FLOW0_ID,
            )
        return make_packet_source(
            options,
            check_seed=1,
            min_payload_bytes=16,
            max_payload_bytes=16,
            initial_gap_cycles=initial_gap,
        )
    if tile_name == "S01_AXIS_nmu":
        if STEERING == "flow_prefix":
            return make_packet_source(
                options,
                check_seed=2,
                initial_gap_cycles=initial_gap,
                prefix_bytes=FLOW_PREFIX_BYTES,
                prefix_value=FLOW1_ID,
            )
        return make_packet_source(
            options,
            check_seed=2,
            min_payload_bytes=16,
            max_payload_bytes=16,
            initial_gap_cycles=initial_gap,
        )
    if tile_name in ("S02_AXIS_nmu", "S03_AXIS_nmu"):
        return get_ppe_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


def aliases():
    if STEERING == "flow_prefix":
        return [
            ("S02_AXIS_nmu", FLOW0_TDEST, "M00_AXIS_nsu"),
            ("S03_AXIS_nmu", FLOW1_TDEST, "M01_AXIS_nsu"),
        ]
    if STEERING == "five_tuple_hash":
        return [
            ("S02_AXIS_nmu", FLOW0_TDEST, "M00_AXIS_nsu"),
        ]
    return None


print(f"[PPE 2x steering smoke] STEERING={STEERING}")
run_axis_test(TOPOLOGY, make_nsu, make_nmu, axis_tdest_aliases=aliases())
