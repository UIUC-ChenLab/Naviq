#!/usr/bin/env python3
"""
Generate a comparison table of Vivado vs gem5 latency and bandwidth metrics.

Reads placement test results and produces a side-by-side comparison table
showing min/avg/max latency and bandwidth for both simulators.

Usage:
    python generate_comparison_table.py --vivado <vivado.csv> --gem5 <gem5.csv> [-o <output>] [--format latex|csv|markdown]

Example:
    python generate_comparison_table.py \
        --vivado results/vivado_placement_retest.csv \
        --gem5 results/gem5_placement.csv \
        -o results/comparison_table.tex --format latex
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd


def extract_test_key(name: str) -> str:
    """Extract base test key for matching (e.g., 'pos_2hop_64pkt')."""
    # Remove _rtl, _tlm, _gem5 suffix
    for suffix in ['_gem5', '_rtl', '_tlm', '_systemc']:
        if name.lower().endswith(suffix):
            return name[:-(len(suffix))]
    return name


def extract_sim_mode(name: str) -> str:
    """Extract simulation mode from test name."""
    if '_rtl' in name.lower():
        return 'rtl'
    elif '_tlm' in name.lower() or '_systemc' in name.lower():
        return 'tlm'
    return 'unknown'


def load_vivado_data(csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load Vivado results and return separate RTL and TLM dataframes."""
    df = pd.read_csv(csv_path)
    
    # Filter out HBM tests
    df = df[~df['name'].str.contains('hbm', case=False)]
    
    df['test_key'] = df['name'].apply(extract_test_key)
    df['sim_mode'] = df['name'].apply(extract_sim_mode)
    
    # Select relevant columns
    cols = [
        'test_key', 'sim_mode',
        'achieved_write_bandwidth_MBps', 'achieved_read_bandwidth_MBps',
        'write_latency_min', 'write_latency_avg', 'write_latency_max',
        'read_latency_min', 'read_latency_avg', 'read_latency_max'
    ]
    df = df[cols]
    
    # Split RTL and TLM
    rtl_df = df[df['sim_mode'] == 'rtl'].copy()
    tlm_df = df[df['sim_mode'] == 'tlm'].copy()
    
    # Rename columns for RTL
    rtl_df = rtl_df.rename(columns={
        'achieved_write_bandwidth_MBps': 'rtl_write_bw',
        'achieved_read_bandwidth_MBps': 'rtl_read_bw',
        'write_latency_min': 'rtl_wr_lat_min',
        'write_latency_avg': 'rtl_wr_lat_avg',
        'write_latency_max': 'rtl_wr_lat_max',
        'read_latency_min': 'rtl_rd_lat_min',
        'read_latency_avg': 'rtl_rd_lat_avg',
        'read_latency_max': 'rtl_rd_lat_max'
    }).drop(columns=['sim_mode'])
    
    # Rename columns for TLM
    tlm_df = tlm_df.rename(columns={
        'achieved_write_bandwidth_MBps': 'tlm_write_bw',
        'achieved_read_bandwidth_MBps': 'tlm_read_bw',
        'write_latency_min': 'tlm_wr_lat_min',
        'write_latency_avg': 'tlm_wr_lat_avg',
        'write_latency_max': 'tlm_wr_lat_max',
        'read_latency_min': 'tlm_rd_lat_min',
        'read_latency_avg': 'tlm_rd_lat_avg',
        'read_latency_max': 'tlm_rd_lat_max'
    }).drop(columns=['sim_mode'])
    
    return rtl_df, tlm_df


