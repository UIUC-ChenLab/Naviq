from generic_smoke_common import run_generic_smoke


run_generic_smoke(
    [
        "--noc-topology",
        "src/noc/topology/topologies/1_to_1_far",
        "--num-packets",
        "4",
    ],
    "AXIMM 1_to_1_far smoke",
)
