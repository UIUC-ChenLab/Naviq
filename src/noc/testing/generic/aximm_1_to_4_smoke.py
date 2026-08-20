from generic_v2_smoke_common import (
    build_aximm_param_overrides,
    run_v2_smoke,
)

run_v2_smoke(
    label="AXIMM 1_to_4 smoke",
    noc_topology="src/noc/testing/fixtures/topologies/1to4_aximm/1to4_aximm",
    connections_json="noc_testing/topology_jsons/multi_endpoint/1to4_aximm.conn.json",
    default_args=[
        "--num-packets",
        "8",
        "--sim-cycles",
        "2000000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=build_aximm_param_overrides(
        ["tg_0", "tg_1", "tg_2", "tg_3"],
        num_transactions=8,
        beat_size_bytes=64,
        bandwidth_MBps=800,
    ),
)
