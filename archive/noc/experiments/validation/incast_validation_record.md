# Historical Validation Record: Naviq vs Vivado Multi-Source Incast

> **Archived record (2026-08-16).** This dated engineering record is retained
> for investigation history. It is not a maintained validation guide; use
> `noc_testing/experiments/validation/README.md` for supported workflows.

**Last updated:** 2026-07-06
**Goal:** Match Versal NoC (Vivado RTL) on **min / max / avg latency** for 2-to-1 and
4-to-1 AXI-MM incast. Target ~95%. 1-to-1 tests already pass.

**Related historical records:**

| Doc | Role |
|---|---|
| `README.md` | Archive index |
| `incast_validation_record.md` | This dated validation record |
| `incast_validation_findings.md` | Historical deep-dive on model changes, results, and open failures |

---

## Validation TG Timing Rule

For Vivado-vs-gem5 latency validation sweeps, keep AXI-MM traffic-generator
timing deterministic unless the specific experiment is about TG randomness:

- Set `param.tg_N.gap_distribution=FIXED`.
- Set `param.tg_N.min_gap_cycles=0` and `param.tg_N.max_gap_cycles=0`.
- Set a nonzero fixed `param.tg_N.seed` for each TG.

The default `AxiRandomTrafficGenerator` behavior uses `seed=0` as a
time-based seed and `gap_distribution=UNIFORM` with `max_gap_cycles=10`. In
the compact 4-to-1 512B tx1 incast anchor, that random initial/inter-command
gap changes which source completes its write first. Because interleaved reads
are issued after write completion, the seed indirectly changes AR issue order
and therefore which source receives the fast vs slow read-response slot. With
fixed zero gaps, the compact anchor is stable and matches the observed Vivado
service ordering.

Use the generic sweep CSV escape hatch for these controls:
`param.<component>.<param>`, for example `param.tg_0.gap_distribution`.

## Validation TG Address Rule

For fixed-size AXI-MM latency sweeps, keep gem5 and Vivado on the same address
sequence:

- Conn-json master `base_address`/`high_address` ranges must be honored by both
  Vivado and gem5.
- gem5 clips each master's `nsu_min_addrs`/`nsu_address_spaces` to the
  configured master range; do not only check the visible `base_addr` param.
- Fixed-size rows should step by `transaction_bytes`, not `beat_bytes`.
- For final 4-to-1 incast latency sweeps, use the same-base connection file
  `topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm_same_base.conn.json`.
  The staggered-base file is useful for waveform/debug address separation only.

This matters for 512B buildup rows. A 64B step makes later 512B transactions
overlap and straddle 256B NPP boundaries, which creates a latency artifact that
is not the Vivado traffic pattern.

The staggered-base corrected-address probes confirm that gem5 can honor
per-source master windows (`tg_0=+0x0`, `tg_1=+0x200`, `tg_2=+0x400`,
`tg_3=+0x600`) and advance fixed 512B transactions by `0x200`. Those staggered
bases were for waveform readability, not the final validation baseline.

## NSU Read Response Pacing Rule

Treat the NSU read-response `gap1` behavior as structural, not as a row-level
sweep knob. Current waveform evidence suggests the NSU emits read data at
half-rate when it has to return read responses on multiple physical VCs, such
as one source using READ VC 2 and another using READ VC 6. If all read-response
paths from that NSU use the same VC, keep the normal 4-flit/16-flit gap
behavior.

The current model implements this through the route-to-VC map: if an NSU has
AXI-MM read-response routes on more than one VC, its read response drain uses a
one-cycle per-flit gap. Anchor checks:

- Corner 2-to-1, READ VCs `2/6`: gem5 `166/118` read cycles vs Vivado
  `159/116`; after the diagnostic two-cycle CDC view, `+5/+0`.
- Compact-y3 2-to-1, READ VCs `6/6`: gem5 `70/93` read cycles vs Vivado
  `68/91`; after the diagnostic two-cycle CDC view, exact match.

## Executive summary

