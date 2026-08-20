## General
- [ ] create functional tests to verify noc

## HBM
- [x] Must have: keep the intentional NMU 256B-boundary restriction, but update HBM traffic generation / test setup so "unaligned" mode does not generate illegal bursts. In practice this means using deterministic start addresses that are divisible by beat size and do not create beats crossing a 256B-aligned boundary.
- [x] Should have: expand HBM regression coverage with targeted v2 cases that current smokes miss:
  - [x] beat-aligned but otherwise unaligned AXI-MM traffic that still respects the NMU 256B-boundary rule
  - [x] higher-contention / multi-outstanding traffic
  - [x] mixed HBM + non-HBM endpoint cases
- [x] Should have: validate existing HBM v2 topologies (`1hbm_to_1hbm`, `2hbm_to_2hbm`, mixed cases) and record expected latency/bandwidth baselines.
- [x] Optional: characterize multi-endpoint HBM saturation with a `32 TG / 16 MC / 32 pseudo-channel` offered-load sweep and record the observed aggregate plateau.
- [x] Optional: compare the observed `32 TG / 16 MC / 32 pseudo-channel` saturation plateau against the intended AMD aggregate HBM bandwidth target once that reference target is pinned down.
- [ ] Optional: calibrate HBM backend/frontend timing knobs against Versal V80 HBM2e behavior once hardware measurements or a trusted reference target are available.


## Topology Analysis
- [x] Percentile latencies: P50 / P95 / P99 / P99.9
- [x] Fairness metric
- [ ] Offered-load sweeps + knee point detection
- [ ] Top-k bottleneck summaries in the main CSV
- [ ] Baseline delta columns
- [ ] Mixed-traffic breakdowns for SmartNIC later
