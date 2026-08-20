import os
import sys
from pathlib import Path


GENERIC_DIR = Path(__file__).resolve().parents[1] / "generic"
if str(GENERIC_DIR) not in sys.path:
    sys.path.insert(0, str(GENERIC_DIR))

from generic_v3_smoke_common import build_aximm_param_overrides, run_v3_smoke


def _workspace_root() -> Path:
    here = Path(__file__).resolve()
    for d in (here.parent, *here.parents):
        if (d / "noc_testing").is_dir():
            return d
    return here.parents[3]


REPO_ROOT = _workspace_root()
TOPOLOGY_DIR = REPO_ROOT / "src/noc/topology/topologies/hbm_1stack_16GB/1tg"
STEM = "1tg"
CONNECTIONS_JSON = TOPOLOGY_DIR / f"{STEM}.conn.json"
PLACEMENT_JSON = TOPOLOGY_DIR / f"{STEM}.place.json"
NTS_FILE = TOPOLOGY_DIR / f"{STEM}.nts"
NCR_FILE = TOPOLOGY_DIR / f"{STEM}.ncr"

TG = "hbm_sat_tg_00"
HBM_PORT = "hbm0_port0"

TRANSACTIONS = int(os.environ.get("HBM_SINGLE_FLOW_TRANSACTIONS", "1000"))
OUTSTANDING = int(os.environ.get("HBM_SINGLE_FLOW_OUTSTANDING", "32"))
ARID_DISTRIBUTION = os.environ.get("HBM_SINGLE_FLOW_ARID_DISTRIBUTION", "INCREMENT").upper()
MIN_ARID = int(os.environ.get("HBM_SINGLE_FLOW_MIN_ARID", "0"))
MAX_ARID = int(os.environ.get("HBM_SINGLE_FLOW_MAX_ARID", "3"))
MODE = os.environ.get("HBM_SINGLE_FLOW_MODE", "WRITE_ONLY").upper()
if MODE not in ("WRITE_ONLY", "READ_ONLY", "SEQUENTIAL", "INTERLEAVED"):
    raise ValueError(
        "HBM_SINGLE_FLOW_MODE must be WRITE_ONLY, READ_ONLY, SEQUENTIAL, or INTERLEAVED"
    )

STATS_CSV = os.environ.get("HBM_SINGLE_FLOW_STATS_CSV", "")
STATS_SAMPLE_GAP_CYCLES = int(
    os.environ.get("HBM_SINGLE_FLOW_STATS_SAMPLE_GAP_CYCLES", "100")
)


def _hbm_stats_overrides() -> list[str]:
    if not STATS_CSV:
        return []
    return [
        f"{HBM_PORT}.hbm_stats_csv_path={STATS_CSV}",
        f"{HBM_PORT}.hbm_stats_sample_gap_cycles={STATS_SAMPLE_GAP_CYCLES}",
    ]


if __name__ in ("__main__", "__m5_main__"):
    run_v3_smoke(
        label=f"HBM single-flow bandwidth {MODE}",
        noc_topology=TOPOLOGY_DIR,
        connections_json=CONNECTIONS_JSON,
        placement_json=PLACEMENT_JSON,
        default_args=[
            "--nts-file",
            NTS_FILE,
            "--ncr-file",
            NCR_FILE,
            "--abs-max-tick",
            os.environ.get("HBM_SINGLE_FLOW_ABS_MAX_TICK", "10000000000"),
        ],
        param_overrides=(
            build_aximm_param_overrides(
                [TG],
                num_transactions=TRANSACTIONS,
                beat_size_bytes=32,
                transaction_size_bytes=512,
                bandwidth_MBps=0,
                read_write_mode=MODE,
                max_outstanding_writes=OUTSTANDING,
                align_addresses=False,
                address_distribution="INCREMENT",
                address_increment_bytes=512,
                awid_distribution="INCREMENT",
                min_awid=0,
                max_awid=3,
            )
            + [
                f"{TG}.arid_distribution={ARID_DISTRIBUTION}",
                f"{TG}.min_arid={MIN_ARID}",
                f"{TG}.max_arid={MAX_ARID}",
            ]
            + _hbm_stats_overrides()
        ),
    )
