from generic_smoke_common import run_generic_smoke


run_generic_smoke(
    [
        "--noc-topology",
        "src/noc/topology/topologies/aximm_1to1_close",
        "--num-packets",
        "4",
    ],
    "AXIMM 1_to_1_close smoke",
)
