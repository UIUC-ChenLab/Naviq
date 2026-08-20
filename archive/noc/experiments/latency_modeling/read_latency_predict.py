#!/usr/bin/env python3
"""
Predict read latency for transactions over the Versal NoC based on AXI configuration.
Models the dual-bottleneck pipeline discovered through cycle-accurate Vivado traces.

Usage:
  python3 read_latency_predict.py --validation-csv ../results/latency_tests.csv
  python3 read_latency_predict.py --size 64 --beats 4 --tx 1
"""
import argparse
import csv
import math
import sys
import os

def get_nmu_resp(size: int, beats_param: int) -> int:
    """Calculate the NMU response processing time."""
    tot = size * beats_param
    df = math.ceil(tot / 16)
    
    if size == 64: 
        return 10
    if size == 32: 
        return 8 if beats_param % 2 != 0 else 7
    if size == 16:
        group = (df - 1) // 4
        return 7 - (group % 3)
    
    # For sizes <16B, this value doesn't matter because the Beat Bottleneck dominates
    return 7

def predict_single_read_latency(size: int, beats_param: int) -> int:
    """Predict the deterministic latency of a single, isolated read transaction."""
    tot = size * beats_param
    df = math.ceil(tot / 16)
    
    nmu_resp = get_nmu_resp(size, beats_param)
    gaps = math.ceil(df / 4)
    
    # Pipelined Bottleneck 1: Waiting for all network flits to traverse the system
    # Base 18 + NSU start 1 + (flits - 1) serial time + burst gaps + NMU processing
    flit_bottleneck = 18 + 1 + (df - 1) + gaps + nmu_resp
    
    # Pipelined Bottleneck 2: NMU R-beat generation time
    # The NMU starts processing immediately upon the first flit's arrival: Base 18 + 1 + 7 = 26
    beat_bottleneck = 26 + beats_param
    
    return max(flit_bottleneck, beat_bottleneck)

def run_csv_validation(csv_path: str):
    """Validate the deterministic tx=1 predictor against the provided CSV."""
    if not os.path.exists(csv_path):
        print(f"Error: Could not find CSV file at {csv_path}")
        sys.exit(1)
        
    data = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                s = int(row['axi_write_size_bytes'])
                b = int(row['axi_write_len_beats']) + 1  # AXI len is 0-indexed beats-1
                tx = int(row['num_write_transactions_cfg'])
                rmin = int(row['read_latency_min'])
                
                # Only validate single-transaction sweeps to avoid multi-tx drift and 4KB chopping
                if rmin > 0 and tx == 1:
                    data.append((s, b, rmin))
            except (ValueError, KeyError):
                pass
                
    if not data:
        print("Error: No valid tx=1 read latency data found in CSV.")
        sys.exit(1)

    print(f"Validating prediction model on {len(data)} tx=1 configurations...")
    print(f"{'Size':>5} {'Beats':>5} {'Act Lat':>8} | {'Pred Lat':>8} {'Diff':>5}")
    print("-" * 45)
    
    perfect = 0
    mismatches = []
    
    for size, beats_param, actual in sorted(set(data)):
        pred = predict_single_read_latency(size, beats_param)
        diff = actual - pred
        
        if diff == 0:
            perfect += 1
        else:
            mismatches.append((size, beats_param, actual, pred, diff))
            
        marker = "" if diff == 0 else f"{diff:+d}"
        if diff != 0:
             print(f"{size:5} {beats_param:5} {actual:8} | {pred:8} {marker:5}")
             
    acc = 100 * perfect / len(data)
    print(f"\nModel Accuracy: {perfect}/{len(data)} ({acc:.1f}%) perfect tx=1 matches.")
    
    if mismatches:
        print("Note: Review mismatched configurations.")
    else:
        print("Success: Zero mismatches! Model is cycle-accurate for determinism.")

def main():
    parser = argparse.ArgumentParser(description="Predict Versal NoC Read Latency")
    parser.add_argument('--size', type=int, help='AXI ARSIZE in bytes (e.g., 2, 4, 8, 16, 32, 64)')
    parser.add_argument('--beats', type=int, help='AXI ARLEN (actual beats, i.e. 1-256)')
    parser.add_argument('--tx', type=int, default=1, help='Number of transactions (Note: predictable drift occurs for tx > 1)')
    parser.add_argument('--validation-csv', type=str, help='Path to Vivado latency_tests.csv to run full validation')
    
    args = parser.parse_args()
    
    if args.validation_csv:
        run_csv_validation(args.validation_csv)
    elif args.size and args.beats:
        lat = predict_single_read_latency(args.size, args.beats)
        print(f"Predicted Read Latency (tx=1): {lat} cycles")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
