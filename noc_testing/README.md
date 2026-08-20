# NoC experiment and evaluation harness

`noc_testing` contains the maintained campaign launcher, sweep driver,
topology inputs, and reusable experiment tooling for the Naviq NoC extension.
It is separate from `src/noc/testing`, which holds small simulator scenarios
and unit-test helpers.

## Start here

List maintained campaigns and validate their inputs without launching a long
simulation:

```sh
python3 noc_testing/experiments/run_experiment.py --list
python3 noc_testing/experiments/run_experiment.py \
  --id evaluation.experiment1 --dry-run
```

Use `--run --output <directory>` only with a caller-selected output directory.
Vivado and external-RTL campaigns additionally require `--allow-external` and
their documented licensed environment.

For generic row-based sweeps, run the driver from the repository root:

```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/4to1_512_same_base_fixed_inputs_smoke.csv \
  --mode gem5_only
```

## Maintained layout

| Path | Purpose |
| --- | --- |
| `experiments/` | Manifest-backed evaluation, validation, and manual campaigns. |
| `tools/` | Reusable topology-generation and visualization tools. |
| `sweep_plans/` | Current validation, sizing, endpoint, and placement plans. |
| `topology_jsons/` | Maintained connection and placement inputs. |
| `lib/` | Shared Tcl and Python support used by the sweep driver. |
| `artifacts/` | Ignored runtime output only. |

Historical results, plotting, old mappings, scratch plans, and exploratory
latency analysis are retained under `archive/noc/experiments/`. They are for
review and provenance, not public campaign entry points or regression data.

See [the experiment guide](../docs/NOC_EXPERIMENTS.md),
[the artifact policy](../docs/NOC_ARTIFACT_POLICY.md), and
[the archive index](../archive/noc/INDEX.md) for details.
