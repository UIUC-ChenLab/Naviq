from smartnic_limiter_common import run_limiter_case


run_limiter_case(
    "smartnic_limiter_none_v2_pkt100",
    config_name="none",
    period=1,
    allow=1,
    enabled=True,
)