| Area | Current state |
|---|---|
| 1-to-1 latency | Still expected to be excellent from the older latency-modeling work; revalidate before using as final evidence. |
| Final input contract | Locked for current 4-to-1 512B checks: same-base TG windows, fixed zero TG gaps, fixed nonzero seeds, transaction-sized address increments, and no row-level NSU pacing overrides. |
| 4-to-1 512B capped latency | Best current family matches aggregate latency well up to the 1200 MBps soft validation cap. Per-source read accuracy still has weak spots. |
| NSU read-response pacing | Structural rule under test: multi-read-response-VC NSUs use one-flit-every-other-cycle pacing; same-VC cases keep normal 4-flit/16-flit gap behavior. |
| Read response ordering | The old hardcoded canonical source order is removed. Read groups flush in first-ready queue order; upstream arbitration and endpoint readiness should determine source order. |
| Address generation | gem5 now clips TG target windows to conn-json master ranges and uses transaction-sized address steps for fixed-size rows. Staggered bases are debug-only, not final baselines. |
| Remaining model issue | The contiguous-read/read-tracker grouping behavior is still relevant to the current src3 latency mismatch and is intentionally left for later model work. |

---

## Historical investigation priorities (priority order)

1. **Validate the locked smoke inputs** before using a 4-to-1 512B result as
   final-baseline evidence:
   ```sh
   python3 noc_testing/experiments/validation/validate_latency_inputs.py \
     noc_testing/sweep_plans/validation/4to1_512_same_base_fixed_inputs_smoke.csv
   ```

2. **Run the locked 4-to-1 512B smoke rows** with Vivado-made topology and compare
   tx1/tx2/tx10 against the known Vivado references or freshly generated Vivado
   outputs.

3. **Keep manual diagnostic knobs out of final plans.** Row-level
   `nsu_read_response_half_rate`,
   `nsu_read_response_per_flit_gap_cycles`, staggered TG bases, and forced
   outstanding-read limits should stay in scratch plans unless the experiment is
   explicitly about those knobs.

4. **Continue the contiguous-read investigation** only after the final inputs are
   stable. The current evidence points to tile-request/read-tracker grouping as
   the remaining source of src3 latency mismatch, not address propagation or
   source relabeling.

5. **Older trace-smoke path** if the broader trace workflow needs to be resumed:
   ```sh
   python3 noc_testing/noc_sweep.py \
     --plan noc_testing/sweep_plans/validation/vivado_naviq_incast_trace_smoke.csv \
     --mode gem5_only --topo-gen vivado \
     --reuse-tag incast_suite --run-tag trace_smoke --row 1
   ```

Do not chase source-index relabeling; prior checks verified that mapping is not
the root issue.

---

## Canonical test suite (`incast_suite`)

**Plan (9 rows):** `sweep_plans/validation/vivado_naviq_incast_suite.csv`  
All rows: `max_outstanding_writes=16`, `topo_gen=vivado`, 512-bit, 1 GHz.

| name | load | notes |
|---|---|---|
| `4to1_std_tx10` | 800 MBps, tx10 | Strong (~92–97% lat); good trace target for capped ordering |
| `4to1_std_tx50` | 800 MBps, tx50 | Solid |
| `4to1_low_tx10` | 200 MBps | Rate-limited |
| `4to1_sat_tx5` | uncapped, tx5 | Saturated |
| `4to1_sat_tx10` | uncapped, tx10 | Weak reads (~45% read lat); trace target for read tails |
| `4to1_std_256B_tx10` | 800 MBps | Shape variant |
| `4to1_std_1024B_tx10` | 800 MBps | Write ~80% |
| `2to1_std_tx10` | 800 MBps | Strong |
| `2to1_sat_tx10` | uncapped | Saturated 2-to-1 |

Dropped from suite: `4to1_sat_tx50` (queue blow-up; exclude from proof).

**Full Vivado + gem5 run:**
```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_incast_suite.csv \
  --mode vivado_then_gem5 --topo-gen vivado --run-tag incast_suite
```

**Gem5-only rerun** (reuse Vivado topology):
```sh
python3 noc_testing/noc_sweep.py \
  --plan noc_testing/sweep_plans/validation/vivado_naviq_incast_suite.csv \
  --mode gem5_only --topo-gen vivado \
  --reuse-tag incast_suite --run-tag <new_tag>
```

