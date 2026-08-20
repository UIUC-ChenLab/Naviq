# NoC TestLib Tests

This directory exposes the existing NoC smoke configurations through gem5's
TestLib infrastructure. The runnable scenarios remain under `src/noc/testing`;
this layer only provides TestLib discovery, tagging, binary selection, output
directories, and NoC-specific completion verification.

`run_noc_smoke.py` is a small TestLib runner that changes to the repository
root before executing a smoke script. This preserves the existing NoC scripts'
repo-root-relative topology paths.

## Listing Tests

From the `tests` directory:

```sh
./main.py list -q --suites gem5/noc
```

## Running Tests

Run the short NULL-ISA NoC smoke tests:

```sh
./main.py run --length=quick --isa=NULL --variant=opt gem5/noc
```

This is the required fast release gate. It runs bounded AXI-MM and AXIS
scenarios as well as the static topology-fixture and Vivado-accuracy checks.
Use `--skip-build` only after building the matching binary.

Run the longer NoC regression set:

```sh
./main.py run --length=long --variant=opt gem5/noc
```

Run only the CPU-backed NoC smoke tests:

```sh
./main.py run --length=long --isa=X86 --variant=opt --include-tags noc-cpu gem5/noc
```

CPU suites are skipped by a fixture when their required x86 test binaries are
missing.

Run the storage-safe sweep regression checks:

```sh
./main.py run --exclude-tags '.*' --include-tags noc-sweep gem5/noc
```

These checks do not run `noc_testing/noc_sweep.py` by default. They validate
the sweep plan against checked-in trusted result snapshots and compare the
trusted CSV to itself, so TestLib does not generate sweep artifacts.

To compare a newly generated result CSV against the trusted snapshot, set one
or both environment variables before running the same command:

```sh
NOC_SWEEP_OBSERVED_SIZING_CSV=/path/to/gem5_noc_plan_all_sizes_v2.csv \
NOC_SWEEP_OBSERVED_PLACEMENT_CSV=/path/to/gem5_placement_route_ladder.csv \
./main.py run --exclude-tags '.*' --include-tags noc-sweep gem5/noc
```

Latency and bandwidth metric differences are reported as `WARNING:` log
messages, not test failures. Missing trusted coverage or malformed CSV input is
treated as an infrastructure failure.

## Vivado Accuracy Regression

The `noc-vivado` check protects the published sizing-latency comparison. By
default it validates the checked-in gem5 and Vivado CSV baselines, so it does
not require Vivado or run a full sweep. To validate a newly generated gem5
result against the pinned Vivado reference, run:

```sh
NOC_VIVADO_ACCURACY_OBSERVED_CSV=/path/to/gem5_noc_plan_all_sizes_v2.csv \
./main.py run --length=quick --exclude-tags '.*' --include-tags noc-vivado gem5/noc
```

The current envelope requires at least 1,200 matching passing rows. For
average latency, AXI-MM writes must remain within p95/max absolute error of
6/12 cycles and reads within 6.5/16 cycles. Maximum latency is also gated for
both reads and writes at 4/6 cycles. Minimum latency remains diagnostic-only
because the pinned corpus has much larger outliers there. This is a release
acceptance check: coverage or envelope failures fail the suite rather than
merely logging a warning.

Run the NMU/NSU-focused deep matrix cases:

```sh
./main.py run --exclude-tags '.*' --include-tags 'noc-nmu|noc-nsu' \
  --isa=NULL --variant=opt gem5/noc
```

Run only the longer stress subset added by the deep matrix:

```sh
./main.py run --skip-build --exclude-tags '.*' --include-tags noc-stress \
  --isa=NULL --variant=opt gem5/noc
```

## Resolved-bug history

There are currently no active known-bug suites. The resolved reproducers and
their promoted regressions are recorded in `src/noc/testing/BUG_LOG.md`.
If a future issue needs an isolated reproducer, it must remain outside passing
quick/long coverage until its behavior and expected-failure handling are
explicitly defined.

## Tags

All suites include `noc`. Additional tags describe the scenario family:

- `noc-generic`: generic AXI-MM/AXIS smoke tests
- `noc-ddr`: DDR-backed smoke tests
- `noc-hbm`: HBM-backed smoke tests
- `noc-cpu`: CPU-backed smoke tests
- `noc-sweep`: storage-safe sweep regression checks
- `noc-fixture`: current topology-input and generated-description checks
- `noc-accuracy`: checked-in numerical accuracy regressions
- `noc-vivado`: gem5-to-Vivado sizing-latency acceptance check
- `noc-sizing`: all-sizes sweep regression check
- `noc-placement`: placement route-ladder regression check
- `noc-nmu`: tests intended to exercise NoC master unit behavior
- `noc-nsu`: tests intended to exercise NoC slave unit behavior
- `noc-aximm`: AXI-MM NoC traffic tests
- `noc-axis`: AXI Stream NoC traffic tests
- `noc-stress`: higher-pressure long tests
- `noc-nightly`: larger/manual stress candidates
- `external-rtl`: tests that require optional external RTL SimObjects

## Completion Verification

`NoCCompletionVerifier` checks `simout.txt` and `simerr.txt` for NoC-specific
completion evidence. It fails on panic/fatal markers, timeout-like exit causes,
end-of-run outstanding transactions, zero completion counters, missing
completion evidence, or unexpected `SMOKE_SKIP:` markers. AXI-MM suites always
require writes to drain. AXIS suites may explicitly allow the monitor's
stream-write accounting to remain outstanding after all bounded sinks complete;
those suites still require normal simulator completion and a minimum write
count. Known optional external-RTL skips may be explicitly allowed by the suite
declaration. Individual suites may also require minimum read, write, or packet
completion counters.

## Deep Matrix

`src/noc/testing/generic/deep_matrix_smoke.py` is a small parameterized smoke
driver for deeper AXI-MM and AXIS cases. Each case still runs through the normal
gem5 NoC setup path; TestLib passes `--case <name>` and adds the right tags and
completion expectations.

Keep the matrix deterministic. Use fixed seeds, bounded packet/transaction
counts, and explicit `--abs-max-tick` values. Do not register a matrix case
until it exits through real completion evidence rather than a sim-cycle limit.

## Adding Future NoC Tests

Add new runnable scenarios under `src/noc/testing` first. Then register the
existing scenario path in `test.py` with the appropriate length, ISA, and tags.
Do not put scenario setup logic in this TestLib layer.

Use a checked-in current topology fixture for public quick tests; the legacy
flat topology scripts remain available for direct investigation but are not
release-gate suites.

For sweep regression checks, copy stable baseline CSVs into
`trusted_results/`, then add a `SweepRegressionSpec` in `test.py`. The test
should remain artifact-free by default; use an environment variable for
optional comparison against externally generated sweep results.
