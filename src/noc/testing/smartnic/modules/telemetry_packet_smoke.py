import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, make_stream_rtl_node, run_axis_test
from m5.objects import TelemetryRtlNode


TOPOLOGY = "src/noc/topology/topologies/smartnic_tests/axis_module_smoke"
telemetry_node = None


def get_telemetry_node(options):
    global telemetry_node
    if telemetry_node is None:
        telemetry_node = make_stream_rtl_node(TelemetryRtlNode, options)
    return telemetry_node


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        return make_packet_checker(options, check_mode="exact")
    if tile_name == "M01_AXIS_nsu":
        return get_telemetry_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        return make_packet_source(options)
    if tile_name == "S01_AXIS_nmu":
        return get_telemetry_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


run_axis_test(TOPOLOGY, make_nsu, make_nmu)
