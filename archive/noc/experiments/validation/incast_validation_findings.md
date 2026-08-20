# Historical Naviq vs Vivado Incast Findings and Changes

> **Archived record (2026-08-16).** This document preserves dated observations
> and implementation history from an active validation investigation. It is not
> a maintained release claim or user guide; use
> `noc_testing/experiments/validation/README.md` for supported workflows.

**Last updated:** 2026-07-06  
**Scope:** AXI-MM multi-endpoint incast validation against Vivado/XSim.

This document records the Naviq vs Vivado incast investigation as it stood
when it was archived. Later model changes or validation results may supersede
individual observations below.

## Current Validation Envelope

For now, use a **soft validation cap of 1200 MBps** for the 4-to-1 512B tx10
incast work.

This is not a simulator behavior cap and does not change traffic generation.
It is the current confidence envelope for reporting latency accuracy while the
higher-load and saturated read paths are still being debugged.

Current acceptance framing:

- Primary metric: aggregate average write/read latency vs Vivado.
- Target: approximately 95% or better.
- Current best passing family: 4-to-1, 512B, tx10, bandwidth <= 1200 MBps,
  with structural NSU multi-read-response-VC per-flit pacing and default
  packetized NMU read-request chunks.
  Historical direct `gap1` runs established the target behavior before this was
  promoted into model logic.
- Per-source accuracy is not uniformly above 95%; src0 read is the most common
  residual weak point.
- Saturated rows remain outside the current reporting envelope. They either
  expose large latency mismatches or hit the current gem5 message-buffer
  capacity assertion.

## Sweep Reproducibility Note: TG Gaps and Seeds

Latency validation sweeps should pin AXI-MM traffic-generator timing with
fixed zero command gaps and nonzero fixed seeds:

- `param.tg_N.gap_distribution=FIXED`
- `param.tg_N.min_gap_cycles=0`
- `param.tg_N.max_gap_cycles=0`
- `param.tg_N.seed=<nonzero fixed value>`

The default generator has `seed=0` and `gap_distribution=UNIFORM` with a
0..10 cycle gap range. `seed=0` is time-based, so otherwise-identical gem5
runs can change the initial write issue phase. In `rw_interleaved` mode, reads
are generated after write completion; a shifted write phase changes B
completion order, then AR issue order, then which source gets the early
read-response slot. This is TG phasing, not evidence of random NoC arbitration.

For the compact 4-to-1 512B tx1 anchor, fixed zero gaps stabilize the order and
match the Vivado source service pattern. If an experiment intentionally studies
Vivado TG randomness, document that separately and match the Vivado seed/gap
settings explicitly.

## AXI-MM Address Generation Rule

Vivado and gem5 must agree on both the starting address and the address step for
each traffic generator.

For multi-source AXI-MM incast debug, the conn JSON can give each master a
different `base_address`/`high_address` range. Vivado applies those ranges to
the TGs directly. gem5 must also apply them to the generator's target windows,
not only to the visible `base_addr` parameter. The runtime generator chooses
addresses from `nsu_min_addrs`/`nsu_address_spaces`; if those windows are left
at the raw NSU memory range, all sources start at the same target base even
when their conn-json master bases are offset.

The setup loaders now clip each AXI-MM master's NSU target windows to the
master port's configured base/high range. For example, the 4-to-1 spread setup
should issue from:

- `tg_0`: `0x20100000000`
- `tg_1`: `0x20100000200`
- `tg_2`: `0x20100000400`
- `tg_3`: `0x20100000600`

Those staggered source bases were a debug aid for waveform readability. Final
4-to-1 incast latency sweeps should use
`topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm_same_base.conn.json`,
where all four TGs start at `0x20100000000`. Keep the staggered connection file
available for targeted debug reruns, but do not use it as the final baseline.

The current locked input smoke plan is:

`noc_testing/sweep_plans/validation/4to1_512_same_base_fixed_inputs_smoke.csv`

Before treating a latency plan as final-baseline data, run:

```bash
python3 noc_testing/experiments/validation/validate_latency_inputs.py \
  noc_testing/sweep_plans/validation/4to1_512_same_base_fixed_inputs_smoke.csv
```

That validator checks same-base TG windows, fixed zero TG gaps, nonzero fixed
seeds, transaction-sized explicit address increments, and absence of manual
row-level NSU read-response pacing overrides. For intentional waveform/debug
plans with staggered bases, pass `--allow-staggered-bases` so the exception is
visible in the command line.

For fixed-size Vivado latency sweeps, use a transaction-sized address step. The
old sweep default used `address_increment=beat_bytes` (64B for 512-bit AXI),
which made a 512B tx2 row issue the second transaction at `base+0x40`. That can
split the transaction across 256B NPP boundaries and create false read-latency
skew. The sweep default now uses `transaction_bytes` when present and leaves
explicit `param.tg_N.address_increment` overrides intact.

Diagnostic evidence:

- Vivado batch logs for the 512B tx2 spread run showed `tg_1/tg_2/tg_3`
  programmed at `+0x200/+0x400/+0x600`.
- Before the fix, gem5 BRAM read traces still showed those sources issuing at
  `0x20100000000`.
- A direct `address_increment=512`, aligned probe without the per-source base
  correction restored close tx2/tx10 latency agreement, which isolated address
  stepping as one dominant buildup artifact.
- After honoring the per-source bases, the gem5 BRAM trace matches the Vivado
  address intent: `tg_0` starts at `0x20100000000`, `tg_1` at
  `0x20100000200`, `tg_2` at `0x20100000400`, and `tg_3` at
  `0x20100000600`, with each fixed 512B transaction advancing by `0x200`.
- The corrected-address tx2/tx10 reruns still show a separate src3 read-latency
  mismatch. In the tx10 half-rate probe, after the diagnostic `gem5 - 2 cycles`
  CDC view, src0/src1/src2 reads are within about 0-2 cycles of Vivado, while
  src3 read is about 27 cycles late. Treat this as the next modeling issue, not
  as unresolved address propagation.

Latest corrected-address probes:

- tx2 gem5 result:
  `noc_testing/artifacts/generated/results/gem5_fixed_tg_4to1_512_tx2_tx5_half_rate_probe_20260706_024706.csv`
- tx2 BRAM trace:
  `noc_testing/artifacts/generated/diagnostics/tx2_addr_window_fix_probe_20260706/bram_read_trace.csv`
- tx10 gem5 result:
  `noc_testing/artifacts/generated/results/gem5_fixed_tg_4to1_512_txcount_half_rate_probe_20260706_024938.csv`
- tx10 BRAM trace:
  `noc_testing/artifacts/generated/diagnostics/tx10_addr_window_fix_probe_20260706/bram_read_trace.csv`

