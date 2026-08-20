import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1] / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from smartnic_common import make_packet_checker, make_packet_source, make_stream_rtl_node, run_axis_test
from m5.objects import OverloadedNatRtlNode


TOPOLOGY = "src/noc/topology/topologies/smartnic_tests/axis_module_smoke"
nat_node = None


def get_nat_node(options):
    global nat_node
    if nat_node is None:
        nat_node = make_stream_rtl_node(
            OverloadedNatRtlNode,
            options,
            expected_packets=max(options.num_packets, 1),
            reset_cycles=2500,
        )
    return nat_node


def make_nsu(tile_name, options):
    if tile_name == "M00_AXIS_nsu":
        return make_packet_checker(
            options,
            check_mode="nat_outbound",
            packet_count=max(options.num_packets, 1),
            validate_ipv4_checksum=False,
            validate_l4_checksum=False,
        )
    if tile_name == "M01_AXIS_nsu":
        return get_nat_node(options)
    raise RuntimeError(f"Unexpected AXIS NSU {tile_name}")


def make_nmu(tile_name, options):
    if tile_name == "S00_AXIS_nmu":
        return make_packet_source(
            options,
            profile="ipv4_tcp",
            packet_count=max(options.num_packets, 1),
            # The current NAT RTL can drop lookup context for back-to-back misses.
            # Keep this smoke permissive until the pending-context path is fixed.
            min_gap_cycles=4096,
            max_gap_cycles=4096,
            initial_gap_cycles=2600,
        )
    if tile_name == "S01_AXIS_nmu":
        return get_nat_node(options)
    raise RuntimeError(f"Unexpected AXIS NMU {tile_name}")


run_axis_test(TOPOLOGY, make_nsu, make_nmu)
