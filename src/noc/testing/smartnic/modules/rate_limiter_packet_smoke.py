import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, make_stream_rtl_node, run_axis_test
from m5.objects import PacketRateLimiterRtlNode


TOPOLOGY = "src/noc/testing/fixtures/topologies/smartnic/axis_module_smoke"
rate_limiter_node = None


def get_rate_limiter_node(options):
    global rate_limiter_node
    if rate_limiter_node is None:
        rate_limiter_node = make_stream_rtl_node(PacketRateLimiterRtlNode, options)
    return rate_limiter_node


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        return make_packet_checker(options, check_mode="exact")
    if tile_name == "M01_AXIS_nsu":
        return get_rate_limiter_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        return make_packet_source(options)
    if tile_name == "S01_AXIS_nmu":
        return get_rate_limiter_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


run_axis_test(TOPOLOGY, make_nsu, make_nmu)