def load_gem5_data(csv_path: Path) -> pd.DataFrame:
    """Load gem5 results and normalize column names."""
    df = pd.read_csv(csv_path)
    
    # Filter out HBM tests
    df = df[~df['name'].str.contains('hbm', case=False)]
    
    df['test_key'] = df['name'].apply(extract_test_key)
    
    # Select and rename relevant columns
    df = df[[
        'test_key',
        'gem5_achieved_write_bw_MBps', 'gem5_achieved_read_bw_MBps',
        'gem5_min_write_lat_cycles', 'gem5_avg_write_lat_cycles', 'gem5_max_write_lat_cycles',
        'gem5_min_read_lat_cycles', 'gem5_avg_read_lat_cycles', 'gem5_max_read_lat_cycles'
    ]].rename(columns={
        'gem5_achieved_write_bw_MBps': 'gem5_write_bw',
        'gem5_achieved_read_bw_MBps': 'gem5_read_bw',
        'gem5_min_write_lat_cycles': 'gem5_wr_lat_min',
        'gem5_avg_write_lat_cycles': 'gem5_wr_lat_avg',
        'gem5_max_write_lat_cycles': 'gem5_wr_lat_max',
        'gem5_min_read_lat_cycles': 'gem5_rd_lat_min',
        'gem5_avg_read_lat_cycles': 'gem5_rd_lat_avg',
        'gem5_max_read_lat_cycles': 'gem5_rd_lat_max'
    })
    
    return df


def merge_data(rtl_df: pd.DataFrame, tlm_df: pd.DataFrame, gem5_df: pd.DataFrame) -> pd.DataFrame:
    """Merge RTL, TLM, and gem5 data on test key."""
    # Merge RTL and TLM first
    merged = pd.merge(rtl_df, tlm_df, on='test_key', how='outer')
    
    # Then merge with gem5
    merged = pd.merge(merged, gem5_df, on='test_key', how='inner')
    
    # Sort by endpoint type and hop count
    def sort_key(name):
        endpoint = name.split('_')[0]  # pos, ddr
        hop_match = re.search(r'(\d+)hop', name)
        hop = int(hop_match.group(1)) if hop_match else 0
        pkt_match = re.search(r'(\d+)pkt', name)
        pkt = int(pkt_match.group(1)) if pkt_match else 0
        return (endpoint, hop, pkt)
    
    merged['sort_key'] = merged['test_key'].apply(sort_key)
    merged = merged.sort_values('sort_key').drop(columns=['sort_key'])
    
    return merged


def format_latex(df: pd.DataFrame) -> str:
    """Format as LaTeX table."""
    lines = [
        r"\begin{table}[h]",
        r"\centering",
        r"\caption{Vivado RTL vs Naviq Latency Comparison (cycles)}",
        r"\label{tab:latency_comparison}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{l|rrr|rrr|rrr|rrr}",
        r"\hline",
        r"& \multicolumn{6}{c|}{Write Latency} & \multicolumn{6}{c}{Read Latency} \\",
        r"& \multicolumn{3}{c|}{RTL} & \multicolumn{3}{c|}{Naviq} & \multicolumn{3}{c|}{RTL} & \multicolumn{3}{c}{Naviq} \\",
        r"Test & Min & Avg & Max & Min & Avg & Max & Min & Avg & Max & Min & Avg & Max \\",
        r"\hline",
    ]
    
    for _, row in df.iterrows():
        # Format test name (replace _ with space, uppercase endpoint)
        test_name = row['test_key'].replace('_', ' ').replace('pos', 'BRAM').replace('ddr', 'DDR')
        
        line = f"{test_name} & "
        line += f"{int(row['rtl_wr_lat_min'])} & {row['rtl_wr_lat_avg']:.0f} & {int(row['rtl_wr_lat_max'])} & "
        line += f"{int(row['gem5_wr_lat_min'])} & {row['gem5_wr_lat_avg']:.0f} & {int(row['gem5_wr_lat_max'])} & "
        line += f"{int(row['rtl_rd_lat_min'])} & {row['rtl_rd_lat_avg']:.0f} & {int(row['rtl_rd_lat_max'])} & "
        line += f"{int(row['gem5_rd_lat_min'])} & {row['gem5_rd_lat_avg']:.0f} & {int(row['gem5_rd_lat_max'])} \\\\"
        lines.append(line)
    
    lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"}",
        r"\end{table}",
    ])
    
    return '\n'.join(lines)


