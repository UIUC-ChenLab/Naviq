from cpu_ppe_steering_common import run_cpu_ppe_steering_smoke


run_cpu_ppe_steering_smoke(
    steering="five_tuple_hash",
    binary_name="ppe_five_tuple_hash_mmio_x86",
    enable_dma=False,
    sim_cycles=200000,
    abs_max_tick=200000000,
    summary="[CPU PPE five-tuple-hash MMIO smoke] CPU programmed and read back PPE steering entries",
)
