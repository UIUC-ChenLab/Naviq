"""Deterministic AXI-MM VALID-stall smoke using the shared 2-to-2 fixture."""

from generic_v2_smoke_common import build_aximm_param_overrides, run_v2_smoke


COMPONENTS = ("first_dummy", "tg_1")

run_v2_smoke(
    label="AXI-MM handshake-stress smoke",
    noc_topology="src/noc/testing/fixtures/topologies/2to2_aximm/2to2_aximm",
    connections_json=(
        "noc_testing/topology_jsons/experiments/"
        "axi_handshake_stress_2to2.conn.json"
    ),
    placement_json="noc_testing/topology_jsons/multi_endpoint/2to2_aximm.place.json",
    default_args=("--sim-cycles", "1000000", "--abs-max-tick", "5000000000"),
    param_overrides=build_aximm_param_overrides(
        COMPONENTS,
        num_transactions=4,
        beat_size_bytes=64,
        transaction_size_bytes=64,
        bandwidth_MBps=800,
        read_write_mode="WRITE_ONLY",
        max_outstanding_writes=2,
        align_addresses=False,
        address_increment_bytes=64,
    ),
)
