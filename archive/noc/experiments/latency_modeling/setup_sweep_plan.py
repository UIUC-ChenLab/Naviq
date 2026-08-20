#!/usr/bin/env python3
import csv
import sys
from pathlib import Path

def main():
    plan_dir = Path(__file__).resolve().parent.parent / "sweep_plans"
    csv_path = plan_dir / "noc_plan_all_sizes.csv"
    
    if not csv_path.exists():
        print(f"Error: Could not find {csv_path}")
        sys.exit(1)

    # Relative to the workspace where noc_sweep.py executes (noc_testing/)
    ncr_val = "../src/noc/topology/topologies/1_to_1_close.ncr"
    nts_val = "../src/noc/topology/topologies/1_to_1_close.nts"

    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        if not fields:
            print("CSV is empty or missing headers.")
            sys.exit(1)
            
        if "ncr" not in fields:
            fields.append("ncr")
        if "nts" not in fields:
            fields.append("nts")
        
        rows = list(reader)

    # Update all rows
    for row in rows:
        row["ncr"] = ncr_val
        row["nts"] = nts_val

    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Successfully updated {len(rows)} rows with custom route configuration:")
    print(f"  NCR: {ncr_val}")
    print(f"  NTS: {nts_val}")

if __name__ == "__main__":
    main()
