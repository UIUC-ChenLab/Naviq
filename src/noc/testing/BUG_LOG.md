# NoC Testing Bug Log

This log tracks NoC bugs or suspected bugs found while expanding test coverage.
Entries here should include a small repro command, the observed failure mode,
and whether the reproducer is registered in TestLib. Known-bad reproducers
should not be promoted into the passing TestLib suite until the underlying bug
is fixed.

Run commands from the repository root unless noted otherwise.

All bugs recorded in this log are currently resolved and have been promoted to
passing regressions. There are no active known-bug TestLib suites. If a future
reproducer must remain isolated before a fix, register it explicitly in
`tests/gem5/noc/test.py` rather than treating it as passing coverage.

## Bugs and Resolutions

### BUG-NOC-001: AXIS FIFO sub-flit packets do not complete cleanly

Status: resolved
Area: AXIS NMU/NSU, FIFO, packetization, TLAST/TKEEP
Severity: correctness or liveness risk
Regression in TestLib: `noc-axis-fifo-15b-clean-completion` and
`noc-axis-fifo-17b-clean-completion`, quick gate

Passing TestLib regressions: `noc-axis-fifo-15b-clean-completion` and
`noc-axis-fifo-17b-clean-completion` in the quick gate.

Direct repro, 15-byte packets:

```sh
./build/NULL/gem5.opt src/noc/testing/generic/axis_fifo_smoke.py \
  --sim-cycles 500000 \
  --abs-max-tick 5000000000 \
  --param axis_tg_0.min_packet_size_bytes=15 \
  --param axis_tg_0.max_packet_size_bytes=15 \
  --param axis_tg_0.packet_size_distribution=FIXED \
  --param axis_tg_0.max_packets=8 \
  --param axis_fifo.expected_packets=8 \
  --param axis_fifo.fifo_depth=2 \
  --param axis_end_0.expected_packets=8
```

Direct repro, 17-byte packets:

```sh
./build/NULL/gem5.opt src/noc/testing/generic/axis_fifo_smoke.py \
  --sim-cycles 500000 \
  --abs-max-tick 5000000000 \
  --param axis_tg_0.min_packet_size_bytes=17 \
  --param axis_tg_0.max_packet_size_bytes=17 \
  --param axis_tg_0.packet_size_distribution=FIXED \
  --param axis_tg_0.max_packets=8 \
  --param axis_fifo.expected_packets=8 \
  --param axis_fifo.fifo_depth=2 \
  --param axis_end_0.expected_packets=8
```

Root cause and fix:

- The finite AXIS random generator evaluated its stop condition using the
  pre-handshake packet state. On TLAST it immediately started another packet,
  so `max_packets=8` never drained.
- It now evaluates the post-handshake state. Both 15B and 17B FIFO scenarios
  exit through normal completion with 16 aggregate writes and no outstanding
  transactions.

### BUG-NOC-002: AXIS 65-byte 128-bit 2-to-2 backpressure data mismatch

Status: resolved
Area: AXIS NMU/NSU, width conversion, backpressure, monitor data checking
Severity: correctness
Regression in TestLib: `noc-deep-axis-2to2-65b-128w-backpressure`, quick gate

Original behavior:

- The monitor panicked at byte 0 when 65-byte packets crossed the 64-byte NPP
  boundary at a 128-bit endpoint width under sink backpressure.
- The same stale implementation also corrupted 64-byte 128-bit packets.

Root cause and fix:

- `sNocSlaveUnit` carried a separate, stale depacketization implementation
  whose narrow-width sideband and TLAST handling had diverged from the tested
  helper.
- The production path now calls `depacketizeAxisPayloadFlit`, so it shares the
  helper's byte-range sideband mapping, TKEEP, and TLAST behavior.
- The boundary matrix includes deterministic 64B and 65B 128-bit two-source
  cases with 60% sink readiness; both require 16 completed writes and normal
  simulator completion.

### BUG-NOC-003: AXI-MM interleaved read/write multi-ID case left reads outstanding

Status: resolved
Area: AXI-MM NMU/NSU, read responses, RROB, outstanding transaction tracking
Severity: liveness or completion accounting risk
Registered in TestLib: yes, quick gate as
`noc-aximm-interleaved-multi-id-readback`

Root cause and fix:

