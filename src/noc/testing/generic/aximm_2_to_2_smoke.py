from generic_v2_smoke_common import (
    build_aximm_param_overrides,
    run_v2_smoke,
)

run_v2_smoke(
    label="AXIMM 2_to_2 smoke",
    noc_topology="src/noc/testing/fixtures/topologies/2to2_aximm/2to2_aximm",
    connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_aximm.conn.json",
    default_args=[
        "--num-packets",
        "8",
        "--sim-cycles",
        "2000000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=build_aximm_param_overrides(
        ["first_dummy", "tg_1"],
        num_transactions=8,
        beat_size_bytes=64,
        bandwidth_MBps=800,
    ),
)
