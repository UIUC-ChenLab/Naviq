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
DATA_ONLY_BINARY = (
    REPO_ROOT
    / "src"
    / "noc"
    / "cpu"
    / "programs"
    / "ddr_dma_control_data_only_pkt100_x86"
)
DDR_HEAVY_BINARY = (
    REPO_ROOT
    / "src"
    / "noc"
    / "cpu"
    / "programs"
    / "ddr_dma_control_ddr_heavy_pkt100_x86"
)


def run_ddr_stress_case(run_label, *, scratch_read_burst_bytes=None):
    def configure_options(options):
        options.binary = str(
            DATA_ONLY_BINARY if scratch_read_burst_bytes is None else DDR_HEAVY_BINARY
        )
        options.num_packets = 100
        options.sim_cycles = max(options.sim_cycles, 3_000_000)
        options.abs_max_tick = max(options.abs_max_tick, 3_000_000_000)
        if scratch_read_burst_bytes is not None:
            options.cpu_scratch_read_burst_bytes = scratch_read_burst_bytes
        options.metrics_run_label = run_label

    run_cpu_ddr_dma_test(
        TOPOLOGY,
        with_ppe=True,
        configure_options=configure_options,
        offload="none",
    )

    print(f"[{run_label}] PASS")
