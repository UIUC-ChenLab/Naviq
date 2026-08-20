# NoC Testing Guide

This directory contains runnable NoC gem5 scenarios and shared test support.
The official regression entry point is the gem5 TestLib wrapper in
`tests/gem5/noc`; the scripts here remain the source of truth for scenario
setup.

Use this guide for day-to-day commands and for deciding where new tests belong.
See `tests/gem5/noc/README.md` for TestLib-specific details.

For active bug reproducers and the deeper coverage backlog, see
`BUG_LOG.md` and `TEST_TODO.md`.

## Test Layers

### Direct Smoke Scripts

Run an individual scenario directly from the repository root:

```sh
./build/NULL/gem5.opt src/noc/testing/generic/axis_1_to_1_smoke.py
```

CPU-backed scenarios require an X86 gem5 build and the corresponding test
binary:

```sh
./build/X86/gem5.opt src/noc/testing/ddr/cpu_ddr_hello_smoke.py
```

Direct runs are useful while developing one scenario. They do not give you
TestLib tagging, result indexing, or the NoC completion verifier.

### TestLib Regressions

Run the quick NoC smoke suite:

```sh
cd tests
./main.py run --skip-build --length=quick --isa=NULL --variant=opt gem5/noc
```

Run the longer NoC regression set:

```sh
cd tests
./main.py run --length=long --variant=opt gem5/noc
```

Run only CPU-backed NoC tests:

```sh
cd tests
./main.py run --length=long --isa=X86 --variant=opt --include-tags noc-cpu gem5/noc
```

List registered NoC suites without running them:

```sh
cd tests
./main.py list -q --suites gem5/noc
```

Run the NMU/NSU-focused deep matrix:

```sh
cd tests
./main.py run --skip-build --exclude-tags '.*' --include-tags 'noc-nmu|noc-nsu' \
  --isa=NULL --variant=opt gem5/noc
```

Run just the longer stress subset from that matrix:

```sh
cd tests
./main.py run --skip-build --exclude-tags '.*' --include-tags noc-stress \
  --isa=NULL --variant=opt gem5/noc
```

### AXIS Boundary Matrix

The AXIS regression strategy is deliberately layered instead of a large,
slow cross-product. `noc_axis_depacketizer.test` checks byte reconstruction,
TKEEP, TLAST, and TID/TDEST/TUSER propagation for 1B, 15B, 16B, 17B, 63B,
64B, 65B, and 1500B payloads at 64-, 128-, and 512-bit endpoint widths.

The quick TestLib gate adds integration checks for 15B, 17B, 64B, and 65B AXIS
packets. The 64B/65B cases use deterministic two-source traffic at 128-bit
width with 60% sink readiness; the FIFO cases require 16 completed writes and
normal completion without outstanding transactions.

Do not launch multiple TestLib runs concurrently unless each run is configured
with a separate result directory. TestLib writes to `tests/testing-results`, so
parallel runs can overwrite or interfere with each other.

TestLib runs set `NOC_RUNTIME_ARTIFACT_DIR` so runtime traces land under the
gem5 output directory for that test. Direct gem5 runs without that environment
variable may still write legacy graph artifacts such as
`src/noc/out/csv/` (runtime traces, traffic monitor CSVs) and `src/noc/out/graphs/` (plot PNGs).

### Sweep Regression Checks

The sweep regression checks are storage-safe by default. They do not run
`noc_testing/noc_sweep.py`; instead they validate sweep plans against trusted
CSV snapshots under `tests/gem5/noc/trusted_results`.

Run only the sweep checks:

```sh
cd tests
./main.py run --exclude-tags '.*' --include-tags noc-sweep gem5/noc
```

Compare externally generated sweep output against the trusted snapshots:

```sh
cd tests
NOC_SWEEP_OBSERVED_SIZING_CSV=/path/to/gem5_noc_plan_all_sizes_v2.csv \
NOC_SWEEP_OBSERVED_PLACEMENT_CSV=/path/to/gem5_placement_route_ladder.csv \
./main.py run --exclude-tags '.*' --include-tags noc-sweep gem5/noc
```

Latency and bandwidth differences are reported as `WARNING:` messages, not test
failures. Missing trusted coverage, malformed CSVs, or missing metric columns
are infrastructure failures.

### Vivado Accuracy Checks

`noc-vivado` is the release acceptance check for the checked-in sizing-latency
comparison. It validates gem5 results against a pinned Vivado reference without
launching Vivado or a full sweep. Run the baseline check with:

```sh
cd tests
./main.py run --length=quick --exclude-tags '.*' --include-tags noc-vivado gem5/noc
```

To compare a fresh gem5 sweep, set
`NOC_VIVADO_ACCURACY_OBSERVED_CSV=/path/to/result.csv` before the same command.
The required coverage and latency-error envelope are defined beside the
baseline in `tests/gem5/noc/test.py`. The current release gate covers average
and maximum AXI-MM latency; minimum latency remains diagnostic-only because
the pinned Vivado comparison contains large minimum-latency outliers.

