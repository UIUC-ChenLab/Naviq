# Phase 2 Incast Buffer-Depth Sweep Analysis

Source: `noc_testing/artifacts/generated/results/gem5_buffer_depth_aximm_incast_phase2_parameter_sweep_phase2_incast.csv`

This is the post-live-capacity-patch rerun. The 4-NMU/1-NSU incast workload uses AXI-MM interleaved traffic, 1000 transactions per source, unlimited injection, and the spread placement.

All 8 plan rows completed with `gem5_return_code=0`, producing 32 source-level rows. Aggregates below use mean source average latency, worst source P95/P99/max latency, and summed source bandwidth.

## Data VC Sweep (`ctrl_vc=1`)

| row | data_vc | Avg W | dW | Avg R | dR | P95/P99 W | P95/P99 R | Total BW W | dBW W | Total BW R | dBW R | Max W/R | JFI W/R | Runtime s | RC |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 345.22 | +0.00% | 324.51 | +0.00% | 480/502 | 414/458 | 5825.99 | +0.00% | 5827.56 | +0.00% | 522/491 | 0.9981/0.9981 | 20.64 | 0 |
| 2 | 2 | 345.15 | -0.02% | 323.81 | -0.21% | 473/501 | 404/456 | 5824.78 | -0.02% | 5826.35 | -0.02% | 529/475 | 0.9983/0.9983 | 20.44 | 0 |
| 3 | 4 | 343.64 | -0.45% | 324.22 | -0.09% | 471/498 | 402/453 | 5848.23 | +0.38% | 5850.00 | +0.39% | 515/475 | 0.9986/0.9986 | 20.37 | 0 |
| 4 | 8 | 345.32 | +0.03% | 324.24 | -0.08% | 474/503 | 403/452 | 5823.16 | -0.05% | 5824.83 | -0.05% | 525/478 | 0.9983/0.9983 | 20.69 | 0 |
| 5 | 16 | 342.36 | -0.83% | 323.71 | -0.24% | 469/500 | 397/446 | 5870.10 | +0.76% | 5871.76 | +0.76% | 529/470 | 0.9988/0.9988 | 20.63 | 0 |

## Control VC Sweep (`data_vc=4`)

| row | ctrl_vc | Avg W | dW | Avg R | dR | P95/P99 W | P95/P99 R | Total BW W | dBW W | Total BW R | dBW R | Max W/R | JFI W/R | Runtime s | RC |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 1 | 343.64 | +0.00% | 324.22 | +0.00% | 471/498 | 402/453 | 5848.23 | +0.00% | 5850.00 | +0.00% | 515/475 | 0.9986/0.9986 | 20.37 | 0 |
| 6 | 2 | 270.19 | -21.38% | 262.78 | -18.95% | 346/355 | 311/333 | 7401.03 | +26.55% | 7402.02 | +26.53% | 370/338 | 0.9985/0.9985 | 18.32 | 0 |
| 7 | 4 | 247.09 | -28.10% | 240.53 | -25.81% | 302/324 | 286/308 | 8068.64 | +37.97% | 8070.18 | +37.95% | 345/334 | 0.9989/0.9989 | 17.13 | 0 |
| 8 | 8 | 246.99 | -28.13% | 240.48 | -25.83% | 297/334 | 284/301 | 8070.01 | +37.99% | 8071.94 | +37.98% | 355/323 | 0.9989/0.9989 | 16.78 | 0 |

## Per-Source Skew

| row | config | write spread | read spread | slow W src | slow R src | fast W src | fast R src |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | data1_ctrl1 | 38.86 | 25.66 | 3 | 3 | 0 | 0 |
| 2 | data2_ctrl1 | 35.53 | 23.75 | 3 | 3 | 2 | 0 |
| 3 | data4_ctrl1 | 32.68 | 24.52 | 3 | 3 | 0 | 0 |
| 4 | data8_ctrl1 | 36.35 | 24.97 | 3 | 3 | 0 | 0 |
| 5 | data16_ctrl1 | 29.32 | 24.46 | 3 | 3 | 0 | 0 |
| 6 | data4_ctrl2 | 27.45 | 22.78 | 3 | 3 | 0 | 0 |
| 7 | data4_ctrl4 | 23.87 | 28.57 | 3 | 3 | 1 | 1 |
| 8 | data4_ctrl8 | 23.42 | 27.48 | 3 | 3 | 1 | 1 |

