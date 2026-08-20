# Vivado vs Naviq Incast Scaling Latency Checks

Status: planned validation follow-up.

This campaign narrows the latency comparison by reducing the number of AXI-MM
sources while keeping the same base-component setup style:

```text
1 AXI traffic generator / NMU -> 1 AXI BRAM / NSU
2 AXI traffic generators / NMUs -> 1 AXI BRAM / NSU
```

The goal is to compare the latency mismatch seen in the 4-to-1 incast sweep
against simpler cases with less contention.

## Sweep Plans

```text
noc_testing/sweep_plans/validation/vivado_naviq_1to1_aximm_latency.csv
noc_testing/sweep_plans/validation/vivado_naviq_2to1_incast_latency.csv
```

Both plans use:

- traffic mode: `rw_interleaved`
- transaction counts per source: 1, 2, 5, 10 writes and matching reads
- offered load: 800 MBps
- transaction shape: 8 beats x 64 bytes = 512 bytes
- RTL sim mode, 512-bit TG and BRAM interfaces, 1 GHz NoC AXI clock
- Vivado-generated NoC routing

## Commands

Run 1-to-1:

```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_1to1_aximm_latency.csv \
  --mode vivado_then_gem5 \
  --topo-gen vivado \
  --run-tag validation_1to1_latency
```

Run 2-to-1:

```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_2to1_incast_latency.csv \
  --mode vivado_then_gem5 \
  --topo-gen vivado \
  --run-tag validation_2to1_latency
```

If Vivado completes but gem5 needs to be rerun, reuse the Vivado artifacts:

```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_2to1_incast_latency.csv \
  --mode gem5_only \
  --topo-gen vivado \
  --reuse-tag validation_2to1_latency \
  --run-tag validation_2to1_latency_gem5fix
```

For live Vivado progress:

```sh
tail -f vivado.log
```
