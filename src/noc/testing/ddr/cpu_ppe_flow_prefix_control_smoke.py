from cpu_ppe_steering_common import run_cpu_ppe_steering_smoke


run_cpu_ppe_steering_smoke(
    steering="flow_prefix",
    binary_name="ppe_flow_prefix_control_x86",
    enable_dma=True,
    sim_cycles=1000000,
    abs_max_tick=1000000000,
    summary="[CPU PPE flow-prefix control smoke] CPU programmed PPE steering table",
)
