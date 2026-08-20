#!/usr/bin/env python3
"""
Plot speedup of gem5 over Vivado simulations (RTL or SystemC/TLM).

Speedup = Vivado_time / gem5_time (so speedup > 1 means gem5 is faster)

Usage:
    python plot_speedup.py <csv_file> [-o <output_dir>]

Example:
    python plot_speedup.py results/gem5_rtl_placement_simplified.csv -o plots/
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
    """Extract simulation mode from test name."""
    if '_gem5' in name.lower():
        return 'gem5'
    elif '_rtl' in name.lower():
        return 'RTL'
    elif '_tlm' in name.lower() or '_systemc' in name.lower():
        return 'SystemC'
    return 'unknown'


def extract_test_key(name: str) -> str:
    """Extract the base test key (without sim mode suffix) for matching."""
    # Remove the sim mode suffix to get a key like "pos_2hop_64pkt"
    for suffix in ['_gem5', '_rtl', '_tlm', '_systemc']:
        if name.lower().endswith(suffix):
            return name[:-(len(suffix))]
    return name


def plot_speedup(csv_path: Path, output_dir: Path = None) -> None:
    """
    Plot speedup of gem5 over Vivado (RTL or SystemC).
    
    Speedup = Vivado_time / gem5_time
    """
    df = pd.read_csv(csv_path)

    # Extract metadata
    df['hop_count'] = df['name'].apply(extract_hop_count)
    df['sim_mode'] = df['name'].apply(extract_sim_mode)
    df['test_key'] = df['name'].apply(extract_test_key)
    df['total_data_KB'] = (df['total_packets'] * PACKET_SIZE_BYTES) / 1024

    # Separate gem5 and Vivado data
    gem5_df = df[df['sim_mode'] == 'gem5'].copy()
    vivado_df = df[df['sim_mode'] != 'gem5'].copy()
    
    if gem5_df.empty:
        print("Error: No gem5 data found in CSV")
        sys.exit(1)
    
    # Determine what Vivado mode we're comparing against
    vivado_mode = vivado_df['sim_mode'].iloc[0] if not vivado_df.empty else 'Vivado'
    
    # Merge gem5 with vivado data on test_key
    merged = pd.merge(
        gem5_df[['test_key', 'config', 'hop_count', 'total_data_KB', 'sim_time_s']],
        vivado_df[['test_key', 'sim_time_s', 'sim_mode']],
        on='test_key',
        suffixes=('_gem5', '_vivado')
    )
    
    if merged.empty:
        print("Error: Could not match gem5 runs with Vivado runs")
        sys.exit(1)
    
    # Calculate speedup (Vivado / gem5, so >1 means gem5 is faster)
    merged['speedup'] = merged['sim_time_s_vivado'] / merged['sim_time_s_gem5']
    
    # Get unique endpoint types
    endpoint_types = sorted(merged['config'].unique())

    # Create separate plots for each endpoint type
    for endpoint in endpoint_types:
        fig, ax = plt.subplots(figsize=(10, 7))
        subset = merged[merged['config'] == endpoint]

        # Sort hop counts numerically
        hop_counts = sorted(
            subset['hop_count'].unique(),
            key=lambda x: int(x.replace('hop', '')) if x != 'unknown' else 0
        )

        for hop in hop_counts:
            data = subset[subset['hop_count'] == hop].sort_values('total_data_KB')
            if data.empty:
                continue
            
            color = HOP_COLORS.get(hop, 'gray')
            ax.plot(
                data['total_data_KB'], data['speedup'],
                marker='o', label=hop, color=color,
                linewidth=2, markersize=8
            )

        ax.set_xlabel('Total Data Transferred (KB)', fontsize=12)
        ax.set_ylabel(f'Speedup over {vivado_mode} (×)', fontsize=12)
        # Display name mapping (pos -> BRAM)
        display_name = 'BRAM' if endpoint == 'pos' else endpoint.upper()
        
        ax.set_title(
            f'{display_name} Endpoint - gem5 Speedup over {vivado_mode}',
            fontsize=14
        )
        ax.legend(title='Hop Count', fontsize=10, loc='best')
        ax.grid(True, alpha=0.3)
        
        # Add a horizontal line at speedup=1 for reference
        ax.axhline(y=1, color='gray', linestyle='--', alpha=0.5, label='_nolegend_')
        
        # Set y-axis to start at 0
        ax.set_ylim(bottom=0)

        plt.tight_layout()

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{csv_path.stem}_{endpoint}_speedup.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            print(f"Saved plot to: {output_path}")
        else:
            plt.show()

        plt.close()
    
    # Print summary statistics
    print(f"\nSpeedup Summary ({vivado_mode} → gem5):")
    print(f"  Min speedup:  {merged['speedup'].min():.1f}×")
    print(f"  Max speedup:  {merged['speedup'].max():.1f}×")
    print(f"  Mean speedup: {merged['speedup'].mean():.1f}×")


def main():
    parser = argparse.ArgumentParser(
        description='Plot gem5 speedup over Vivado RTL/SystemC.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: python plot_speedup.py results/gem5_rtl_placement_simplified.csv -o plots/'
    )
    parser.add_argument('csv', type=Path, help='Path to CSV with both gem5 and Vivado data')
    parser.add_argument(
        '--output-dir', '-o', type=Path, default=None,
        help='Directory to save plot (shows interactively if not specified)'
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    plot_speedup(args.csv, args.output_dir)


if __name__ == '__main__':
    main()
