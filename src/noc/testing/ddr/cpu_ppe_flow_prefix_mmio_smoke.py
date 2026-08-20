from cpu_ppe_steering_common import run_cpu_ppe_steering_smoke


run_cpu_ppe_steering_smoke(
    steering="flow_prefix",
    binary_name="ppe_flow_prefix_mmio_x86",
    enable_dma=False,
    sim_cycles=200000,
    abs_max_tick=200000000,
    summary="[CPU PPE flow-prefix MMIO smoke] CPU programmed and read back PPE steering entry",
)
