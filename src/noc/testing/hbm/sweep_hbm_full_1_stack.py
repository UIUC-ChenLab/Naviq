#!/usr/bin/env python3
"""
Sweep num_tgs = 1..32: run the same gem5 invocation as hbm_full_1_stack_16GB.py,
sum all "Achieved Write BW = ..." lines each run, write CSV under src/noc/out/csv.

Usage (from repo root):

  python3 src/noc/testing/hbm/sweep_hbm_full_1_stack.py
  python3 src/noc/testing/hbm/sweep_hbm_full_1_stack.py --gem5 build/NULL/gem5.opt
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path


HBM_DIR = Path(__file__).resolve().parent

if str(HBM_DIR) not in sys.path:
    sys.path.insert(0, str(HBM_DIR))
GENERIC_DIR = HBM_DIR.parent / "generic"
if str(GENERIC_DIR) not in sys.path:
    sys.path.insert(0, str(GENERIC_DIR))

import hbm_full_1_stack_16GB as hbm  # noqa: E402

REPO_ROOT = hbm.REPO_ROOT
from generic_v3_smoke_common import build_aximm_param_overrides  # noqa: E402

WRITE_BW_RE = re.compile(r"Achieved Write BW\s*=\s*([0-9.]+)")

DEFAULT_OUT = (
    REPO_ROOT / "src" / "noc" / "out" / "csv" / "hbm_full_1_stack_sweep_bw.csv"
)


def _default_gem5_relpath() -> str:
    """Path relative to repo root (for subprocess cwd=REPO_ROOT)."""
    for name in ("gem5.opt", "gem5.debug", "gem5.fast"):
        rel = f"build/NULL/{name}"
        if (REPO_ROOT / rel).is_file():
            return rel
    return "build/NULL/gem5.opt"


def _repo_rel(path_str: str) -> str:
    """Prefer repo-relative strings for argv when under REPO_ROOT."""
    p = Path(path_str)
    if not p.is_absolute():
        return path_str.replace("\\", "/")
    try:
        return os.path.relpath(p, REPO_ROOT).replace("\\", "/")
    except ValueError:
        return path_str


def _build_gem5_cmd(num_tgs: int, gem5_argv0: str) -> list[str]:
    sat_tgs = [f"hbm_sat_tg_{idx:02d}" for idx in range(num_tgs)]
    connections_json = hbm._filtered_connections_json_for_num_tgs(num_tgs)
    param_overrides = (
        build_aximm_param_overrides(
            sat_tgs,
            num_transactions=100,
            beat_size_bytes=32,
            transaction_size_bytes=hbm.HBM_TRANSACTION_SIZE_BYTES,
            bandwidth_MBps=0,
            max_outstanding_writes=32,
            align_addresses=False,
            address_distribution="INCREMENT",
            address_increment_bytes=hbm.HBM_TRANSACTION_SIZE_BYTES,
            awid_distribution="INCREMENT",
            min_awid=0,
            max_awid=3,
        )
        + hbm._split_pc_address_overrides(sat_tgs)
    )
    cmd: list[str] = [
        gem5_argv0.replace("\\", "/"),
        "src/noc/setup/noc_setup_config.py",
        "--noc-topology",
        _repo_rel(os.fspath(hbm.TOPOLOGY_DIR)),
        "--connections-json",
        _repo_rel(connections_json),
        "--placement-json",
        _repo_rel(os.fspath(hbm.PLACEMENT_JSON)),
        "--num-packets",
        "64",
        "--abs-max-tick",
        "10000000000",
    ]
    for override in param_overrides:
        cmd.extend(["--param", override])
    return cmd


def _sum_achieved_write_bw_mb_s(text: str) -> float:
    return sum(float(m.group(1)) for m in WRITE_BW_RE.finditer(text))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HBM full 1-stack num_tgs sweep; aggregate Achieved Write BW per run."
    )
    parser.add_argument(
        "--gem5",
        type=str,
        default=None,
        help="gem5 binary relative to repo root, e.g. build/NULL/gem5.opt (default: auto)",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output CSV (default: {DEFAULT_OUT})",
    )
    parser.add_argument("--min-tgs", type=int, default=1)
    parser.add_argument("--max-tgs", type=int, default=32)
    args = parser.parse_args()

    gem5_in = (args.gem5 or _default_gem5_relpath()).replace("\\", "/")
    gem5_path = Path(gem5_in)
    if gem5_path.is_absolute():
        gem5_ok = gem5_path.is_file()
        gem5_cmd0 = gem5_in
    else:
        gem5_ok = (REPO_ROOT / gem5_in).is_file()
        gem5_cmd0 = gem5_in
    if not gem5_ok:
        print(f"error: gem5 binary not found: {gem5_in}", file=sys.stderr)
        return 1

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[int, str, int]] = []

    for num_tg in range(args.min_tgs, args.max_tgs + 1):
        cmd = _build_gem5_cmd(num_tg, gem5_cmd0)
        print(f"\n=== num_tgs={num_tg} ===", flush=True)
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        text = proc.stdout + "\n" + proc.stderr
        if proc.returncode != 0:
            print(
                f"warning: gem5 exit {proc.returncode} for num_tgs={num_tg}",
                file=sys.stderr,
            )
            rows.append((num_tg, "", proc.returncode))
            continue
        agg = _sum_achieved_write_bw_mb_s(text)
        print(
            f"num_tgs={num_tg} aggregate_write_bw_MBps (sum) = {agg:.6f}",
            flush=True,
        )
        rows.append((num_tg, f"{agg:.6f}", proc.returncode))

    with args.out_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["num_tg", "aggregate_write_bw_MBps", "gem5_exit_code"])
        writer.writerows(rows)

    print(f"\nWrote {args.out_csv}")
    return 0 if all(code == 0 for _, _, code in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
