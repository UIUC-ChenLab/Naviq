#!/usr/bin/env python3
"""
Plot Naviq versus Vivado write-latency validation across route distance.

By default this compares:
  - tests/gem5/noc/trusted_results/placement_route_ladder_gem5.csv
  - noc_testing/results/placement_route_ladder_vivado.csv

Outputs are written under noc_testing/plots/distance_validation/.
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
NOC_TESTING_DIR = SCRIPT_DIR.parent
REPO_ROOT = NOC_TESTING_DIR.parent
TRUSTED_RESULTS_DIR = REPO_ROOT / "tests" / "gem5" / "noc" / "trusted_results"
DEFAULT_GEM5_CSV = TRUSTED_RESULTS_DIR / "placement_route_ladder_gem5.csv"
DEFAULT_VIVADO_CSV = (
    NOC_TESTING_DIR / "results" / "placement_route_ladder_vivado.csv"
)
DEFAULT_OUTPUT_DIR = NOC_TESTING_DIR / "plots" / "distance_validation"

BURST_COLORS = {
    4: "#2ca25f",
    16: "#3182bd",
    32: "#de2d26",
}
BURST_MARKERS = {
    4: "o",
    16: "s",
    32: "^",
}
DEFAULT_FIGSIZE = (11.2, 4.8)


def extract_hop_count(name: str) -> int:
    match = re.search(r"ladder_(\d+)hop", name)
    if not match:
        raise ValueError(f"Could not extract hop count from test name: {name}")
    return int(match.group(1))


def load_and_match(gem5_csv: Path, vivado_csv: Path) -> pd.DataFrame:
    gem5 = pd.read_csv(gem5_csv)
    vivado = pd.read_csv(vivado_csv)

    gem5_cols = [
        "name",
        "axi_write_size_bytes",
        "axi_write_len_beats",
        "num_write_transactions_cfg",
        "gem5_avg_write_lat_cycles",
    ]
    vivado_cols = [
        "name",
        "axi_write_size_bytes",
        "axi_write_len_beats",
        "num_write_transactions_cfg",
        "write_latency_avg",
    ]

    merged = gem5[gem5_cols].merge(
        vivado[vivado_cols],
        on="name",
        suffixes=("_gem5", "_vivado"),
        validate="one_to_one",
    )

    if merged.empty:
        raise ValueError("No matching Naviq/Vivado ladder test names found")

    for field in [
        "axi_write_size_bytes",
        "axi_write_len_beats",
        "num_write_transactions_cfg",
    ]:
        left = merged[f"{field}_gem5"]
        right = merged[f"{field}_vivado"]
        if not left.equals(right):
            raise ValueError(f"Matched rows disagree on {field}")

    merged = merged.rename(
        columns={
            "axi_write_size_bytes_gem5": "axi_write_size_bytes",
            "axi_write_len_beats_gem5": "axi_write_len_beats",
            "num_write_transactions_cfg_gem5": "num_write_transactions_cfg",
            "gem5_avg_write_lat_cycles": "naviq_write",
            "write_latency_avg": "vivado_write",
        }
    )
    merged["hop_count"] = merged["name"].apply(extract_hop_count)
    merged["burst_beats"] = merged["axi_write_len_beats"] + 1

    return merged.sort_values(["burst_beats", "hop_count"])


def plot_distance_validation(
    matched: pd.DataFrame,
    output_dir: Path,
    basename: str,
    formats: list[str],
    cdc_offset_cycles: float,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=DEFAULT_FIGSIZE, sharey=True)
    output_paths = []

    matched = matched.copy()
    matched["naviq_write_adjusted"] = (
        matched["naviq_write"] - cdc_offset_cycles
    )

    panels = [
        ("Vivado Write Latency", "vivado_write"),
        (
            f"Naviq Write Latency (-{cdc_offset_cycles:g} CDC cycles)",
            "naviq_write_adjusted",
        ),
    ]

    for ax, (title, latency_col) in zip(axes, panels):
        for burst in sorted(matched["burst_beats"].unique()):
            data = matched[matched["burst_beats"] == burst].sort_values(
                "hop_count"
            )
            burst = int(burst)
            marker = BURST_MARKERS.get(int(burst), "o")
            label_suffix = f"{int(burst)} beats"

            ax.plot(
                data["hop_count"],
                data[latency_col],
                color=BURST_COLORS.get(burst, "gray"),
                linestyle="-",
                linewidth=2.0,
                marker=marker,
                markersize=5.5,
                label=label_suffix,
            )

        ax.set_title(title, fontsize=12)
        ax.set_xlabel("Route Distance (hops)", fontsize=11)
        ax.grid(True, alpha=0.28, linestyle="--", linewidth=0.7)
        ax.tick_params(axis="both", labelsize=10)
        ax.set_xticks(sorted(matched["hop_count"].unique()))

    axes[0].set_ylabel("Average Write Latency (NoC cycles)", fontsize=11)
    axes[0].legend(
        title="Burst Length",
        fontsize=9,
        title_fontsize=9,
        loc="upper left",
        frameon=True,
        framealpha=0.95,
    )

    fig.suptitle("Naviq vs Vivado Distance Validation", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    for fmt in formats:
        output_path = output_dir / f"{basename}.{fmt}"
        fig.savefig(output_path, bbox_inches="tight", dpi=300)
        output_paths.append(output_path)
        print(f"Saved plot to: {output_path}")

    plt.close(fig)
    return output_paths


def print_error_summary(matched: pd.DataFrame, cdc_offset_cycles: float) -> None:
    raw_error = matched["naviq_write"] - matched["vivado_write"]
    adjusted_error = (
        matched["naviq_write"] - cdc_offset_cycles - matched["vivado_write"]
    )

    print("Raw Naviq - Vivado write latency:")
    print(f"  Mean: {raw_error.mean():.2f} cycles")
    print(f"  Min:  {raw_error.min():.2f} cycles")
    print(f"  Max:  {raw_error.max():.2f} cycles")
    print(f"After {cdc_offset_cycles:g}-cycle CDC adjustment:")
    print(f"  Mean: {adjusted_error.mean():.2f} cycles")
    print(f"  Min:  {adjusted_error.min():.2f} cycles")
    print(f"  Max:  {adjusted_error.max():.2f} cycles")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot Naviq versus Vivado distance validation for writes."
    )
    parser.add_argument(
        "--gem5-csv",
        type=Path,
        default=DEFAULT_GEM5_CSV,
        help=f"Naviq/gem5 CSV path (default: {DEFAULT_GEM5_CSV})",
    )
    parser.add_argument(
        "--vivado-csv",
        type=Path,
        default=DEFAULT_VIVADO_CSV,
        help=f"Vivado CSV path (default: {DEFAULT_VIVADO_CSV})",
    )
    parser.add_argument(
        "--cdc-offset-cycles",
        type=float,
        default=2.0,
        help="Cycles subtracted from Naviq in the adjusted panel (default: 2)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for plots (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--basename",
        default="naviq_vivado_distance_write",
        help="Output file basename without extension",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["pdf", "svg", "png"],
        choices=["pdf", "svg", "png"],
        help="Output formats to write (default: pdf svg png)",
    )
    args = parser.parse_args()

    for csv_path in [args.gem5_csv, args.vivado_csv]:
        if not csv_path.exists():
            print(f"Error: CSV not found: {csv_path}", file=sys.stderr)
            sys.exit(1)

    try:
        matched = load_and_match(args.gem5_csv, args.vivado_csv)
        plot_distance_validation(
            matched,
            args.output_dir,
            args.basename,
            args.formats,
            args.cdc_offset_cycles,
        )
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    print()
    print(
        f"Plotted {len(matched)} matched write tests across "
        f"{matched['hop_count'].nunique()} route distances and "
        f"{matched['burst_beats'].nunique()} burst lengths."
    )
    print_error_summary(matched, args.cdc_offset_cycles)


if __name__ == "__main__":
    main()