- `mmNocMasterUnit` imposed a global active-ID lock on RROB wakeups. AXI only
  requires ordering within an ID, so this lock could discard a wakeup for a
  different ready ID and leave its read response stranded.
- RROB output now preserves each per-ID queue's order while allowing ready
  responses for different IDs to proceed independently.
- The promoted TestLib regression runs two deterministic 64B AXI-MM sources,
  rotating addresses and IDs 0 through 3. It requires all 16 writes and all 16
  reads to complete with no end-of-run outstanding transactions.

Why this matters:

- This is the closest current reproducer for deeper RROB/read-response
  behavior in the integrated AXI-MM path.
- It exercises multi-ID traffic, rotating multi-NSU selection, writes followed
  by reads, and read completion accounting.

Registration detail: the regression uses the
`aximm-write-64b-multi-id-rotate` deep-matrix setup, with both traffic
generators explicitly configured for `INTERLEAVED` read/write traffic. It is
therefore a read-return regression, not a write-only variant.

### BUG-NOC-004: `aximmWriteBuffer` drops WSTRB bits for 64-byte beats

Status: resolved
Area: AXI-MM NMU, write packetization, WSTRB
Severity: correctness
Regression: `AximmWriteBufferTest.PacketizesWideWritesWithFullStrobes`

The full-width mask path now explicitly uses `~0ULL` for a 64-byte copy, rather
than shifting a 64-bit integer by 64. The enabled regression verifies valid
bytes for 64B, 128B, and 256B writes.

### BUG-NOC-005: `axisWriteBuffer` can emit an oversized NPP after 1500B packetization

Status: resolved
Area: AXIS NMU, packetization, NPP splitting
Severity: correctness
Regression: `AxisWriteBufferTest.PacketizesMtuSizedPacketAsMultipleNpps`

After each dequeue, the next packet size now takes the earlier of the pending
TLAST boundary and the 256B NPP limit. The enabled 1500B regression verifies
that every emitted NPP is 256B or smaller and that only the final one carries
TLAST.

### BUG-NOC-006: 64-byte AXIS four-source fan-in corrupts payload data

Status: resolved
Area: AXIS NMU/NSU, multi-source arbitration, monitor data checking
Severity: correctness
Regression in TestLib: `noc-axis_1_to_4_smoke`, included in the quick gate

Original failure:

- The four 512-bit sources each send eight 64-byte AXIS packets to one sink.
- At tick 141,000, `NocTrafficMonitor::checkWriteData` panics with an AXIS
  data mismatch (the observed run first differed at byte 16).

Root cause and fix:

- `sNocSlaveUnit` used one shared flit index and wide-beat assembly buffer for
  every incoming AXIS packet. Interleaved packets therefore wrote into one
  another's 64-byte reconstructed beat.
- Reconstruction now uses the flit's real packet-local index and retains a
  separate aggregate buffer for each network packet ID.
- The promoted regression uses fixed source seeds 4100–4103, requires at least
  32 completed writes, and verifies normal simulator completion.

## Recently Avoided False Positives

### AXIS NSU width conversion must stay centralized

The former production duplicate had different narrow-width TKEEP, TLAST, and
sideband behavior than the boundary-tested helper. The NSU now uses that helper
directly, and `noc_axis_depacketizer.test` is registered in the standard C++
test command. The 15B/17B FIFO liveness issue was resolved separately as
BUG-NOC-001, so its integration coverage remains visible in the quick TestLib
gate.

### Completion by sim-cycle limit is not enough

While adding deep matrix cases, some gem5 runs returned process status 0 but
only because `Network Tester completed simCycles`. These should be treated as
failures unless the run also has strong completion evidence and no outstanding
transactions.

Current verifier behavior:

- `NoCCompletionVerifier` fails on end-of-run monitor lines for outstanding
  read/write transactions, so nonzero completion counters no longer hide
  leftover work.

## Testing Infrastructure Notes

### NoC verifier failure paths should raise clear assertions

While adding the outstanding-transaction check, the NoC-local verifier and
known-bug harness failure paths were found to call `test_util.fail`, but this
TestLib checkout does not define that helper. The NoC test helpers now raise
`AssertionError` with the intended failure message instead.

Repro for the verifier-only check:

```sh
PYTHONPATH=ext:tests:tests/gem5/noc \
  python3 tests/gem5/noc/noc_verifier_unittest.py
```
