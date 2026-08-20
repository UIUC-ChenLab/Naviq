from hbm_limiter_experiment import run_limiter_case


run_limiter_case(
    "smartnic_hbm_rtl_limiter_strong_pkt100",
    config_name="strong",
    period=16,
    allow=1,
    enabled=True,
)
