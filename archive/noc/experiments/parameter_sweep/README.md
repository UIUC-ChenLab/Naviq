# Naviq Parameter Sweep Notes

This folder is the working notebook for the Naviq evaluation plan. The project
goal is to characterize the gem5/Naviq NoC model under controlled changes to
topology, traffic, routing, buffering, and endpoint placement, then collect
latency, throughput, congestion, and queue/backpressure evidence for each run.

QoS is intentionally out of scope for this first pass. Some older sweep CSVs include QoS-shaped columns because they were useful for Vivado scripts, but they should not drive the current Naviq experiments until there is a real model behavior attached to them.

## Project Framing

Naviq is a cycle-accurate AXI4 NoC simulator based on gem5/Garnet. For this project, we use it as a faster design-space exploration tool for FPGA/SoC-style interconnects, especially AMD Versal/V80-like NoCs where Vivado-based simulation is too slow for broad parameter sweeps.

The research question is:

> How do configurable AXI4 NoC topology, traffic, routing, buffering, and endpoint-placement choices affect latency, throughput, congestion, and bottleneck formation?

This project is not just trying to improve latency or bandwidth. It is a behavioral study of how different AXI4 NoC parameters affect the simulated system. Latency and bandwidth are useful summary metrics, but the sweep flow should also expose deeper system effects such as congestion, queueing, backpressure, saturation points, traffic interference, fairness between flows, and localized hotspots.

The intended output is not just a set of simulation logs. The sweep flow should produce tables, summaries, traces, and plots that help answer:

- Which NoC settings improve latency?
- Which settings improve achieved bandwidth?
- Which configurations create congestion, unfairness, or early saturation?
- How does performance change with hop count, endpoint placement, offered load, and traffic shape?
- Are bottlenecks localized to specific paths/endpoints, or caused by global saturation?

The one-sentence project goal is:

> Use Naviq to rapidly sweep AXI4 NoC configurations and traffic patterns, then generate latency, bandwidth, and bottleneck-analysis outputs that explain how topology, routing, buffering, and workload shape affect NoC performance.

## Current Status

Work completed or partially completed so far:

- Latency model refinement: Naviq results have been compared against Vivado-style baselines. Early results were close for short paths but less accurate for long paths; internal NPS/NoC timing updates improved long-path latency accuracy.
- Topology-aware testing: experiments can vary hop count, endpoint distance, and topology/path placement. Preliminary AXI4-MM read/write tests show latency increasing and bandwidth decreasing as hop count grows.
- Traffic intensity testing: fixed-rate per-run sweeps are possible by changing traffic generator settings between runs. Dynamic in-run traffic-rate changes are not currently part of the flow.
- CDC and analysis tooling: CDC support and hotspot graphing have been explored. Because hotspot graphing may not be complete, the sweep flow should still produce useful scalar and table outputs.
- SmartNIC integration: some SmartNIC components have been connected and simulated in Naviq. Full SmartNIC simulation is not required for the first sweep pass, but it remains a possible final case study.
- Phase 0 baseline reproduction: the tiny 1-transaction AXI-MM plumbing run, trace rerun, and 1000-transaction 2-hop metric sanity run have been executed with fixed run tags under `noc_testing/artifacts/`.
- Phase 1 initial knob exposure: CSV rows can now carry fabric buffer-depth and NPS credit behavior knobs separately from instrumentation knobs such as `record_mode`, `hotspot_mode`, and `hotspot_occ_gap_cycles`.

## Expected Outputs

Every sweep run should emit enough scalar data to compare runs even when graphing or hotspot instrumentation is incomplete:

- test name, topology, endpoint pair, and hop count
- offered load, transaction size, burst length, and read/write mode
- achieved read and write bandwidth
- average, minimum, and maximum read/write latency when available
- simulation runtime and pass/fail status

The sweep should also preserve deeper diagnostic outputs when enabled. These outputs explain why a run behaved the way it did, not just what the headline latency or bandwidth was:

- per-transaction latency and bandwidth CSVs
- ready/valid traces for endpoint backpressure and stalls
- queue occupancy and credit-pressure traces
- hotspot summaries identifying the most active NPS/router/link resources
- fairness metrics across active flows or NMUs
- path/hop/overlap metadata that connects measured behavior back to topology

Useful derived summaries include:

- best and worst configurations by read/write latency
- best configurations by achieved bandwidth
- configurations that saturate early
- percent change versus a baseline configuration
- cases with high latency but low achieved bandwidth
- flows or configurations with fairness loss
- localized hotspots and the paths or endpoints that contribute to them

If hotspot instrumentation is available, the sweep flow should also preserve heatmaps, top congested routers/links, source-destination pairs with the highest latency, and queue/backpressure traces. If it is not available, use scalar congestion proxies such as saturation point, throughput ceiling, latency growth with offered load, and paths that fail to scale.

## Diagnostic Trace Sources

Naviq already has tracing hooks that can support parameter-effect analysis:

