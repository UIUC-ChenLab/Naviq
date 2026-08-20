#!/usr/bin/env python3
"""
Plot Naviq versus Vivado latency validation for size-sweep tests.

By default this plots the fixed 10-transaction subset from:
  - tests/gem5/noc/trusted_results/latency_comp_sizes_gem5.csv
  - tests/gem5/noc/trusted_results/latency_comp_sizes_vivado.csv

Outputs are written under noc_testing/plots/latency_validation/.
"""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
NOC_TESTING_DIR = SCRIPT_DIR.parent
REPO_ROOT = NOC_TESTING_DIR.parent
TRUSTED_RESULTS_DIR = REPO_ROOT / "tests" / "gem5" / "noc" / "trusted_results"
DEFAULT_GEM5_CSV = TRUSTED_RESULTS_DIR / "latency_comp_sizes_gem5.csv"
DEFAULT_VIVADO_CSV = TRUSTED_RESULTS_DIR / "latency_comp_sizes_vivado.csv"
DEFAULT_OUTPUT_DIR = NOC_TESTING_DIR / "plots" / "latency_validation"

SIM_COLORS = {
    "Naviq": "#2ca25f",
    "Vivado": "#de2d26",
}
DEFAULT_FIGSIZE = (7.2, 4.6)


def payload_bytes(df: pd.DataFrame) -> pd.Series:
    """Compute payload bytes per AXI transaction.

    The CSV uses AXI len-style numbering where 0 means one beat, so the
    transaction payload is size_bytes * (len + 1).
    """
    return df["axi_write_size_bytes"] * (df["axi_write_len_beats"] + 1)


def load_and_match(
    gem5_csv: Path,
    vivado_csv: Path,
    transaction_count: int,
) -> pd.DataFrame:
    gem5 = pd.read_csv(gem5_csv)
    vivado = pd.read_csv(vivado_csv)

    gem5 = gem5[gem5["num_write_transactions_cfg"] == transaction_count].copy()
    vivado = vivado[
        vivado["num_write_transactions_cfg"] == transaction_count
    ].copy()

    if gem5.empty:
        raise ValueError(f"No Naviq rows found for {transaction_count} transactions")
    if vivado.empty:
        raise ValueError(f"No Vivado rows found for {transaction_count} transactions")

    gem5["payload_bytes"] = payload_bytes(gem5)
    vivado["payload_bytes"] = payload_bytes(vivado)

    gem5_cols = [
        "name",
        "payload_bytes",
        "axi_write_size_bytes",
        "axi_write_len_beats",
        "gem5_avg_write_lat_cycles",
        "gem5_avg_read_lat_cycles",
    ]
    vivado_cols = [
        "name",
        "payload_bytes",
        "axi_write_size_bytes",
        "axi_write_len_beats",
        "write_latency_avg",
        "read_latency_avg",
    ]

    merged = gem5[gem5_cols].merge(
        vivado[vivado_cols],
        on="name",
        suffixes=("_gem5", "_vivado"),
        validate="one_to_one",
    )

    if merged.empty:
        raise ValueError("No matching Naviq/Vivado test names found")

    for field in [
        "payload_bytes",
        "axi_write_size_bytes",
        "axi_write_len_beats",
    ]:
        left = merged[f"{field}_gem5"]
        right = merged[f"{field}_vivado"]
        if not left.equals(right):
            raise ValueError(f"Matched rows disagree on {field}")

    merged = merged.rename(
        columns={
            "payload_bytes_gem5": "payload_bytes",
            "axi_write_size_bytes_gem5": "axi_write_size_bytes",
            "axi_write_len_beats_gem5": "axi_write_len_beats",
            "gem5_avg_write_lat_cycles": "naviq_write",
            "gem5_avg_read_lat_cycles": "naviq_read",
            "write_latency_avg": "vivado_write",
            "read_latency_avg": "vivado_read",
        }
    )

    return merged.sort_values(
        ["payload_bytes", "axi_write_size_bytes", "axi_write_len_beats"]
    )


