import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, make_stream_rtl_node, run_axis_test
from m5.objects import PacketRateLimiterThrottleRtlNode


TOPOLOGY = "src/noc/testing/fixtures/topologies/smartnic/axis_module_smoke"
INPUT_PACKETS = 2
EXPECTED_OUTPUT_PACKETS = INPUT_PACKETS
INITIAL_GAP_CYCLES = 20000
rate_limiter_node = None


def get_rate_limiter_node(options):
    global rate_limiter_node
    if rate_limiter_node is None:
        rate_limiter_node = make_stream_rtl_node(
            PacketRateLimiterThrottleRtlNode,
            options,
            expected_packets=EXPECTED_OUTPUT_PACKETS,
        )
    return rate_limiter_node


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        return make_packet_checker(
            options,
            check_mode="exact",
            profile="ipv4_udp",
            min_payload_bytes=32,
            max_payload_bytes=32,
            packet_count=EXPECTED_OUTPUT_PACKETS,
            flow_count=1,
        )
    if tile_name == "M01_AXIS_nsu":
        return get_rate_limiter_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        return make_packet_source(
            options,
            profile="ipv4_udp",
            min_payload_bytes=32,
            max_payload_bytes=32,
            initial_gap_cycles=INITIAL_GAP_CYCLES,
            packet_count=INPUT_PACKETS,
            flow_count=1,
        )
    if tile_name == "S01_AXIS_nmu":
        return get_rate_limiter_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


def configure_options(options):
    options.num_packets = INPUT_PACKETS
    options.sim_cycles = 100_000_000
    options.abs_max_tick = 100_000_000


run_axis_test(TOPOLOGY, make_nsu, make_nmu, configure_options=configure_options)