---

## Key result files

Under `noc_testing/artifacts/generated/results/`:

| File | Contents |
|---|---|
| `gem5_vivado_naviq_incast_suite_incast_suite.csv` | Latest gem5 incast_suite run |
| `vivado_results_vivado_naviq_incast_suite_incast_suite.csv` | Vivado reference (same tag) |
| `gem5_vivado_naviq_4to1_incast_comprehensive_proof_4to1.csv` | Full 4-to-1 comprehensive gem5 (depth 16) |
| `incast_accuracy_summary.md` | Aggregate accuracy report |
| `incast_accuracy_detail.csv` | Per-test/per-metric detail |
| `incast_match_check.csv` | Side-by-side match table (**may need regen** — often header-only) |

**Topology artifacts (reuse for gem5):**  
`artifacts/noc_desc/incast_suite/4nmu_to_1nsu_incast_aximm__4nmu_to_1nsu_incast_spread/`  
(`.ncr`, `.nts` — shared routes)

**Placement:** `topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_spread.place.json`  
NMUs at X0–X3 Y18; NSU at X1Y0. `tg_N` → `src_id` N → NMU X(N)Y18.

---

## Trace comparison (phased)

Detailed steps: `README.md` § Trace Comparison Plan.

| Phase | Plan file | Purpose |
|---|---|---|
| **0 smoke** | `vivado_naviq_incast_trace_smoke.csv` | 1 txn/source; verify trace plumbing |
| **1 targets** | `vivado_naviq_incast_trace_targets.csv` | Capped + saturated with `record_mode=2`, `hotspot_mode=both` |
| **2 Vivado** | (not implemented) | Waveform NPS extraction via TCL |
| **3 diff** | — | Align gem5 CSVs vs Vivado waveforms |

**Merge switches to inspect** (from `.ncr`):

- `NOC_NPS_VNOC_X1Y18` — X0/X1 merge
- `NOC_NPS7575_X5Y0` — X2 joins
- `NOC_NPS_VNOC_X1Y0` — final merge (X3 late path)

**gem5 trace outputs** (when enabled):

- Endpoint: `src/noc/testing/artifacts/graphs/nmu_*_AXIMM_{write,read}.csv`, `ready_valid.csv`
- Hotspot copy: `artifacts/generated/hotspot/<run-tag>/row_*`
- NPS queue: `nps_queue_trace.csv` — **may be missing** if binary lacks
  `NocGarnetNetwork.nps_queue_trace_*` params (seen on earlier smoke attempt)

**Trace docs:** `archive/noc/experiments/parameter_sweep/README.md`
(historical trace hooks), `noc_sweep.py --hotspot-mode`

---

## Analysis scripts (this folder)

```sh
cd naviq

# Side-by-side match CSV (comprehensive + 2to1 campaigns)
python3 noc_testing/experiments/validation/build_match_check.py

# Per-campaign markdown report (4-to-1)
python3 noc_testing/experiments/validation/vivado_naviq_4to1_incast/analyze_results.py \
  --vivado noc_testing/artifacts/generated/results/vivado_results_<...>.csv \
  --gem5 noc_testing/artifacts/generated/results/gem5_<...>.csv \
  --output noc_testing/artifacts/generated/results/<report>.md
```

`README.md` references `compare_accuracy.py` for comprehensive runs — if missing,
use `incast_accuracy_*.md/csv` in results or regenerate from suite CSVs.

---

## Code / config touchpoints (no sim changes yet)

| Location | Relevance |
|---|---|
| `noc_testing/noc_sweep.py` | `max_outstanding_writes` column → `build_v2_param_overrides`; `--hotspot-mode`, `--record-mode` |
| `src/noc/endpoints/generator/AXIMMTrafficGenerator.py` | Default `max_outstanding_writes=1` if plan omits column |
| `src/noc/lib/external/.../AxiRandomStrategy.cpp` | INTERLEAVED read-after-write behavior |
| `src/noc/monitors/NocTrafficMonitor.cc` | Latency stats / `record_mode` traces |
| `src/noc/core/network/NocSwitchAllocator.cc` | Token+LRU arbitration |
| `noc_testing/lib/noc_results.tcl` | Vivado result parsing (no waveform trace yet) |
| `archive/noc/experiments/latency_modeling/` | Historical 1-to-1 calibration notes (ILA waveforms) |

