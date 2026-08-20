# Experiment 1 Equal Buffer-Depth Sweep Analysis

Source: `noc_testing/artifacts/generated/results/gem5_buffer_depth_aximm_incast_equal_exp1_parameter_sweep_exp1_equal_buffer_depth.csv`

Plan: `noc_testing/sweep_plans/parameter_sweep/buffer_depth_aximm_incast_equal_exp1.csv`

This is the report-facing replacement for the earlier split data/control buffer sweep. It uses the same 4-NMU/1-NSU AXI-MM incast workload, spread placement, interleaved reads/writes, 1000 transactions per source, unlimited injection, and fixed 512-byte transactions. The sweep varies one common buffer-depth knob by setting `buffers_per_data_vc` and `buffers_per_ctrl_vc` to the same value in every row.

All 5 plan rows completed with `gem5_return_code=0`, producing 20 source-level rows. Aggregates below use mean source average latency, worst source P95/P99/max latency, and summed source bandwidth. Latencies are cycles and bandwidth is MB/s.

## Equal Data/Control VC Depth Sweep

Baseline: `data_vc=1, ctrl_vc=1`.

| row | VC depth | Avg W | dW | Avg R | dR | Avg W/R | dAvg | P95/P99 W | P95/P99 R | Total BW W | dBW W | Total BW R | dBW R | Max W/R | JFI W/R | Runtime s | RC |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 345.64 | +0.00% | 324.35 | +0.00% | 335.00 | +0.00% | 476/503 | 405/458 | 5818.12 | +0.00% | 5819.84 | +0.00% | 527/472 | 0.9982/0.9982 | 20.80 | 0 |
| 2 | 2 | 270.25 | -21.81% | 262.35 | -19.12% | 266.30 | -20.51% | 347/355 | 313/333 | 7400.34 | +27.19% | 7401.37 | +27.17% | 375/366 | 0.9983/0.9983 | 18.25 | 0 |
| 3 | 4 | 246.72 | -28.62% | 240.11 | -25.97% | 243.42 | -27.34% | 297/331 | 284/302 | 8080.47 | +38.88% | 8082.20 | +38.87% | 357/380 | 0.9987/0.9987 | 17.08 | 0 |
| 4 | 8 | 246.38 | -28.72% | 240.09 | -25.98% | 243.24 | -27.39% | 305/330 | 287/302 | 8095.78 | +39.15% | 8097.56 | +39.14% | 352/315 | 0.9985/0.9985 | 17.10 | 0 |
| 5 | 16 | 246.83 | -28.59% | 240.47 | -25.86% | 243.65 | -27.27% | 301/327 | 285/301 | 8078.34 | +38.85% | 8080.09 | +38.84% | 354/314 | 0.9987/0.9987 | 17.30 | 0 |

## Interpretation

- Setting data and control VC depths together gives a clean report story: increasing common VC depth from 1 to 4 sharply improves both latency and bandwidth.
- The knee is still around depth 4. Depth 1 to 2 reduces aggregate average latency by about 20.5%, while depth 1 to 4 reduces it by about 27.3%. Depths 8 and 16 are effectively flat relative to depth 4.
- Aggregate write/read bandwidth rises from about 5.82 GB/s at depth 1 to about 8.08 GB/s at depth 4, with little additional bandwidth at depth 8 or 16.
- Tail latency also improves strongly. Worst-source write P99 drops from 503 cycles to 331 cycles at depth 4, and worst-source read P99 drops from 458 cycles to 302 cycles.
- All rows completed successfully, and bandwidth fairness remains high across all depths. This makes the equal-depth sweep a better main-report Experiment 1 than the earlier split data/control sensitivity sweep.

## Report Takeaway

For the 4-NMU/1-NSU AXI-MM incast workload, a small common VC buffer depth creates backpressure and high tail latency. Increasing both data and control VC depths to 4 recovers most of the lost performance, while deeper buffers provide little extra benefit.
