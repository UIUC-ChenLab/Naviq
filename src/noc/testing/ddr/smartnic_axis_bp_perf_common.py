import sys
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parents[1]
NOC_ROOT = MAIN_DIR.parents[0]
REPO_ROOT = NOC_ROOT.parents[1]
LEGACY_SETUP_DIR = NOC_ROOT / "setup" / "legacy"
if str(LEGACY_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_SETUP_DIR))

from noc_cpu_ddr_dma_config import run_cpu_ddr_dma_test


TOPOLOGY = "src/noc/topology/topologies/cpu/cpu_ddr_dma_ppe_base_axis"
BINARY = (
    REPO_ROOT
    / "src"
    / "noc"
    / "cpu"
    / "programs"
    / "ddr_dma_control_data_only_bp_pkt100_x86"
)


def run_axis_bp_perf_case(run_label, *, config_name, period, allow):
    def configure_options(options):
        options.binary = str(BINARY)
        options.num_packets = 100
        options.sim_cycles = max(options.sim_cycles, 3_000_000)
        options.abs_max_tick = max(options.abs_max_tick, 3_000_000_000)
        options.metrics_run_label = run_label

    backpressure_config = {
        "enabled": True,
        "config_name": config_name,
        "period": period,
        "allow": allow,
        "scope": "dma_fed_axis_valid_gated_backpressure_v1",
        "fifo_depth": 1,
    }
    run_cpu_ddr_dma_test(
        TOPOLOGY,
        configure_options=configure_options,
        backpressure_config=backpressure_config,
        offload="none",
    )

    print(f"[{run_label}] PASS")
