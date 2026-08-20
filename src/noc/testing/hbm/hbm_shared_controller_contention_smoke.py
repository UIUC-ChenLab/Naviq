import sys
from pathlib import Path


GENERIC_DIR = Path(__file__).resolve().parents[1] / "generic"
if str(GENERIC_DIR) not in sys.path:
    sys.path.insert(0, str(GENERIC_DIR))

from generic_v2_smoke_common import build_aximm_param_overrides, run_v2_smoke


run_v2_smoke(
    label="HBM shared controller contention smoke",
    noc_topology=(
        "src/noc/testing/fixtures/topologies/hbm_shared_controller/"
        "hbm_shared_controller"
    ),
    connections_json="noc_testing/topology_jsons/hbm/hbm_shared_controller.conn.json",
    default_args=["--num-packets", "100"],
    param_overrides=build_aximm_param_overrides(
        ["hbm_tg_0"],
        num_transactions=100,
        beat_size_bytes=64,
        bandwidth_MBps=800,
        read_write_mode="INTERLEAVED",
        max_outstanding_writes=1,
    ),
)
