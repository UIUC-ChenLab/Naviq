"""Manual V1 AXI-MM NoC smoke for the generated RTL slave bridge."""

from generic_v2_smoke_common import build_aximm_param_overrides, run_v2_smoke


run_v2_smoke(
    label="AXI-MM RTL memory smoke",
    noc_topology="src/noc/testing/fixtures/topologies/2to2_aximm/2to2_aximm",
    connections_json="noc_testing/topology_jsons/aximm/aximm_rtl_memory_smoke.conn.json",
    placement_json="noc_testing/topology_jsons/aximm/aximm_rtl_memory_smoke.place.json",
    default_args=[
        "--sim-cycles",
        "400000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=build_aximm_param_overrides(
        ["tg_0"],
        num_transactions=4,
        beat_size_bytes=64,
        transaction_size_bytes=64,
        read_write_mode="SEQUENTIAL",
        max_outstanding_writes=1,
        align_addresses=True,
    ),
)
