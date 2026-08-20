# NoC experiment guide

The manifest launcher is the public index for maintained NoC campaigns. It
does not replace campaign drivers; it makes their inputs, dependencies,
retained references, and validation rules visible in one place.

```bash
python3 noc_testing/experiments/run_experiment.py --list
python3 noc_testing/experiments/run_experiment.py --id evaluation.experiment1 --dry-run
python3 noc_testing/experiments/run_experiment.py --id validation.vivado_reference --dry-run
```

To execute a campaign, select an output directory outside the source tree:

```bash
python3 noc_testing/experiments/run_experiment.py \
  --id smartnic.packet_modules --run --output /tmp/noc-smartnic-smoke
```

The launcher saves the resolved command and manifest in that directory. Some
compatibility drivers still write their historical detailed results below
ignored artifact roots. Those paths are recorded in their drivers and will be
converted one at a time; no generated result belongs in a source or topology
directory.

Install the repository's Python experiment dependencies before running
route-generation campaigns:

```bash
python3 -m pip install -r requirements.txt
```

## Campaign classes

| ID prefix | Release role | Default gate |
| --- | --- | --- |
| `evaluation.*` | Reproduce evaluation campaigns 1–4 and uncapped sensitivity | manifest dry-run; representative non-external run in clean-clone rehearsal |
| `validation.*` | Check retained Vivado inputs/reference-data invariants | portable CI acceptance |
| `smartnic.*` | AXIS and SmartNIC behavior | portable TestLib smoke suite |
| `ddr.*` | DDR study | manual/nightly X86 gate |
| `hbm.*` | HBM study and optional external RTL | portable HBM TestLib smoke; manual full-campaign gate |
| `debug.*` | Fixed-seed protocol stress and diagnostic scenarios | focused TestLib smoke plus an explicit manual run |

`hbm.aes_ctr_pipeline` is intentionally listed as **planned**, rather than
pretending it is reproducible: its checked-in campaign manifest defines the
acceptance criteria, but it has no runnable driver yet.

`evaluation.experiment2` is maintained. Its high-overlap route policies are
recorded per case, so the regenerated low/high pairs satisfy the declared
hop-match and overlap-separation checks without changing endpoints or placement.
`--allow-validation-failures` remains diagnostic-only and must not be used for
a release claim.

## Vivado and external RTL

The launcher never starts a Vivado or external-RTL campaign unless
`--allow-external` is supplied. It reports missing tools, builds, and
dependencies before execution. Full Vivado/RTL reproduction therefore remains
a licensed-environment release gate; the portable CI only validates the pinned
input/reference acceptance case.
