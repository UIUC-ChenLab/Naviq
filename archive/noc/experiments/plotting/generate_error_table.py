#!/usr/bin/env python3
"""
Generate a percent error comparison table of Naviq vs Vivado (RTL and SystemC).

Percent Error = (Naviq - Vivado) / Vivado * 100

Usage:
    python generate_error_table.py --vivado <vivado.csv> --gem5 <gem5.csv> [-o <output>]

Example:
    python generate_error_table.py \
        --vivado results/vivado_placement_retest.csv \
        --gem5 results/gem5_placement.csv \
        -o results/error_table.tex
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd


def extract_test_key(name: str) -> str:
    """Extract base test key for matching."""
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
    df = df[~df['name'].str.contains('hbm', case=False)]
    df['test_key'] = df['name'].apply(extract_test_key)
    df['sim_mode'] = df['name'].apply(extract_sim_mode)
    
    cols = [
        'test_key', 'sim_mode',
        'achieved_write_bandwidth_MBps', 'achieved_read_bandwidth_MBps',
        'write_latency_min', 'write_latency_avg', 'write_latency_max',
        'read_latency_min', 'read_latency_avg', 'read_latency_max'
    ]
    df = df[cols]
    
    rtl_df = df[df['sim_mode'] == 'rtl'].copy()
    tlm_df = df[df['sim_mode'] == 'tlm'].copy()
    
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
    """Load gem5 results."""
    df = pd.read_csv(csv_path)
    df = df[~df['name'].str.contains('hbm', case=False)]
    df['test_key'] = df['name'].apply(extract_test_key)
    
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
    merged = pd.merge(rtl_df, tlm_df, on='test_key', how='outer')
    merged = pd.merge(merged, gem5_df, on='test_key', how='inner')
    
    def sort_key(name):
        endpoint = name.split('_')[0]
        hop_match = re.search(r'(\d+)hop', name)
        hop = int(hop_match.group(1)) if hop_match else 0
        pkt_match = re.search(r'(\d+)pkt', name)
        pkt = int(pkt_match.group(1)) if pkt_match else 0
        return (endpoint, hop, pkt)
    
    merged['sort_key'] = merged['test_key'].apply(sort_key)
    merged = merged.sort_values('sort_key').drop(columns=['sort_key'])
    
    return merged


def percent_error(naviq, vivado):
    """Calculate percent error: (naviq - vivado) / vivado * 100"""
    if vivado == 0:
        return 0
    return (naviq - vivado) / vivado * 100


def format_latex_error(df: pd.DataFrame) -> str:
    """Format as LaTeX table showing percent error vs RTL."""
    # Filter out DDR, 256pkt, and 8hop tests
    df = df[~df['test_key'].str.contains('ddr', case=False)]
    df = df[~df['test_key'].str.contains('256pkt', case=False)]
    df = df[~df['test_key'].str.contains('8hop', case=False)]
    
    lines = [
        r"\begin{table}[h]",
        r"\centering",
        r"\caption{Percent Error vs RTL - BRAM Endpoint (\%)}",
        r"\label{tab:error_comparison}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{l|rrrr|rrrr|rrrr|rrrr}",
        r"\hline",
        r"& \multicolumn{8}{c|}{Naviq vs RTL (\%)} & \multicolumn{8}{c}{SystemC vs RTL (\%)} \\",
        r"& \multicolumn{4}{c|}{Write} & \multicolumn{4}{c|}{Read} & \multicolumn{4}{c|}{Write} & \multicolumn{4}{c}{Read} \\",
        r"Test & BW & Min & Avg & Max & BW & Min & Avg & Max & BW & Min & Avg & Max & BW & Min & Avg & Max \\",
        r"\hline",
    ]
    
    for _, row in df.iterrows():
        test_name = row['test_key'].replace('pos_', '').replace('_', ' ')
        
        # Naviq vs RTL write errors
        naviq_wr_bw_err = percent_error(row['gem5_write_bw'], row['rtl_write_bw'])
        naviq_wr_min_err = percent_error(row['gem5_wr_lat_min'], row['rtl_wr_lat_min'])
        naviq_wr_avg_err = percent_error(row['gem5_wr_lat_avg'], row['rtl_wr_lat_avg'])
        naviq_wr_max_err = percent_error(row['gem5_wr_lat_max'], row['rtl_wr_lat_max'])
        
        # Naviq vs RTL read errors
        naviq_rd_bw_err = percent_error(row['gem5_read_bw'], row['rtl_read_bw'])
        naviq_rd_min_err = percent_error(row['gem5_rd_lat_min'], row['rtl_rd_lat_min'])
        naviq_rd_avg_err = percent_error(row['gem5_rd_lat_avg'], row['rtl_rd_lat_avg'])
        naviq_rd_max_err = percent_error(row['gem5_rd_lat_max'], row['rtl_rd_lat_max'])
        
        # SystemC vs RTL write errors
        tlm_wr_bw_err = percent_error(row['tlm_write_bw'], row['rtl_write_bw'])
        tlm_wr_min_err = percent_error(row['tlm_wr_lat_min'], row['rtl_wr_lat_min'])
        tlm_wr_avg_err = percent_error(row['tlm_wr_lat_avg'], row['rtl_wr_lat_avg'])
        tlm_wr_max_err = percent_error(row['tlm_wr_lat_max'], row['rtl_wr_lat_max'])
        
        # SystemC vs RTL read errors
        tlm_rd_bw_err = percent_error(row['tlm_read_bw'], row['rtl_read_bw'])
        tlm_rd_min_err = percent_error(row['tlm_rd_lat_min'], row['rtl_rd_lat_min'])
        tlm_rd_avg_err = percent_error(row['tlm_rd_lat_avg'], row['rtl_rd_lat_avg'])
        tlm_rd_max_err = percent_error(row['tlm_rd_lat_max'], row['rtl_rd_lat_max'])
        
        line = f"{test_name} & "
        line += f"{naviq_wr_bw_err:.1f} & {naviq_wr_min_err:.1f} & {naviq_wr_avg_err:.1f} & {naviq_wr_max_err:.1f} & "
        line += f"{naviq_rd_bw_err:.1f} & {naviq_rd_min_err:.1f} & {naviq_rd_avg_err:.1f} & {naviq_rd_max_err:.1f} & "
        line += f"{tlm_wr_bw_err:.1f} & {tlm_wr_min_err:.1f} & {tlm_wr_avg_err:.1f} & {tlm_wr_max_err:.1f} & "
        line += f"{tlm_rd_bw_err:.1f} & {tlm_rd_min_err:.1f} & {tlm_rd_avg_err:.1f} & {tlm_rd_max_err:.1f} \\\\"
        lines.append(line)
    
    lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"}",
        r"\end{table}",
    ])
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Generate percent error comparison table.')
    parser.add_argument('--vivado', type=Path, required=True, help='Vivado results CSV')
    parser.add_argument('--gem5', type=Path, required=True, help='gem5 results CSV')
    parser.add_argument('--output', '-o', type=Path, help='Output file')
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

    output = format_latex_error(merged)

    if args.output:
        args.output.write_text(output)
        print(f"Saved to: {args.output}")
    else:
        print(output)


if __name__ == '__main__':
    main()
