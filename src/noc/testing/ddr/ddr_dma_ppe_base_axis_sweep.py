import os
import sys
from pathlib import Path

NOC_ROOT = Path(__file__).resolve().parents[2]
DDR_SETUP_DIR = NOC_ROOT / "ddr" / "setup"
if str(DDR_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(DDR_SETUP_DIR))

from noc_ddr_packet_dma_config import run_ddr_dma_ppe_base_axis_sink_test


TOPOLOGY = "src/noc/topology/topologies/ddr/ddr_dma_ppe_base_axis"
PAYLOAD_SIZES = os.environ.get(
    "DDR_DMA_PAYLOAD_SIZES",
    "16,100,160,228,484,996,1472",
)
PACKETS = int(os.environ.get("DDR_DMA_PACKET_COUNT", "1000"))
OFFLOAD = os.environ.get("PPE_OFFLOAD", "none").lower()
MAX_READ_BURST_BEATS = int(os.environ.get("DDR_DMA_MAX_READ_BURST_BEATS", "16"))
START_DELAY_CYCLES_ENV = os.environ.get("DDR_DMA_START_DELAY_CYCLES")
START_DELAY_CYCLES = (
    int(START_DELAY_CYCLES_ENV) if START_DELAY_CYCLES_ENV is not None else None
)
PACKET_GAP_CYCLES_ENV = os.environ.get("DDR_DMA_PACKET_GAP_CYCLES")
PACKET_GAP_CYCLES = (
    int(PACKET_GAP_CYCLES_ENV) if PACKET_GAP_CYCLES_ENV is not None else None
)
PROFILE = os.environ.get(
    "DDR_DMA_PROFILE",
    "ipv4_tcp" if OFFLOAD == "nat" else "ipv4_udp",
)


def configure_options(options):
    options.num_packets = max(options.num_packets, PACKETS)
    options.sim_cycles = max(options.sim_cycles, 10000000)


run_ddr_dma_ppe_base_axis_sink_test(
    TOPOLOGY,
    configure_options=configure_options,
    packet_count=PACKETS,
    offload=OFFLOAD,
    profile=PROFILE,
    payload_sizes=PAYLOAD_SIZES,
    corrupt_ipv4_checksum=OFFLOAD == "checksum",
    corrupt_l4_checksum=OFFLOAD == "checksum",
    max_read_burst_beats=MAX_READ_BURST_BEATS,
    start_delay_cycles=START_DELAY_CYCLES,
    packet_gap_cycles=PACKET_GAP_CYCLES,
    seed=11,
    flow_count=32,
    tid=3,
    tdest=0,
    tuser=0x55,
)

print(
    "[DDR DMA PPE base AXIS sweep] "
    f"offload={OFFLOAD} packets={PACKETS} payload_sizes={PAYLOAD_SIZES} "
    f"profile={PROFILE} "
    f"max_read_burst_beats={MAX_READ_BURST_BEATS} "
    f"start_delay_cycles={START_DELAY_CYCLES} "
    f"packet_gap_cycles={PACKET_GAP_CYCLES}"
)
