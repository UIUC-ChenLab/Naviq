from generic_smoke_common import run_generic_smoke


run_generic_smoke(
    [
        "--noc-topology",
        "src/noc/topology/topologies/axis_1to1_close",
        "--num-packets",
        "16",
        "--write-size",
        "6",
        "--write-length",
        "3",
        "--sim-cycles",
        "2000000",
        "--abs-max-tick",
        "5000000000",
    ],
    "AXIS 1_to_1 long smoke",
)
