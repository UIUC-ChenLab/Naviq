import sys
from pathlib import Path


GENERIC_DIR = Path(__file__).resolve().parents[1] / "generic"
if str(GENERIC_DIR) not in sys.path:
    sys.path.insert(0, str(GENERIC_DIR))

from generic_v2_smoke_common import build_aximm_param_overrides, run_v2_smoke


run_v2_smoke(
    label="HBM single port smoke",
    noc_topology="src/noc/topology/topologies/hbm/1hbm_to_1hbm",
    connections_json="noc_testing/topology_jsons/hbm/1hbm_to_1hbm.conn.json",
    default_args=[
        "--num-packets",
        "16",
        "--sim-cycles",
        "2000000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=build_aximm_param_overrides(
        ["hbm_tg_0"],
        num_transactions=16,
        beat_size_bytes=64,
        bandwidth_MBps=1200,
    ),
)
