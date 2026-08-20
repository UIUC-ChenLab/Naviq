import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
NOC_ROOT = THIS_DIR.parents[1]
REPO_ROOT = NOC_ROOT.parents[1]
LEGACY_SETUP_DIR = NOC_ROOT / "setup" / "legacy"
if str(LEGACY_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_SETUP_DIR))

from noc_cpu_ddr_dma_config import run_cpu_hbm_dma_test


DIRECT_TOPOLOGY = "src/noc/topology/topologies/cpu/cpu_hbm_dma_axis"
MIDDLE_TOPOLOGY = "src/noc/topology/topologies/cpu/cpu_hbm_dma_ppe_base_axis"
PROGRAMS_DIR = REPO_ROOT / "src" / "noc" / "cpu" / "programs"


HBM_DATA_ONLY_PKT500_BINARY = PROGRAMS_DIR / "ddr_dma_control_data_only_hbm_cpuwrite_pkt500_x86"
HBM_LIMITER_PKT100_BINARY = PROGRAMS_DIR / "ddr_dma_control_data_only_limiter_hbm_cpuwrite_pkt100_x86"


def run_cpuwrite_hbm_dma(
    *,
    run_label=None,
    binary,
    packets,
    topology=MIDDLE_TOPOLOGY,
    with_ppe=True,
    offload="none",
    sim_cycles=2_000_000,
    abs_max_tick=2_000_000_000,
    limiter_config=None,
    backpressure_config=None,
    scratch_read_burst_bytes=None,
    dma_max_outstanding_reads=None,
    dma_descriptor_prefetch_depth=None,
    dma_packet_prefetch_depth=None,
    dma_post_preload_read_delay_cycles=None,
    dma_fixed_payload_bytes=None,
    dma_packet_stride=None,
    dma_functional_preload_packets=None,
    nsu_read_response_gap_cycles=None,
    nmu_read_response_delay_cycles=None,
    aximm_master_rrob_max_entries=None,
    noc_interface_buffer_size=None,
    hbm_endpoint_clock=None,
):
    def configure_options(options):
        options.binary = str(binary)
        options.num_packets = packets
        options.sim_cycles = max(options.sim_cycles, sim_cycles)
        options.abs_max_tick = max(options.abs_max_tick, abs_max_tick)
        options.post_cpu_exit_sim_ticks = abs_max_tick
        if scratch_read_burst_bytes is not None:
            options.cpu_scratch_read_burst_bytes = scratch_read_burst_bytes
        if dma_max_outstanding_reads is not None:
            options.dma_max_outstanding_reads = dma_max_outstanding_reads
        if dma_descriptor_prefetch_depth is not None:
            options.dma_descriptor_prefetch_depth = dma_descriptor_prefetch_depth
        if dma_packet_prefetch_depth is not None:
            options.dma_packet_prefetch_depth = dma_packet_prefetch_depth
        if dma_post_preload_read_delay_cycles is not None:
            options.dma_post_preload_read_delay_cycles = (
                dma_post_preload_read_delay_cycles
            )
        if dma_fixed_payload_bytes is not None:
            options.dma_fixed_payload_bytes = dma_fixed_payload_bytes
        if dma_packet_stride is not None:
            options.dma_packet_stride = dma_packet_stride
        if dma_functional_preload_packets is not None:
            options.dma_functional_preload_packets = dma_functional_preload_packets
        if nsu_read_response_gap_cycles is not None:
            options.nsu_read_response_gap_cycles = nsu_read_response_gap_cycles
        if nmu_read_response_delay_cycles is not None:
            options.nmu_read_response_delay_cycles = nmu_read_response_delay_cycles
        if aximm_master_rrob_max_entries is not None:
            options.aximm_master_rrob_max_entries = aximm_master_rrob_max_entries
        if noc_interface_buffer_size is not None:
            options.noc_interface_buffer_size = noc_interface_buffer_size
        if hbm_endpoint_clock is not None:
            options.ddr_endpoint_clock = hbm_endpoint_clock
        if run_label is not None:
            options.metrics_run_label = run_label

    run_cpu_hbm_dma_test(
        topology,
        with_ppe=with_ppe and limiter_config is None and backpressure_config is None,
        configure_options=configure_options,
        offload=offload,
        limiter_config=limiter_config,
        backpressure_config=backpressure_config,
        map_cpu_scratch=scratch_read_burst_bytes is not None,
        cpu_writes_descriptors=True,
        cpu_init_scratch=True,
    )
