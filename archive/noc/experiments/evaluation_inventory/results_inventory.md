# Historical Evaluation Results Inventory

This file separates report-ready results from debug, trace-only, and superseded runs. Do not treat files in the debug/superseded section as final report evidence unless the note explicitly says they are diagnostic support.

## Experiment Inventory

### Experiment 1: Buffer-Depth Sensitivity

- Purpose: Measure whether common live NoC VC buffer capacity affects AXI-MM latency, bandwidth, tails, and fairness.
- Status: final.
- Sweep plans:
  - `noc_testing/sweep_plans/parameter_sweep/buffer_depth_aximm_incast_equal_exp1.csv`
- Result CSVs:
  - `noc_testing/artifacts/curated/final_project/results/final/gem5_buffer_depth_aximm_incast_equal_exp1_parameter_sweep_exp1_equal_buffer_depth.csv`
- Analysis reports:
  - `archive/noc/experiments/parameter_sweep/exp1_equal_buffer_depth_analysis.md`
- Relevant trace artifacts: none for the final equal-depth full sweep.
- Figure artifacts:
  - `noc_testing/plots/511/exp1_buffer_depth_knee.png`
  - `noc_testing/plots/511/exp1_buffer_depth_knee.svg`
  - `noc_testing/plots/511/exp1_buffer_depth_knee.pdf`
- Takeaway: The corrected equal-depth run shows a clear knee around common VC depth 4. Raising both `buffers_per_data_vc` and `buffers_per_ctrl_vc` from 1 to 4 reduces aggregate average latency by about 27% and increases aggregate bandwidth by about 39%, while depths 8 and 16 add little.
- Caveats: Any buffer-depth results generated before the live-capacity/control-VC patch are superseded. The earlier split data/control sweep is useful for internal diagnosis, but the final report should use the equal-depth run because it avoids over-emphasizing the data/control naming distinction.
- Recommended tables: Equal buffer-depth summary table in the main report; the earlier split sweep can be mentioned only as supporting/debug context.

### Experiment 2: Placement/Path Sensitivity

- Purpose: Show how endpoint placement and route overlap affect per-source latency skew, fairness, and aggregate behavior.
- Status: final.
- Sweep plan: `noc_testing/sweep_plans/parameter_sweep/incast_placement_path_phase3.csv`
- Result CSV: `noc_testing/artifacts/curated/final_project/results/final/gem5_incast_placement_path_phase3_parameter_sweep_phase3_incast_placement.csv`
- Analysis report: `archive/noc/experiments/parameter_sweep/phase3_incast_placement_path_analysis.md`
- Relevant trace artifacts:
  - `noc_testing/artifacts/curated/final_project/traces/experiment2/parameter_sweep_phase3_incast_placement_row1_occ_trace/row_1_incast_spread_baseline/nps_occ_all.csv`
  - `noc_testing/artifacts/curated/final_project/traces/experiment2/parameter_sweep_phase3_incast_placement_row6_occ_trace/row_6_incast_mixed_spread/nps_occ_all.csv`
  - `noc_testing/artifacts/curated/final_project/traces/experiment2/parameter_sweep_phase3_incast_placement_row7_occ_trace/row_7_incast_center_hotspot/nps_occ_all.csv`
- Figure artifacts:
  - `noc_testing/plots/511/exp2_placement_source_skew.png`
  - `noc_testing/plots/511/exp2_placement_source_skew.svg`
  - `noc_testing/plots/511/exp2_placement_source_skew.pdf`
- Takeaway: Placement dominates source skew. Reversing source ordering moves the slow source, destination movement changes spread and fairness, mixed spread creates the worst source imbalance, and center hotspot is surprisingly balanced for this topology.
- Caveats: The compact clustered row has a read-side anomaly and should be discussed with the diagnostic evidence below rather than treated as an ordinary placement datapoint.
- Recommended tables: Placement/path summary table in the main report; per-source placement details in the appendix.

### Experiment 3: Routing/Arbitration Sensitivity

