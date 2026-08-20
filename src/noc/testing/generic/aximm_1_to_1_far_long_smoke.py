from generic_smoke_common import run_generic_smoke


run_generic_smoke(
    [
        "--noc-topology",
        "src/noc/topology/topologies/1_to_1_far",
        "--num-packets",
        "8",
        "--write-size",
        "6",
        "--write-length",
        "3",
        "--direction",
        "WRITE_ONLY",
        "--sim-cycles",
        "3000000",
    ],
    "AXIMM 1_to_1 far long smoke",
)
