from generic_smoke_common import run_script_smoke


run_script_smoke(
    "src/noc/testing/smartnic/loopback/axis_packet_loopback.py",
    [
        "--num-packets",
        "4",
    ],
    "AXIS packet loopback smoke",
)
