import sys
from pathlib import Path


GENERIC_DIR = Path(__file__).resolve().parents[1] / "generic"
if str(GENERIC_DIR) not in sys.path:
    sys.path.insert(0, str(GENERIC_DIR))

from generic_v2_smoke_common import build_aximm_param_overrides, run_v2_smoke


run_v2_smoke(
    label="HBM mixed BRAM/HBM smoke",
    noc_topology=(
        "src/noc/testing/fixtures/topologies/hbm_mixed_bram_hbm/"
        "mixed_nmu_to_bram_hbm"
    ),
    connections_json="noc_testing/topology_jsons/hbm/mixed_nmu_to_bram_hbm.conn.json",
    default_args=[
        "--num-packets",
        "8",
        "--sim-cycles",
        "5000000",
        "--abs-max-tick",
        "5000000000",
    ],
    param_overrides=build_aximm_param_overrides(
        ["tg_0", "hbm_tg_0"],
        num_transactions=8,
        beat_size_bytes=64,
        bandwidth_MBps=800,
        max_outstanding_writes=4,
    ),
)