- Purpose: Compare routing/path choices such as shortest, bad path, high-overlap, and path-diverse cases.
- Status: tentative.
- Sweep plans: chapter/demo experiment 3 plans, including the tornado and chapter3 demo variants.
- Result CSV candidates:
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment3_plan_chapter3_demo_exp3__r01__exp3_shortest.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment3_plan_chapter3_demo_exp3__r01__exp3_bad_path.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment3_plan_chapter3_demo_exp3__r01__exp3_high_overlap.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment3_plan_chapter3_demo_exp3__r01__exp3_path_diverse.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment3_plan_exp3_tornado_uncapped__r01__*.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment3_plan_exp3_tornado_uncapped_tx500__r01__*.csv`
- Analysis report: not yet identified in `archive/noc/experiments/parameter_sweep`.
- Relevant trace artifacts:
  - `noc_testing/artifacts/curated/final_project/traces/experiment3/chapter3_demo_exp3__r01__exp3_shortest/`
  - `noc_testing/artifacts/curated/final_project/traces/experiment3/chapter3_demo_exp3__r01__exp3_bad_path/`
  - `noc_testing/artifacts/curated/final_project/traces/experiment3/chapter3_demo_exp3__r01__exp3_high_overlap/`
  - `noc_testing/artifacts/curated/final_project/traces/experiment3/chapter3_demo_exp3__r01__exp3_path_diverse/`
- Takeaway: There are result files for routing/path variants, but they need a short consistency pass before they should be used as final evidence. Treat this experiment as planned/tentative unless someone confirms which run set is the intended final one.
- Caveats: Do not mix demo, tornado, capped, and uncapped variants in one table without normalizing the workload and explaining the difference.
- Recommended tables: Optional appendix table after final run-set selection.

### Experiment 4: Mixed AXI-MM / AXI-S Traffic

- Purpose: Study interference between memory-mapped AXI-MM and streaming AXI-S traffic under shared or overlapping NoC paths.
- Status: pending/tentative.
- Result CSV candidates:
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment4_plan_exp4_main_1__r01__exp4_near_single_target.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment4_plan_exp4_main_1__r01__exp4_near_distributed_targets.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment4_plan_exp4_main_1__r01__exp4_spread_single_target.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment4_plan_exp4_main_1__r01__exp4_spread_distributed_targets.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment4_plan_exp4_main_1__r01__exp4_far_single_target.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment4_plan_exp4_main_1__r01__exp4_far_distributed_targets.csv`
  - `noc_testing/artifacts/curated/final_project/results/tentative/gem5_experiment4_uncapped_plan_chapter3_uncapped_sensitivity_20260505_exp4.csv`
- Analysis report: not yet identified in `archive/noc/experiments/parameter_sweep`.
- Relevant trace artifacts:
  - `noc_testing/artifacts/curated/final_project/traces/experiment4/chapter3_uncapped_sensitivity_20260505_exp4/`
- Takeaway: There are Experiment 4-looking artifacts, but they should be treated as pending until the partner data and workload definition are confirmed. The report can include a placeholder table if mixed AXI-MM/AXI-S results are not ready.
- Caveats: Current file names alone do not prove the final mixed AXI-MM/AXI-S setup, path-overlap condition, or whether the rows are report-ready.
- Recommended tables: Placeholder mixed AXI-MM/AXI-S table only.

### Experiment 5: Endpoint-Width Sensitivity

- Purpose: Measure how NMU/NSU endpoint data width affects AXI-MM latency, bandwidth, fairness, and read/write behavior under fixed 512-byte transactions.
- Status: final.
- Sweep plan: `noc_testing/sweep_plans/parameter_sweep/endpoint_width_incast_exp5.csv`
- Result CSV: `noc_testing/artifacts/curated/final_project/results/final/gem5_endpoint_width_incast_exp5_parameter_sweep_exp5_endpoint_width.csv`
- Analysis report: `archive/noc/experiments/parameter_sweep/endpoint_width_exp5_analysis.md`
- Relevant trace artifacts: none from the corrected final full sweep; older trace-only reruns are debug-only.
- Takeaway: Endpoint width is not the dominant bottleneck for the tested incast workloads. Spread placement is stable around 8.1 GB/s under unlimited load, compact placement has high write bandwidth but pathological read latency under unlimited load, and controlled 400 MB/s/source rows are stable for all widths.
- Caveats: Use only the corrected rerun with `address_increment=512` and controlled rows at 400 MB/s/source. Exclude the old failed compact 128-bit unlimited row and all pre-fix endpoint-width diagnostics from final tables.
- Recommended tables: Endpoint-width summary table in the main report; per-source rows in the appendix.

