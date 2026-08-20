from generic_v2_smoke_common import (
    build_axis_source_param_overrides,
    build_expected_packet_overrides,
    run_v2_smoke,
)

run_v2_smoke(
    label="AXIS 2_to_2 long smoke",
    noc_topology="src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis",
    connections_json="noc_testing/topology_jsons/multi_endpoint/2to2_axis.conn.json",
    default_args=[
        "--sim-cycles",
        "1000000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=(
        build_axis_source_param_overrides(
            ["tg_0", "tg_1"],
            packets=16,
            packet_size_bytes=256,
        )
        + build_expected_packet_overrides(
            {
                "bram_0": 16,
                "bram_1": 16,
            }
        )
    ),
)
