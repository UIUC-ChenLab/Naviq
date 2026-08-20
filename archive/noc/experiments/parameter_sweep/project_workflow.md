# Project Workflow

This file tracks what we should build around the knob inventory so the project becomes a repeatable experiment rather than a pile of one-off runs.

## Phase 0: Baseline Reproduction

Goal: make sure the current checked-in flow can run a small known case and emit the expected results.

Tasks:

- Pick one AXI-MM topology from `noc_testing/topology_jsons/placement_tests/`.
- Run a very small `gem5_only` point through `noc_testing/noc_sweep.py`.
- Rerun the same point with hotspot tracing enabled to verify trace artifact capture.
- Run a slightly larger same-topology point so latency percentiles and bandwidth are meaningful enough for sanity checking.
- Confirm the result CSV includes latency, bandwidth, request counts, and status.
- Save the exact command and generated topology files in the run log.

Minimum outputs:

- one sweep CSV row
- stdout/stderr log
- copied topology inputs
- pass/fail status
- exact selected input row snapshot
- run log with command line, git hash/dirty state, run tag, input CSV, row number, row-index rule, topology JSON, placement JSON, and output CSV

Current Phase 0 runs:

- `parameter_sweep_phase0_row1`: 1-transaction 2-hop AXI-MM plumbing test, hotspot off.
- `parameter_sweep_phase0_row1_trace`: same row with `--hotspot-mode both`.
- `parameter_sweep_phase0_5_2hop_1000txn`: 1000-transaction 2-hop AXI-MM metric sanity test.

Important interpretation rule: the 1-transaction runs are plumbing tests only. Use the 1000-transaction run, larger load sweeps, and selected trace-enabled reruns for performance claims.

## Phase 1: Expose Missing Model Knobs

Goal: make buffer and credit sweeps possible from CSV without editing Python by hand.

Highest-priority behavior args to add:

- `--buffers-per-data-vc`
- `--buffers-per-ctrl-vc`
- `--rptr-credits`
- `--vnoc-credits`
- `--hnoc-credits`
- `--ncrb-credits`
- `--nidb-credits`

Later NPS timing behavior args:

- `--rptr-latency`
- `--vnoc-latency`
- `--hnoc-latency`
- `--ncrb-latency`
- `--nidb-latency`

Highest-priority instrumentation args to expose separately:

- `--record-mode`
- `--hotspot-mode`
- `--hotspot-occ-gap-cycles`

Later adapter/backpressure args:

- `--protocol-buffer-size`
- `--protocol-buffer-dequeue-rate`
- `--rrob-entries`
- `--nmu-max-outstanding-reads`
- `--nmu-max-outstanding-writes`
- `--nmu-write-buffer-bytes`
- `--nsu-request-tracker-entries`
- `--axis-sink-ready-percent`

Files likely touched:

- `src/noc/setup/noc_config_funcs.py`
- `src/noc/setup/noc_config.py`
- `noc_testing/noc_sweep.py`
- CSV plans under `noc_testing/sweep_plans/`

Definition of done:

- A CSV row can set fabric buffer depths and NPS credits.
- Instrumentation columns are recorded separately from behavior knobs.
- The generated gem5 command records these values.
- The output CSV repeats these values so plots can group by them.

## Phase 2: Standardize Per-Run Artifacts

Goal: every run should leave enough evidence to debug and reproduce it.

Recommended per-run artifact directory:

```text
noc_testing/artifacts/runs/<plan>/<run_name>/
```

Recommended files:

- `manifest.json`: knobs, paths, git state, command, start/end time.
- `gem5_stdout.log` and `gem5_stderr.log`.
- copied `.nts`, `.ncr`, topology JSON, and placement JSON when used.
- copied monitor CSVs from `src/noc/testing/artifacts/graphs/`.
- optional plot images generated from the monitor CSVs.

Important cleanup: `src/noc/testing/artifacts/graphs/` appears to be a shared output location, so the sweep runner should copy or move it into the per-run artifact directory before the next run overwrites it.

## Phase 3: Build The First Real Sweep Set

Goal: collect enough data to answer the proposal questions without exploding the design space.

Analysis workflow:

1. Run broad sweeps with summary metrics and tracing disabled or limited.
2. Rank and flag interesting cases: high tail latency, bandwidth collapse, saturation, fairness loss, or hotspot concentration.
3. Rerun selected cases with hotspot and ready/valid tracing enabled.
4. Use the trace artifacts to explain the summary metrics in terms of queueing, backpressure, route overlap, and localized congestion.

Recommended order:

