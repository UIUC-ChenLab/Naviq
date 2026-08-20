# NoC Artifact Policy

Tracked NoC artifacts must be small, deterministic inputs or references needed
to run or validate a public scenario. Examples are topology fixtures, manifest
inputs, and the trusted CSV snapshots under `tests/gem5/noc/trusted_results`.

Generated logs, waves, plots, timing captures, simulator output directories,
and exploratory sweep results are not source code. They must be written to an
ignored runtime directory or an explicit experiment `--output` directory.

## Retained references

- TestLib regression references live under `tests/gem5/noc/trusted_results`.
- `tests/gem5/noc/trusted_results/SHA256SUMS` records their content hashes;
  validate them with `(cd tests/gem5/noc/trusted_results && sha256sum -c SHA256SUMS)`.
- Each public experiment manifest names its retained baseline inputs and
  validation rule.
- Material retained for in-repository review is grouped under `archive/noc/`
  and indexed in `archive/noc/INDEX.md`; it is not a source of release claims.

## Before committing an artifact

1. Confirm it is required to reproduce or validate a documented test/campaign.
2. Prefer a compact, normalized CSV or JSON input over raw simulator output.
3. Record the producing command and validation role in the relevant manifest
   or README.
4. Do not commit raw Vivado projects, waves, `m5out` directories, runtime logs,
   generated PNGs, or timestamped diagnostic captures.
