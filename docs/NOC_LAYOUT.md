# NoC Repository Layout

This repository is a gem5 fork with a maintained AMD NoC extension. The
directories below are the stable public entry points.

| Location | Status | Purpose |
|---|---|---|
| `src/noc/core/` | Canonical | NoC control, interfaces, and network behavior. |
| `src/noc/endpoints/` | Canonical | Traffic generators, memory endpoints, RTL adapters, and sinks. |
| `src/noc/lib/` | Canonical | AXI types, message helpers, serialization, and shared utilities. |
| `src/noc/setup/` | Canonical | NoC simulation configuration and topology loading. |
| `src/noc/testing/` | Canonical | Runnable smoke scenarios, unit-test helpers, and maintained test campaigns. |
| `tests/gem5/noc/` | Canonical | TestLib registration, completion verification, and trusted regression references. |
| `noc_testing/` | Canonical | Experiment manifests, topology generation, sweep plans, and result analysis. |
| `src/noc/setup/legacy/` | Archival/compatibility | Historical CPU and system setup scripts; see its README for unsupported HBM-NMU paths. |
| `archive/noc/` | Archival | Historical endpoints, topologies, results, plotting, and exploratory tools; see `archive/noc/INDEX.md`. |
| `src/noc/internals/hbm/` | Internal | Shared HBM arbiter declarations. Supported `HBM_NMU` endpoints use `mmNocMasterUnit`. |
| `src/noc/out/` and `noc_testing/artifacts/` | Generated | Runtime output only; ignored by Git except intentionally retained references. |

## Rules for new work

- Add reusable simulator behavior under `src/noc/core`, `endpoints`, or `lib`.
- Add deterministic test scenarios under `src/noc/testing` and register them in
  `tests/gem5/noc`.
- Add report-facing campaigns under `noc_testing/experiments` with a manifest.
- Keep generated logs, waves, plots, and full sweep output outside tracked
  source paths. Use a caller-selected output directory for long experiments.
- Do not add new work to `archive/`. Review an archive group, audit its
  references, and pass the release gates before retiring it.
