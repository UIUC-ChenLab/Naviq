#!/usr/bin/env python3
"""
Generate a latency comparison table between Vivado golden model tests and gem5 output.

Usage:
    python compare_latency_sweep.py --vivado <vivado.csv> --gem5 <gem5.csv> [-o <output.csv>]
"""

import argparse
import csv
import sys
from pathlib import Path

def load_data(csv_path: Path):
    data = {}
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if 'name' in row:
                data[row['name']] = row
    return data

def main():
    parser = argparse.ArgumentParser(description='Compare Vivado and gem5 latency sweeps.')
    parser.add_argument('--vivado', type=Path, required=True, help='Path to Vivado results (e.g. latency_tests.csv)')
    parser.add_argument('--gem5', type=Path, required=True, help='Path to gem5 results CSV')
    parser.add_argument('--output', '-o', type=Path, help='Output comparison CSV file')
    
    args = parser.parse_args()

    if not args.vivado.exists():
        print(f"Error: Vivado CSV not found: {args.vivado}", file=sys.stderr)
        sys.exit(1)
    if not args.gem5.exists():
        print(f"Error: gem5 CSV not found: {args.gem5}", file=sys.stderr)
        sys.exit(1)

    vivado_data = load_data(args.vivado)
    gem5_data = load_data(args.gem5)
    
    # Merge on test name
    matched_names = set(vivado_data.keys()).intersection(set(gem5_data.keys()))
    
    if not matched_names:
        print("Error: No intersecting row names found between Vivado and gem5 CSVs.", file=sys.stderr)
        sys.exit(1)
        
    metrics = ['write_lat_min', 'write_lat_avg', 'write_lat_max', 'read_lat_min', 'read_lat_avg', 'read_lat_max']
    vivado_prefixes = {'write_lat_min': 'write_latency_min', 'write_lat_avg': 'write_latency_avg', 
                       'write_lat_max': 'write_latency_max', 'read_lat_min': 'read_latency_min',
                       'read_lat_avg': 'read_latency_avg', 'read_lat_max': 'read_latency_max'}
    gem5_prefixes = {'write_lat_min': 'gem5_min_write_lat_cycles', 'write_lat_avg': 'gem5_avg_write_lat_cycles',
                     'write_lat_max': 'gem5_max_write_lat_cycles', 'read_lat_min': 'gem5_min_read_lat_cycles',
                     'read_lat_avg': 'gem5_avg_read_lat_cycles', 'read_lat_max': 'gem5_max_read_lat_cycles'}

    results = []
    perfect_min = 0
    worst_mismatches = []

    for name in matched_names:
        v_row = vivado_data[name]
        g_row = gem5_data[name]
        
        result_row = {'name': name}
        
        for m in metrics:
            v_key = vivado_prefixes[m]
            g_key = gem5_prefixes[m]
            
            if v_key in v_row and g_key in g_row and v_row[v_key] and g_row[g_key]:
                try:
                    v_val = float(v_row[v_key])
                    g_val = float(g_row[g_key])
                    
                    diff = g_val - v_val
                    err_pct = (diff / v_val * 100) if v_val != 0 else 0.0
                    
                    result_row[f'vivado_{m}'] = v_val
                    result_row[f'gem5_{m}'] = g_val
                    result_row[f'diff_{m}'] = diff
                    result_row[f'err_pct_{m}'] = round(err_pct, 2)
                    
                    if m == 'write_lat_min':
                        if diff == 0:
                            perfect_min += 1
                        else:
                            worst_mismatches.append((name, v_val, g_val, diff))
                except ValueError:
                    pass
        results.append(result_row)

    print(f"\nMatched {len(matched_names)} test configurations.")
    
    if len(results) > 0 and 'diff_write_lat_min' in results[0]:
        pct = (perfect_min / len(matched_names)) * 100
        print(f"Perfect Min Write Latency: {perfect_min}/{len(matched_names)} ({pct:.1f}%)")
        
        if worst_mismatches:
            print("\nLargest Min Write Latency differences (gem5 - Vivado):")
            worst_mismatches.sort(key=lambda x: abs(x[3]), reverse=True)
            for m in worst_mismatches[:10]:
                print(f"  {m[0]:<15}: Vivado={m[1]:>4.0f}, gem5={m[2]:>4.0f}  (diff={m[3]:>+4.0f})")

    if args.output:
        if results:
            keys = list(results[0].keys())
            with open(args.output, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(results)
            print(f"\nDetailed comparison saved to: {args.output}")

if __name__ == '__main__':
    main()
