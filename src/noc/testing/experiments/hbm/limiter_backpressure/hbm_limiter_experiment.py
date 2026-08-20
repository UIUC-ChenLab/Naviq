import sys
from pathlib import Path


HBM_SMARTNIC_DIR = Path(__file__).resolve().parents[3] / "hbm_smartnic"
if str(HBM_SMARTNIC_DIR) not in sys.path:
    sys.path.insert(0, str(HBM_SMARTNIC_DIR))

from cpuwrite_hbm_common import HBM_LIMITER_PKT100_BINARY, run_cpuwrite_hbm_dma
from validate import load_csv_row, load_json, validate_limiter_run


def run_limiter_case(run_label, *, config_name, period, allow, enabled):
    limiter_config = {
        "enabled": enabled,
        "node_type": "throttle",
        "config_name": config_name,
        "rate_setting": f"period{period}_allow{allow}",
        "scope": "csr_programmed_plus_axis_backpressure_v1",
        "period": period,
        "allow": allow,
        "reset_cycles": 16,
    }
    run_cpuwrite_hbm_dma(
        run_label=run_label,
        binary=HBM_LIMITER_PKT100_BINARY,
        packets=100,
        sim_cycles=2_000_000,
        abs_max_tick=2_000_000_000,
        limiter_config=limiter_config,
    )
    validate_limiter_run(run_label, load_json(run_label), load_csv_row(run_label))

    print(f"[{run_label}] PASS")
