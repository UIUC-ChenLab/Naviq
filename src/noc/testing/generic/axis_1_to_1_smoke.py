from generic_smoke_common import run_generic_smoke


run_generic_smoke(
    [
        "--noc-topology",
        "src/noc/topology/topologies/axis_1to1_close",
        "--num-packets",
        "4",
    ],
    "AXIS 1_to_1 smoke",
)
