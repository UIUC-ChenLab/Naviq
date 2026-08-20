# Congestion Analysis Demo

This demo shows Naviq as a congestion-analysis workflow. It starts with a basic congestion test, then walks through the Chapter 3 experiment artifacts one experiment at a time. The goal is to show that the tooling can identify hotspots, route overlap, convergence, and endpoint imbalance from measured data.

By default, the demo uses existing artifacts. This keeps the demo stable and avoids depending on the current route generator producing exactly the same candidates every time. Live reruns are available when you want gem5 activity in the terminal.

## Run

From the repository root:

```bash
python3 noc_testing/demo/chapter3_demo.py
```

Regenerate Experiment 1, Experiment 2, and Experiment 3 locally:

```bash
python3 noc_testing/demo/chapter3_demo.py --run-live-experiments
```

Also rerun optional Experiment 4:

```bash
python3 noc_testing/demo/chapter3_demo.py --run-live-experiments --include-exp4
```

Force artifact-only output with no live gem5 runs:

```bash
python3 noc_testing/demo/chapter3_demo.py --offline
```

Fail instead of falling back if a live experiment fails:

```bash
python3 noc_testing/demo/chapter3_demo.py --run-live-experiments --require-live-experiments
```

## Configuration

Live rerun settings live in:

```text
noc_testing/demo/chapter3_demo_config.json
```

Common knobs are near the top:

- `bandwidth_mbps`
- `num_transactions`
- `beat_bytes`
- `beat_count`
- `data_width_bits`
- `bram_data_width_bits`
- `noc_clk_mhz`
- `abs_max_tick`

Each experiment has its own `run_tag`, script path, existing summary CSV, and extra args. Live outputs are written under:

```text
noc_testing/demo/artifacts_ch3/live_experiments/
```

## Demo Flow

1. Basic congestion test: compares uncapped 4-to-1 compact and 4-to-1 far cases, then prints hotspot, P99, bandwidth, fairness, and top-hotspot fields.
2. Experiment 1: analyzes placement/convergence metrics within Experiment 1 only.
3. Experiment 2: analyzes route-overlap pair comparisons and the incast destination-convergence case.
4. Experiment 3: analyzes routing-strategy metrics within Experiment 3.
5. Optional Experiment 4: analyzes memory-target attachment if the artifact exists or live rerun is requested.
6. Recommendation layer: runs once per experiment artifact and writes separate deterministic evidence and Markdown files for each experiment.

## Inputs

Artifact mode expects existing CSVs:

- Experiment 1: `noc_testing/experiments/evaluation/artifacts/exp1_evaluation_1/analysis/repeat_01.csv`
- Experiment 2: `noc_testing/experiments/evaluation/artifacts/exp2_evaluation/analysis/repeat_01_final.csv`
- Experiment 3: `noc_testing/experiments/evaluation/artifacts/exp3_tornado_uncapped_tx500/analysis/repeat_01_final.csv`
- optional Experiment 4: `noc_testing/experiments/evaluation/artifacts/exp4_main_1/analysis/repeat_01_final.csv`
- basic uncapped test: `noc_testing/experiments/evaluation/artifacts/chapter3_uncapped_sensitivity_20260505/results/experiment1_uncapped_table.csv`

Live mode also expects:

- `build/NULL/gem5.opt`
- `noc_testing/experiments/evaluation/run_experiment1.py`
- `noc_testing/experiments/evaluation/run_experiment2.py`
- `noc_testing/experiments/evaluation/run_experiment3.py`
- optional `noc_testing/experiments/evaluation/run_experiment4.py`
- route/topology JSONs referenced by those scripts

## Outputs

The demo writes to:

```text
noc_testing/demo/artifacts_ch3/
```

Generated files:

- `chapter3_demo_report.md`
- `chapter3_recommendations.md`, an index of per-experiment recommendation reports
- `chapter3_recommendations_evidence.json`, an index of per-experiment evidence bundles
- `chapter3_demo_tables.md`
- `recommendations/*_recommendations.md`
- `recommendations/*_recommendations_evidence.json`
- `live_experiments/<run_tag>/...` for live rerun plans, results, analysis, and manifests
- `live_experiments/logs/*.log` for live rerun terminal output

## Speaking Script

1. Start with the goal: this is a congestion-analysis demo, not a publication-proof demo.
2. Show the basic congestion test: with bandwidth uncapped, compare 4-to-1 compact against 4-to-1 far and point out how hotspot concentration and P99 separate.
3. Show Experiment 1: placement and convergence change P99 and hotspot fields even when bandwidth is similar.
4. Show Experiment 2: route-overlap pairs identify whether congestion tracks shared route resources or destination convergence.
5. Show Experiment 3: routing-strategy rows are analyzed using their own metrics, not assumed to prove a cross-experiment claim.
6. Open `chapter3_recommendations.md`: it shows that the recommendation stage runs per experiment, not as one combined diagnosis.
7. Open a file under `recommendations/*_recommendations_evidence.json`: the deterministic diagnosis evidence is auditable for that specific experiment.
