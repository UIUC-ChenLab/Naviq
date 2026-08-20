#!/usr/bin/env python3
"""
NoC Write Latency Prediction Model

Cycle-accurate prediction of AXI write latency through the Versal NoC.
Derived from Vivado simulation waveform analysis.

See write_latency_model.md for the full explanation of each rule.

Usage:
    python3 write_latency_predict.py                      # Validate against CSV
    python3 write_latency_predict.py --size 32 --beats 8  # Predict specific config
"""

import csv
import math
import argparse
import os

# =============================================================================
# Constants
# =============================================================================

RESPONSE_TIME = 15  # NPS forward + NSU processing + BRAM + NPS return


# =============================================================================
# NPP Chopping
# =============================================================================

def get_npps(size, beats, start_addr):
    """
    Break an AXI transaction into NPPs based on 256-byte address-aligned boundaries.

    Returns a list of (npp_bytes, data_flits, npp_beats) tuples.
    """
    total_bytes = size * beats
    npps = []
    pos = start_addr
    while pos < start_addr + total_bytes:
        block_end = min(((pos // 256) + 1) * 256, start_addr + total_bytes)
        npp_bytes = block_end - pos
        # Data flits are 16-byte address-aligned
        data_flits = (block_end - 1) // 16 - pos // 16 + 1
        # Beats consumed by this NPP
        npp_beats = math.ceil(npp_bytes / size)
        npps.append((npp_bytes, data_flits, npp_beats))
        pos = block_end
    return npps


# =============================================================================
# NMU Prep Time
# =============================================================================

def nmu_prep(beats, data_flits):
    """
    Compute NMU prep time for a single NPP.

    - Full NPP (16 data flits = 256B): fixed at 24 cycles
    - Otherwise: 9 + MAX(beats, data_flits)
    """
    if data_flits >= 16:
        return 24
    return 9 + max(beats, data_flits)


# =============================================================================
# Cycle-Accurate Transaction Prediction
# =============================================================================

def predict_transaction(size, beats, tx_index):
    """
    Predict write latency for a single transaction at a given address.

    Returns the predicted latency in clock cycles, or None if the transaction
    crosses a 4KB boundary (which causes the traffic generator to split it).
    """
    total_bytes = size * beats
    start_addr = tx_index * total_bytes
    end_addr = start_addr + total_bytes - 1

    # 4KB boundary check
    if start_addr // 4096 != end_addr // 4096:
        return None

    npps = get_npps(size, beats, start_addr)
    if not npps:
        return None

    # --- NPP 0 ---
    npp0_bytes, npp0_df, npp0_beats = npps[0]
    ready = [nmu_prep(npp0_beats, npp0_df)]
    emit = [ready[0]]

    # --- Cumulative beats before each NPP ---
    beats_before = [0]
    cumul = npp0_beats
    for i in range(1, len(npps)):
        beats_before.append(cumul)
        cumul += npps[i][2]

    # --- Subsequent NPPs ---
    for i in range(1, len(npps)):
        prev_emit_end = emit[i - 1] + 1 + npps[i - 1][1]  # header + data flits
        df_i = npps[i][1]
        npp_i_beats = npps[i][2]

        # Two constraints on when this NPP is ready:
        # 1. Pipeline: internal prep finishes df_i cycles after previous ready
        pipeline_ready = ready[i - 1] + df_i

        # 2. Beat arrival: can't start until all preceding beats have arrived
        beat_arrival_ready = beats_before[i] + 1 + 9 + max(npp_i_beats, df_i)

        curr_ready = max(pipeline_ready, beat_arrival_ready)
        ready.append(curr_ready)

        # Emission starts when both: previous NPP done AND this NPP ready
        curr_emit = max(prev_emit_end, curr_ready)

        # +1 gap transition overhead when:
        #   - There IS a gap (curr_emit > prev_emit_end)
        #   - Pipeline-ready is the binding constraint
        #   - Post-gap NPP is NOT a full 256B NPP
        has_gap = curr_emit > prev_emit_end
        if has_gap and pipeline_ready >= beat_arrival_ready and df_i < 16:
            curr_emit += 1

        emit.append(curr_emit)

    # --- Last flit and response ---
    last_idx = len(npps) - 1
    last_df = npps[last_idx][1]
    last_flit_cycle = emit[last_idx] + 1 + last_df  # header + data

    # --- BRAM back-to-back penalty ---
    bram_penalty = 0
    if len(npps) > 1:
        prev_end = emit[last_idx - 1] + 1 + npps[last_idx - 1][1]
        is_back_to_back = (emit[last_idx] == prev_end)
        last_npp_total_flits = 1 + last_df
        if is_back_to_back and last_npp_total_flits < 4:
            bram_penalty = 1

    return last_flit_cycle + RESPONSE_TIME + bram_penalty


# =============================================================================
# Multi-Transaction Min/Max Prediction
# =============================================================================

def predict_config(size, beats, num_tx):
    """
    Predict min and max latency across multiple transactions.

    Returns (predicted_min, predicted_max, has_4kb_split).
    """
    latencies = []
    has_4kb = False

    for i in range(num_tx):
        lat = predict_transaction(size, beats, i)
        if lat is not None:
            latencies.append(lat)
        else:
            has_4kb = True

    if not latencies:
        return None, None, has_4kb

    return min(latencies), max(latencies), has_4kb


# =============================================================================
# CSV Validation
# =============================================================================

def validate_csv(csv_path):
    """Validate predictions against the CSV test data."""
    data = []
    with open(csv_path, 'r') as f:
        for row in csv.DictReader(f):
            try:
                data.append({
                    'size': int(row['axi_write_size_bytes']),
                    'beats': int(row['axi_write_len_beats']) + 1,
                    'tx': int(row['num_write_transactions_cfg']),
                    'min_lat': int(row['write_latency_min']),
                    'max_lat': int(row['write_latency_max'])
                })
            except (ValueError, KeyError):
                pass

    perfect = 0
    total = 0
    mismatches = []

    for d in sorted(data, key=lambda x: (x['size'], x['beats'], x['tx'])):
        s, b, tx = d['size'], d['beats'], d['tx']
        total += 1

        p_min, p_max, has_4kb = predict_config(s, b, tx)
        if p_min is None:
            continue

        a_min, a_max = d['min_lat'], d['max_lat']
        dm = a_min - p_min
        dM = a_max - p_max

        # 4KB splits can cause min to drop below prediction
        if has_4kb and dm < 0:
            dm = 0

        if dm == 0 and dM == 0:
            perfect += 1
        else:
            mismatches.append({
                'config': f"{s}x{b}",
                'tx': tx, 'dm': dm, 'dM': dM,
                'pred': f"[{p_min},{p_max}]",
                'actual': f"[{a_min},{a_max}]"
            })

    print(f"Validation: {perfect}/{total} perfect ({100 * perfect / total:.1f}%)")
    print(f"Mismatches: {len(mismatches)}")

    bram_drift = sum(1 for m in mismatches if m['tx'] >= 50)
    other = len(mismatches) - bram_drift
    print(f"  BRAM drift (tx>=50): {bram_drift}")
    print(f"  Other (tx<50):       {other}")

    if other > 0:
        print(f"\nNon-BRAM mismatches:")
        for m in [x for x in mismatches if x['tx'] < 50][:15]:
            print(f"  {m['config']:>5} tx={m['tx']:<3} pred={m['pred']:<12} "
                  f"actual={m['actual']:<12} dm={m['dm']:+d} dM={m['dM']:+d}")


# =============================================================================
# Single Config Prediction
# =============================================================================

def predict_single(size, beats, num_tx=1):
    """Print detailed prediction for a single configuration."""
    total_bytes = size * beats
    print(f"\n{'='*60}")
    print(f"Config: size={size}B, beats={beats}, total={total_bytes}B")
    print(f"{'='*60}")

    for tx_i in range(num_tx):
        lat = predict_transaction(size, beats, tx_i)
        start_addr = tx_i * total_bytes
        npps = get_npps(size, beats, start_addr)

        npp_str = " + ".join(f"{b}B({df}df)" for b, df, _ in npps)
        status = f"4KB split" if lat is None else f"{lat} cycles"

        print(f"  Tx {tx_i}: addr {start_addr:>5} | {npp_str} | {status}")

    p_min, p_max, _ = predict_config(size, beats, num_tx)
    if p_min is not None:
        print(f"\n  Predicted: min={p_min}, max={p_max}")


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NoC Write Latency Predictor')
    parser.add_argument('--validate', action='store_true',
                        help='Validate against CSV data')
    parser.add_argument('--csv', type=str,
                        default=os.path.join(os.path.dirname(__file__),
                                             '..', 'results', 'latency_tests.csv'),
                        help='Path to latency_tests.csv')
    parser.add_argument('--size', type=int, help='AXI write size in bytes')
    parser.add_argument('--beats', type=int, help='AXI write beats')
    parser.add_argument('--tx', type=int, default=1,
                        help='Number of transactions (default: 1)')
    args = parser.parse_args()

    if args.size and args.beats:
        predict_single(args.size, args.beats, args.tx)
    elif args.validate:
        validate_csv(args.csv)
    else:
        # Default: validate
        validate_csv(args.csv)
