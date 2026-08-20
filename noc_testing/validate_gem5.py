import csv
import sys
from pathlib import Path

LATENCY_MODEL_DIR = Path(__file__).resolve().parent / "latency_modeling"
latency_model_dir_str = str(LATENCY_MODEL_DIR)
if latency_model_dir_str not in sys.path:
    sys.path.insert(0, latency_model_dir_str)

import write_latency_predict

def main():
    gem5_csv = sys.argv[1]
    data = []
    with open(gem5_csv, 'r') as f:
        for row in csv.DictReader(f):
            try:
                data.append({
                    'name': row['name'],
                    'size': int(row['axi_write_size_bytes']),
                    'beats': int(row['axi_write_len_beats']) + 1,
                    'tx': int(row['num_write_transactions_cfg']),
                    'gem5_min': float(row['gem5_min_write_lat_cycles']),
                    'gem5_max': float(row['gem5_max_write_lat_cycles'])
                })
            except (ValueError, KeyError):
                pass
    perfect = 0
    total = 0
    for d in data:
        p_min, p_max, _ = write_latency_predict.predict_config(d['size'], d['beats'], d['tx'])
        if p_min is None:
            continue
        total += 1
        dm = int(d['gem5_min']) - p_min
        dM = int(d['gem5_max']) - p_max
        if dm == 0 and dM == 0:
            perfect += 1
        else:
            print(f"{d['name']:<15} pred=[{p_min},{p_max}] gem5=[{int(d['gem5_min'])},{int(d['gem5_max'])}] diff=[{dm},{dM}]")
    print(f"Total perfect: {perfect}/{total}")

if __name__ == '__main__':
    main()
