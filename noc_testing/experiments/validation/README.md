# Vivado Reference Validation

This directory contains the maintained input checks used before comparing
Naviq/gem5 AXI-MM latency results with retained Vivado reference data. It is
an entry point for reproducible validation, not a running record of debugging
work.

## Supported baseline

The released input baseline is the 4-to-1, 512-byte AXI-MM incast smoke plan:

`noc_testing/sweep_plans/validation/4to1_512_same_base_fixed_inputs_smoke.csv`

Before using a latency result as baseline evidence, validate that plan from the
repository root:

```sh
python3 noc_testing/experiments/validation/validate_latency_inputs.py \
  noc_testing/sweep_plans/validation/4to1_512_same_base_fixed_inputs_smoke.csv
```

The check verifies deterministic traffic-generator gaps and seeds, same-base
address windows, transaction-sized address increments, and the absence of
manual NSU read-response pacing overrides. The exact rules and the retained
plan inventory are documented in
[`../../sweep_plans/validation/README.md`](../../sweep_plans/validation/README.md).

## Manifest interface

The validation campaign is registered as `validation.vivado_reference`. Use
the experiment launcher to inspect its inputs without starting a simulator:

```sh
python3 noc_testing/experiments/run_experiment.py \
  --id validation.vivado_reference --dry-run
```

List all maintained campaigns with:

```sh
python3 noc_testing/experiments/run_experiment.py --list
```

The pinned Vivado-data acceptance check is portable. Reproducing the full
Vivado design and external RTL remains a separate licensed-environment gate;
the launcher reports required prerequisites before it starts such a campaign.

## Inputs and reference data

- Maintained sweep plans: `noc_testing/sweep_plans/validation/`
- TestLib regression references: `tests/gem5/noc/trusted_results/`
- Generated local outputs: `noc_testing/artifacts/generated/` (ignored by Git)

Use caller-selected output directories for new experiment runs. Do not treat
generated logs, waveforms, or exploratory CSVs as release reference data unless
they are deliberately curated under the repository's artifact policy.

## Scope and limitations

This validation interface checks reproducible inputs and retained references.
It does not claim that every multi-source traffic pattern is an exact Vivado
match. In particular, congested multi-source AXI-MM latency and the full
licensed Vivado/RTL flow require the documented release validation gates before
they are used as publication evidence.

## Historical engineering records

Detailed latency investigations, server-run procedures, and earlier findings
are retained for technical context under
[`archive/noc/experiments/validation/`](../../../archive/noc/experiments/validation/).
They are historical debug records rather than supported user documentation.
