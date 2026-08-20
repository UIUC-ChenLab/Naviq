# Compact Clustered Read-Anomaly Diagnostic

Source runs:

- original compact row: `parameter_sweep_phase3_incast_placement`, row 5
- no-trace reproducibility rerun: `parameter_sweep_phase3_compact_repro`
- occupancy rerun: `parameter_sweep_phase3_compact_occ_trace`
- reduced queue-trace rerun: `parameter_sweep_phase3_compact_short100_queue_trace`
- write-only check: `parameter_sweep_phase3_compact_write_only`

The target is the compact clustered placement from `noc_testing/sweep_plans/parameter_sweep/incast_placement_path_phase3.csv`, with 4 AXI-MM NMUs targeting one NSU.

## Reproducibility

The high compact-clustered read latency is reproducible. The original, no-trace rerun, and occupancy rerun all completed 1000 reads and 1000 writes per source with the same pattern: writes remain low-latency, while reads have very large average and tail latency.

| run | src | avg W | p99 W | max W | avg R | p99 R | max R | read BW | writes | reads |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| original | 0 | 136.10 | 233 | 259 | 6993.82 | 10280 | 10281 | 3216.50 | 1000 | 1000 |
| original | 1 | 142.56 | 220 | 253 | 4145.97 | 10040 | 10240 | 3204.75 | 1000 | 1000 |
| original | 2 | 138.98 | 241 | 318 | 6292.75 | 10280 | 10281 | 3203.48 | 1000 | 1000 |
| original | 3 | 144.44 | 239 | 285 | 3160.41 | 8799 | 8974 | 3200.34 | 1000 | 1000 |
| repro | 0 | 136.69 | 244 | 267 | 6778.66 | 10241 | 10281 | 3204.65 | 1000 | 1000 |
| repro | 1 | 142.13 | 216 | 248 | 4573.46 | 10232 | 10240 | 3202.96 | 1000 | 1000 |
| repro | 2 | 138.85 | 240 | 286 | 6469.97 | 10320 | 10321 | 3203.70 | 1000 | 1000 |
| repro | 3 | 144.47 | 237 | 305 | 2912.12 | 8484 | 8859 | 3199.36 | 1000 | 1000 |
| occ | 0 | 136.57 | 229 | 265 | 6877.60 | 10241 | 10241 | 3205.23 | 1000 | 1000 |
| occ | 1 | 141.83 | 217 | 244 | 4524.65 | 10240 | 10240 | 3204.75 | 1000 | 1000 |
| occ | 2 | 138.70 | 237 | 340 | 6759.76 | 10360 | 10361 | 3204.29 | 1000 | 1000 |
| occ | 3 | 145.03 | 236 | 265 | 2838.40 | 8477 | 8737 | 3200.56 | 1000 | 1000 |

## Reduced Queue-Trace Run

The 100-transaction queue-trace run completed successfully and produced a manageable queue trace:

- result CSV: `noc_testing/artifacts/generated/results/gem5_incast_compact_short_diagnostic_parameter_sweep_phase3_compact_short100_queue_trace.csv`
- queue trace: `noc_testing/artifacts/curated/final_project/traces/diagnostics/parameter_sweep_phase3_compact_short100_queue_trace/row_1_incast_compact_clustered_100txn/nps_queue_trace.csv`
- queue trace size: about 14 MB
- queue trace rows: 267,942

| src | avg W | p99 W | max W | avg R | p99 R | max R | read BW | writes | reads |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 138.61 | 254 | 254 | 674.84 | 1324 | 1324 | 3274.29 | 100 | 100 |
| 1 | 142.42 | 222 | 222 | 593.07 | 1189 | 1189 | 3197.20 | 100 | 100 |
| 2 | 140.63 | 246 | 246 | 653.14 | 1329 | 1329 | 3224.38 | 100 | 100 |
| 3 | 143.67 | 204 | 204 | 581.07 | 1107 | 1107 | 3205.21 | 100 | 100 |

The short run shows the same signature at smaller scale: write latency stays around 140 cycles, while read latency grows into hundreds of cycles and has a much larger tail. The max read latency scaling from roughly 1.1K-1.3K cycles at 100 transactions to roughly 8.7K-10.4K cycles at 1000 transactions suggests accumulated read-side queuing/serialization, not a one-off parser error.