### Diagnostic: Compact Clustered Read Anomaly

- Purpose: Determine whether the compact clustered high read latency is real NoC behavior, a generator artifact, a read-response path issue, or a parsing issue.
- Status: diagnostic support.
- Analysis report: `archive/noc/experiments/parameter_sweep/compact_clustered_read_anomaly_diagnostic.md`
- Result CSVs:
  - `noc_testing/artifacts/curated/final_project/results/final/gem5_incast_placement_path_phase3_parameter_sweep_phase3_incast_placement.csv`
  - `noc_testing/artifacts/curated/final_project/results/diagnostics/gem5_incast_placement_path_phase3_parameter_sweep_phase3_compact_repro.csv`
  - `noc_testing/artifacts/curated/final_project/results/diagnostics/gem5_incast_placement_path_phase3_parameter_sweep_phase3_compact_occ_trace.csv`
  - `noc_testing/artifacts/curated/final_project/results/diagnostics/gem5_incast_compact_short_diagnostic_parameter_sweep_phase3_compact_short100_queue_trace.csv`
  - `noc_testing/artifacts/curated/final_project/results/diagnostics/gem5_incast_compact_short_diagnostic_parameter_sweep_phase3_compact_write_only.csv`
- Relevant trace artifacts:
  - `noc_testing/artifacts/curated/final_project/traces/diagnostics/parameter_sweep_phase3_compact_occ_trace/row_5_incast_compact_clustered/nps_occ_all.csv`
  - `noc_testing/artifacts/curated/final_project/traces/diagnostics/parameter_sweep_phase3_compact_short100_queue_trace/row_1_incast_compact_clustered_100txn/nps_queue_trace.csv`
- Figure artifacts:
  - `noc_testing/plots/511/diagnostic_compact_read_anomaly.png`
  - `noc_testing/plots/511/diagnostic_compact_read_anomaly.svg`
  - `noc_testing/plots/511/diagnostic_compact_read_anomaly.pdf`
- Takeaway: The anomaly is reproducible, all expected transactions complete, write latency remains normal, and the shorter queue-trace run shows the same read-side growth at smaller scale. The evidence points to read-response convergence/serialization around local VNOC resources rather than a CSV parsing issue.
- Caveats: This is a diagnostic subsection, not a separate broad sweep. Use it to explain the compact clustered row in Experiments 2 and 5.
- Recommended tables: Compact clustered diagnostic table in the main report or appendix depending on space.

## Debug/Superseded Runs

