# Validation Sweep Plans

This directory contains sweep plans intended to be reusable validation inputs.
Scratch experiments are preserved under
`archive/noc/experiments/sweep_plans/scratch/`; do not add new plans there.

## Final AXI-MM Latency Input Contract

Before treating a latency comparison as final-baseline data, validate the plan:

```bash
python3 noc_testing/experiments/validation/validate_latency_inputs.py \
  noc_testing/sweep_plans/validation/4to1_512_same_base_fixed_inputs_smoke.csv
```

The validator enforces the current final-input rules:

- all AXI-MM TGs use the same base address unless a debug flag is passed;
- TG command gaps are fixed at zero cycles;
- TG seeds are fixed and nonzero;
- explicit `address_increment` overrides match the fixed transaction size;
- row-level/manual NSU read-response pacing overrides are absent or zero.

For intentional debug plans with staggered TG bases, keep the plan under
`archive/noc/experiments/sweep_plans/scratch/` and make that intent explicit:

```bash
python3 noc_testing/experiments/validation/validate_latency_inputs.py \
  --allow-staggered-bases \
  archive/noc/experiments/sweep_plans/scratch/<debug-plan>.csv
```

Do not use staggered-base plans as final latency baselines unless the experiment
is explicitly about address-window behavior.

## Current Locked Smoke Plan

`4to1_512_same_base_fixed_inputs_smoke.csv` is the current small input-stability
smoke set for the 4-to-1 512B spread case. It covers tx1, tx2, and tx10 using:

- `4nmu_to_1nsu_incast_aximm_same_base.conn.json`
- `4nmu_to_1nsu_incast_spread.place.json`
- fixed zero command gaps
- fixed nonzero seeds `100..103`
- no manual `nsu_read_response_half_rate` input override

The simulator should provide structural NSU read-response pacing; the plan
should not force it through a row-level diagnostic knob.

## NMU Read-Request Packetization

Chopped AXI-MM read requests now use packetized back-to-back NPP request flits
by default. This is part of the model, not a row-level validation override.
The old behavior, where each chopped read request chunk was emitted as an
independent one-flit packet, can still be restored for diagnostics with:

```bash
NOC_LEGACY_SPLIT_READ_REQ_CHUNKS=1 python3 noc_testing/noc_sweep.py ...
```

Do not set that variable for final latency baselines. It is retained only as a
repro/debug escape hatch when comparing against older runs.