Latest fixed-TG anchor rerun:

- Diagnostic plan was a transient scratch row for the compact 512B tx1 anchor.
- Vivado reference:
  `noc_testing/artifacts/generated/results/vivado_results_vivado_naviq_4to1_incast_compact_512B_tx1_anchor_normal.csv`
- gem5 result:
  `noc_testing/artifacts/generated/results/gem5_compact_512B_tx1_fixed_tg_compact_512B_tx1_fixed_tg_20260702.csv`
- Raw aggregate average-latency accuracy: write `99.21%`, read `99.09%`.
- With the diagnostic `gem5 - 2 cycles` CDC view: write `99.46%`, read `98.83%`.
- Per-source raw deltas were small and matched Vivado ordering:
  `src0 W+2/R+0`, `src1 W+2/R+0`, `src2 W+1/R+1`, `src3 W+0/R+2`.

## Executive Summary

The most important discovery was that 512B AXI reads were chopped into two 256B
NPP requests and could be serviced as independent chunks. That created read
response holes and interleavings that Vivado does not show. A diagnostic that
delayed tile/read-tracker visibility until a complete original read was ready
removed the large intra-read response divergence, but that delay is not retained
yet.

The second important discovery was that the first grouping implementation was
too 512B-specific. It held 256B reads as if they needed another chunk. Carrying
the original AXI read size from the NMU to the NSU fixed that over-hold.

The model is now good for several 4-to-1 512B capped rows up to 1200 MBps, but
it is not done:

- 1600 MBps read latency diverges badly.
- Saturated tx10 rows abort in gem5 on a `MessageBuffer::enqueue` max-size
  assertion before latency can be evaluated.
- NSU read response pacing is now structural: an NSU uses one-flit-every-other-
  cycle pacing when it has read-response routes to AXI-MM NMUs on multiple VCs;
  otherwise it keeps the normal 4-flit/16-flit gap behavior.
- NMU read-request chunk packetization is now structural: when one AXI read is
  chopped into multiple NPP read requests, those request flits are emitted as
  one packet with consecutive flit IDs. This makes the chopped request chunks
  leave the NMU back-to-back instead of as independently arbitrated one-flit
  packets.
- The old canonical 4-source read order patch was a validation aid, not a final
  arbitration model. Read request groups now flush in first-ready queue order;
  network arbitration should determine which source reaches the NSU first.

## Current State: What Is Retained, Rejected, and Open

Retained model/input changes:

- AXI-MM TG inputs for final latency validation are deterministic: fixed zero
  gaps, fixed nonzero seeds, same-base TG windows for final 4-to-1 baselines,
  and transaction-sized address increments.
- gem5 setup honors conn-json AXI-MM master address windows when constructing TG
  target ranges.
- Original AXI read size and final-chunk metadata are carried through chopped
  NPP reads and traces/checkpoints. The delayed grouped-read scheduling model
  remains open work.
- Chopped AXI read-request chunks are packetized by default at the NMU. The
  legacy independent one-flit-packet behavior is available only with
  `NOC_LEGACY_SPLIT_READ_REQ_CHUNKS=1` for diagnostics.
- NSU read groups are no longer forced into the historical `1,3,2,0` canonical
  order; queued read groups flush in first-ready order.
- NSU read-response pacing is structural: multi-read-response-VC NSUs use
  one-flit-every-other-cycle pacing, while same-VC cases use the normal
  4-flit/16-flit gap behavior.

Rejected or diagnostic-only changes:

- Staggered TG bases (`+0x200/+0x400/+0x600`) are waveform/debug aids only.
  Final 4-to-1 latency baselines should use the same-base connection JSON.
- Row-level `nsu_read_response_half_rate` or per-flit gap overrides are
  diagnostics. Final plans should let the simulator choose pacing structurally.
- The hardcoded canonical read-response/source order was removed; it matched one
  observation but is not a defensible arbitration model.
- `max_outstanding_reads=1` and similar source-throttling experiments can help
  diagnose ordering, but they are not current model fixes.
- `NOC_LEGACY_SPLIT_READ_REQ_CHUNKS=1` restores old split read-request timing
  for comparison against older runs. It should not be set for final validation
  or paper sweeps.

Open modeling issue:

- The remaining src3 read mismatch appears tied to when grouped read chunks are
  made visible to the tile/read tracker. A diagnostic that delayed tile AR
  enqueue/read-tracker insertion until read-group flush improved src3
  contiguity, but that behavior is not yet locked as the permanent model.
  Continue that work separately from input cleanup.
- Saturated rows still need separate capacity/admission work. Packetized NMU
  read-request chunks improve the targeted tx2/tx10 same-base behavior, but the
  wider stress runs show that packetization is not a saturation fix by itself.

## Main Findings

### Vivado Endpoint Behavior

For the 4-to-1 512B tx10 endpoint wave reference:

- Vivado's read response order repeats as `tg1, tg3, tg2, tg0`.
- 512B read responses are continuous eight-beat bursts.
- The observed response beat spacing is rigid enough that missing or reordered
  chunks in gem5 are visible as endpoint latency skew.

This pushed the debug focus away from base NMU/NSU latency constants and toward
read request ordering, read-tracker insertion order, and response-drain timing.

### Root Cause Isolated So Far

The old Naviq behavior inserted each chopped NPP read request into the read
tracker independently. For a 512B AXI read, that meant the two 256B pieces could
be serviced around other sources' chunks. Vivado does not appear to do this for
the tested row.

The best diagnostic model grouped related read request chunks at the NSU and
only inserted the original NPP messages into the read tracker when the group was
flushed to the tile. That kept a single AXI read's response contiguous, but it
is intentionally not retained in the cleaned code path. Current retained code
sends adapted read requests to the tile immediately and preserves the metadata
needed to revisit grouped scheduling later.

Latest same-base 4-to-1 spread diagnostic, 2026-07-06:

- Baseline gem5 still split src3's first 512B read response at the endpoint:
  src3 AXI RVALID groups were `506..530` and `570..594` cycles, while Vivado's
  src3 waveform showed one contiguous eight-beat group at `2145..2201ns`.
- Baseline NSU drain order for the first response set was
  `src1, src1, src3, src2, src3, src2, src0, src0`.
- A temporary diagnostic that actually delayed tile AR enqueue/read-tracker
  insertion until read-group flush changed the NSU drain order to
  `src1, src1, src3, src3, src2, src2, src0, src0` and made src3 RVALID
  contiguous (`511..567` cycles).