- `record_mode=1` in `NocTrafficMonitor` writes per-NMU transaction CSVs under `src/noc/testing/artifacts/traces/`, such as `nmu_<id>_AXIMM_read.csv`, `nmu_<id>_AXIMM_write.csv`, `nmu_<id>_AXIS_sender.csv`, and `nmu_<id>_AXIS_receiver.csv`. These contain timestamp, link id, byte count, transaction-end marker, and AXI-MM latency.
- `record_mode=2` also writes `ready_valid.csv`, with timestamp, node id, protocol, role, channel, ready, and valid. This is the main existing trace for endpoint-level backpressure and stall analysis.
- `link_id_mapping.csv` maps monitor link IDs back to NMU/NSU pairs.
- `--nps-occ-trace` writes `nps_occ_all.csv`, a sampled NPS/router occupancy trace with NPS name/type, port, occupancy sum, and max buffer size.
- `--nps-queue-trace` writes `nps_queue_trace.csv`, a sparse per-cycle queue trace for non-empty NPS input VC and credit queues with tick, cycle, router id, NPS name/type, queue kind, input port, VC, and depth.
- `noc_testing/noc_sweep.py --hotspot-mode {occ,queue,both}` enables the occupancy and/or queue traces for gem5 rows and copies the per-row artifacts into `noc_testing/artifacts/generated/hotspot/<run>/<row>/`.
- `noc_testing/topology_analysis.py` already consumes hotspot trace paths and derives fields such as top hotspot share, primary hotspot location, concentration ratio, and localized-hotspot risk.

These traces should not be turned on for every large sweep by default because they can be expensive and verbose. A practical workflow is to run broad sweeps with scalar metrics first, then rerun selected interesting cases with `--hotspot-mode both` and `record_mode=2` when backpressure detail is needed.

Treat `record_mode`, `hotspot_mode`, and `hotspot_occ_gap_cycles` as instrumentation controls, not NoC behavior parameters. They should be recorded with results for reproducibility, but not analyzed as architectural knobs alongside buffer depth or credit limits.

## Analysis Workflow

The ideal workflow is:

1. Sweep one parameter or traffic pattern at a time.
2. Collect summary metrics for every run.
3. Identify interesting cases: high latency, bandwidth collapse, saturation, fairness loss, or hotspot concentration.
4. Rerun or inspect those cases with tracing and hotspot tools enabled.
5. Produce tables, rankings, and diagnostic plots that explain how the parameter affected system behavior.

## Experimental Narrative

The final class-project story should be:

1. Validate and refine Naviq latency behavior against Vivado-style baseline runs.
2. Sweep topology and traffic parameters such as hop count, endpoint distance, offered load, burst shape, and traffic pattern.
3. Generate latency, bandwidth, ranking, and bottleneck-analysis outputs.
4. Use the results to explain how NoC configuration choices affect performance and to identify promising settings for high-throughput mixed-traffic FPGA systems.

## Files

- `sweep_knobs.md`: detailed inventory of candidate sweep parameters, including status and first-pass value ranges.
- `project_workflow.md`: recommended project phases, outputs, and tooling changes to make the sweeps reproducible.

## Current Code Anchors

- gem5 NoC params: `src/noc/core/network/NocGarnetNetwork.py`
- command-line options for `src/noc/setup/noc_config.py`: `src/noc/setup/noc_config_funcs.py`
- AXI-MM random traffic generator params: `src/noc/endpoints/generator/AXIMMTrafficGenerator.py`
- AXIS random, pcap, and packet traffic generator params: `src/noc/endpoints/generator/AXISTrafficGenerator.py`
- sweep runner: `noc_testing/noc_sweep.py`
- existing CSV plans: `noc_testing/sweep_plans/`
- generated topology support: `noc_testing/tools/topology/` and `noc_testing/topology_jsons/`

## Working Vocabulary

Use these status labels when adding knobs to sweep plans:

- `exposed`: accepted by the current gem5 config CLI or by `noc_testing/noc_sweep.py`.
- `model-param`: implemented in the gem5 SimObject model, but not yet exposed through the project sweep CSV/CLI.
- `topology-input`: comes from topology JSON, `.nts`, or `.ncr` rather than a simple CLI scalar.
- `hardcoded`: set in `src/noc/setup/noc_config.py` or a related setup script today.
- `needs-instrumentation`: useful to collect, but the simulator does not currently emit it cleanly.
- `defer`: valid but intentionally not part of the first pass.

## First-Pass Sweep Families

The first useful sweep should stay small enough to debug and plot:

1. Traffic offered load: bandwidth, burst size, burst length, transaction count, read/write mix.
2. Endpoint placement: near/far paths, hop count, DDR/HBM/BRAM/NSU endpoint type, all-to-all fanout.
3. NMU/NSU adapter behavior: RROB depth, protocol queue sizes, write-buffer capacity, outstanding limits, NPP chunking, and response gap rules.
4. Microarchitecture: `ni_flit_size`, `vcs_per_vnet`, `buffers_per_data_vc`, `buffers_per_ctrl_vc`, NPS credit depths, and NPS latencies.
5. Routing/topology: routing algorithm, custom routing table, path diversity, and NPS/router mix.
6. Output collection: run manifest, per-run stats, per-node latency/bandwidth, ready/valid backpressure, and later queue/VC occupancy.

Buffer sizes are real knobs in the model:

- `buffers_per_data_vc`, default `4`
- `buffers_per_ctrl_vc`, default `1`

They are now exposed through the sweep CSV flow and should be the first real behavior sweep because they directly affect queueing and congestion behavior.
