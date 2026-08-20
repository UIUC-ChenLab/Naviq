from hbm_limiter_experiment import run_limiter_case


run_limiter_case(
    "smartnic_hbm_rtl_limiter_none_pkt100",
    config_name="none",
    period=1,
    allow=1,
    enabled=True,
)