**Sweep driver behavior:** `topo_gen=vivado` → Vivado builds/routes NoC, exports
`.ncr/.nts`; gem5 reads them via `--noc-topology` (same routes, not re-routed).

---

## Accuracy snapshot (`incast_suite`, depth 16)

Rough guide — see `incast_accuracy_summary.md` for full tables.

| Subset | Write lat avg | Read lat avg | Bandwidth |
|---|---:|---:|---:|
| Core capped (excl. `sat*`) | ~87% | ~89% | ~97.5% |
| Rate-limited only | ~87% | ~90% | ~99.5% |
| `4to1_sat_tx10` | ~94% writes | ~45% reads | W 95%, R 76% |
| `4to1_sat_tx50` | broken | — | exclude |

**Strong rows:** `2to1_std_tx10`, `4to1_std_256B_tx10`, `4to1_std_tx50`, `4to1_std_tx10`.  
**Weak rows:** `4to1_sat_tx10` (reads), `4to1_std_1024B_tx10` (writes).

Under saturation, **min/max latency ~73%** — tails diverge, not just means.

---

## Dead ends (do not repeat)

1. **Source-index inversion / relabeling** — bandwidth fingerprint on uncapped
   `high_tx10` proves mapping is correct.
2. **`max_outstanding_reads` sweep** — depths 1/2/4/8/16 tested; capping reads
   made saturated cases worse.
3. **Treating `max_outstanding_writes=16` as the full fix** — helps uncapped;
   overall latency still ~86%; capped ordering unchanged at tx1.

---

## Campaign history (older runs)

| Campaign | Plan | Notes |
|---|---|---|
| 4-to-1 tx1–tx10 | `vivado_naviq_4to1_incast.csv` | Initial incast validation |
| diff_band | `vivado_naviq_4to1_incast_diff_band.csv` | low/med/high; uncapped smoking gun |
| comprehensive | `vivado_naviq_4to1_incast_comprehensive.csv` | 33 rows; outstanding depth sweep |
| 2-to-1 | `vivado_naviq_2to1_incast_latency.csv` | |
| 1-to-1 | `vivado_naviq_1to1_aximm_latency.csv` | sizing baseline |

Subfolder READMEs: `vivado_naviq_4to1_incast/`, `vivado_naviq_incast_scaling_latency/`.

---

## Open questions for trace work

1. At capped load, are gem5 merge-switch queues **empty** while Vivado still shows
   merge-dominated per-source ordering?
2. On `4to1_sat_tx10`, where do read responses queue — NSU, final NPS, or NMUs?
3. Does the ~12% residual offset come from **when** each tool starts/stops the latency
   timer (NMU issue vs first/last beat vs B/R response)?
4. Can the gem5 binary be rebuilt with NPS queue trace params enabled?

---

## 2026-06-29 wave-debug progress note

Latest focused debug used the Vivado/XSim 2025.2 endpoint wave CSVs for the
4-to-1 AXI-MM incast row and gem5 trace probes under
`noc_testing/artifacts/generated/diagnostics/`.

Key artifacts:

| Artifact | Purpose |
|---|---|
| `noc_testing/artifacts/vivado_wave_csv/wave_endpoint_probe_server/endpoint_aximm_sampler_3us.csv` | Vivado endpoint handshake reference |
| `noc_testing/artifacts/generated/diagnostics/lru_seed_probe/` | Baseline after switch LRU seeding; B/AR order matched Vivado |
| `noc_testing/artifacts/generated/diagnostics/nsu_read_tracker_order_probe/` | First useful NSU read grouping fix; removed intra-read R holes |
| `noc_testing/artifacts/generated/diagnostics/nsu_read_canonical_order_probe/` | Historical validation patch with Vivado-like read group order |
| `noc_testing/artifacts/generated/diagnostics/nsu_read_canonical_order_gap0_probe/` | Dead-end runtime knob test; do not pursue |

Findings:

