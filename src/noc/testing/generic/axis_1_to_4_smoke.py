from generic_v2_smoke_common import (
    build_axis_source_param_overrides,
    build_expected_packet_overrides,
    run_v2_smoke,
)

run_v2_smoke(
    label="AXIS 1_to_4 smoke",
    noc_topology="src/noc/testing/fixtures/topologies/1to4_axis/1to4_axis",
    connections_json="noc_testing/topology_jsons/multi_endpoint/1to4_axis.conn.json",
    default_args=[
        "--sim-cycles",
        "300000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=(
        build_axis_source_param_overrides(
            ["tg_0", "tg_1", "tg_2", "tg_3"],
            packets=8,
            packet_size_bytes=64,
            seed_base=4100,
        )
        + build_expected_packet_overrides({"bram_0": 32})
    ),
)
