# NoC Testing Experiments

This directory holds experiment-specific definitions and curated experiment artifacts.

## Campaign launcher

Use the manifest launcher to discover maintained campaigns and verify the
repository inputs before spending simulation time:

```
python3 noc_testing/experiments/run_experiment.py --list
python3 noc_testing/experiments/run_experiment.py --id evaluation.experiment1 --dry-run
python3 noc_testing/experiments/run_experiment.py --id smartnic.packet_modules --run --output /tmp/noc-smoke
```

`--run` always requires a caller-selected `--output` directory. The launcher
records the exact command and manifest there. A campaign that needs Vivado or
external RTL also requires `--allow-external`; it will otherwise stop before
starting the licensed or dependency-specific work. Existing drivers remain the
implementation behind the manifests, so their historical output formats and
manual prerequisites remain documented by their campaign manifest.

## Layout

- `evaluation/`: evaluation-oriented topology experiments, including runners, helper tests,
  pinned route assets, and their generated artifacts.
- `validation/`: simulator validation campaigns that compare Vivado-generated
  base-component designs against Naviq/gem5 results. Current campaigns include
  4-to-1 incast validation and smaller 1-to-1 / 2-to-1 latency scaling checks.
- `debug/`: fixed-seed protocol-stress scenarios used to reproduce and narrow
  NoC interface issues without treating them as performance evaluations.

Generic sweep infrastructure stays outside this directory:

- `noc_testing/noc_sweep.py`
- `noc_testing/sweep_plans/`
- `noc_testing/tools/`
- shared artifact pools under `noc_testing/artifacts/`

Historical parameter-sweep interpretation, plotting, and latency-modeling
material is preserved under `archive/noc/experiments/`, not mixed with
maintained campaigns.

The historical evaluation-results inventory is preserved under
`archive/noc/experiments/evaluation_inventory/`. It is not a maintained
campaign, reproducible result set, or source of public performance claims.

NoC components, endpoint models, C programs, and simulator setup code stay under
`src/noc/`.
