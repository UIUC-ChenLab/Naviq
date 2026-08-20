# AXI-MM Handshake-Stress Experiment

This experiment exercises legal AXI-MM backpressure at the master boundary.
`AxiHandshakeStressGenerator` wraps the normal random AXI-MM traffic source
and probabilistically holds `AWVALID`, `WVALID`, `ARVALID`, `BREADY`, and
`RREADY` without changing payloads, IDs, addresses, or responses.

The checked-in scenario uses one stressed writer and one baseline writer on the
standard 2-to-2 AXI-MM topology. It fixes both the traffic and handshake seeds
and must complete eight writes, so it is also registered as a quick TestLib
smoke. This verifies that legal handshake stalls do not corrupt or deadlock
basic AXI-MM traffic; it does not prove protocol correctness for arbitrary
random schedules.

Run it through the experiment launcher:

```sh
python3 noc_testing/experiments/run_experiment.py \
  --id debug.axi_handshake_stress --run --output /tmp/noc-axi-stress
```

For a TestLib run:

```sh
cd tests
./main.py run --skip-build --exclude-tags '.*' \
  --include-tags noc-axi-handshake-stress --isa=NULL --variant=opt gem5/noc
```

Set every percentage to `100` for the baseline. Set `fault_seed` explicitly
whenever retaining or comparing a stress result. A percentage of `0` blocks
that channel indefinitely and is intentionally unsuitable for completion
tests.

The old branch's HBM warnings, traffic-monitor changes, plotting edits, and
experimental AXIS RTL source are not imported here: current `main` already has
newer monitoring/AXIS infrastructure, while those branch changes have no
standalone test or supported external-RTL registration.
