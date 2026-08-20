import sys
from pathlib import Path

NOC_ROOT = Path(__file__).resolve().parents[2]
DDR_SETUP_DIR = NOC_ROOT / "ddr" / "setup"
if str(DDR_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(DDR_SETUP_DIR))

from noc_ddr_traffic_config import run_ddr_traffic_test


TOPOLOGY = "src/noc/topology/topologies/2nmu_to_ddr"


def configure_options(options):
    options.direction = "WRITE_ONLY"
    options.num_packets = 32
    options.bandwidth = 2000
    options.abs_max_tick = 5_000_000_000
    options.sim_cycles = max(options.sim_cycles, 200000)


run_ddr_traffic_test(TOPOLOGY, configure_options=configure_options)

print("[DDR direct contention smoke] completed")