## Diagnostic Occupancy Traces

| row | reason | run tag | trace status | occ trace size |
| ---: | --- | --- | --- | ---: |
| 1 | lowest buffer depth | `parameter_sweep_phase2_incast_row1_occ_trace` | present | 6.58 MB |
| 5 | highest data VC buffer depth | `parameter_sweep_phase2_incast_row5_occ_trace` | present | 6.76 MB |
| 4 | worst aggregate write latency | `parameter_sweep_phase2_incast_row4_occ_trace` | present | 6.76 MB |

Top occupancy resources from selected traces:

### Row 1: lowest buffer depth

| resource | type | port | max occ | avg occ | max buffer |
| --- | --- | ---: | ---: | ---: | ---: |
| `NOC_NPS_VNOC_X1Y2` | VNOC | 1 | 2 | 0.145 | 20 |
| `NOC_NPS_VNOC_X1Y6` | VNOC | 1 | 2 | 0.143 | 20 |
| `NOC_NPS_VNOC_X1Y4` | VNOC | 1 | 2 | 0.134 | 20 |
| `NOC_NPS_VNOC_X1Y8` | VNOC | 1 | 2 | 0.127 | 20 |
| `NOC_NPS_VNOC_X1Y12` | VNOC | 1 | 2 | 0.125 | 20 |

### Row 5: highest data VC buffer depth

| resource | type | port | max occ | avg occ | max buffer |
| --- | --- | ---: | ---: | ---: | ---: |
| `NOC_NPS_VNOC_X1Y6` | VNOC | 1 | 2 | 0.145 | 140 |
| `NOC_NPS_VNOC_X1Y8` | VNOC | 1 | 2 | 0.134 | 140 |
| `NOC_NPS_VNOC_X1Y2` | VNOC | 1 | 2 | 0.134 | 140 |
| `NOC_NPS_VNOC_X1Y4` | VNOC | 1 | 2 | 0.134 | 140 |
| `NOC_NPS_VNOC_X1Y10` | VNOC | 1 | 2 | 0.132 | 140 |

### Row 4: worst aggregate write latency

| resource | type | port | max occ | avg occ | max buffer |
| --- | --- | ---: | ---: | ---: | ---: |
| `NOC_NPS_VNOC_X1Y6` | VNOC | 1 | 2 | 0.145 | 140 |
| `NOC_NPS_VNOC_X1Y8` | VNOC | 1 | 2 | 0.134 | 140 |
| `NOC_NPS_VNOC_X1Y2` | VNOC | 1 | 2 | 0.134 | 140 |
| `NOC_NPS_VNOC_X1Y4` | VNOC | 1 | 2 | 0.134 | 140 |
| `NOC_NPS_VNOC_X1Y10` | VNOC | 1 | 2 | 0.132 | 140 |

## Interpretation

- After the live-capacity patch, the incast experiment shows a clear control-buffer sensitivity. At `data_vc=4`, increasing `ctrl_vc` from 1 to 4/8 reduces aggregate average write/read latency by about 28%/26% and raises aggregate bandwidth by about 39%/35%.
- Sweeping data VC depth with `ctrl_vc=1` remains a weak effect in this workload. Average latency and bandwidth move only around 1% across data depths 1-16, so the bottleneck is not primarily data VC storage for this placement and traffic shape.
- The best rows are `data_vc=4, ctrl_vc=4` and `data_vc=4, ctrl_vc=8`; they are almost identical. That suggests the useful control-buffer knee is around 4 for this test.
- No run failed. There is no sign of simulator instability, but row-level tail latency is much higher when `ctrl_vc=1`, consistent with control-path/response-path pressure in the incast case.