- With the diagnostic and the usual `gem5 - 2 cycles` CDC view, tx10 same-base
  read errors were approximately `src0 +3.3`, `src1 +4.0`, `src2 +3.3`,
  `src3 +6.4` cycles. This strongly suggests the remaining src3 mismatch is
  caused by tile-request/read-tracker grouping semantics, not by NSU per-flit
  pacing alone.
- Diagnostic artifacts:
  `noc_testing/artifacts/generated/diagnostics/scheduler_compare_20260706/`
  and
  `noc_testing/artifacts/generated/results/gem5_fixed_tg_4to1_512_tx2_tx10_same_base_probe_same_base_tx2_tx10_grouped_ar_diag_20260706.csv`.

### NMU Read-Request Chunk Packetization

The retained NMU-side fix is to packetize chopped read-request chunks. A 512B
AXI read still becomes two 256B NPP read requests, but those request flits now
share one network packet and consecutive flit IDs. That makes the chunks leave
the NMU back-to-back through the normal NI/router packet path.

This is now the default model behavior. To reproduce the old behavior for
diagnostics, set:

```bash
NOC_LEGACY_SPLIT_READ_REQ_CHUNKS=1
```

Do not set that variable for final validation or paper sweeps.

Same-base 4-to-1 spread evidence:

- tx2 src3 read changed from raw gem5 `294` cycles to raw gem5 `262` cycles.
  With the usual diagnostic two-cycle CDC view, that is `260`, matching Vivado
  `260` exactly.
- tx10 src3 read changed from raw gem5 `289.2` cycles to raw gem5 `263.6`
  cycles. With the two-cycle CDC view, that is `261.6` vs Vivado `260`.
- Other sources and write latencies were essentially unchanged in the same-base
  tx2/tx10 smoke comparison.
- Detailed artifact:
  `noc_testing/artifacts/generated/diagnostics/packetize_read_req_chunks_comparison_20260706.csv`.
- Default-behavior confirmation after promotion:
  `noc_testing/artifacts/generated/diagnostics/packetized_default_same_base_comparison_20260706.csv`.
- Legacy opt-out sanity check:
  `NOC_LEGACY_SPLIT_READ_REQ_CHUNKS=1` restores the old tx2 src3 read latency
  (`294` raw gem5, `292` after the two-cycle CDC view), confirming the revert
  path is functional.

Wider staggered-base spread/stress evidence:

- `4to1_low_tx10`: CDC-adjusted read error range `-6.2..+4.9` cycles.
- `2to1_std_tx10`: CDC-adjusted read error range `-2.7..0.0` cycles.
- `4to1_std_tx50`: CDC-adjusted read error range `-22.24..+19.12` cycles.
- `2to1_sat_tx10`: still poor, `+148.9..+185.9` cycles late on read average.
- `4to1_sat_tx10`: gem5 aborts on `NocMessageBuffer.cc:896` max-size
  assertion at tick `519000`.
- Detailed artifact:
  `noc_testing/artifacts/generated/diagnostics/packetize_read_req_chunks_wider_spread_comparison_20260706.csv`.

Interpretation: packetized read-request chunks are the best default behavior
for the current 512B tx2/tx10 accuracy target, but they do not solve saturated
traffic. Treat saturated rows as a separate admission/capacity problem.

### Original Read Size Metadata

The first grouping fix used a hardcoded 512B target. That worked for the 512B
row but failed on 256B reads.

The current patch carries explicit metadata:

- `NocMemoryMsg::originalReadBytes`
- `NocMemoryMsg::finalReadChunk`

The NMU stamps those fields when it chops an AXI read into NPP requests. The
NSU uses the original byte count to decide when a read group is complete.

### Read Response Gap Is Not Universal

The runtime knob `--nsu-read-response-per-flit-gap-cycles 1` improves aggregate
read accuracy for 4-to-1 512B capped rows through 1200 MBps.

It is not generally correct:

- It hurts the 256B row.
- It hurts 2-to-1 reads.
- It does not rescue the 1600 MBps 4-to-1 read case.

The model now has an automatic NSU-side per-flit pacing condition under test.
It latches a one-cycle per-flit gap when the NSU has read-response routes to
AXI-MM NMUs on multiple physical VCs. This matches the current Vivado waveform
hypothesis: when one NSU has to return read data on different response VCs
(for example VC 2 for one source and VC 6 for another), it behaves like a
half-rate response emitter. When all read responses from that NSU use the same
VC, the normal 4-flit/16-flit gap behavior remains active. The CLI knob remains
available as a diagnostic override, but this auto rule is the candidate general
replacement for row-level `gap1` runs.

Anchor checks for the structural multi-VC rule:

- Different-VC corner 2-to-1:
  reused Vivado topology tag `20260705_133602`.
  The Vivado NCR has READ VCs `2` and `6`. With automatic structural pacing,
  gem5 result
  `noc_testing/artifacts/generated/results/gem5_corner_2to1_auto_vc_pacing_probe_20260706_032443.csv`
  gives read latencies `166/118` cycles vs Vivado `159/116`; after the
  diagnostic two-cycle CDC view this is `+5/+0` cycles.
- Same-VC compact-y3 2-to-1:
  reused Vivado topology tag `20260704_175303`.
  The Vivado NCR has READ VCs `6` and `6`. With automatic structural pacing,
  gem5 result
  `noc_testing/artifacts/generated/results/gem5_route_location_2to1_compact_auto_vc_pacing_probe_20260706_032444.csv`
  gives read latencies `70/93` cycles vs Vivado `68/91`; after the diagnostic
  two-cycle CDC view this matches exactly.

### Read Request Groups Use First-Ready Queue Order

The 4-source canonical order `1,3,2,0` was derived from the 512B endpoint wave
reference. It was useful for validating that grouped read-tracker insertion
removed intra-read response holes, but it is not an AXI-MM ordering rule.
Applying it globally created lock-transition artifacts: once the order locked,
the NSU could hold a ready source behind the next learned source even though
that other request had not become ready.

The current model removes the learned source-order lock. Read groups are still
coalesced until the original AXI read is complete, but once a group is ready
or reaches its coalescing deadline, the NSU flushes the first ready group in
queue order. This keeps ordering tied to upstream request arrival/arbitration
instead of imposing a global NSU round-robin across masters.

The old sub-256B validation showed why this matters:

- `size32_tx10`: aggregate read accuracy improves from `92.0%` to `98.2%`.
- `size64_tx10`: aggregate read accuracy improves from `93.0%` to `98.3%`.
- `size128_tx10`: aggregate read accuracy improves from `86.4%` to `97.9%`.
- `size256_tx10`: remains above target at `97.5%` aggregate read accuracy.

## Code Changes Under Test

These are the current model/debug changes relevant to the incast work.

