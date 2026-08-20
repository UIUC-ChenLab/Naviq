from generic_smoke_common import run_generic_smoke


run_generic_smoke(
    [
        "--noc-topology",
        "src/noc/topology/topologies/aximm_1to1_close",
        "--num-packets",
        "10",
        "--write-size",
        "6",
        "--write-length",
        "3",
        "--direction",
        "WRITE_ONLY",
        "--sim-cycles",
        "3000000",
        "--abs-max-tick",
        "5000000000",
    ],
    "AXIMM 1_to_1_close long smoke",
)
