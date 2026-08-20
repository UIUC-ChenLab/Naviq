#!/usr/bin/env python3
"""
Plot normalized simulation time bar chart - 1-column format for papers.

gem5 is normalized to 1.0, RTL and SystemC are scaled relative to gem5.
Bars are grouped by test case (hop count + packet count), with small gaps
between different hop groups.

Usage:
    python plot_normalized_bars_1col.py <csv_file> [-o <output_dir>]
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


def extract_hop_count(name: str) -> int:
    match = re.search(r'(\d+)hop', name)
    return int(match.group(1)) if match else 0


def extract_hop_count_str(name: str) -> str:
    match = re.search(r'(\d+hop)', name)
    return match.group(1) if match else 'unknown'


def extract_packet_count(name: str) -> str:
    match = re.search(r'(\d+pkt)', name)
    return match.group(1) if match else 'unknown'


def extract_sim_mode(name: str) -> str:
    if '_gem5' in name.lower():
        return 'Naviq'
    elif '_rtl' in name.lower():
        return 'RTL'
    elif '_tlm' in name.lower() or '_systemc' in name.lower():
        return 'SystemC'
    return 'unknown'


def extract_test_key(name: str) -> str:
    for suffix in ['_gem5', '_rtl', '_tlm', '_systemc']:
        if name.lower().endswith(suffix):
            return name[:-(len(suffix))]
    return name


def plot_normalized_bars(csv_path: Path, output_dir: Path = None) -> None:
    df = pd.read_csv(csv_path)

    df['hop_count'] = df['name'].apply(extract_hop_count)
    df['pkt_count'] = df['name'].apply(extract_packet_count)
    df['sim_mode'] = df['name'].apply(extract_sim_mode)
    df['test_key'] = df['name'].apply(extract_test_key)

    endpoint_types = sorted(df['config'].unique())
    available_modes = [m for m in ['Naviq', 'RTL', 'SystemC'] if m in df['sim_mode'].values]

    if 'Naviq' not in available_modes:
        print("Error: Naviq data required for normalization")
        sys.exit(1)

    for endpoint in endpoint_types:
        subset = df[df['config'] == endpoint]

        test_keys = sorted(
            subset['test_key'].unique(),
            key=lambda x: (
                extract_hop_count(x),
                int(re.search(r'(\d+)pkt', x).group(1)) if re.search(r'(\d+)pkt', x) else 0
            )
        )

        labels = []
        gem5_times = []
        normalized_data = {mode: [] for mode in available_modes}
        x_positions = []

        current_x = 0
        last_hop = None

        # Spacing: tight within a hop group, small gap between groups
        gap_within_group = 1.0
        gap_between_groups = 1.0

        for key in test_keys:
            key_data = subset[subset['test_key'] == key]

            naviq_row = key_data[key_data['sim_mode'] == 'Naviq']
            if naviq_row.empty:
                continue
            naviq_time = naviq_row['sim_time_s'].iloc[0]
            gem5_times.append(naviq_time)

            hop = extract_hop_count(key)
            if last_hop is not None:
                if hop != last_hop:
                    current_x += gap_between_groups
                else:
                    current_x += gap_within_group
            x_positions.append(current_x)
            last_hop = hop

            # Use the same label style as the original: "2hop\n64pkt"
            hop_str = extract_hop_count_str(key)
            pkt_str = extract_packet_count(key)
            labels.append(f"{hop_str}\n{pkt_str}")

            for mode in available_modes:
                mode_row = key_data[key_data['sim_mode'] == mode]
                if not mode_row.empty:
                    normalized_data[mode].append(mode_row['sim_time_s'].iloc[0] / naviq_time)
                else:
                    normalized_data[mode].append(0)

        if not labels:
            continue

        x = np.array(x_positions)
        width = 0.25
        n_modes = len(available_modes)

        # Wider and shorter for single-column format
        fig, ax = plt.subplots(figsize=(5.5, 3.3))

        max_val = max(max(normalized_data[m]) for m in available_modes if normalized_data[m])

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

            # Speedup annotations on bars
            for j, bar in enumerate(bars):
                height = bar.get_height()
                if mode == 'Naviq':
                    # Show raw time for Naviq (compact)
                    raw_time = gem5_times[j]
                    label_text = f'{raw_time:.1f}s' if raw_time < 10 else f'{raw_time:.0f}s'
                    bar_center = bar.get_x() + bar.get_width() / 2 + 0.03
                    ax.text(
                        bar_center, height + max_val * 0.03, label_text,
                        ha='center', va='bottom', fontsize=9, rotation=90
                    )
                elif height > 1.5:
                    bar_center = bar.get_x() + bar.get_width() / 2 + 0.03
                    ax.text(
                        bar_center, height + max_val * 0.01, f'{height:.0f}×',
                        ha='center', va='bottom', fontsize=9, rotation=90
                    )

        ax.set_xlabel('Test Configuration', fontsize=9)
        ax.set_ylabel('Normalized Simulation Time', fontsize=9)
        display_name = 'BRAM' if endpoint == 'pos' else endpoint.upper()
        ax.set_title(
            'CompoNIC vs Vivado Simulation Time',
            fontsize=10
        )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9)
        ax.legend(title='Simulator', fontsize=9, title_fontsize=9,
                  markerscale=1.2, handlelength=1.5)
        ax.tick_params(axis='y', labelsize=8)
        ax.grid(True, axis='y', alpha=0.3, linestyle='--')

        # Baseline line at 1.0
        ax.axhline(y=1, color='gray', linestyle='--', alpha=0.7, linewidth=0.8)

        # Y-axis range
        ax.set_ylim(bottom=0, top=max_val * 1.2)

        # Naviq diamond markers at baseline
        naviq_idx = available_modes.index('Naviq')
        naviq_offset = (naviq_idx - (n_modes - 1) / 2) * width
        ax.scatter(x + naviq_offset, [1] * len(x), marker='D', s=20,
                   color=MODE_COLORS['Naviq'], edgecolor='black', zorder=5,
                   label='_nolegend_', linewidth=0.5)

        # X limits with small padding
        ax.set_xlim(x[0] - 0.5, x[-1] + 0.5)

        plt.tight_layout(pad=0.2)

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path_pdf = output_dir / f"{csv_path.stem}_{endpoint}_bars_1col.pdf"
            output_path_svg = output_dir / f"{csv_path.stem}_{endpoint}_bars_1col.svg"
            plt.savefig(output_path_pdf, format='pdf', bbox_inches='tight')
            plt.savefig(output_path_svg, format='svg', bbox_inches='tight')
            print(f"Saved plot to: {output_path_pdf}")
            print(f"Saved plot to: {output_path_svg}")
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
        description='Plot normalized 1-column bar chart (gem5=1.0).'
    )
    parser.add_argument('csv', type=Path, help='Path to CSV')
    parser.add_argument('--output-dir', '-o', type=Path, default=None,
                        help='Directory to save plot (shows interactively if not specified)')
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    plot_normalized_bars(args.csv, args.output_dir)


if __name__ == '__main__':
    main()