- Vivado endpoint R timing is rigid for this row:
  - source order repeats as `tg1, tg3, tg2, tg0`;
  - R latencies are stable at `tg0=354`, `tg1=228`, `tg2=307`, `tg3=260`;
  - every 512B R response is eight beats with 8-cycle beat spacing.
- The largest Naviq read-side divergence was not base NMU/NSU latency. It was
  chopped 512B reads being serviced as separate NPP chunks, allowing patterns
  like `src3 half, src2 half, src3 half`. This created artificial holes inside
  an AXI read response that Vivado does not have.
- A diagnostic that moved read-tracker insertion to grouped NSU read-request
  flush fixed the intra-read holes. That behavior is evidence for the next
  model step, but is not retained in the cleaned code path yet.
- A historical validation patch that canonicalized the 4-source read group
  service order to `1,3,2,0` brought the per-channel averages close:

  | src | W accuracy | R accuracy |
  |---:|---:|---:|
  | 0 | 98.2% | 94.3% |
  | 1 | 97.1% | 95.9% |
  | 2 | 98.3% | 93.1% |
  | 3 | 97.5% | 95.3% |

  This is good enough if the acceptance metric is aggregate average latency, but
  not if every source/channel must clear 95%.
- `--nsu-read-response-gap-cycles 0` made src0 worse and should not be chased.

Follow-up on 2026-06-29:

- The fixed 512B read coalescing target was too specific. On
  `4to1_std_256B_tx10`, it held single-chunk 256B reads as if they needed a
  second 256B chunk, producing very poor read accuracy against Vivado
  (`aggregate R ~= 62%`).
- Retained code now carries original AXI read metadata from NMU to NSU:
  `NocMemoryMsg::originalReadBytes` and `finalReadChunk`. The grouped-read
  scheduling rule that waits for accumulated NPP bytes to reach the original AXI
  read size remains the next modeling target.
- Verification artifacts:

  | Artifact | Result |
  |---|---|
  | `noc_testing/artifacts/generated/results/gem5_vivado_naviq_incast_suite_incast_256B_origsize_fix.csv` | 256B sweep rerun, no per-flit gap: aggregate W `99.9%`, aggregate R `97.7%`; src0/src2 reads still below 95% |
  | `noc_testing/artifacts/generated/diagnostics/incast_512B_origsize_wave_topo_perflit_gap1/` | 512B direct rerun, wave topology + `--nsu-read-response-per-flit-gap-cycles 1`: aggregate W `99.6%`, aggregate R `95.5%`; src0 read `92.2%` |
  | `noc_testing/artifacts/generated/diagnostics/incast_256B_origsize_wave_topo_perflit_gap1/` | 256B direct rerun with the same per-flit gap: aggregate R fell to `90.0%` |

- Interpretation: original-size metadata fixes the 256B over-hold. The remaining
  read mismatch is not a single global NSU response-gap constant: 512B benefits
  from the per-flit gap, while 256B is hurt by it. The next principled lead is a
  response-drain/beat-spacing rule that depends on actual response burst
  structure or packetization, not on a global knob.
