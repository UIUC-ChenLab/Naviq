# Naviq vs Vivado 4-to-1 AXI-MM Incast Validation

Status: planned validation campaign.

This campaign compares Naviq against Vivado RTL on a base-component AXI-MM
incast topology:

```text
4 AXI traffic generators / NMUs -> 1 AXI BRAM / NSU
```

Vivado owns routing for this validation. The intended flow is to let Vivado build
the block design, generate the NoC solution, export `.ncr/.nts`, and then run
Naviq against those Vivado-generated topology artifacts. The comparison is
trend-based for v1, not cycle-exact.

## Sweep Plan

```text
noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast.csv
```

Rows:

- active: `interleaved_tx1` through `interleaved_tx10`
- disabled for now: write-only rows plus `interleaved_tx50` and
  `interleaved_tx200` are commented out in the CSV

Traffic and topology defaults:

- topology: `topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm.conn.json`
- placement: `topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_spread.place.json`
- transaction shape: 8 beats x 64 bytes = 512 bytes
- traffic mode: `rw_interleaved`
- transaction counts per source: 1 through 10 writes and matching reads
- offered load: 800 MBps
- RTL sim mode, 512-bit TG and BRAM interfaces, 1 GHz NoC AXI clock
- Vivado XSim runtime: 1 ms for bring-up

## Bring-Up Flow

To check Tcl block-design generation and Vivado NoC routing without simulation,
run only topology export for the first row:

```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast.csv \
  --mode topology_only \
  --topo-gen vivado \
  --row 1
```

Then run only the first Vivado simulation row:

```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast.csv \
  --mode vivado_only \
  --topo-gen vivado \
  --row 1
```

Manually inspect the Vivado block design/TCL setup:

- 4 AXI traffic generators exist.
- 1 AXI BRAM endpoint exists.
- all four TGs target the same BRAM/NSU.
- physical placements match the placement JSON.
- Vivado exported `.ncr` and `.nts` artifacts under `noc_testing/artifacts/noc_desc/`.

After the setup is verified, run the full comparison:

```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast.csv \
  --mode vivado_then_gem5 \
  --topo-gen vivado
```

The sweep plan also sets `topo_gen=vivado` on every row. That prevents
`noc_sweep.py` from setting `CUSTOM_NCR_FILE` and invoking `read_noc_solution`;
Vivado should create and route the NoC solution itself.

For live diagnostics while `noc_sweep.py` is waiting on Vivado, tail the Vivado
log from another shell:

```sh
tail -f vivado.log
```

## Analysis

Generate the Markdown comparison report:

```sh
python3 noc_testing/experiments/validation/vivado_naviq_4to1_incast/analyze_results.py \
  --vivado noc_testing/artifacts/generated/results/vivado_results_vivado_naviq_4to1_incast_<tag>.csv \
  --gem5 noc_testing/artifacts/generated/results/gem5_vivado_naviq_4to1_incast_<tag>.csv \
  --output noc_testing/artifacts/generated/results/vivado_naviq_4to1_incast_analysis_<tag>.md
```

The report joins Vivado and Naviq rows by `name` and `src_id`, then checks:

- Vivado `test_status` is `TEST PASSED`.
- Naviq `gem5_return_code` is zero.
- each expected source has paired Vivado and Naviq rows.
- write/read transaction counts are nonzero for the configured traffic mode.
- bandwidth and average-latency trends are directionally similar from low to
  medium to uncapped.

Min/max latency is reported as diagnostic evidence only.

## Notes

- Read-only is intentionally excluded because it is not supported well enough
  for this first comparison.
- Do not force a manual routing plan for this validation. If TCL changes are
  needed, keep them limited to making the base-component design faithful.
- If the uncapped row does not expose a useful trend, tune offered-load points
  before expanding beyond the 4-to-1 topology.