| Area | Files | Why |
|---|---|---|
| Switch arbitration LRU | `src/noc/core/network/switch/NocSwitchAllocator.*` | Newly active requesters are inserted into the LRU set before winner selection, and winners move to MRU. This fixed unfair repeated losses from unseen requesters. |
| Physical VC buffer depth | `src/mem/ruby/network/garnet/InputUnit.cc`, network helpers | Use effective physical VC depth rather than only vnet-level depth. |
| Switch/NI tracing | `NocGarnetNetwork.*`, `NocNetworkInterface.cc`, setup helpers | Added NPS arbitration/queue/NI trace support for comparing merge behavior. |
| NSU read grouping diagnostic | `src/noc/core/network/nsu_types/mmNocSlaveUnit.*` | Grouped/delayed read scheduling was isolated as the likely next fix, but is not retained in the cleaned model. |
| Original read metadata | `NocMemoryMsg.hh`, `NocMessageBuffer.cc`, `mmNocMasterUnit.cc` | Carry original AXI read size/final chunk marker through NPP messages and checkpoints. |
| NMU read-request packetization | `src/noc/core/network/nmu_types/mmNocMasterUnit.*` | Chopped read-request chunks are emitted as one back-to-back packet by default; `NOC_LEGACY_SPLIT_READ_REQ_CHUNKS=1` restores old independent one-flit packets for diagnostics. |
| NSU read response pacing | `src/noc/core/network/nsu_types/mmNocSlaveUnit.*`, `src/noc/core/network/NocGarnetNetwork.*`, setup helpers | Adds automatic per-flit pacing when one NSU returns read data across multiple response VCs; the old gap knob remains as a diagnostic override. |
| Read group ordering | `src/noc/core/network/nsu_types/mmNocSlaveUnit.cc` | Removes the learned 4-source canonical order lock and flushes the first ready queued read group. |
| Bandwidth probe plan | `noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_bw_probe.csv` | Adds reproducible 1200/1600 MBps 4-to-1 512B tx10 probes. |
| Size probe plan | `noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_size_probe.csv` | Adds comparable 128/256/512/1024B 4-to-1 tx10 probes at 800 MBps. |
| Small-size probe plan | `noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_small_size_probe.csv` | Adds comparable 32/64B 4-to-1 tx10 probes at 800 MBps. |

## Current Results

Accuracy values below are aggregate average latency accuracy unless noted.

### 4-to-1 512B tx10 Bandwidth Sweep

| Bandwidth | gem5 mode | Write | Read | Status |
|---:|---|---:|---:|---|
| 50 MBps | default sweep | 99.4% | 90.4% | read under-runs without gap |
| 50 MBps | direct gap1 | 99.8% | 95.5% | pass aggregate |
| 200 MBps | direct gap1 | 99.9% | 95.5% | pass aggregate |
| 800 MBps | direct gap1 | 99.6% | 95.5% | pass aggregate |
| 1200 MBps | default sweep | 99.1% | 89.4% | read under-runs without gap |
| 1200 MBps | direct gap1 | 99.2% | 96.3% | pass aggregate |
| 1600 MBps | default sweep | 98.7% | 78.0% | fail read |
| 1600 MBps | direct gap1 | 99.5% | 75.9% | fail read |
| max/saturated tx10 | default sweep | n/a | n/a | gem5 aborts before stats |

Soft cap conclusion: 4-to-1 512B tx10 is currently usable through **1200 MBps**
for aggregate latency validation with the current structural model path
(automatic NSU multi-read-response-VC pacing plus default packetized NMU
read-request chunks). The direct `gap1` rows are retained as historical
evidence, not as the desired final run mode.

### Other 512B Rows

| Row | gem5 mode | Write | Read | Status |
|---|---|---:|---:|---|
| `size512_tx2_same_base` | default packetized read requests | close | exact src3 read after CDC | clean targeted fix |
| `size512_tx10_same_base` | default packetized read requests | close | src3 read +1.6 cycles after CDC | clean targeted fix |
| `4to1_std_tx50` | direct gap1 | 100.0% | 94.5% | close, read just below 95 |
| `4to1_low_tx10` | direct gap1 | 99.9% | 95.5% | pass aggregate |
| `4to1_low_tx10` | default packetized read requests, staggered-base spread | close | read error -6.2..+4.9 cycles after CDC | pass targeted wider check |
| `4to1_std_tx50` | default packetized read requests, staggered-base spread | close | read error -22.24..+19.12 cycles after CDC | mixed; not final baseline |
| `2to1_std_tx10` | default sweep | 97.8% | 94.9% | near miss |
| `2to1_std_tx10` | default packetized read requests, staggered-base spread | close | read error -2.7..0.0 cycles after CDC | pass targeted wider check |
| `2to1_std_tx10` | automatic long-read/four-source pacing guard | 97.3% | 94.7% | near miss; confirms auto rule does not reproduce bad global gap1 |
| `2to1_std_tx10` | direct gap1 | 97.4% | 82.1% | gap1 is wrong for 2-to-1 |
| `4to1_sat_tx10` | default sweep | n/a | n/a | gem5 aborts at tick 943000 |
| `4to1_sat_tx10` | default packetized read requests, staggered-base spread | n/a | n/a | gem5 aborts at tick 519000 |
| `2to1_sat_tx10` | default sweep | n/a | n/a | gem5 aborts at tick 900000 |
| `2to1_sat_tx10` | default packetized read requests, staggered-base spread | close BW | read +148.9..+185.9 cycles after CDC | saturated latency still bad |

### Size Variants

| Row | gem5 mode | Write | Read | Status |
|---|---|---:|---:|---|
| `size32_tx10` | default sweep | 98.7% | 92.0% | fail read aggregate; src3 read too slow |
| `size32_tx10` | sub-256 arrival-order patch | 98.9% | 98.2% | pass aggregate |
| `size64_tx10` | default sweep | 98.3% | 93.0% | fail read aggregate; src3 read too slow |
| `size64_tx10` | sub-256 arrival-order patch | 98.4% | 98.3% | pass aggregate |
| `size128_tx10` | default sweep | 97.3% | 86.4% | fail read; src3 read is much too slow |
| `size128_tx10` | sub-256 arrival-order patch | 98.2% | 97.9% | pass aggregate |
| `4to1_std_256B_tx10` | default sweep after original-size metadata | 99.9% | 97.7% | pass aggregate |
| `size256_tx10` | default size probe | 99.8% | 98.8% | pass aggregate |
| `size256_tx10` | sub-256 arrival-order patch | 99.4% | 97.5% | pass aggregate |
| `4to1_std_256B_tx10` | direct gap1 | n/a | 90.0% | gap1 hurts |
| `size512_tx10` | default size probe | 99.2% | 91.1% | read under-runs without gap1 |
| `size512_tx10` | sub-256 arrival-order patch, default gap | 99.4% | 90.8% | unchanged known default-gap miss |
| `size512_tx10` | automatic long-read/four-source pacing | 97.2% | 95.3% | pass aggregate; replaces manual gap1 for this row |
| `4to1_std_512B_tx10` | direct gap1 | 99.6% | 95.5% | pass aggregate |
| `size1024_tx10` | default size probe | n/a | n/a | Vivado passed; gem5 aborted at tick 591000 |

