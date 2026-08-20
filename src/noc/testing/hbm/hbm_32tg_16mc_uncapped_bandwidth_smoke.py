import sys
from pathlib import Path


GENERIC_DIR = Path(__file__).resolve().parents[1] / "generic"
if str(GENERIC_DIR) not in sys.path:
    sys.path.insert(0, str(GENERIC_DIR))

from generic_v2_smoke_common import build_aximm_param_overrides, run_v2_smoke


HBM_SAT_TGS = [f"hbm_sat_tg_{idx:02d}" for idx in range(32)]


run_v2_smoke(
    label="HBM 32TG/16MC uncapped bandwidth smoke",
    noc_topology=(
        "src/noc/testing/fixtures/topologies/"
        "hbm_32tg_16mc_uncapped_bandwidth/hbm_32tg_16mc_saturation"
    ),
    connections_json="noc_testing/topology_jsons/hbm/hbm_32tg_16mc_saturation.conn.json",
    default_args=[
        "--num-packets",
        "64",
        "--abs-max-tick",
        "10000000000",
    ],
    param_overrides=build_aximm_param_overrides(
        HBM_SAT_TGS,
        num_transactions=64,
        beat_size_bytes=64,
        transaction_size_bytes=256,
        bandwidth_MBps=0,
        max_outstanding_writes=32,
        align_addresses=True,
        address_increment_bytes=256,
    ),
)
