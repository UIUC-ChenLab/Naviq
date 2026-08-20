#!/usr/bin/env python3
"""
Plot placement test results: simulation time vs data transferred.

Creates subplots by endpoint type (BRAM, HBM, DDR), with lines grouped by
hop count (2hop, 8hop, 16hop, 32hop) and simulation mode (RTL vs SystemC).

Usage:
    python plot_placement.py <csv_file> [-o <output_dir>]

Example:
    python plot_placement.py results/placement_simplified.csv -o plots/
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# Assumed packet size for data calculation
PACKET_SIZE_BYTES = 512

# Color mapping for hop counts
HOP_COLORS = {
    '2hop': 'blue',
    '8hop': 'orange',
    '16hop': 'green',
    '32hop': 'red'
}


def extract_hop_count(name: str) -> str:
    """Extract hop count (e.g., '2hop', '8hop') from test name."""
    match = re.search(r'(\d+hop)', name)
    return match.group(1) if match else 'unknown'


def extract_sim_mode(name: str) -> str:
    """Extract simulation mode (RTL, SystemC, or gem5) from test name."""
    if '_gem5' in name.lower():
        return 'gem5'
    elif '_rtl' in name.lower():
        return 'RTL'
    elif '_tlm' in name.lower() or '_systemc' in name.lower():
        return 'SystemC'
    return 'unknown'


def plot_placement_results(csv_path: Path, output_dir: Path = None) -> None:
    """
    Plot simulation time vs data transferred for placement tests.

    Creates one subplot per endpoint type (BRAM, HBM, DDR), each with lines
    for different hop counts. RTL uses solid lines with circle markers,
    SystemC uses dotted lines with square markers, gem5 uses dashed lines
    with triangle markers.

    Args:
        csv_path: Path to the simplified CSV file with columns:
                  name, config, sim_time_s, total_packets
        output_dir: Directory to save the plot. If None, displays interactively.
    """
    df = pd.read_csv(csv_path)

    # Extract metadata from test names
    df['hop_count'] = df['name'].apply(extract_hop_count)
    df['sim_mode'] = df['name'].apply(extract_sim_mode)

    # Convert units: seconds to minutes, packets to KB
    df['sim_time_min'] = df['sim_time_s'] / 60
    df['total_data_KB'] = (df['total_packets'] * PACKET_SIZE_BYTES) / 1024

    # Get unique endpoint types
    endpoint_types = sorted(df['config'].unique())

    # Create separate plots for each endpoint type
    for endpoint in endpoint_types:
        fig, ax = plt.subplots(figsize=(10, 7))
        subset = df[df['config'] == endpoint]

        # Sort hop counts numerically
        hop_counts = sorted(
            subset['hop_count'].unique(),
            key=lambda x: int(x.replace('hop', '')) if x != 'unknown' else 0
        )

        for hop in hop_counts:
            for sim_mode in ['RTL', 'SystemC', 'gem5']:
                data = subset[(subset['hop_count'] == hop) & (subset['sim_mode'] == sim_mode)]
                if data.empty:
                    continue
                data = data.sort_values('total_data_KB')

                # Different styles for each sim mode
                if sim_mode == 'RTL':
                    linestyle, marker = '-', 'o'
                elif sim_mode == 'SystemC':
                    linestyle, marker = ':', 's'
                else:  # gem5
                    linestyle, marker = '--', '^'
                
                color = HOP_COLORS.get(hop, 'gray')

                ax.plot(
                    data['total_data_KB'], data['sim_time_min'],
                    marker=marker, label=f"{hop} - {sim_mode}", color=color,
                    linewidth=2, linestyle=linestyle, markersize=6
                )

        ax.set_xlabel('Total Data Transferred (KB)', fontsize=14)
        ax.set_ylabel('Simulation Time (minutes)', fontsize=14)
        # Display name mapping (pos -> BRAM)
        display_name = 'BRAM' if endpoint == 'pos' else endpoint.upper()
        
        ax.set_title(
            f'{display_name} Endpoint\n(RTL: solid ●, SystemC: dotted ■, gem5: dashed ▲)',
            fontsize=16
        )
        ax.legend(title='Hop Count - Mode', fontsize=12, loc='best', handlelength=4, title_fontsize=13)
        ax.tick_params(axis='both', which='major', labelsize=12)
        ax.grid(True, alpha=0.3)
        # ax.set_xscale('log')

        # Set explicit x-axis ticks
        unique_data = sorted(subset['total_data_KB'].unique())
        ax.set_xticks(unique_data)
        ax.set_xticklabels([f"{int(x)}" for x in unique_data], rotation=45, ha='right')

        plt.tight_layout()

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{csv_path.stem}_{endpoint}_plot.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            print(f"Saved plot to: {output_path}")
        else:
            plt.show()

        plt.close()


def main():
    parser = argparse.ArgumentParser(
        description='Plot placement test results (hop count vs simulation time).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: python plot_placement.py results/placement_simplified.csv -o plots/'
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

    plot_placement_results(args.csv, args.output_dir)


if __name__ == '__main__':
    main()