## Known Failures and Open Issues

### 1. 1600 MBps Read Divergence

At 1600 MBps, write latency remains accurate but read latency diverges badly.
The issue is source-specific and read-side:

- src0 read becomes much too slow.
- src2 read becomes much too slow.
- gap1 does not help and slightly worsens aggregate read accuracy.

This is the main reason for the 1200 MBps soft cap.

Latest diagnostic evidence:

- A `record-mode=1` trace of default 1600 MBps reproduced the scalar failure:
  src0/src2 read latency stayed very high while src1 remained near Vivado.
- Endpoint CSVs show same-source read pairs issued almost back-to-back at high
  bandwidth, for example src0 starts reads at cycles `651` and `652`; one
  completes quickly and the other waits an additional service rotation.
- NSU read-drain CSV shows no busy drops. The delay is queue/admission shape:
  the second same-source read is valid in gem5 much earlier than the Vivado
  average latency implies.
- Setting `tg_*.max_outstanding_reads=1` is diagnostic, not yet a fix, but it
  removes the catastrophic buildup while preserving bandwidth: aggregate read
  accuracy improves from about `78%` to `91.5%` at 1600 MBps.
- Combining `max_outstanding_reads=1` with the existing 512B per-flit gap1
  diagnostic reaches aggregate `99.1%` write / `98.4%` read latency accuracy
  and about `97.9%` read bandwidth accuracy at 1600 MBps.

Current lead: the 1600 MBps miss appears to be the combination of two effects:

- gem5 over-admits AXI reads for this capped high-bandwidth traffic pattern
  relative to the Vivado reference;
- after admission is constrained, the residual miss is the already-known 512B
  read response pacing issue that gap1 compensates for.

Next validation question: determine whether Vivado's traffic generator is
implicitly enforcing one outstanding read in this row, or whether Naviq's AXI
read-admission/AR-ready model is accepting new reads too eagerly.

### 2. Saturated Rows Abort in gem5

The saturated tx10 rows tested so far abort before stats:

- `4to1_sat_tx10`: `MessageBuffer::enqueue` max-size assertion at tick 943000.
- `2to1_sat_tx10`: same assertion at tick 900000.
- `size1024_tx10`: same assertion at tick 591000.

Vivado passes these rows. They should not be counted as latency mismatches yet;
they are simulator capacity/assertion failures.

### 2a. Small-Size Read-Side Shape Mismatch

The new 32/64/128B rows complete in gem5, but aggregate read accuracy is below
95%. The common outlier is src3 read, which is too slow in gem5:

- `size32_tx10`: src3 read `198` vs `235.6`, aggregate R `92.0%`.
- `size64_tx10`: src3 read `204` vs `236.9`, aggregate R `93.0%`.
- `size128_tx10`: src3 read `222` vs `322.9`, aggregate R `86.4%`.

The 256B row recovers, so this looks like a sub-256B size-dependent
read-order/response-drain problem rather than the same 512B chunk-coalescing
issue.

Status: fixed by the sub-256B arrival-order patch. The historical failure
details below are retained because they explain the fix.

Latest trace evidence for `size128_tx10`:

- Artifact directory:
  `noc_testing/artifacts/generated/diagnostics/size128_read_shape_trace/`.
- The request-side NPS trace shows both early src3 read requests reached the
  NSU before cycle 320.
- The NSU read-drain trace services only one src3 response in the first wave
  (`select` at cycle 339/344), then defers the next src3 response until cycle
  444/450.
- Other sources in the same startup wave receive two early responses before
  the read-group order locks; src3 is the fourth discovered source and gets cut
  over to the canonical order after only one early response.

That strongly localizes the 128B issue to NSU read-request group ordering at
the transition from discovery order to locked canonical order. It is not a
network-return-path delay: the request arrived on time, and the return latency
after NSU injection is in the expected range.

Rejected first-order hypothesis:

- A temporary patch allowed the source that completed discovery to drain one
  additional same-source group before advancing to the canonical order.
- Result: src3 improved from roughly `322.9` cycles to `231.6`, and all 10
  src3 reads completed, but src1 regressed from roughly `190.2` to `233.7`.
- The patch was not retained. It proves the transfer boundary is important, but a
  simple same-source continuation rule only moves the unfairness.

Follow-up fix:

- Remove canonical source-order learning entirely.
- This keeps all read groups in the order they become available at the NSU,
  avoiding discovery-to-canonical transition artifacts and avoiding a global
  round-robin policy that is not required by AXI-MM.
- Validation used gem5-only reruns against the existing Vivado references and
  existing Vivado-generated topology tags.

### 3. Per-Source Accuracy Still Has Weak Spots

Even when aggregate accuracy passes, per-source read accuracy may not. The most
common weak source is src0 read. If the acceptance criterion changes from
aggregate latency to every source/channel >= 95%, more work is needed.

### 4. Canonical Read Order Was Removed

The 4-source canonical order of `1,3,2,0` was historical validation evidence
from one spread-placement endpoint wave. It is no longer implemented as an NSU
policy. The NSU now uses first-ready queued read-group flushing; source order
should come from upstream network arbitration and endpoint readiness.

### 5. Manual Gap/Pacing Knobs Are Diagnostic

The sweep path now has explicit fields for manual NSU read-response pacing
diagnostics:

- `nsu_read_response_gap_cycles`
- `nsu_read_response_per_flit_gap_cycles`
- `nsu_read_response_half_rate`

Use these fields only in scratch/debug plans. Final validation plans should not
set them; structural simulator logic should choose the pacing from route/VC
state. The locked-plan validator rejects nonzero manual pacing fields by
default.

## Important Artifacts

