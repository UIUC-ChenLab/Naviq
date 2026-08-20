import sys
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parents[1]
NOC_ROOT = MAIN_DIR.parents[0]
REPO_ROOT = NOC_ROOT.parents[1]
LEGACY_SETUP_DIR = NOC_ROOT / "setup" / "legacy"
if str(LEGACY_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_SETUP_DIR))

from noc_cpu_ddr_dma_config import run_cpu_ppe_steering_control_test


TOPOLOGY = "src/noc/topology/topologies/cpu/cpu_ddr_dma_ppe_base_axis"


def run_cpu_ppe_steering_smoke(
    *,
    steering,
    binary_name,
    enable_dma,
    sim_cycles,
    abs_max_tick,
    summary,
):
    binary = REPO_ROOT / "src" / "noc" / "cpu" / "programs" / binary_name

    def configure_options(options):
        options.binary = str(binary)
        options.num_packets = max(options.num_packets, 4)
        options.sim_cycles = max(options.sim_cycles, sim_cycles)
        options.abs_max_tick = max(options.abs_max_tick, abs_max_tick)

    run_cpu_ppe_steering_control_test(
        TOPOLOGY,
        steering=steering,
        configure_options=configure_options,
        enable_dma=enable_dma,
    )
    print(summary)
