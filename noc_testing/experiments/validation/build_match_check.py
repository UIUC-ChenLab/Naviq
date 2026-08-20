#!/usr/bin/env python3
"""Refined side-by-side CSV for manual match-checking.

One row per (test, src_id), with gem5 and Vivado values placed adjacent for
each latency metric (min/avg/max, write+read) and bandwidth (write+read), plus
a delta% for convenience. gem5 side = comprehensive depth-16 run (4-to-1) and
the 2-to-1 run. Vivado = invariant reference (deduped from reused-tag rows).
"""
import csv
import os

R = "naviq/noc_testing/artifacts/generated/results"

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

# (label, gem5_col, vivado_col)
METRICS = [
    ("Wlat_min", "gem5_min_write_lat_cycles", "write_latency_min"),
    ("Wlat_avg", "gem5_avg_write_lat_cycles", "write_latency_avg"),
    ("Wlat_max", "gem5_max_write_lat_cycles", "write_latency_max"),
    ("Rlat_min", "gem5_min_read_lat_cycles", "read_latency_min"),
    ("Rlat_avg", "gem5_avg_read_lat_cycles", "read_latency_avg"),
    ("Rlat_max", "gem5_max_read_lat_cycles", "read_latency_max"),
]


def load(p):
    with open(os.path.join(R, p)) as f:
        return list(csv.DictReader(f))


def dedupe_last(rows):
    out = {}
    for r in rows:
        out[(r["name"], r["src_id"])] = r
    return out


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def round_or_blank(x):
    return round(x, 1) if x is not None else ""


def main():
    out_rows = []
    for label, topo, vfile, gfile, pred in CAMPAIGNS:
        viv = dedupe_last(load(vfile))
        gem5 = dedupe_last(load(gfile))
        keys = sorted((k for k in viv if pred(k[0])),
                      key=lambda k: (k[0], int(k[1]) if k[1].isdigit() else 0))
        for (name, src) in keys:
            v = viv[(name, src)]
            g = gem5.get((name, src))
            row = {
                "test": name,
                "bw_cfg_MBps": v.get("axi_write_bandwidth_cfg_MBps", ""),
                "src_id": src,
            }
            for mlabel, gc, vc in METRICS:
                gv = fnum(g.get(gc)) if g else None
                vv = fnum(v.get(vc))
                row[f"{mlabel}_gem5"] = round_or_blank(gv)
                row[f"{mlabel}_viv"] = round_or_blank(vv)
            out_rows.append(row)

    cols = ["test", "bw_cfg_MBps", "src_id"]
    for mlabel, _g, _v in METRICS:
        cols += [f"{mlabel}_gem5", f"{mlabel}_viv"]

    path = os.path.join(R, "incast_match_check.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {path}  ({len(out_rows)} rows)")
    print("Columns:", ", ".join(cols))


if __name__ == "__main__":
    main()
