#!/usr/bin/env python3
import csv
import sys
import os
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Compare Gem5 latency test results with Vivado baseline.")
    parser.add_argument("vivado_csv", help="Path to the Vivado latency baseline CSV (e.g. noc_testing/results/latency_tests.csv)")
    parser.add_argument("gem5_csv", help="Path to the Gem5 output CSV (e.g. noc_testing/artifacts/generated/results/xyz.csv)")
    args = parser.parse_args()

    vivado_path = Path(args.vivado_csv)
    gem5_path = Path(args.gem5_csv)

    if not vivado_path.is_file():
        print(f"Error: {vivado_path} not found.")
        sys.exit(1)
    if not gem5_path.is_file():
        print(f"Error: {gem5_path} not found.")
        sys.exit(1)

    # 1. Load Vivado baseline data
    vivado_data = {}
    with open(vivado_path, 'r', newline='') as v_file:
        reader = csv.DictReader(v_file)
        for row in reader:
            name = row.get('name')
            if name:
                vivado_data[name] = {
                    'v_min': row.get('write_latency_min', '').strip(),
                    'v_max': row.get('write_latency_max', '').strip(),
                    'v_r_min': row.get('read_latency_min', '').strip(),
                    'v_r_max': row.get('read_latency_max', '').strip(),
                }

    # 2. Iterate through Gem5 data, compare, and build output
    comparisons = []
    
    # Track metrics
    total_compared = 0
    total_perfect_match = 0
    total_write_match = 0
    total_read_match = 0

    with open(gem5_path, 'r', newline='') as g_file:
        reader = csv.DictReader(g_file)
        for row in reader:
            name = row.get('name')
            
            g_min = row.get('gem5_min_write_lat_cycles', '').strip()
            g_max = row.get('gem5_max_write_lat_cycles', '').strip()
            g_r_min = row.get('gem5_min_read_lat_cycles', '').strip()
            g_r_max = row.get('gem5_max_read_lat_cycles', '').strip()

            # Fix floats like "29.0" vs "29" 
            if g_min.endswith(".0"): g_min = g_min[:-2]
            if g_max.endswith(".0"): g_max = g_max[:-2]
            if g_r_min.endswith(".0"): g_r_min = g_r_min[:-2]
            if g_r_max.endswith(".0"): g_r_max = g_r_max[:-2]

            if not name or name not in vivado_data:
                continue

            v_min = vivado_data[name]['v_min']
            v_max = vivado_data[name]['v_max']
            v_r_min = vivado_data[name]['v_r_min']
            v_r_max = vivado_data[name]['v_r_max']

            # Make comparison
            matches_w_min = (v_min != "" and g_min != "" and v_min == g_min)
            matches_w_max = (v_max != "" and g_max != "" and v_max == g_max)
            matches_r_min = (v_r_min != "" and g_r_min != "" and v_r_min == g_r_min)
            matches_r_max = (v_r_max != "" and g_r_max != "" and v_r_max == g_r_max)

            is_write_match = matches_w_min and matches_w_max
            is_read_match = matches_r_min and matches_r_max

            if is_write_match and is_read_match:
                total_perfect_match += 1
            if is_write_match:
                total_write_match += 1
            if is_read_match:
                total_read_match += 1
            total_compared += 1

            comparisons.append({
                'name': name,
                'vivado_write_min': v_min,
                'gem5_write_min': g_min,
                'vivado_write_max': v_max,
                'gem5_write_max': g_max,
                'write_match': str(is_write_match),
                'vivado_read_min': v_r_min,
                'gem5_read_min': g_r_min,
                'vivado_read_max': v_r_max,
                'gem5_read_max': g_r_max,
                'read_match': str(is_read_match),
            })

    # 3. Create output directory
    out_dir = Path("noc_testing/latency_modeling/comparisons")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate output file name based on gem5 file name
    out_file = out_dir / f"compare_{gem5_path.name}"

    fieldnames = ['name', 'vivado_write_min', 'gem5_write_min', 'vivado_write_max', 'gem5_write_max', 'write_match', 'vivado_read_min', 'gem5_read_min', 'vivado_read_max', 'gem5_read_max', 'read_match']

    # 4. Write CSV
    with open(out_file, 'w', newline='') as out_csv:
        writer = csv.DictWriter(out_csv, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(comparisons)

    print(f"Comparison complete! Evaluated {total_compared} matching tests.")
    if total_compared > 0:
        print(f"Perfect Matches: {total_perfect_match}/{total_compared} ({total_perfect_match/total_compared*100:.1f}%)")
        print(f"Write Matches:   {total_write_match}/{total_compared} ({total_write_match/total_compared*100:.1f}%)")
        print(f"Read Matches:    {total_read_match}/{total_compared} ({total_read_match/total_compared*100:.1f}%)")
    else:
        print("No tests compared.")
    print(f"File saved to: {out_file}")

if __name__ == '__main__':
    main()
