# NoC Test Coverage TODO

This is the bug-finding backlog for making NoC coverage deeper. Prioritize
small, deterministic tests that expose one class of failure before adding large
cross-product sweeps.

## P0: Turn Known Bugs Into Regressions

- Done: every formerly known NoC bug in `BUG_LOG.md` has been promoted to
  passing coverage; there are currently no active known-bug suites. A future
  isolated reproducer must not be counted as quick/long passing coverage.
- Done: `NoCCompletionVerifier` now fails on monitor end-of-run outstanding
  transaction markers like `read transactions still outstanding` and
  `write transactions still outstanding`.
- Done: BUG-NOC-001 15B/17B AXIS FIFO packets complete without outstanding
  transactions and are in the quick TestLib gate.
- Done: BUG-NOC-002 is promoted to quick TestLib coverage as deterministic
  64B/65B 128-bit AXIS backpressure cases.
- Done: BUG-NOC-003 AXI-MM interleaved multi-ID read/write traffic drains all
  reads and is covered by a quick TestLib regression.

## P0: NSU-Focused Unit Tests

- Done: `noc_axis_depacketizer.test` is registered and covers AXIS NSU
  depacketization at 1B, 15B, 16B, 17B, 63B, 64B, 65B, and 1500B, including
  64-, 128-, and 512-bit endpoint widths, TLAST, TKEEP, and sideband fields.
- Parked: exploratory `noc_axis_stream_contract.test` coverage was written but
  is not registered while AXIS production refactors are held for review.
- Done: added `noc_mm_write_depacketizer.test` coverage for AXI-MM
  `mmNocSlaveUnit` write data assembly across 16-byte NoC flit boundaries,
  including a full 64-byte beat, a partial tail after a full beat, and an
  unaligned wide write.
- Done: extended `noc_mm_write_depacketizer.test` with partial-strobe narrow
  slave beats and a short single-flit burst on a 16-byte slave.
- Add `mmNocSlaveUnit` read-response generation tests for 1-beat, multi-beat,
  and boundary-crossing reads.

## P0: NMU-Focused Unit Tests

- Done: extended `axisWriteBuffer` tests for 1B, 15B, 16B, 17B, 63B, 64B, 65B,
  255B, 256B, and 257B payloads.
- Done: enabled `AxisWriteBufferTest.PacketizesMtuSizedPacketAsMultipleNpps`
  verifies a 1500B packet is split into 256B-or-smaller NPPs.
- Done: added tests where `TID` or `TDEST` changes before `TLAST`; current
  policy is to panic/throw loudly.
- Done: added enabled `aximmWriteBuffer` tests for 1B, 16B, and 65B writes.
- Done: enabled `AximmWriteBufferTest.PacketizesWideWritesWithFullStrobes`
  verifies full WSTRB preservation for 64B, 128B, and 256B writes.
- Done: added `WriteTracker` tests for multiple AXI IDs, response error
  aggregation, response ordering, and tracker removal after responses arrive.
- Done: added deeper RROB tests for out-of-order flit arrival, multi-entry
  64B beats, per-AXI-ID ordering, and read-ready scanning.

## P1: Router, Link, VC, and Credit Tests

- Add router allocator tests for independent VC allocation and no duplicate
  grants in one cycle.
- Add credit accounting tests that verify credits return exactly once per flit.
- Add buffer-depth edge cases for `buffers_per_data_vc` and
  `buffers_per_ctrl_vc`.
- Add deadlock/liveness stress cases with small buffers and high injection
  rates.
- Add route-table validation tests for missing route, duplicate route, invalid
  VC, invalid link ID, and unreachable destination.
- Add incast and hotspot tests that explicitly verify all sources make progress.

## P1: Full-System AXI-MM Scenarios

- Add read-only AXI-MM tests once the traffic generator has a clean read-only
  mode or an equivalent preloaded-read scenario.
- Add write-then-read verification where read data is compared against prior
  writes.
- Add interleaved read/write with fixed AXI ID, then multiple AXI IDs, then
  randomized IDs.