def format_csv(df: pd.DataFrame) -> str:
    """Format as CSV."""
    output_cols = [
        'test_key',
        'rtl_wr_lat_min', 'rtl_wr_lat_avg', 'rtl_wr_lat_max',
        'tlm_wr_lat_min', 'tlm_wr_lat_avg', 'tlm_wr_lat_max',
        'gem5_wr_lat_min', 'gem5_wr_lat_avg', 'gem5_wr_lat_max',
        'rtl_rd_lat_min', 'rtl_rd_lat_avg', 'rtl_rd_lat_max',
        'tlm_rd_lat_min', 'tlm_rd_lat_avg', 'tlm_rd_lat_max',
        'gem5_rd_lat_min', 'gem5_rd_lat_avg', 'gem5_rd_lat_max',
        'rtl_write_bw', 'tlm_write_bw', 'gem5_write_bw',
        'rtl_read_bw', 'tlm_read_bw', 'gem5_read_bw'
    ]
    return df[output_cols].to_csv(index=False)


def format_markdown(df: pd.DataFrame) -> str:
    """Format as Markdown table."""
    lines = [
        "| Test | RTL Wr Min | RTL Wr Avg | RTL Wr Max | Naviq Wr Min | Naviq Wr Avg | Naviq Wr Max | RTL Rd Min | RTL Rd Avg | RTL Rd Max | Naviq Rd Min | Naviq Rd Avg | Naviq Rd Max |",
        "|------|------------|------------|------------|--------------|--------------|--------------|------------|------------|------------|--------------|--------------|--------------|",
    ]
    
    for _, row in df.iterrows():
        test_name = row['test_key'].replace('pos', 'BRAM').replace('ddr', 'DDR')
        line = f"| {test_name} | "
        line += f"{int(row['rtl_wr_lat_min'])} | {row['rtl_wr_lat_avg']:.0f} | {int(row['rtl_wr_lat_max'])} | "
        line += f"{int(row['gem5_wr_lat_min'])} | {row['gem5_wr_lat_avg']:.0f} | {int(row['gem5_wr_lat_max'])} | "
        line += f"{int(row['rtl_rd_lat_min'])} | {row['rtl_rd_lat_avg']:.0f} | {int(row['rtl_rd_lat_max'])} | "
        line += f"{int(row['gem5_rd_lat_min'])} | {row['gem5_rd_lat_avg']:.0f} | {int(row['gem5_rd_lat_max'])} |"
        lines.append(line)
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Generate Vivado vs gem5 comparison table.',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--vivado', type=Path, required=True, help='Vivado results CSV')
    parser.add_argument('--gem5', type=Path, required=True, help='gem5 results CSV')
    parser.add_argument('--output', '-o', type=Path, help='Output file (prints to stdout if not specified)')
    parser.add_argument('--format', '-f', choices=['latex', 'csv', 'markdown'], default='latex',
                        help='Output format (default: latex)')
    args = parser.parse_args()

    if not args.vivado.exists():
        print(f"Error: Vivado CSV not found: {args.vivado}", file=sys.stderr)
        sys.exit(1)
    if not args.gem5.exists():
        print(f"Error: gem5 CSV not found: {args.gem5}", file=sys.stderr)
        sys.exit(1)

    rtl_df, tlm_df = load_vivado_data(args.vivado)
    gem5_df = load_gem5_data(args.gem5)
    merged = merge_data(rtl_df, tlm_df, gem5_df)
    
    print(f"Matched {len(merged)} test configurations")

    if args.format == 'latex':
        output = format_latex(merged)
    elif args.format == 'csv':
        output = format_csv(merged)
    else:
        output = format_markdown(merged)

    if args.output:
        args.output.write_text(output)
        print(f"Saved to: {args.output}")
    else:
        print(output)


if __name__ == '__main__':
    main()
