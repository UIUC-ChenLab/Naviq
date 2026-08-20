# NoC archive index

This index records material moved out of active NoC paths during the public
release cleanup. These moves preserve Git history and content; they do not
declare the archived material incorrect or disposable.

| Archive location | Former active location | Status and replacement |
| --- | --- | --- |
| `topologies/` | `src/noc/topology/topologies/old/` | Historical `.ncr`/`.nts` pairs. Use `src/noc/testing/fixtures/topologies/` for tests and `noc_testing/topology_jsons/` plus manifests for maintained campaigns. |
| `endpoints/legacy/` | `src/noc/endpoints/legacy/` | Unregistered `tile` prototype and standalone Garnet example. The supported HBM path uses `mmNocMasterUnit` and `tileNSU_HBM`. |
| `graph_helpers/` | `src/noc/test/graphs/` | Historical plotting scripts. Use maintained experiment analysis or caller-selected output tools. |
| `experiments/results/` | `noc_testing/results/` | Superseded presentation-oriented result tables. Trusted regression data lives under `tests/gem5/noc/trusted_results/`. |
| `experiments/plotting/` | `noc_testing/plotting/` | Historical plot/table generators coupled to archived results. |
| `experiments/latency_modeling/` | `noc_testing/latency_modeling/` | Calibration notes and exploratory models; not a maintained validation entry point. |
| `experiments/parameter_sweep/` | `noc_testing/parameter_sweep/` | Historical analysis notes and prior sweep interpretation. Maintained evaluation runners live under `noc_testing/experiments/evaluation/`. |
| `experiments/sweep_plans/scratch/` | `noc_testing/sweep_plans/scratch/` | Debug-only plans. Use current validation, sizing, endpoint, or placement plans for new runs. |
| `experiments/topology_mapping/` | `noc_testing/topology_generation/old_topo_mapping/` | Superseded mapping prototype. Use `noc_testing/tools/topology/`. |
| `experiments/lib_old/` | `noc_testing/lib/old/` | Historical helper inputs and plans; not imported by the maintained sweep driver. |
| `experiments/notebooks/` | `src/noc/setup/graph.ipynb` | Historical interactive graph notebook with embedded output. Use `src/noc/setup/include/noc_graphs.py` for maintained reporting helpers. |
| `experiments/evaluation_inventory/` | `noc_testing/experiments/final_project/` | Historical evaluation notes that refer to local, untracked artifacts. Not a reproducible campaign or source of public performance claims. |
| `experiments/validation/` | Historical multi-source validation records | Historical debugging records, wave-extraction procedures, and dated incast findings. Use the active validation README and manifests for supported workflows. |

Before retiring any archive group, review its contents, search for references,
record the decision in this index, and run the applicable release gates.

## Retention decision

As of 2026-08-08, all archive groups listed above are intentionally retained.
They may contain useful reference configurations, experimental context, or
historical implementation details. They are excluded from supported public
entry points, but are not designated for deletion. Reconsider removal only
after a future, group-by-group review.