- Add multi-NSU address selection tests for `INTERLEAVE`, `ROTATE`, and
  `RANDOM`.
- Add boundary-size tests: 1B, 15B, 16B, 17B, 63B, 64B, 65B, 128B, 256B.
- Add near-limit outstanding write tests: 1, 4, 16, 63, 64, and over-limit.
- Add decoupled AXI-MM AW/W tests (W-before-AW and multiple independent
  requests). W-before-AW is currently unsupported: add a pending-W queue and
  deterministic regression before claiming general AXI independent-channel
  support.
- Add W-ready boundary tests at 448B/512B occupancy before changing W-buffer
  admission policy; verify the next beat cannot exceed the modeled 512-byte
  capacity.
- Add address boundary tests around NSU base/end ranges and overlapping ranges.

## P1: Full-System AXIS Scenarios

- Add AXIS sink ready-percent sweeps: 100, 75, 50, 25, and bursty deterministic
  backpressure.
- Add FIFO depth sweeps: 1, 2, 4, 16, and large depth.
- Add 1-to-N multicast-style destination selection where supported.
- Add N-to-1 incast AXIS stress.
- Add packet checker coverage for exact mode, IPv4 mode, checksum repair, NAT
  mode, sideband preservation, and corrupted-packet expected failures.

## P1: Checkpoint and Restore

- Add AXI-MM checkpoint tests while writes are outstanding.
- Add AXI-MM checkpoint tests while reads are outstanding and RROB entries are
  partially filled.
- Add AXIS checkpoint tests while the NMU write buffer has partial packets.
- Add AXIS checkpoint tests while the NSU has partially depacketized state.
- Verify restored runs complete with the same counters as uninterrupted runs.
- Add seeded-random requirements for checkpointable traffic generators.

## P2: DDR, HBM, CPU, and SmartNIC Coverage

- Add DDR direct read/write data-integrity tests, not only completion tests.
- Add DDR contention tests with expected fairness or progress constraints.
- Add HBM single-port, shared-controller, mixed BRAM/HBM, and multi-controller
  stress with completion expectations.
- Add CPU-backed tests that check memory contents after NoC DMA or CPU traffic.
- Add PPE/RTL tests behind explicit external dependency tags, with clear skip
  messages when RTL is unavailable.
- Add SmartNIC backpressure and limiter tests to TestLib if they can run
  storage-safely.

## P2: Sweep and Performance Regression Coverage

- Add trusted baselines for a small AXIS packet-size sweep after BUG-NOC-001 is
  fixed.
- Add trusted baselines for AXI-MM read/write latency, including the promoted
  multi-ID readback regression.
- Add warning-only bandwidth drift checks for route ladder, incast, HBM, and DDR
  contention.
- Add explicit metric coverage checks so missing latency/bandwidth columns fail
  as infrastructure errors.
- Keep full sweep execution manual or nightly; TestLib should compare trusted
  snapshots by default.

## P2: Negative and Failure-Mode Tests

- Add expected-failure support for cases that should panic or fatal, such as
  invalid topology, invalid placement, invalid VC, unsupported width, or bad
  packet checksum.
- Add malformed JSON setup tests for missing endpoints, unknown components, and
  protocol mismatches.
- Done: added timeout-like exit cause unit coverage for
  `NoCCompletionVerifier`.
- Done: added `SMOKE_SKIP:` unit coverage for allowed and unexpected skip
  behavior.

## P3: Tooling and CI Hygiene

- Add native expected-failure handling if TestLib grows support for it, before
  any future known-bug reproducer is exposed through TestLib.
- Add a no-tracked-file-changes guard after quick tests.
- Done: added `src/noc/testing/run_noc_gtests.sh` to build and run only NoC
  GTests.
- Add a nightly command that runs `noc-nightly`, sweep comparisons, and
  checkpoint/restore tests.
- Keep generated artifacts under gem5/TestLib output directories and out of
  tracked source paths.
- Document runtime budgets for quick, long, stress, and nightly suites.