- Additional 512B coverage on 2026-06-29:

  | Row | gem5 mode | Aggregate W | Aggregate R | Notes |
  |---|---|---:|---:|---|
  | `4to1_std_tx50` | direct, `--nsu-read-response-per-flit-gap-cycles 1` | `100.0%` | `94.5%` | close, src0 read remains high |
  | `4to1_low_tx10` | direct, `--nsu-read-response-per-flit-gap-cycles 1` | `99.9%` | `95.5%` | passes aggregate and all per-source reads are >=95% by rounding |
  | `2to1_std_tx10` | default sweep | `97.8%` | `94.9%` | near miss without per-flit gap |
  | `2to1_std_tx10` | direct, `--nsu-read-response-per-flit-gap-cycles 1` | `97.4%` | `82.1%` | per-flit gap is wrong for 2-to-1 |
  | `4to1_sat_tx10` | default sweep | n/a | n/a | Vivado passed; gem5 aborted at tick `943000` on `MessageBuffer::enqueue` max-size assertion |
  | `2to1_sat_tx10` | default sweep | n/a | n/a | Vivado passed; gem5 aborted at tick `900000` on same max-size assertion |
  | `4to1_low50_tx10` | direct, `--nsu-read-response-per-flit-gap-cycles 1` | `99.8%` | `95.5%` | new 50 MBps point; matches the 200/800 MBps aggregate pattern |
  | `4to1_bw1200_tx10` | direct, `--nsu-read-response-per-flit-gap-cycles 1` | `99.2%` | `96.3%` | still passes aggregate read; src0 read below 95% |
  | `4to1_bw1600_tx10` | direct, `--nsu-read-response-per-flit-gap-cycles 1` | `99.5%` | `75.9%` | clear read-side break; default sweep read was also poor at `78.0%` |

  Fresh Vivado/gem5 artifacts use run tags
  `incast_512B_cov_std_tx50`, `incast_512B_cov_low_tx10`, and
  `incast_512B_cov_2to1_std_tx10`; saturated tx10 artifacts use
  `incast_512B_cov_4to1_sat_tx10` and `incast_512B_cov_2to1_sat_tx10`.
  The 50 MBps bandwidth point uses `incast_512B_bw50_tx10`.
  The 1200/1600 MBps points use
  `noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast_bw_probe.csv`
  with run tags `incast_512B_bw1200_tx10` and `incast_512B_bw1600_tx10`.
  Direct tuned logs are under matching
  `noc_testing/artifacts/generated/diagnostics/incast_512B_cov_*_gap1/`
  directories, plus
  `noc_testing/artifacts/generated/diagnostics/incast_512B_bw50_tx10_gap1/`,
  `noc_testing/artifacts/generated/diagnostics/incast_512B_bw1200_tx10_gap1/`,
  and `noc_testing/artifacts/generated/diagnostics/incast_512B_bw1600_tx10_gap1/`.

- Size sweep at 800 MBps / tx10 (`vivado_naviq_4to1_incast_size_probe.csv`,
  run tag `incast_size_probe_tx10_800`):

  | Row | gem5 mode | Aggregate W | Aggregate R | Notes |
  |---|---|---:|---:|---|
  | `size32_tx10` | default sweep | `98.7%` | `92.0%` | src3 read too slow (`198` vs `235.6`) |
  | `size64_tx10` | default sweep | `98.3%` | `93.0%` | src3 read too slow (`204` vs `236.9`) |
  | `size128_tx10` | default sweep | `97.3%` | `86.4%` | src3 read too slow (`222` vs `322.9`) |
  | `size256_tx10` | default sweep | `99.8%` | `98.8%` | passes aggregate |
  | `size512_tx10` | default sweep | `99.2%` | `91.1%` | expected read under-run without gap1 |
  | `size1024_tx10` | default sweep | n/a | n/a | Vivado passed; gem5 aborted at tick `591000` on `MessageBuffer::enqueue` max-size assertion |

Current best lead, if more accuracy is required:

- Remaining error is likely read-side arbitration phase/order timing upstream of
  the NSU read response drain, not latency constants.
- The response grouping fix proved the mechanism. The canonical `1,3,2,0`
  order was a validation patch, not a principled final arbitration model; the
  NSU should use first-ready queued read-group flushing and let upstream
  arbitration determine source order.
- The next high-confidence investigation would compare when each source's
  complete read group becomes ready at the NSU versus when its AR/NPP packets
  leave the upstream merge routers. Only pursue this if per-source/per-channel
  95% is required; otherwise stop here and avoid destabilizing passing rows.

Do not repeat:

- Retuning NMU/NSU base latency constants for this row before resolving ordering.
- `--nsu-read-response-gap-cycles 0`.
- Manually inspecting Vivado waveforms unless the automated CSV sampler cannot
  find useful signals.

---

## Historical investigation checklist

- [ ] Read `README.md` Findings #5 and #6 (mapping + per-hop vs queuing).
- [ ] Open `gem5_*_incast_suite_*.csv` and `vivado_*_incast_suite_*.csv` side by side.
- [ ] Run Phase 0 smoke trace; update phase table in `README.md`.
- [ ] If traces work, run Phase 1 and inspect merge switches in `.ncr` + hotspot artifacts.
- [ ] Only then consider simulator or TG model changes.
