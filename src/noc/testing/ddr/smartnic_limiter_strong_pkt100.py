from smartnic_limiter_common import run_limiter_case


run_limiter_case(
    "smartnic_limiter_strong_v2_pkt100",
    config_name="strong",
    period=16,
    allow=1,
    enabled=True,
)