## Write-Only Check

The write-only compact run completed 1000 writes and 0 reads per source. Write latency stayed normal:

| src | avg W | p99 W | max W | write BW | writes | reads |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 132.01 | 225 | 269 | 3820.58 | 1000 | 0 |
| 1 | 136.66 | 209 | 264 | 3692.57 | 1000 | 0 |
| 2 | 134.66 | 226 | 251 | 3746.52 | 1000 | 0 |
| 3 | 139.69 | 225 | 277 | 3613.55 | 1000 | 0 |

This argues against a general write-response-path problem. In the interleaved compact runs, writes and write responses remain healthy while read data responses are delayed.

## Baseline Comparison

| placement | mean avg W | W spread | mean avg R | R spread | read p99 range | read max range |
|---|---:|---:|---:|---:|---:|---:|
| spread baseline | 246.60 | 26.61 | 240.57 | 27.72 | 280-309 | 302-355 |
| center hotspot | 174.76 | 0.89 | 172.02 | 2.00 | 217-225 | 238-262 |
| compact original | 140.52 | 8.34 | 5148.24 | 3833.41 | 8799-10280 | 8974-10281 |
| compact repro | 140.54 | 7.78 | 5183.55 | 3866.54 | 8484-10320 | 8859-10321 |
| compact occupancy | 140.53 | 8.46 | 5250.10 | 4039.20 | 8477-10360 | 8737-10361 |

Compact clustered is therefore not simply "bad placement" in both directions. It is excellent for writes, but pathological for reads.

## Occupancy And Queue Resources

Full compact occupancy trace:

- run tag: `parameter_sweep_phase3_compact_occ_trace`
- trace: `noc_testing/artifacts/curated/final_project/traces/diagnostics/parameter_sweep_phase3_compact_occ_trace/row_5_incast_compact_clustered/nps_occ_all.csv`
- size: about 483 KB

Top occupancy resources:

| resource | type | port | max occupancy | avg occupancy |
|---|---|---:|---:|---:|
| `NOC_NPS_VNOC_X0Y0` | VNOC | 1 | 13 | 4.913 |
| `NOC_NPS_VNOC_X0Y3` | VNOC | 3 | 10 | 2.588 |
| `NOC_NPS_VNOC_X0Y1` | VNOC | 2 | 8 | 2.634 |
| `NOC_NPS_VNOC_X0Y0` | VNOC | 2 | 8 | 2.409 |
| `NOC_NPS_VNOC_X0Y1` | VNOC | 0 | 8 | 1.913 |

Top queue-depth resources from the 100-transaction queue trace:

| resource | type | queue | inport | vc | max depth | avg depth |
|---|---|---|---:|---:|---:|---:|
| `NOC_NPS_VNOC_X0Y3` | VNOC | credit | 3 | -1 | 7 | 1.560 |
| `NOC_NPS_VNOC_X0Y0` | VNOC | data_vc | 2 | 1 | 5 | 3.692 |
| `NOC_NPS_VNOC_X0Y0` | VNOC | data_vc | 1 | 1 | 5 | 3.670 |
| `NOC_NPS_VNOC_X0Y3` | VNOC | data_vc | 0 | 5 | 5 | 3.579 |
| `NOC_NPS_VNOC_X0Y1` | VNOC | data_vc | 0 | 1 | 5 | 3.546 |

The compact trace points to local VNOC resources around X0Y0-X0Y3, not to the high-occupancy HNOC/RPTR resources seen in the spread baseline. This is consistent with a local read-response convergence/serialization issue in the clustered placement.

## Conclusion

The compact clustered read anomaly appears to be real simulator behavior, not a result CSV parsing issue:

- the monitor log directly reports the high read latencies;
- all expected reads and writes complete;
- the pattern is reproducible across independent runs;
- a shorter 100-transaction run shows the same read-only latency growth at smaller scale;
- write latency remains normal in interleaved and write-only compact runs.

The best current explanation is a read-response path issue caused by compact placement: multiple nearby NMUs target one nearby NSU, and read data responses appear to serialize through local VNOC resources. It does not look like a general write-response bottleneck. A pure read-only test would be useful, but the current C++ `AxiRandomTrafficGenerator` mode parser does not accept `READ_ONLY` even though the Python parameter advertises it, so that should be fixed before using read-only runs as evidence.
