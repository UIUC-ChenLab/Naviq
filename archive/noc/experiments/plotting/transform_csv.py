#!/usr/bin/env python3
"""
Transform Vivado result CSV to simplified format for plotting.

Aggregates rows by test name (since Vivado outputs one row per src_id) and
calculates total packets based on topology configuration.

For all-to-all topologies: total_packets = num_write_transactions × sources × destinations

Usage:
    python transform_csv.py <input.csv> [output.csv]

Example:
    python transform_csv.py results/vivado_results.csv
    # Creates: results/vivado_results_simplified.csv
"""

import csv
import sys
from pathlib import Path
from typing import Tuple


def extract_multiplier(name: str) -> Tuple[int, int]:
    """
    Extract source and destination counts from test name.

    Parses names like '16to16_medium' to extract (16, 16).
    Returns (1, 1) if parsing fails.

    Args:
        name: Test name string (e.g., '4to4_small', '1to1_large')

    Returns:
        Tuple of (num_sources, num_destinations)
    """
    parts = name.split('_')
    if parts and 'to' in parts[0]:
        sides = parts[0].split('to')
        if len(sides) == 2:
            try:
                return int(sides[0]), int(sides[1])
            except ValueError:
                pass
    return 1, 1


def transform_csv(input_path: Path, output_path: Path) -> None:
    """
    Transform Vivado CSV to simplified format.

    Deduplicates rows by test name (keeping first occurrence for sim_time)
    and calculates total packets for all-to-all topologies.

    Args:
        input_path: Path to input Vivado CSV
        output_path: Path for output simplified CSV
    """
    with open(input_path, newline='') as f_in:
        reader = csv.DictReader(f_in)
        rows = list(reader)

    # Deduplicate by test name (keep first row for sim_time)
    seen_names = set()
    simplified_rows = []

    for row in rows:
        name = row['name']
        if name in seen_names:
            continue
        seen_names.add(name)

        sources, dests = extract_multiplier(name)
        num_write_trans = int(row.get('num_write_transactions_cfg', 0))

        # For all-to-all: each source sends to all destinations
        total_packets = num_write_trans * sources * dests

        simplified_rows.append({
            'name': name,
            'config': name.split('_')[0] if '_' in name else name,
            'sim_time_s': row['sim_time_s'],
            'num_write_trans_cfg': num_write_trans,
            'num_sources': sources,
            'num_dests': dests,
            'total_packets': total_packets,
        })

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        'name', 'config', 'sim_time_s', 'num_write_trans_cfg',
        'num_sources', 'num_dests', 'total_packets'
    ]

    with open(output_path, 'w', newline='') as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(simplified_rows)

    print(f"Wrote {len(simplified_rows)} rows to {output_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python transform_csv.py <input.csv> [output.csv]")
        print("  If output.csv is not specified, creates <input>_simplified.csv")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.parent / f"{input_path.stem}_simplified.csv"

    transform_csv(input_path, output_path)


if __name__ == '__main__':
    main()
