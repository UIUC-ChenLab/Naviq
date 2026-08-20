from generic_v2_smoke_common import (
    build_axis_source_param_overrides,
    build_expected_packet_overrides,
    run_v2_smoke,
)

run_v2_smoke(
    label="AXIS 2_to_2 smoke",
    noc_topology="src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis",
    connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_axis.conn.json",
    default_args=[
        "--sim-cycles",
        "200000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=(
        build_axis_source_param_overrides(
            ["tg_0", "tg_1"],
            packets=8,
            packet_size_bytes=64,
        )
        + build_expected_packet_overrides(
            {
                "bram_0": 8,
                "bram_1": 8,
            }
        )
    ),
)
