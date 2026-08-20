import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, run_axis_test


TOPOLOGY = "src/noc/topology/topologies/smartnic_tests/axis_packet_loopback"


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        return make_packet_checker(options, check_mode="exact", profile="ipv4_tcp")
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        return make_packet_source(options, profile="ipv4_tcp", initial_gap_cycles=0)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


run_axis_test(TOPOLOGY, make_nsu, make_nmu)