| Path or group | Why superseded/debug-only | Exclude from report tables? | Still useful? |
|---|---|---:|---|
| Any buffer-depth CSV/report generated before the live-capacity/control-VC patch | The old rows changed CSV knobs but did not drive the live VC/credit capacity correctly. Current final buffer-depth files are the post-fix reruns listed under Experiment 1. | Yes | Historical only |
| `noc_testing/artifacts/generated/results/gem5_buffer_depth_aximm_incast_phase2_parameter_sweep_phase2_incast.csv` and `archive/noc/experiments/parameter_sweep/phase2_incast_buffer_depth_analysis.md` | Superseded as the main report Experiment 1 by the equal-depth sweep. The split data/control interpretation is less clean for presentation. | Yes | Yes, supporting context |
| `noc_testing/artifacts/generated/results/gem5_buffer_depth_aximm_first_parameter_sweep_buffer_depth_first.csv` and `archive/noc/experiments/parameter_sweep/buffer_depth_first_analysis.md` | Single-flow buffer-depth baseline; useful sanity check, but not the final incast result. | Yes | Yes, appendix/debug context |
| Historical pre-fix version of `noc_testing/artifacts/generated/results/gem5_endpoint_width_incast_exp5_parameter_sweep_exp5_endpoint_width.csv` | The corrected rerun overwrote this path before the curated copy was made; the old run used overlapping/default address stepping and included the compact 128-bit unlimited failure. | Yes | Only as history if recovered |
| `noc_testing/artifacts/generated/results/gem5_compact128_diag_100txn_parameter_sweep_exp5_compact128_100txn_diag.csv` | Endpoint-width compact 128-bit debug run that reproduced the AxiListManager/tag 255 failure before the address increment fix. | Yes | Yes, documents root-cause debugging |
| `noc_testing/artifacts/generated/results/gem5_compact128_unique_ids_100txn_parameter_sweep_exp5_compact128_unique_ids_100txn_diag.csv` | Debug attempt for the same compact 128-bit failure; not a final workload. | Yes | Yes, debugging history |
| `noc_testing/artifacts/generated/results/gem5_compact128_256B_100txn_parameter_sweep_exp5_compact128_256B_100txn_diag.csv` | Short diagnostic variant used to isolate the address/split issue. | Yes | Yes, debugging history |
| `noc_testing/artifacts/generated/results/gem5_compact128_512B_addrinc512_100txn_parameter_sweep_exp5_compact128_addrinc512_100txn_diag.csv` | Short verification of the address increment fix; superseded by full Experiment 5 rerun. | Yes | Yes, fix validation |
| `noc_testing/artifacts/generated/results/gem5_compact128_512B_addrinc512_1000txn_parameter_sweep_exp5_compact128_addrinc512_1000txn_diag.csv` | Full-size compact 128-bit verification; superseded by corrected 12-row Experiment 5 rerun. | Yes | Yes, fix validation |
| `noc_testing/artifacts/generated/results/gem5_endpoint_width_incast_exp5_parameter_sweep_exp5_compact128_controlled400_diag.csv` | Single-row endpoint-width diagnostic; superseded by corrected full Experiment 5 rerun. | Yes | Yes, fix validation |
| `noc_testing/artifacts/generated/results/gem5_endpoint_width_incast_exp5_parameter_sweep_exp5_compact128_fixed_addrinc_verify.csv` | Single-row address-increment verification; superseded by corrected full Experiment 5 rerun. | Yes | Yes, fix validation |
| `noc_testing/artifacts/generated/results/gem5_placement_test_really_small_parameter_sweep_phase0_row1.csv` | Phase 0 plumbing run with one transaction; validates workflow only. | Yes | Yes, reproducibility |
| `noc_testing/artifacts/generated/results/gem5_placement_test_really_small_parameter_sweep_phase0_row1_trace.csv` | Phase 0 trace-plumbing run with one transaction; not performance evidence. | Yes | Yes, artifact capture check |
| `noc_testing/artifacts/generated/results/gem5_placement_intensity_short_long_v2_parameter_sweep_phase0_5_2hop_1000txn.csv` | Phase 0.5 metric sanity baseline; not part of final experiment narrative. | Yes | Yes, sanity baseline |
| `noc_testing/artifacts/generated/results/gem5_parameter_sweep_phase1_knob_smoke_parameter_sweep_phase1_knob_smoke.csv` | Phase 1 knob smoke test; not a report experiment. | Yes | Yes, configuration plumbing |
| `noc_testing/artifacts/generated/results/gem5_buffer_depth_aximm_incast_phase2_parameter_sweep_phase2_incast_row1_occ_trace.csv`, row4, row5 | Trace-only reruns duplicate Experiment 1 settings and are intended for diagnostics, not final metric tables. | Yes | Yes, trace support |
| `noc_testing/artifacts/generated/results/gem5_incast_placement_path_phase3_parameter_sweep_phase3_incast_placement_row1_occ_trace.csv`, row6, row7 | Trace-only reruns duplicate Experiment 2 settings and are intended for diagnostics. | Yes | Yes, trace support |
| `noc_testing/artifacts/generated/results/gem5_endpoint_width_incast_exp5_parameter_sweep_exp5_endpoint_width_row4_occ_trace.csv`, row6, row10, row12 | Older endpoint-width trace reruns from the pre-corrected load/address setup. | Yes | Debug only |
| `noc_testing/artifacts/generated/results/gem5_endpoint_width_incast_exp5_short_queue_parameter_sweep_exp5_endpoint_width_compact512_short100_queue.csv` | Reduced queue-trace diagnostic, not part of the final full endpoint-width sweep. | Yes | Appendix/debug only |
| `noc_testing/artifacts/curated/final_project/results/diagnostics/gem5_incast_placement_path_phase3_parameter_sweep_phase3_compact_repro.csv` and compact diagnostic reruns | Diagnostic repeats of the compact clustered placement. | No for diagnostic table; yes for ordinary sweep tables | Yes, supports anomaly explanation |

## Recommended Final Tables

### A. Buffer-Depth Summary Table