| Artifact | Contents |
|---|---|
| `noc_testing/artifacts/generated/diagnostics/nsu_read_canonical_order_probe/` | Historical 512B validation probe that showed the canonical order patch was only a diagnostic aid |
| `noc_testing/artifacts/generated/results/gem5_vivado_naviq_incast_suite_incast_256B_origsize_fix.csv` | 256B sweep after original-size metadata fix |
| `noc_testing/artifacts/generated/diagnostics/incast_512B_origsize_wave_topo_perflit_gap1/` | 512B tx10 direct gap1 validation |
| `noc_testing/artifacts/generated/diagnostics/incast_512B_bw50_tx10_gap1/` | 50 MBps tx10 direct gap1 run |
| `noc_testing/artifacts/generated/diagnostics/incast_512B_bw1200_tx10_gap1/` | 1200 MBps tx10 direct gap1 run |
| `noc_testing/artifacts/generated/diagnostics/incast_512B_bw1600_tx10_gap1/` | 1600 MBps tx10 direct gap1 run |
| `noc_testing/artifacts/generated/diagnostics/incast_512B_bw1600_default_trace/` | 1600 MBps default trace plus OR=1 and OR=1+gap1 diagnostic logs |
| `noc_testing/artifacts/generated/results/vivado_results_vivado_naviq_4to1_incast_size_probe_incast_size_probe_tx10_800.csv` | Fresh Vivado size sweep reference for 128/256/512/1024B tx10 at 800 MBps |
| `noc_testing/artifacts/generated/results/gem5_vivado_naviq_4to1_incast_size_probe_incast_size_probe_tx10_800.csv` | Default gem5 size sweep result; 1024B row has return code -6 |
| `noc_testing/artifacts/generated/results/vivado_results_vivado_naviq_4to1_incast_small_size_probe_incast_small_size_probe_tx10_800.csv` | Fresh Vivado small-size reference for 32/64B tx10 at 800 MBps |
| `noc_testing/artifacts/generated/results/gem5_vivado_naviq_4to1_incast_small_size_probe_incast_small_size_probe_tx10_800.csv` | Default gem5 small-size sweep result |
| `noc_testing/artifacts/generated/results/gem5_vivado_naviq_4to1_incast_small_size_probe_incast_small_size_probe_tx10_800_sub256_fifo.csv` | 32/64B gem5-only validation after sub-256B arrival-order patch |
| `noc_testing/artifacts/generated/results/gem5_vivado_naviq_4to1_incast_size_probe_incast_size128_tx10_800_sub256_fifo.csv` | 128B gem5-only validation after sub-256B arrival-order patch |
| `noc_testing/artifacts/generated/results/gem5_vivado_naviq_4to1_incast_size_probe_incast_size256_tx10_800_sub256_fifo.csv` | 256B regression after sub-256B arrival-order patch |
| `noc_testing/artifacts/generated/results/gem5_vivado_naviq_4to1_incast_size_probe_incast_size512_tx10_800_sub256_fifo.csv` | 512B default-gap regression after sub-256B arrival-order patch |
| `noc_testing/artifacts/generated/simlogs/simlogs_incast_512B_cov_4to1_sat_tx10/gem5_4to1_sat_tx10.log` | 4-to-1 saturated assertion failure |
| `noc_testing/artifacts/generated/simlogs/simlogs_incast_512B_cov_2to1_sat_tx10/gem5_2to1_sat_tx10.log` | 2-to-1 saturated assertion failure |
| `noc_testing/artifacts/generated/simlogs/simlogs_incast_size_probe_tx10_800/gem5_size1024_tx10.log` | 1024B size-probe assertion failure |

## Reproduction Notes

### Placement Baseline Change

On 2026-06-30, the 4-to-1 incast validation sweep plans were switched from
`4nmu_to_1nsu_incast_spread.place.json` to
`4nmu_to_1nsu_incast_compact.place.json` to make Vivado waveform inspection
easier. The compact placement is:

| Endpoint | Site |
|---|---|
| `tg_0.m_axi` | `NOC_NMU512_X0Y0` |
| `tg_1.m_axi` | `NOC_NMU512_X0Y1` |
| `tg_2.m_axi` | `NOC_NMU512_X0Y2` |
| `tg_3.m_axi` | `NOC_NMU512_X0Y3` |
| `bram_0.s_axi` | `NOC_NSU512_X0Y0` |

Old spread-placement Vivado references should not be mixed with new
compact-placement gem5 runs. Re-run at least the compact 512B tx10 anchor in
Vivado and gem5 before using the compact-placement results as a replacement
baseline.

### Compact 512B Tx1 Anchor

Command:

```sh
RUN_TAG=incast_compact_4to1_512B_tx1 timeout 3600 python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_comprehensive.csv \
  --mode vivado_then_gem5 --topo-gen vivado --row 1
```

Exit status: 0.

Artifacts:

| Artifact | Contents |
|---|---|
| `noc_testing/artifacts/generated/results/vivado_results_vivado_naviq_4to1_incast_comprehensive_20260630_130147.csv` | compact Vivado tx1 reference |
| `noc_testing/artifacts/generated/results/gem5_vivado_naviq_4to1_incast_comprehensive_20260630_130147.csv` | compact gem5 tx1 result |
| `noc_testing/artifacts/simlogs/simlogs_20260630_130147/Vivado_interleaved_tx1.log` | Vivado tx1 log |
| `noc_testing/artifacts/generated/simlogs/simlogs_20260630_130147/gem5_interleaved_tx1.log` | gem5 tx1 log |
| `noc_testing/artifacts/noc_desc/20260630_130147/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_compact/noc_subsystem.ncr` | generated compact NCR |
| `noc_testing/artifacts/noc_desc/20260630_130147/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_compact/noc_subsystem.nts` | generated compact NTS |

Results:

| Source | Vivado W | gem5 W | W accuracy | Vivado R | gem5 R | R accuracy |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 164 | 165 | 99.4% | 107 | 163 | 47.7% |
| 1 | 183 | 184 | 99.5% | 130 | 209 | 39.2% |
| 2 | 116 | 117 | 99.1% | 79 | 99 | 74.7% |
| 3 | 153 | 150 | 98.0% | 84 | 117 | 60.7% |

Mean write accuracy was 99.0%. Mean read accuracy was 55.6%.
Vivado and gem5 both ranked read latency by source as `2,3,0,1`, so the old
spread-placement `1,3,2,0` read-order observation does not carry over to this
compact tx1 anchor.

### Compact 512B Tx1 With Copied NCR

Command:

```sh
CUSTOM_NCR_FILE=/home/lukasez2/noc/noc_testing/artifacts/noc_desc/20260630_134343/other_nts_ncs/noc_subsystem.ncr \
RUN_TAG=incast_compact_tx1_other_ncr_vivado \
timeout 1800 vivado -mode batch -source noc_testing/main.tcl \
  -tclargs csv_row noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_comprehensive.csv 1 \
  noc_testing/artifacts/generated/results/vivado_results_incast_compact_tx1_other_ncr_vivado.csv
```

