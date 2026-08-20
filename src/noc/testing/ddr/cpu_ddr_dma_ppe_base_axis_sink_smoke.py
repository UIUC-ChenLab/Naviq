import sys
import os
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parents[1]
NOC_ROOT = MAIN_DIR.parents[0]
REPO_ROOT = NOC_ROOT.parents[1]
LEGACY_SETUP_DIR = NOC_ROOT / "setup" / "legacy"
if str(LEGACY_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_SETUP_DIR))

from noc_cpu_ddr_dma_config import run_cpu_ddr_dma_test


TOPOLOGY = "src/noc/topology/topologies/cpu/cpu_ddr_dma_ppe_base_axis"
BINARY = REPO_ROOT / "src" / "noc" / "cpu" / "programs" / "ddr_dma_control_x86"
OFFLOAD = os.environ.get("PPE_OFFLOAD", "none").lower()


def configure_options(options):
    options.binary = str(BINARY)
    options.num_packets = max(options.num_packets, 4)
    options.sim_cycles = max(options.sim_cycles, 500000)
    options.abs_max_tick = max(options.abs_max_tick, 500000000)


run_cpu_ddr_dma_test(
    TOPOLOGY,
    with_ppe=True,
    configure_options=configure_options,
    offload=OFFLOAD,
)

print(f"[CPU DDR DMA PPE base smoke] CPU wrote descriptors and started DMA through PPE OFFLOAD_{OFFLOAD.upper()}")
