#!/usr/bin/env python3
"""
Plot simulation time vs total data transferred from simplified CSV files.

Designed for all-to-all topology results with configs like "1to1", "2to2", etc.
Supports comparison between RTL and SystemC simulation modes.

Usage:
    python plot_results.py <csv_file> [-o <output_dir>]

Example:
    python plot_results.py results/vivado_all_to_all_simplified.csv -o plots/
"""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# Assumed packet size for data calculation
PACKET_SIZE_BYTES = 512


def plot_sim_time_vs_data(csv_path: Path, output_dir: Path = None) -> None:
    """
    Plot simulation time (y-axis) vs total data transferred (x-axis).

    Lines are grouped by configuration (1to1, 2to2, etc.) and simulation mode
    (RTL vs SystemC). RTL uses solid lines with circle markers, SystemC uses
    dotted lines with square markers.

    Args:
        csv_path: Path to the simplified CSV file with columns:
                  name, config, sim_time_s, total_packets
        output_dir: Directory to save the plot. If None, displays interactively.
    """
    df = pd.read_csv(csv_path)

    # Detect simulation mode from test name
    df['sim_mode'] = df['name'].apply(
        lambda x: 'SystemC' if ('systemc' in x.lower() or 'tlm' in x.lower()) else 'RTL'
    )

    # Convert units: packets to KB, seconds to minutes
    df['total_data_KB'] = (df['total_packets'] * PACKET_SIZE_BYTES) / 1024
    df['sim_time_min'] = df['sim_time_s'] / 60

    fig, ax = plt.subplots(figsize=(12, 7))

    # Sort configs numerically (1to1 < 2to2 < 4to4 < ...)
    configs = sorted(
        df['config'].unique(),
        key=lambda x: int(x.split('to')[0]) if 'to' in x else 0
    )

    colors = plt.cm.tab10.colors

    for i, config in enumerate(configs):
        for sim_mode in ['RTL', 'SystemC']:
            subset = df[(df['config'] == config) & (df['sim_mode'] == sim_mode)]
            if subset.empty:
                continue
            subset = subset.sort_values('total_data_KB')

            linestyle = '-' if sim_mode == 'RTL' else ':'
            marker = 'o' if sim_mode == 'RTL' else 's'
            label = f"{config} - {sim_mode}"

            ax.plot(
                subset['total_data_KB'], subset['sim_time_min'],
                marker=marker, label=label, color=colors[i % len(colors)],
                linewidth=2, linestyle=linestyle, markersize=6
            )

    ax.set_xlabel('Total Data Transferred (KB)', fontsize=14)
    ax.set_ylabel('Simulation Time (minutes)', fontsize=14)
    ax.set_title(
        'Simulation Time vs Data Transferred (RTL: solid ●, SystemC: dotted ■)',
        fontsize=16
    )
    ax.legend(title='Configuration - Mode', loc='best', fontsize=12, ncol=2, handlelength=4, title_fontsize=13)
    ax.tick_params(axis='both', which='major', labelsize=12)
    ax.grid(True, alpha=0.3)
    # ax.set_xscale('log')

    # Set explicit x-axis ticks at actual data values
    unique_data = sorted(df['total_data_KB'].unique())
    ax.set_xticks(unique_data)
    ax.set_xticklabels([f"{int(x)}" for x in unique_data], rotation=45, ha='right')

    plt.tight_layout()

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{csv_path.stem}_plot.png"
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Saved plot to: {output_path}")
    else:
        plt.show()

    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description='Plot simulation time vs total data transferred.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: python plot_results.py results/simplified.csv -o plots/'
    )
    parser.add_argument('csv', type=Path, help='Path to simplified CSV file')
    parser.add_argument(
        '--output-dir', '-o', type=Path, default=None,
        help='Directory to save plot (shows interactively if not specified)'
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    plot_sim_time_vs_data(args.csv, args.output_dir)


if __name__ == '__main__':
    main()