- Source CSV/report:
  - `noc_testing/artifacts/curated/final_project/results/final/gem5_buffer_depth_aximm_incast_equal_exp1_parameter_sweep_exp1_equal_buffer_depth.csv`
  - `archive/noc/experiments/parameter_sweep/exp1_equal_buffer_depth_analysis.md`
- Placement: main report.
- Columns: workload/placement, common VC buffer depth, average write latency, average read latency, aggregate average latency, total write bandwidth, total read bandwidth, P99/max latency, return code, main conclusion.
- Caption draft: "Shared VC buffer depth has a clear knee for the incast workload. Increasing both data and control VC depths from 1 to 4 recovers most of the latency and bandwidth loss, while deeper buffers add little."
- Exclude: pre-fix buffer-depth runs, the older split data/control sweep, the single-flow sweep, and trace-only reruns.

### B. Placement/Path Summary Table

- Source CSV/report:
  - `noc_testing/artifacts/curated/final_project/results/final/gem5_incast_placement_path_phase3_parameter_sweep_phase3_incast_placement.csv`
  - `archive/noc/experiments/parameter_sweep/phase3_incast_placement_path_analysis.md`
- Placement: main report.
- Columns: placement, mean write latency, mean read latency, write spread, read spread, bandwidth JFI, slowest source, aggregate bandwidth, main observation.
- Caption draft: "Endpoint placement and route structure dominate source skew. Reordering or moving endpoints changes which source is slow and how fair the incast workload appears."
- Exclude: trace-only reruns; discuss compact clustered separately with the diagnostic table.

### C. Compact Clustered Diagnostic Table

- Source CSV/report:
  - `archive/noc/experiments/parameter_sweep/compact_clustered_read_anomaly_diagnostic.md`
  - `noc_testing/artifacts/curated/final_project/results/final/gem5_incast_placement_path_phase3_parameter_sweep_phase3_incast_placement.csv`
- Placement: main report if space allows; otherwise appendix with a short main-text callout.
- Columns: placement/run, mean write latency, mean read latency, write spread, read spread, read P99/max, top trace resource, interpretation.
- Caption draft: "Compact clustered placement is fast for writes but pathological for reads under unlimited pressure. Reproducibility and trace evidence point to local read-response serialization around VNOC resources."
- Exclude: endpoint-width compact 128-bit tag-failure runs, which are a separate address-increment artifact.

### D. Endpoint-Width Summary Table

- Source CSV/report:
  - `noc_testing/artifacts/curated/final_project/results/final/gem5_endpoint_width_incast_exp5_parameter_sweep_exp5_endpoint_width.csv`
  - `archive/noc/experiments/parameter_sweep/endpoint_width_exp5_analysis.md`
- Placement: main report.
- Columns: placement, load, width, mean write latency, mean read latency, total write bandwidth, total read bandwidth, max write/read latency, conclusion or note.
- Caption draft: "Endpoint width is not the dominant bottleneck for this incast workload. Placement and offered load explain the major behavior changes, while width has only small effects once 512-byte address increments are enforced."
- Exclude: old failed compact 128-bit unlimited row, all pre-address-increment endpoint-width diagnostics, and trace-only reruns.

### E. Mixed AXI-MM / AXI-S Table

- Source CSV/report: pending partner-confirmed results.
- Placement: appendix or placeholder in main report if data is not ready.
- Columns: workload case, AXI-MM load, AXI-S load, path overlap condition, AXI-MM avg/P99 latency, AXI-MM bandwidth retention, AXI-S bandwidth, main observation.
- Caption draft: "Planned mixed-traffic table showing how AXI-S traffic interferes with AXI-MM latency and bandwidth when paths overlap."
- Exclude: unverified Experiment 4 files until the workload definition and partner data are confirmed.

## Missing Items Or Questions

- Experiment 3 needs a chosen final run set and a short analysis report before it is report-ready.
- Experiment 4 needs partner confirmation that the available files are the intended mixed AXI-MM/AXI-S data, or else it should remain a placeholder.
- Figures still need to be selected or generated from the final tables; likely candidates are buffer control-VC knee, placement latency spread, compact read anomaly, and endpoint-width aggregate bandwidth.
- The final report should explicitly state that Phase 0/0.5 runs validate reproducibility and plumbing, not performance behavior.
