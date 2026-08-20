#!/usr/bin/env python3
"""
Plot normalized simulation time bar chart.

gem5 is normalized to 1.0, RTL and SystemC are scaled relative to gem5.
Bars are grouped by test case (hop count + packet count).

Usage:
    python plot_normalized_bars.py <csv_file> [-o <output_dir>]

Example:
    python plot_normalized_bars.py results/all_placement_simplified.csv -o plots/
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Color mapping for sim modes
MODE_COLORS = {
    'Naviq': '#2ecc71',     # Green
    'RTL': '#e74c3c',       # Red
    'SystemC': '#3498db',   # Blue
}


def extract_hop_count(name: str) -> str:
    """Extract hop count (e.g., '2hop', '8hop') from test name."""
    match = re.search(r'(\d+hop)', name)
    return match.group(1) if match else 'unknown'


def extract_packet_count(name: str) -> str:
    """Extract packet count (e.g., '64pkt', '256pkt') from test name."""
    match = re.search(r'(\d+pkt)', name)
    return match.group(1) if match else 'unknown'


def extract_sim_mode(name: str) -> str:
    """Extract simulation mode from test name."""
    if '_gem5' in name.lower():
        return 'Naviq'
    elif '_rtl' in name.lower():
        return 'RTL'
    elif '_tlm' in name.lower() or '_systemc' in name.lower():
        return 'SystemC'
    return 'unknown'


def extract_test_key(name: str) -> str:
    """Extract the base test key (without sim mode suffix) for matching."""
    for suffix in ['_gem5', '_rtl', '_tlm', '_systemc']:
        if name.lower().endswith(suffix):
            return name[:-(len(suffix))]
    return name


def plot_normalized_bars(csv_path: Path, output_dir: Path = None) -> None:
    """
    Plot normalized bar chart with gem5=1.0 as baseline.
    """
    df = pd.read_csv(csv_path)

    # Extract metadata
    df['hop_count'] = df['name'].apply(extract_hop_count)
    df['pkt_count'] = df['name'].apply(extract_packet_count)
    df['sim_mode'] = df['name'].apply(extract_sim_mode)
    df['test_key'] = df['name'].apply(extract_test_key)

    # Get unique endpoint types
    endpoint_types = sorted(df['config'].unique())

    # Determine which modes are present
    available_modes = [m for m in ['Naviq', 'RTL', 'SystemC'] if m in df['sim_mode'].values]
    
    if 'Naviq' not in available_modes:
        print("Error: Naviq data required for normalization")
        sys.exit(1)

    for endpoint in endpoint_types:
        subset = df[df['config'] == endpoint]
        
        # Get unique test keys for this endpoint
        test_keys = sorted(
            subset['test_key'].unique(),
            key=lambda x: (
                int(re.search(r'(\d+)hop', x).group(1)) if re.search(r'(\d+)hop', x) else 0,
                int(re.search(r'(\d+)pkt', x).group(1)) if re.search(r'(\d+)pkt', x) else 0
            )
        )
        
        # Build data for plotting
        labels = []
        gem5_times = []
        normalized_data = {mode: [] for mode in available_modes}
        
        for key in test_keys:
            key_data = subset[subset['test_key'] == key]
            
            # Get Naviq time for normalization
            naviq_row = key_data[key_data['sim_mode'] == 'Naviq']
            if naviq_row.empty:
                continue
            naviq_time = naviq_row['sim_time_s'].iloc[0]
            gem5_times.append(naviq_time)
            
            # Create label (e.g., "2hop\n64pkt")
            hop = extract_hop_count(key)
            pkt = extract_packet_count(key)
            labels.append(f"{hop}\n{pkt}")
            
            # Normalize all modes relative to Naviq
            for mode in available_modes:
                mode_row = key_data[key_data['sim_mode'] == mode]
                if not mode_row.empty:
                    normalized_data[mode].append(mode_row['sim_time_s'].iloc[0] / naviq_time)
                else:
                    normalized_data[mode].append(0)
        
        if not labels:
            continue
        
        # Create figure
        fig, ax = plt.subplots(figsize=(14, 7))
        plt.subplots_adjust(left=0.08)  # Add left margin for y-axis tick labels
        
        x = np.arange(len(labels))
        width = 0.25
        n_modes = len(available_modes)
        
        # Plot bars for each mode
        for i, mode in enumerate(available_modes):
            offset = (i - (n_modes - 1) / 2) * width
            bars = ax.bar(
                x + offset, 
                normalized_data[mode], 
                width, 
                label=mode,
                color=MODE_COLORS.get(mode, 'gray'),
                edgecolor='black',
                linewidth=0.5
            )
            
            # Add value labels on bars
            for j, bar in enumerate(bars):
                height = bar.get_height()
                if mode == 'Naviq':
                    # Show raw time for Naviq
                    raw_time = gem5_times[j]
                    label = f'{raw_time:.1f}s' if raw_time < 10 else f'{raw_time:.0f}s'
                    ax.annotate(
                        label,
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 8),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=14, rotation=90
                    )
                elif height > 1.5:
                    # Show speedup for RTL/SystemC
                    ax.annotate(
                        f'{height:.0f}×',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=14, rotation=90
                    )
        
        ax.set_xlabel('Test Configuration', fontsize=14)
        ax.set_ylabel('Normalized Simulation Time (Naviq = 1.0)', fontsize=18)
        # Display name mapping (pos -> BRAM)
        display_name = 'BRAM' if endpoint == 'pos' else endpoint.upper()
        
        ax.set_title(
            f'{display_name} Endpoint - Simulation Time Comparison\n(Lower is faster, Naviq normalized to 1.0)',
            fontsize=14
        )
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=13)
        ax.legend(title='Simulator', fontsize=12)
        ax.tick_params(axis='y', labelsize=14)  # Bigger y-axis tick numbers
        ax.grid(True, axis='y', alpha=0.3)
        
        # Add horizontal line at 1.0
        ax.axhline(y=1, color='gray', linestyle='--', alpha=0.7, linewidth=1)
        
        # Set y-axis to start at 0 with some top margin for labels
        max_val = max(max(normalized_data[m]) for m in available_modes if normalized_data[m])
        ax.set_ylim(bottom=0, top=max_val * 1.15)
        
        # Add diamond markers for Naviq at the baseline (since bars are too small to see)
        naviq_idx = available_modes.index('Naviq')
        naviq_offset = (naviq_idx - (n_modes - 1) / 2) * width
        ax.scatter(x + naviq_offset, [1] * len(x), marker='D', s=50, 
                   color=MODE_COLORS['Naviq'], edgecolor='black', zorder=5, label='_nolegend_')

        plt.tight_layout()
        
        # Reduce left/right margins by extending x limits closer to bars
        ax.set_xlim(-0.5, len(labels) - 0.5)

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{csv_path.stem}_{endpoint}_bars.svg"
            plt.savefig(output_path, format='svg', bbox_inches='tight')
            print(f"Saved plot to: {output_path}")
        else:
            plt.show()

        plt.close()
    
    # Print summary
    print(f"\nNormalization Summary:")
    for mode in available_modes:
        if mode != 'Naviq':
            all_vals = [v for v in normalized_data[mode] if v > 0]
            if all_vals:
                print(f"  {mode}: {min(all_vals):.0f}× - {max(all_vals):.0f}× slower than Naviq")


def main():
    parser = argparse.ArgumentParser(
        description='Plot normalized simulation time bar chart (gem5=1.0).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: python plot_normalized_bars.py results/all_placement_simplified.csv -o plots/'
    )
    parser.add_argument('csv', type=Path, help='Path to CSV with gem5, RTL, and/or SystemC data')
    parser.add_argument(
        '--output-dir', '-o', type=Path, default=None,
        help='Directory to save plot (shows interactively if not specified)'
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    plot_normalized_bars(args.csv, args.output_dir)


if __name__ == '__main__':
    main()
