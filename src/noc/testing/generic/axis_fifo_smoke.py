from generic_v2_smoke_common import (
    build_axis_source_param_overrides,
    build_expected_packet_overrides,
    run_v2_smoke,
)

run_v2_smoke(
    label="AXIS FIFO smoke",
    noc_topology="src/noc/testing/fixtures/topologies/axis_fifo/axis_fifo",
    connections_json="noc_testing/topology_jsons/axis/axis_fifo_topo.conn.json",
    placement_json="noc_testing/topology_jsons/axis/axis_fifo_placement.place.json",
    default_args=[
        "--sim-cycles",
        "200000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=(
        build_axis_source_param_overrides(
            ["axis_tg_0"],
            packets=8,
            packet_size_bytes=64,
        )
        + build_expected_packet_overrides(
            {
                "axis_fifo": 8,
                "axis_end_0": 8,
            }
        )
    ),
)
