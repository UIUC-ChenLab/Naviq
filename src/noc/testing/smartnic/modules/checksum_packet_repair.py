import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, make_stream_rtl_node, run_axis_test
from m5.objects import ChecksumRtlNode


TOPOLOGY = "src/noc/topology/topologies/smartnic_tests/axis_module_smoke"
checksum_node = None


def get_checksum_node(options):
    global checksum_node
    if checksum_node is None:
        checksum_node = make_stream_rtl_node(ChecksumRtlNode, options)
    return checksum_node


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        return make_packet_checker(options, check_mode="ipv4")
    if tile_name == "M01_AXIS_nsu":
        return get_checksum_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        return make_packet_source(
            options,
            corrupt_ipv4_checksum=True,
            corrupt_l4_checksum=True,
        )
    if tile_name == "S01_AXIS_nmu":
        return get_checksum_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


run_axis_test(TOPOLOGY, make_nsu, make_nmu)