def summarize_by_payload(matched: pd.DataFrame) -> pd.DataFrame:
    summary = (
        matched.groupby("payload_bytes", as_index=False)
        .agg(
            naviq_write_mean=("naviq_write", "mean"),
            naviq_write_min=("naviq_write", "min"),
            naviq_write_max=("naviq_write", "max"),
            vivado_write_mean=("vivado_write", "mean"),
            vivado_write_min=("vivado_write", "min"),
            vivado_write_max=("vivado_write", "max"),
            naviq_read_mean=("naviq_read", "mean"),
            naviq_read_min=("naviq_read", "min"),
            naviq_read_max=("naviq_read", "max"),
            vivado_read_mean=("vivado_read", "mean"),
            vivado_read_min=("vivado_read", "min"),
            vivado_read_max=("vivado_read", "max"),
            test_count=("name", "count"),
        )
        .sort_values("payload_bytes")
    )
    return summary


def plot_latency_validation(
    summary: pd.DataFrame,
    output_dir: Path,
    basename: str,
    formats: list[str],
    transaction_count: int,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = []
    x = summary["payload_bytes"]
    unique_payloads = summary["payload_bytes"].tolist()
    tick_values = [
        value
        for value in [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
        if min(unique_payloads) <= value <= max(unique_payloads)
    ]

    for kind, title in [
        ("write", "Average Write Latency"),
        ("read", "Average Read Latency"),
    ]:
        fig, ax = plt.subplots(figsize=DEFAULT_FIGSIZE)

        for sim in ["Naviq", "Vivado"]:
            key = sim.lower()
            mean = summary[f"{key}_{kind}_mean"]
            low = summary[f"{key}_{kind}_min"]
            high = summary[f"{key}_{kind}_max"]

            ax.plot(
                x,
                mean,
                linewidth=2.4,
                color=SIM_COLORS[sim],
                label=sim,
            )
            ax.fill_between(
                x,
                low,
                high,
                color=SIM_COLORS[sim],
                alpha=0.10,
                linewidth=0,
            )

        ax.set_xscale("log", base=2)
        ax.set_xlabel("Transaction Payload (bytes)", fontsize=12)
        ax.set_ylabel("Latency (NoC cycles)", fontsize=12)
        ax.set_title(
            f"Naviq vs Vivado {title} ({transaction_count} transactions)",
            fontsize=13,
        )
        ax.grid(True, which="major", alpha=0.30, linestyle="--", linewidth=0.7)
        ax.grid(True, which="minor", alpha=0.12, linestyle="--", linewidth=0.5)
        ax.tick_params(axis="both", labelsize=11)
        ax.set_xticks(tick_values)
        ax.set_xticklabels([str(value) for value in tick_values])
        ax.set_xlim(min(unique_payloads) * 0.9, max(unique_payloads) * 1.1)
        ax.legend(
            title="Simulator",
            fontsize=11,
            title_fontsize=11,
            loc="upper left",
            frameon=True,
            framealpha=0.95,
        )

        fig.tight_layout()

        for fmt in formats:
            output_path = output_dir / f"{basename}_{kind}.{fmt}"
            fig.savefig(output_path, bbox_inches="tight", dpi=300)
            output_paths.append(output_path)
            print(f"Saved plot to: {output_path}")

        plt.close(fig)

    return output_paths


def print_error_summary(matched: pd.DataFrame) -> None:
    for kind in ["write", "read"]:
        naviq = matched[f"naviq_{kind}"]
        vivado = matched[f"vivado_{kind}"]
        abs_error = (naviq - vivado).abs()
        pct_error = abs_error / vivado.replace(0, pd.NA) * 100

        print(f"{kind.capitalize()} latency error:")
        print(f"  Mean absolute error: {abs_error.mean():.2f} cycles")
        print(f"  Max absolute error:  {abs_error.max():.2f} cycles")
        print(f"  Mean percent error:  {pct_error.mean():.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot Naviq versus Vivado latency validation."
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
        "--transaction-count",
        type=int,
        default=10,
        help="Filter to this num_write_transactions_cfg value (default: 10)",
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
        default=None,
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
        basename = args.basename or (
            f"naviq_vivado_latency_tx{args.transaction_count}"
        )
        matched = load_and_match(
            args.gem5_csv,
            args.vivado_csv,
            args.transaction_count,
        )
        summary = summarize_by_payload(matched)
        plot_latency_validation(
            summary,
            args.output_dir,
            basename,
            args.formats,
            args.transaction_count,
        )
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    print()
    print(
        f"Plotted {len(matched)} matched tests across "
        f"{summary['payload_bytes'].nunique()} payload sizes."
    )
    print_error_summary(matched)


if __name__ == "__main__":
    main()