Exit status: 0.

Artifacts:

| Artifact | Contents |
|---|---|
| `noc_testing/artifacts/generated/results/vivado_results_incast_compact_tx1_other_ncr_vivado.csv` | Vivado tx1 result after reading copied NCR |
| `noc_testing/artifacts/simlogs/simlogs_incast_compact_tx1_other_ncr_vivado/Vivado_interleaved_tx1.log` | Vivado tx1 log |
| `noc_testing/artifacts/noc_desc/incast_compact_tx1_other_ncr_vivado/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_compact/noc_subsystem.ncr` | emitted NCR after run |
| `noc_testing/artifacts/noc_desc/incast_compact_tx1_other_ncr_vivado/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_compact/noc_subsystem.nts` | emitted NTS after run |

The run log confirmed `read_noc_solution` consumed the copied NCR, but the
emitted NCR hash was identical to the local compact-generated NCR rather than
the copied NCR. The latencies also matched the local compact anchor exactly:

| Source | Vivado W | Vivado R |
|---|---:|---:|
| 0 | 164 | 107 |
| 1 | 183 | 130 |
| 2 | 116 | 79 |
| 3 | 153 | 84 |

This means the current Vivado Tcl path is not enough to force simulation of the
copied physical route. It accepts the copied NCR as an incremental solution but
normalizes or re-routes back to the local solution before simulation.

Follow-up with all copied-NCR `PathLocked` fields set to `true`:

```sh
CUSTOM_NCR_FILE=/home/lukasez2/noc/noc_testing/artifacts/noc_desc/20260630_134343/other_nts_ncs_locked/noc_subsystem.ncr \
RUN_TAG=incast_compact_tx1_other_ncr_locked_vivado \
timeout 1800 vivado -mode batch -source noc_testing/main.tcl \
  -tclargs csv_row noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_comprehensive.csv 1 \
  noc_testing/artifacts/generated/results/vivado_results_incast_compact_tx1_other_ncr_locked_vivado.csv
```

Exit status: 0, but the simulation failed before any useful latency data. The
first real error was:

```text
time 1665 ns  NOC Packet Switch is unable to route the packet.
Cross check the AXI AW Address 'h20100000000 to the address editor and the NOC
transactions from NMU with Master ID = 'd256
```

The locked NCR changed the Vivado solution checksum after `read_noc_solution`,
but the route was not self-consistent for this locally generated BD/addressing
context. The emitted NCR under the run artifact still matched the local compact
NCR and had `PathLocked: false`, so this locked-NCR attempt is evidence that
the copied route cannot be replayed naively in this project state.

The most direct mismatch is on the VC encoding. In the failed locked-NCR run,
the first write packet reached `nps_0` with `VC = 'h1`, `src = 'h100`, and
`dst = 'h140`, then the packet switch reported that it could not route the
packet. The copied locked NCR expects the `S00_AXI_nmu` write path to use
VC 5, while the local compact NCR expects VC 1 for that same write path. The
local generated NMU/simulation wrapper therefore injects the write on VC 1, but
the locked copied route programs the path as VC 5. That explains the immediate
route failure before PMON latency data is available.

Follow-up with the copied physical routes kept locked, but with each
`(source NMU, traffic class)` VC changed to match the local Vivado compact NCR:

```sh
CUSTOM_NCR_FILE=/home/lukasez2/noc/noc_testing/artifacts/noc_desc/20260630_134343/other_nts_ncs_locked_local_vc/noc_subsystem.ncr \
RUN_TAG=incast_compact_tx1_other_route_local_vc_vivado \
timeout 1800 vivado -mode batch -source noc_testing/main.tcl \
  -tclargs csv_row noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_comprehensive.csv 1 \
  noc_testing/artifacts/generated/results/vivado_results_incast_compact_tx1_other_route_local_vc_vivado.csv
```

Exit status: 0. XSim passed all sources.

VC substitutions applied to the copied locked NCR:

| Source path | Traffic class | Copied VC | Local Vivado VC |
|---|---|---:|---:|
| `S00_AXI_nmu` | `READ_REQ` | 0 | 4 |
| `S00_AXI_nmu` | `WRITE` | 5 | 1 |
| `S01_AXI_nmu` | `READ_REQ` | 0 | 4 |
| `S01_AXI_nmu` | `WRITE` | 5 | 1 |
| `S02_AXI_nmu` | `READ_REQ` | 0 | 4 |
| `S02_AXI_nmu` | `WRITE_RESP` | 7 | 3 |
| `S03_AXI_nmu` | `READ_REQ` | 0 | 4 |
| `S03_AXI_nmu` | `WRITE` | 5 | 1 |

Artifacts:

| Artifact | Contents |
|---|---|
| `noc_testing/artifacts/noc_desc/20260630_134343/other_nts_ncs_locked_local_vc/noc_subsystem.ncr` | copied physical routes, locked, with local Vivado VC assignment |
| `noc_testing/artifacts/generated/results/vivado_results_incast_compact_tx1_other_route_local_vc_vivado.csv` | Vivado tx1 PMON result for the hybrid route/VC solution |
| `noc_testing/artifacts/simlogs/simlogs_incast_compact_tx1_other_route_local_vc_vivado/Vivado_interleaved_tx1.log` | XSim log showing all four sources passed |

Results:

| Source | Vivado W | Vivado R |
|---|---:|---:|
| 0 | 129 | 101 |
| 1 | 168 | 104 |
| 2 | 116 | 78 |
| 3 | 189 | 127 |

This does not reproduce the other machine's exact PMON values, but it does
prove the locked copied route can be simulated locally when its VC assignments
are made consistent with the locally generated Vivado solution. The likely
model is that a replayed `.ncr` needs both the route nodes and the VC numbers to
match the NMU/NSU/simulation-context solution; locking paths while carrying
foreign VC numbers can program a route the locally generated traffic cannot
enter.

Tooling notes from Vivado 2025.2:

- `read_noc_solution` reads an `.ncr` solution and, unless `-no_update` is used,
  runs the NoC compiler after import.
- `write_noc_solution` is the supported Tcl path for exporting an `.ncr`.
- `get_noc_net_routes -of_objects [get_noc_logical_paths]` exposes
  `noc_net_route` objects. These objects report `CHANNELS`, `LOCK`,
  `REQUIRED_BANDWIDTH`, `ACHIEVED_BANDWIDTH`, and `VIRTUAL_CHANNEL`.
- `LOCK` is writable and is what the current harness sets for every route.
- `VIRTUAL_CHANNEL` is observable but read-only:

```text
ERROR: [Common 17-107] Cannot change read-only property 'VIRTUAL_CHANNEL'.
```

