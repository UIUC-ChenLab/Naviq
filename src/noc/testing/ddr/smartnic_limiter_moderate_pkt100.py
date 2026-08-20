from smartnic_limiter_common import run_limiter_case


run_limiter_case(
    "smartnic_limiter_moderate_v2_pkt100",
    config_name="moderate",
    period=8,
    allow=2,
    enabled=True,
)
