# Phase 3 Incast Placement/Path Diagnostic Sweep

Source: `noc_testing/artifacts/generated/results/gem5_incast_placement_path_phase3_parameter_sweep_phase3_incast_placement.csv`

Plan: `noc_testing/sweep_plans/parameter_sweep/incast_placement_path_phase3.csv`

This sweep keeps the Phase 2 4-NMU/1-NSU AXI-MM incast workload but varies placement/path shape:

- traffic: AXI-MM interleaved, 1000 transactions per source, 512-byte transactions, unlimited normalized injection
- buffers: `buffers_per_data_vc=4`, `buffers_per_ctrl_vc=1`
- full sweep tracing: off
- result shape: each plan row emits four source-level rows

All 7 plan rows completed with `gem5_return_code=0`, producing 28 source-level result rows.

## Aggregate Placement Summary

`W spread` and `R spread` are `max source avg latency - min source avg latency`. `W CV` and `R CV` are coefficient of variation across the four source average latencies. Bandwidth is summed across sources.

| row | placement | W spread | R spread | W CV | R CV | Total BW W | Total BW R | JFI W/R | Max W/R | slow/fast W src | runtime s | RC |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | spread baseline | 26.61 | 27.72 | 0.0397 | 0.0408 | 8088.04 | 8089.89 | 0.9986/0.9986 | 342/355 | 3/1 | 16.77 | 0 |
| 2 | reversed sources | 24.98 | 28.28 | 0.0369 | 0.0421 | 8067.77 | 8069.61 | 0.9988/0.9988 | 359/322 | 0/2 | 16.81 | 0 |
| 3 | spread, dest X0 | 52.42 | 53.06 | 0.0755 | 0.0795 | 7799.28 | 7800.78 | 0.9946/0.9946 | 380/367 | 3/0 | 17.03 | 0 |
| 4 | spread, dest X3 | 53.74 | 53.49 | 0.0780 | 0.0822 | 7753.99 | 7755.57 | 0.9943/0.9943 | 359/372 | 0/3 | 18.37 | 0 |
| 5 | compact clustered | 8.34 | 3833.41 | 0.0229 | 0.3020 | 13892.50 | 12825.08 | 1.0000/1.0000 | 318/10281 | 3/0 | 3.51 | 0 |
| 6 | mixed spread | 143.91 | 139.14 | 0.3576 | 0.3518 | 12115.69 | 12117.13 | 0.8961/0.8961 | 379/364 | 3/2 | 11.55 | 0 |
| 7 | center hotspot | 0.89 | 2.00 | 0.0019 | 0.0042 | 11267.43 | 11271.36 | 1.0000/1.0000 | 264/262 | 0/2 | 9.20 | 0 |

## Per-Source Metrics

Columns are `avgW p95W p99W bwW | avgR p95R p99R bwR`.

### Row 1: Spread Baseline

| src | write | read |
|---:|---:|---:|
| 0 | 243.94 267 281 2040.34 | 240.76 271 286 2040.62 |
| 1 | 236.03 275 291 2106.92 | 226.83 263 280 2107.27 |
| 2 | 243.79 269 281 2041.52 | 240.15 269 284 2042.12 |
| 3 | 262.64 303 324 1899.25 | 254.55 292 309 1899.88 |

### Row 2: Reversed Sources

| src | write | read |
|---:|---:|---:|
| 0 | 261.98 306 341 1904.19 | 253.14 284 302 1904.80 |
| 1 | 245.07 272 294 2030.90 | 242.53 272 289 2031.54 |
| 2 | 237.00 273 285 2099.39 | 224.86 261 273 2099.73 |
| 3 | 244.76 270 293 2033.29 | 241.45 271 286 2033.54 |

### Row 3: Spread, Destination X0

| src | write | read |
|---:|---:|---:|
| 0 | 231.34 276 295 2148.67 | 224.50 266 284 2148.91 |
| 1 | 248.51 291 314 2005.75 | 240.71 283 303 2005.99 |
| 2 | 264.84 304 323 1883.38 | 259.74 295 315 1883.88 |
| 3 | 283.76 323 348 1761.48 | 277.56 319 340 1762.00 |

### Row 4: Spread, Destination X3

