import sys
from pathlib import Path

NOC_ROOT = Path(__file__).resolve().parents[2]
DDR_SETUP_DIR = NOC_ROOT / "ddr" / "setup"
if str(DDR_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(DDR_SETUP_DIR))

from noc_ddr_packet_dma_config import run_ddr_dma_axis_sink_test


TOPOLOGY = "src/noc/topology/topologies/ddr/ddr_dma_axis"
PAYLOAD_SIZES = "16,100,160,228"


def configure_options(options):
    options.num_packets = max(options.num_packets, 4)
    options.sim_cycles = max(options.sim_cycles, 200000)


run_ddr_dma_axis_sink_test(
    TOPOLOGY,
    configure_options=configure_options,
    packet_count=4,
    profile="ipv4_udp",
    payload_sizes=PAYLOAD_SIZES,
    seed=7,
    flow_count=4,
    tid=3,
    tdest=0,
    tuser=0x55,
)

print(f"[DDR DMA AXIS sink smoke] payload_sizes={PAYLOAD_SIZES}")
