import os
import sys
from pathlib import Path

import m5

NOC_ROOT = Path(__file__).resolve().parents[2]
DDR_SETUP_DIR = NOC_ROOT / "ddr" / "setup"
if str(DDR_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(DDR_SETUP_DIR))

from noc_ddr_packet_dma_config import run_ddr_dma_ppe_base_axis_sink_test


TOPOLOGY = "src/noc/topology/topologies/ddr/ddr_dma_ppe_base_axis"
PAYLOAD_SIZES = "16,100,160,228"
OFFLOAD = os.environ.get("PPE_OFFLOAD", "none").lower()


def configure_options(options):
    options.num_packets = max(options.num_packets, 4)
    options.sim_cycles = max(options.sim_cycles, 250000)


required_ppe_objects = [
    "PacketProcessingEngineBaseChecksumRtlNode",
    "PacketProcessingEngineBaseNatRtlNode",
    "PacketProcessingEngineBaseNoneRtlNode",
    "PacketProcessingEngineBaseSegmentationRtlNode",
    "PacketProcessingEngineBaseTelemetryRtlNode",
]

missing_objects = [name for name in required_ppe_objects if not hasattr(m5.objects, name)]
if missing_objects:
    print(
        "SMOKE_SKIP: DDR DMA PPE base AXIS sink smoke requires PPE RTL nodes; "
        f"missing {', '.join(missing_objects)}"
    )
else:
    run_ddr_dma_ppe_base_axis_sink_test(
        TOPOLOGY,
        configure_options=configure_options,
        packet_count=4,
        offload=OFFLOAD,
        profile="ipv4_udp",
        payload_sizes=PAYLOAD_SIZES,
        corrupt_ipv4_checksum=OFFLOAD == "checksum",
        corrupt_l4_checksum=OFFLOAD == "checksum",
        seed=7,
        flow_count=4,
        tid=3,
        tdest=0,
        tuser=0x55,
    )

print(f"[DDR DMA PPE base AXIS sink smoke] offload={OFFLOAD} payload_sizes={PAYLOAD_SIZES}")
