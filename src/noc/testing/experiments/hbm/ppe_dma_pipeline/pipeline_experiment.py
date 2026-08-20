import sys
from pathlib import Path


HBM_SMARTNIC_DIR = Path(__file__).resolve().parents[3] / "hbm_smartnic"
if str(HBM_SMARTNIC_DIR) not in sys.path:
    sys.path.insert(0, str(HBM_SMARTNIC_DIR))

from cpuwrite_hbm_common import (
    DIRECT_TOPOLOGY,
    HBM_DATA_ONLY_PKT500_BINARY,
    MIDDLE_TOPOLOGY,
    run_cpuwrite_hbm_dma,
)


COMMON_OPTIONS = {
    "binary": HBM_DATA_ONLY_PKT500_BINARY,
    "packets": 500,
    "sim_cycles": 5_000_000,
    "abs_max_tick": 5_000_000_000,
    "dma_max_outstanding_reads": 32,
    "dma_descriptor_prefetch_depth": 64,
    "dma_packet_prefetch_depth": 32,
    "dma_functional_preload_packets": True,
    "aximm_master_rrob_max_entries": 128,
    "noc_interface_buffer_size": 128,
    "hbm_endpoint_clock": "1.6GHz",
}


def run_direct_case():
    run_cpuwrite_hbm_dma(
        run_label="smartnic_hbm_direct_dma_pkt500_hbmclk1600_buf128_mo32_rrob128_funcpreload",
        topology=DIRECT_TOPOLOGY,
        with_ppe=False,
        **COMMON_OPTIONS,
    )


def run_ppe_case():
    run_cpuwrite_hbm_dma(
        run_label="smartnic_hbm_ppe_dma_pkt500_hbmclk1600_buf128_mo32_rrob128_funcpreload",
        topology=MIDDLE_TOPOLOGY,
        with_ppe=True,
        **COMMON_OPTIONS,
    )