| src | write | read |
|---:|---:|---:|
| 0 | 286.40 324 342 1745.55 | 278.05 320 340 1746.01 |
| 1 | 267.27 310 336 1866.25 | 259.53 299 326 1866.79 |
| 2 | 248.29 290 312 2006.07 | 237.21 279 299 2006.45 |
| 3 | 232.66 277 300 2136.12 | 224.56 267 289 2136.32 |

### Row 5: Compact Clustered

| src | write | read |
|---:|---:|---:|
| 0 | 136.10 187 233 3578.14 | 6993.82 10241 10280 3216.50 |
| 1 | 142.56 191 220 3424.84 | 4145.97 7736 10040 3204.75 |
| 2 | 138.98 193 241 3507.86 | 6292.75 10241 10280 3203.48 |
| 3 | 144.44 193 239 3381.66 | 3160.41 6337 8799 3200.34 |

### Row 6: Mixed Spread

| src | write | read |
|---:|---:|---:|
| 0 | 119.46 152 170 4050.09 | 117.75 156 168 4050.22 |
| 1 | 236.83 289 312 2100.14 | 229.40 273 292 2100.32 |
| 2 | 118.85 153 166 4066.07 | 117.40 158 169 4066.72 |
| 3 | 262.76 301 355 1899.38 | 256.54 288 315 1899.87 |

### Row 7: Center Hotspot

| src | write | read |
|---:|---:|---:|
| 0 | 175.12 201 227 2811.18 | 172.87 198 221 2812.49 |
| 1 | 174.97 206 227 2814.84 | 170.87 201 219 2816.44 |
| 2 | 174.23 201 223 2822.83 | 172.13 202 225 2823.58 |
| 3 | 174.70 200 215 2818.58 | 172.21 197 217 2818.86 |

## Diagnostic Occupancy Traces

Queue tracing was not enabled. Occupancy-only traces were captured for three rows:

| row | reason | run tag | trace size | status |
|---:|---|---|---:|---|
| 1 | current baseline | `parameter_sweep_phase3_incast_placement_row1_occ_trace` | 4.31 MB | present |
| 6 | worst write/source-fairness skew | `parameter_sweep_phase3_incast_placement_row6_occ_trace` | 2.80 MB | present |
| 7 | best balanced latency spread | `parameter_sweep_phase3_incast_placement_row7_occ_trace` | 2.05 MB | present |

Top maximum-occupancy resources:

| row | top resources |
|---:|---|
| 1 | `NOC_NPS7575_X5Y0` HNOC port 2 max 14; `NOC_NPP_RPTR_X1Y0` RPTR port 1 max 12; `NOC_NPP_RPTR_X2Y15` RPTR port 0 max 11 |
| 6 | `NOC_NPS5555_X12Y1` HNOC port 1 max 8 avg 2.219; `NOC_NPS_VNOC_X1Y0` VNOC ports 1/2 max 8; `NOC_NPS5555_X12Y0` HNOC port 2 max 7 |
| 7 | `NOC_NPS_VNOC_X1Y18` VNOC ports 1/2 max 12; `NOC_NPP_RPTR_X1Y8` RPTR port 1 max 9; `NOC_NPS_VNOC_X1Y14` VNOC port 1 max 8 |

## Interpretation

- Placement is a much stronger effect than buffer depth for this incast workload.
- Reversing source order moves the slow source from source 3 to source 0 while leaving overall spread similar. This supports the idea that the skew is path/placement driven, not inherent to a traffic-generator ID.
- Moving the destination to X0 or X3 roughly doubles the baseline source-latency spread and reduces aggregate bandwidth. The farthest source becomes the slowest in each case.
- Mixed spread creates the worst write-latency skew and lowest bandwidth fairness: write spread is 143.91 cycles and write/read bandwidth JFI drops to 0.8961. Two sources are very close and fast, while the two far sources are much slower.
- Center hotspot is the most balanced placement: write spread is only 0.89 cycles, read spread is 2.00 cycles, and bandwidth fairness is 1.0.
- Compact clustered has low write-latency spread but unusually high read latency and read-latency spread. Follow-up diagnostics are recorded in `noc_testing/parameter_sweep/compact_clustered_read_anomaly_diagnostic.md`; the anomaly is reproducible, read-side-specific, and points to local VNOC read-response queuing rather than CSV parsing.