1. Load sweep: fixed topology, fixed placement, default microarchitecture, vary bandwidth.
2. Burst sweep: fixed below-saturation load, vary burst size and burst length.
3. Placement sweep: fixed traffic profile, vary hop count/path overlap.
4. Buffer sweep: use one congested case and vary data/control VC buffer depths.
5. Credit sweep: use the same congested case and vary one NPS credit family at a time.
6. VC/flit sweep: vary `vcs_per_vnet` and `ni_flit_size` after buffers are understood.

First buffer-depth plan:

- CSV: `noc_testing/sweep_plans/parameter_sweep/buffer_depth_aximm_first.csv`
- Traffic: AXI-MM interleaved, 1000 transactions, 512-byte requests, unlimited offered load.
- Topologies: fixed 2-hop, 16-hop, and 32-hop 1-NMU/1-NSU paths.
- Matrix: vary `buffers_per_data_vc` with `buffers_per_ctrl_vc=1`, then vary `buffers_per_ctrl_vc` with `buffers_per_data_vc=4`.
- Instrumentation: `record_mode=0`, `hotspot_mode=off` by default; rerun selected interesting rows with tracing enabled.

Contention buffer-depth plan:

- CSV: `noc_testing/sweep_plans/parameter_sweep/buffer_depth_aximm_incast_phase2.csv`
- Analysis: `noc_testing/parameter_sweep/phase2_incast_buffer_depth_analysis.md`
- Traffic: 4 AXI-MM NMUs sending to one AXI-MM BRAM/NSU, interleaved reads/writes, 1000 transactions per source, 512-byte requests, unlimited offered load.
- Placement: `topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_spread.place.json`.
- Matrix: vary `buffers_per_data_vc` with `buffers_per_ctrl_vc=1`, then vary `buffers_per_ctrl_vc` with `buffers_per_data_vc=4`.
- Instrumentation: full sweep keeps tracing off; selected diagnostic rows use occupancy tracing only to avoid very large queue-trace artifacts.

Placement/path diagnostic plan:

- CSV: `noc_testing/sweep_plans/parameter_sweep/incast_placement_path_phase3.csv`
- Analysis: `noc_testing/parameter_sweep/phase3_incast_placement_path_analysis.md`
- Compact anomaly follow-up: `noc_testing/parameter_sweep/compact_clustered_read_anomaly_diagnostic.md`
- Traffic: same 4-NMU/1-NSU AXI-MM incast workload as Phase 2.
- Buffers: fixed `buffers_per_data_vc=4`, `buffers_per_ctrl_vc=1`.
- Placements: baseline spread, reversed source ordering, destination moved to X0/X3, compact clustered, mixed spread, and center-hotspot.
- Instrumentation: full sweep keeps tracing off; selected rows use occupancy tracing only.

Primary plots:

- latency vs offered bandwidth
- achieved bandwidth vs offered bandwidth
- latency percentile bars per configuration
- latency vs hop count
- bandwidth/latency vs buffer depth
- ready/valid stall percentage for congested cases
- hotspot top1 share and location for traced cases
- queue depth over time for selected bottleneck resources

## Phase 4: Add Congestion Instrumentation

Goal: move from indirect congestion evidence to direct queue and stall measurements.

Useful counters:

- per-router input buffer occupancy by VC
- max/average occupancy by VC
- no-credit stall cycles
- switch allocator stall reasons
- per-link flit counts
- per-NPS heatmap values

Existing trace channels to reuse before adding new counters:

- `--nps-occ-trace`: writes `src/noc/testing/artifacts/traces/nps_occ_all.csv`.
- `--nps-queue-trace`: writes `src/noc/testing/artifacts/traces/nps_queue_trace.csv`.
- `--hotspot-mode occ|queue|both` in `noc_testing/noc_sweep.py`: enables and copies per-row hotspot artifacts.
- traffic monitor `record_mode=1`: writes per-transaction NMU CSVs.
- traffic monitor `record_mode=2`: writes `ready_valid.csv` for backpressure analysis.

Likely source areas:

- `src/noc/core/network/switch/`
- `src/noc/core/network/NocNetworkInterface.cc`
- `src/noc/monitors/NocTrafficMonitor.*`

Definition of done:

- A buffer-depth sweep can show not only latency changes, but where queues moved and which links/routers stalled.

## Phase 5: Package Results For The Report

Goal: turn runs into project artifacts.

Deliverables:

- final sweep plan CSVs
- summarized results CSVs
- comparison plots
- topology diagrams or heatmaps for key cases
- short notes explaining why each knob was included
- limitations section, especially for QoS and any missing hardware fidelity

## Current Non-Goals

- QoS behavior sweeps. Keep QoS columns out of the core Naviq sweep until they map to real model behavior.
- Exhaustive Cartesian products across all knobs.
- Full PCAP replay before synthetic AXIS and AXI-MM sweeps are stable.
