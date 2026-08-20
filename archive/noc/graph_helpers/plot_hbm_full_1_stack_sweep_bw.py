#!/usr/bin/env python3
"""
Plot aggregate write bandwidth vs number of HBM NMUs from the sweep CSV.

Default input:  src/noc/out/csv/hbm_full_1_stack_sweep_bw.csv
Default output: src/noc/out/graphs/hbm_full_1_stack_sweep_bw.png

Usage:
  python3 src/noc/test/graphs/plot_hbm_full_1_stack_sweep_bw.py
  python3 src/noc/test/graphs/plot_hbm_full_1_stack_sweep_bw.py \\
      --input path/to/hbm_full_1_stack_sweep_bw.csv --output out.png
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

THEORETICAL_MAX_GBPS = 410.0


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[4]
    csv_dir = repo_root / "src" / "noc" / "out" / "csv"
    graph_dir = repo_root / "src" / "noc" / "out" / "graphs"
    parser = argparse.ArgumentParser(
        description="Line plot of HBM sweep aggregate write BW vs num_tg."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=csv_dir / "hbm_full_1_stack_sweep_bw.csv",
        help="CSV from sweep_hbm_full_1_stack (num_tg, aggregate_write_bw_MBps, ...)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=graph_dir / "hbm_full_1_stack_sweep_bw.png",
        help="Output image path",
    )
    parser.add_argument(
        "--theoretical-gbps",
        type=float,
        default=THEORETICAL_MAX_GBPS,
        help="Y value for horizontal reference line (default: 410)",
    )
    parser.add_argument("--dpi", type=int, default=180)
    return parser.parse_args()


def read_series(path: Path) -> tuple[list[int], list[float]]:
    num_tg: list[int] = []
    bw_gbps: list[float] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("num_tg"):
                continue
            try:
                n = int(row["num_tg"])
            except ValueError:
                continue
            bw_field = (row.get("aggregate_write_bw_MBps") or "").strip()
            if not bw_field:
                continue
            try:
                mbps = float(bw_field)
            except ValueError:
                continue
            code = (row.get("gem5_exit_code") or "").strip()
            if code and code != "0":
                continue
            num_tg.append(n)
            bw_gbps.append(mbps / 1000.0)
    return num_tg, bw_gbps


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Input not found: {args.input}")

    x, y = read_series(args.input)
    if len(x) < 1:
        raise SystemExit(f"No plottable rows in {args.input}")

    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    ax.plot(x, y, color="C0", linewidth=2, marker="o", markersize=5, label="Simulated")
    ax.axhline(
        y=args.theoretical_gbps,
        color="C3",
        linestyle=":",
        linewidth=2,
        label="Theoretical maximum",
    )
    ax.set_xlabel("Number of HBM NMUs")
    ax.set_ylabel("Aggregate write bandwidth (GB/s)")
    # ax.set_title("HBM full 1-stack sweep — aggregate write BW vs NMUs")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=args.dpi)
    plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