## Directory Layout

- `generic/`: small AXI-MM and AXIS smoke scenarios.
- `fixtures/topologies/`: checked-in current topology inputs and generated
  NTS/NCR descriptions used by public generic TestLib smokes.
- `ddr/`: DDR, CPU DDR, DMA, and SmartNIC DDR scenarios.
- `hbm/`: HBM endpoint scenarios.
- `experiments/`: named experiment campaigns with comparison drivers,
  metadata, and result criteria.
- `hbm_smartnic/`: shared HBM CPU-write DMA/PPE helper code used by maintained
  HBM SmartNIC experiments.
- `smartnic/`: SmartNIC/AXIS loopback, module, and PPE scenarios.
- `monitors/`: NoC traffic monitor code and analysis helpers.
- `artifacts/`: generated or checked-in runtime artifacts used by tests.

## C++ Unit Tests

Focused C++ tests live beside the code they cover and are registered through
`src/noc/SConscript`.

Build and run the current NoC unit tests from the repository root:

```sh
src/noc/testing/run_noc_gtests.sh
```

The script expands to:

```sh
scons build/NULL/noc/noc_write_structs.test.opt \
      build/NULL/noc/noc_mm_write_depacketizer.test.opt \
      build/NULL/noc/noc_axis_depacketizer.test.opt \
      build/NULL/noc/noc_rrob.test.opt -j8
./build/NULL/noc/noc_write_structs.test.opt
./build/NULL/noc/noc_mm_write_depacketizer.test.opt
./build/NULL/noc/noc_axis_depacketizer.test.opt
./build/NULL/noc/noc_rrob.test.opt
```

Use these tests for small invariants that are hard to isolate in a full gem5
scenario, such as write response tracking, AXI-MM write-buffer assembly, AXIS
TLAST/TKEEP packetization, and RROB entry bookkeeping.

The normal C++ command includes the wide-WSTRB and 1500B AXIS packetization
regressions. Remaining known-bug reproducers, if any, are listed separately
in `BUG_LOG.md` and are not counted as passing release coverage.

## Adding a Smoke Test

1. Add the runnable scenario under the appropriate `src/noc/testing/<family>/`
   directory.
2. Keep topology, traffic, and endpoint setup in the runnable script or shared
   scenario helper. Do not put scenario setup in TestLib.
3. Make the run produce clear completion evidence:
   `Completed Reads`, `Completed Writes`, or an unambiguous completion marker.
4. Register the script in `tests/gem5/noc/test.py` with the right suite group,
   length, ISA, and tags.
5. Prefer `quick` only for short, deterministic smokes. Put stress,
   long-running, CPU-backed, and optional RTL-dependent tests under `long`.

The NoC TestLib wrapper executes scripts through `run_noc_smoke.py`, which
changes to the repository root before running the scenario. This preserves
repo-root-relative paths used by the existing NoC scripts.

For a parameterized deep case, add it to
`generic/deep_matrix_smoke.py`, then register it in `tests/gem5/noc/test.py`
with tags such as `noc-nmu`, `noc-nsu`, `noc-aximm`, `noc-axis`,
`noc-stress`, or `noc-nightly`. Require minimum completion counters when the
case has a known expected number of reads, writes, or packets.

For AXI-MM read coverage, use a bounded `SEQUENTIAL` readback case. The random
traffic generator supports `WRITE_ONLY`, `SEQUENTIAL`, and `INTERLEAVED`; it
does not implement a `READ_ONLY` mode.

## Adding a Sweep Regression

1. Keep the sweep plan under `noc_testing/sweep_plans/...`.
2. Generate or choose a stable gem5 result CSV outside TestLib.
3. Copy that stable baseline into `tests/gem5/noc/trusted_results/`.
4. Add a `SweepRegressionSpec` in `tests/gem5/noc/test.py`.
5. Give the spec an environment variable name for optional observed-result
   comparison.

Do not make TestLib run a full sweep by default. Full sweeps can generate large
artifact trees and should stay in explicit `noc_testing/noc_sweep.py` workflows.

## Nightly-Style Runs

The heavier TestLib subset is tagged but not special-cased by a separate
runner. Use this from `tests/` when you want the current nightly-style NoC
coverage:

```sh
./main.py run --length=long --variant=opt --include-tags noc-nightly gem5/noc
./main.py run --exclude-tags '.*' --include-tags noc-sweep gem5/noc
```

## Verifier Behavior

`NoCCompletionVerifier` checks `simout.txt` and `simerr.txt` after a TestLib
gem5 run. It fails on:

- `panic:`, `fatal:`, or `m5.fatal` markers.
- Timeout-like exit causes such as `simulate() limit reached` or `maxtick`.
- End-of-run monitor warnings for outstanding read/write transactions.
- Completion counters that are present but all zero.
- Missing completion evidence.
- Unexpected `SMOKE_SKIP:` markers.

Known optional external-RTL skips may be explicitly allowed in the suite
registration. Do not rely on generic regex checks for NoC completion unless the
custom verifier cannot represent the condition.
