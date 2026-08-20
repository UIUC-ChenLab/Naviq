#!/usr/bin/env python3
"""Consolidate the per-campaign Vivado reference CSVs (which contain stale
duplicate rows from reused run tags) into:

  1. vivado_incast_combined.csv          - clean, deduped Vivado reference
  2. incast_gem5_vs_vivado_combined.csv  - side-by-side gem5 vs Vivado + delta%

gem5 side uses the comprehensive depth-16 run (4-to-1) and the 2-to-1 run.
Vivado is the invariant reference (not re-run; independent of the gem5
max_outstanding_writes knob).
"""
import csv
import os

R = "naviq/noc_testing/artifacts/generated/results"

# campaign label -> (topology, vivado_file, gem5_file, name_predicate)
CAMPAIGNS = [
    ("4to1_capped800", "4to1",
     "vivado_results_vivado_naviq_4to1_incast_validation_4to1_incast.csv",
     "gem5_vivado_naviq_4to1_incast_comprehensive_proof_4to1.csv",
     lambda n: n.startswith("interleaved_tx")),
    ("4to1_bandwidth", "4to1",
     "vivado_results_vivado_naviq_4to1_incast_diff_band_validation_4to1_incast_diff_band_v2.csv",
     "gem5_vivado_naviq_4to1_incast_comprehensive_proof_4to1.csv",
     lambda n: n.split("_")[0] in ("low", "med", "high")),
    ("4to1_size_shape", "4to1",
     "vivado_results_vivado_naviq_4to1_incast_diff_sizes_validation_4to1_incast_diff_sizes.csv",
     "gem5_vivado_naviq_4to1_incast_comprehensive_proof_4to1.csv",
     lambda n: n.startswith("test_")),
    ("2to1_capped800", "2to1",
     "vivado_results_vivado_naviq_2to1_incast_latency_validation_2to1.csv",
     "gem5_vivado_naviq_2to1_incast_latency_proof_2to1.csv",
     lambda n: n.startswith("interleaved_tx")),
]

# metric label -> (gem5_col, vivado_col)
METRICS = [
    ("W_lat_min", "gem5_min_write_lat_cycles", "write_latency_min"),
    ("W_lat_avg", "gem5_avg_write_lat_cycles", "write_latency_avg"),
    ("W_lat_max", "gem5_max_write_lat_cycles", "write_latency_max"),
    ("R_lat_min", "gem5_min_read_lat_cycles", "read_latency_min"),
    ("R_lat_avg", "gem5_avg_read_lat_cycles", "read_latency_avg"),
    ("R_lat_max", "gem5_max_read_lat_cycles", "read_latency_max"),
    ("W_bw_MBps", "gem5_achieved_write_bw_MBps", "achieved_write_bandwidth_MBps"),
    ("R_bw_MBps", "gem5_achieved_read_bw_MBps", "achieved_read_bandwidth_MBps"),
]

# Vivado config/context columns worth carrying into the combined reference.
VIV_CTX = [
    "tg_mode", "num_write_transactions_cfg", "axi_write_size_bytes",
    "axi_write_len_beats", "axi_write_bandwidth_cfg_MBps", "qos_avg_burst",
    "test_status",
]
VIV_METRIC_COLS = [
    "achieved_write_bandwidth_MBps", "write_latency_min", "write_latency_max",
    "write_latency_avg", "achieved_read_bandwidth_MBps", "read_latency_min",
    "read_latency_max", "read_latency_avg",
]


def load(path):
    with open(os.path.join(R, path)) as f:
        return list(csv.DictReader(f))


def dedupe_last(rows, namekey):
    """Keep the last row per (name, src_id) - drops stale reused-tag rows."""
    out = {}
    for r in rows:
        out[(r[namekey], r["src_id"])] = r
    return out


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def src_sort_key(k):
    name, src = k
    try:
        return (name, int(src))
    except ValueError:
        return (name, 0)


def main():
    viv_rows = []
    cmp_rows = []
    for label, topo, vfile, gfile, pred in CAMPAIGNS:
        viv = dedupe_last(load(vfile), "name")
        gem5 = dedupe_last(load(gfile), "name")
        keys = sorted((k for k in viv if pred(k[0])), key=src_sort_key)
        for (name, src) in keys:
            v = viv[(name, src)]
            # combined Vivado reference row
            vr = {"campaign": label, "topology": topo, "name": name, "src_id": src}
            for c in VIV_CTX:
                vr[c] = v.get(c, "")
            for c in VIV_METRIC_COLS:
                vr[c] = v.get(c, "")
            viv_rows.append(vr)

            # side-by-side comparison row (only where gem5 has a match)
            g = gem5.get((name, src))
            cr = {"campaign": label, "topology": topo, "name": name, "src_id": src,
                  "tx_cfg": v.get("num_write_transactions_cfg", ""),
                  "bw_cfg_MBps": v.get("axi_write_bandwidth_cfg_MBps", ""),
                  "beat_bytes": v.get("axi_write_size_bytes", "")}
            for mlabel, gc, vc in METRICS:
                gv = fnum(g.get(gc)) if g else None
                vv = fnum(v.get(vc))
                cr[f"{mlabel}_gem5"] = gv if gv is not None else ""
                cr[f"{mlabel}_viv"] = vv if vv is not None else ""
                if gv is not None and vv not in (None, 0):
                    cr[f"{mlabel}_delta%"] = round((gv - vv) / vv * 100, 1)
                else:
                    cr[f"{mlabel}_delta%"] = ""
            cmp_rows.append(cr)

    # write combined Vivado reference
    viv_cols = (["campaign", "topology", "name", "src_id"] + VIV_CTX + VIV_METRIC_COLS)
    vpath = os.path.join(R, "vivado_incast_combined.csv")
    with open(vpath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=viv_cols)
        w.writeheader()
        w.writerows(viv_rows)

    # write side-by-side comparison
    cmp_cols = ["campaign", "topology", "name", "src_id", "tx_cfg",
                "bw_cfg_MBps", "beat_bytes"]
    for mlabel, _g, _v in METRICS:
        cmp_cols += [f"{mlabel}_gem5", f"{mlabel}_viv", f"{mlabel}_delta%"]
    cpath = os.path.join(R, "incast_gem5_vs_vivado_combined.csv")
    with open(cpath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cmp_cols)
        w.writeheader()
        w.writerows(cmp_rows)

    print(f"Wrote {vpath}  ({len(viv_rows)} rows, deduped)")
    print(f"Wrote {cpath}  ({len(cmp_rows)} rows, gem5 vs Vivado side-by-side)")


if __name__ == "__main__":
    main()
