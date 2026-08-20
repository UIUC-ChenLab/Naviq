from hbm_limiter_experiment import run_limiter_case


run_limiter_case(
    "smartnic_hbm_rtl_limiter_moderate_pkt100",
    config_name="moderate",
    period=8,
    allow=1,
    enabled=True,
)