So VC is adjustable in the sense that it is serialized in the `.ncr` solution
and can be replayed if the solution is self-consistent, but it does not appear
to be an ordinary mutable Tcl property on a route object. The supported knobs
above that level are QoS/traffic-spec properties and `run_noc_compiler`; those
feed the NoC compiler, which then chooses routes and VCs. Direct NCR editing
remains a useful diagnostic, but a production harness should prefer
generating/importing a coherent Vivado solution rather than trying to patch VC
independently after compilation.

### Compact 512B Tx1 With In-House Topology Generator

The comprehensive CSV row has `topo_gen=vivado`, so a temporary one-row CSV was
created with only `topo_gen` changed to `in_house`:

```text
/tmp/vivado_naviq_4to1_incast_comprehensive_row1_inhouse.csv
```

Running the in-house generator with system Python failed because `networkx` was
missing:

```sh
timeout 300 python3 noc_testing/noc_sweep.py \
  --plan /tmp/vivado_naviq_4to1_incast_comprehensive_row1_inhouse.csv \
  --mode topology_only --topo-gen in_house --row 1 \
  --run-tag incast_compact_tx1_inhouse_topology_check
```

Exit status: 1. First error:

```text
ModuleNotFoundError: No module named 'networkx'
```

Using the project venv succeeded:

```sh
timeout 300 .venv/bin/python noc_testing/noc_sweep.py \
  --plan /tmp/vivado_naviq_4to1_incast_comprehensive_row1_inhouse.csv \
  --mode topology_only --topo-gen in_house --row 1 \
  --run-tag incast_compact_tx1_inhouse_topology_check
```

Exit status: 0. Artifacts:

| Artifact | Contents |
|---|---|
| `noc_testing/artifacts/noc_desc/incast_compact_tx1_inhouse_topology_check/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_compact/noc_subsystem.ncr` | in-house generated locked NCR |
| `noc_testing/artifacts/noc_desc/incast_compact_tx1_inhouse_topology_check/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_compact/noc_subsystem.nts` | in-house generated NTS |

Vivado replay using the in-house route:

```sh
timeout 1800 .venv/bin/python noc_testing/noc_sweep.py \
  --plan /tmp/vivado_naviq_4to1_incast_comprehensive_row1_inhouse.csv \
  --mode vivado_only --topo-gen in_house --row 1 \
  --run-tag incast_compact_tx1_inhouse_vivado
```

Exit status: 0, but the simulation failed before useful latency data. First
real error:

```text
time 1665 ns  NOC Packet Switch is unable to route the packet.
Cross check the AXI AW Address 'h20100000000 to the address editor and the NOC
transactions from NMU with Master ID = 'd64
```

Artifacts:

| Artifact | Contents |
|---|---|
| `noc_testing/artifacts/generated/results/vivado_results_vivado_naviq_4to1_incast_comprehensive_row1_inhouse_incast_compact_tx1_inhouse_vivado.csv` | PMON CSV with blank latencies because the run failed |
| `noc_testing/artifacts/simlogs/simlogs_incast_compact_tx1_inhouse_vivado/Vivado_interleaved_tx1.log` | Vivado/XSim failure log |
| `noc_testing/artifacts/noc_desc/incast_compact_tx1_inhouse_vivado/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_compact/noc_subsystem.ncr` | emitted descriptor, normalized back to local Vivado NCR |
| `noc_testing/artifacts/noc_desc/incast_compact_tx1_inhouse_vivado/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_compact/noc_subsystem.nts` | emitted descriptor, normalized back to local Vivado NTS |

The in-house NTS differs from Vivado's NTS. Most notably, the in-house NSU
`SysAddresses` base is `0x00000000`, while the Vivado-generated compact NTS
uses `0x20100000000`; the failing write address is `0x20100000000`. The
in-house NCR is also a much smaller locked solution (`312` components versus
Vivado's `784`) and assigns different VCs for several read/response paths.
Conclusion: the in-house generator can emit artifacts for the row, but those
artifacts are not currently valid for replay through the Vivado/XSim flow for
this AXI-MM compact incast case.

Fresh Vivado + default gem5 runs:

```sh
timeout 3600 python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_bw_probe.csv \
  --mode vivado_then_gem5 --topo-gen vivado \
  --row 1 --run-tag incast_512B_bw1200_tx10

timeout 3600 python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_bw_probe.csv \
  --mode vivado_then_gem5 --topo-gen vivado \
  --row 2 --run-tag incast_512B_bw1600_tx10
```

For manual gap/pacing diagnostics, prefer an explicit scratch CSV row using the
`nsu_read_response_gap_cycles`, `nsu_read_response_per_flit_gap_cycles`, or
`nsu_read_response_half_rate` fields. If reproducing one of the older direct
gem5-only runs, use the full command line stored at the top of the corresponding
gem5 log and add:

```sh
--nsu-read-response-per-flit-gap-cycles 1
```

Do not use manual pacing fields in final-baseline plans unless the experiment is
explicitly studying that override; the final input validator rejects them by
default.

Keep simulator runs bounded with `timeout`.

## Update Policy

When a fix or new test changes the state:

1. Add the command, exit status, and artifact paths.
2. Add aggregate write/read accuracy and call out per-source failures.
3. Move a failure out of "Known Failures" only after it is validated against
   fresh Vivado or a clearly identified existing Vivado reference.
4. If the 1200 MBps soft cap changes, update the "Current Validation Envelope"
   section first.

## Parked Vivado Route Replay Issue

On 2026-06-30, the copied locked compact NCR could be loaded manually in Vivado
with `read_noc_solution`, and Vivado reported the imported route objects as
locked while preserving the copied VC numbers. That manual acceptance does not
mean the same route/VC assignment is coherent with the locally generated XSim
traffic model.

Batch XSim replay of
`noc_testing/artifacts/noc_desc/20260630_134343/other_nts_ncs_locked/noc_subsystem.ncr`
still failed immediately in the packet switch. The first write packet reached
`nps_0` at `1665 ns` with `VC = 'h1`, `src = 'h100`, `dst = 'h140`, and
`aaddr = 'h20100000000`, while that copied locked NCR programs the S00 write
path as VC 5. The local 2025.2-generated compact solution instead uses VC 1 for
that write path, and the copied-route/local-VC hybrid passed XSim.

Current interpretation: this is a Vivado route-replay/topology-import issue to
park, not a Naviq model issue. Replaying foreign NCRs likely needs both the
physical routes and the VC assignment to match the local Vivado-generated NMU
programming. Do not use the failed copied-old-VC replay as a Naviq-vs-Vivado
latency reference.
