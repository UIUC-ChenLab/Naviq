from cpu_ppe_steering_common import run_cpu_ppe_steering_smoke


run_cpu_ppe_steering_smoke(
    steering="five_tuple_hash",
    binary_name="ppe_five_tuple_hash_control_x86",
    enable_dma=True,
    sim_cycles=1000000,
    abs_max_tick=1000000000,
    summary="[CPU PPE five-tuple-hash control smoke] CPU programmed PPE steering table",
)
