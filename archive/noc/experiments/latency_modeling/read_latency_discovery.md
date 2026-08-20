# NoC Read Latency Discovery Narrative

This document logs the chronological process of discovering the exact mathematical model for read latency across the Versal NoC. It serves as a companion to the `write_latency_discovery.md` and explains how we arrived at the dual-bottleneck pipeline formula.

## Phase 1: Initial Over-Prediction & The Residual Pattern

We started with the assumption that read latency would behave similarly to write latency: a sum of discrete sequential delays. We knew the fixed overhead was roughly 18 cycles (6 NMU AR + 4 NPS + 1 NSU + 3 BRAM + 4 NPS return) and that the NSU processed responses sequentially.

Our first Python models tried to simply add up the fixed delay + response flit emission time + NMU AXI R-beat generation time. These models wildly over-predicted the actual Vivado latency (often by 20-30 cycles for large transactions like 64x17).

We pivoted to residual analysis. By looking at `actual_latency - 26`, we discovered a startlingly clean pattern:
- For small `ARSIZE` (2B to 8B), the actual latency perfectly tracked `26 + beats`. The data flit count (`df`) seemed entirely irrelevant. 
- For large `ARSIZE` (32B and 64B), the latency tracked `total_flits + beats + offset`. 

This proved that read latency acts as a **parallel pipeline**. The NMU can pump out R-beats *while* it is still receiving response flits from the network.

## Phase 2: The Dual Bottleneck Model

We mathematically separated the read path into two competing bottlenecks:
1. **The Beat Bottleneck:** How long it takes the NMU to pump out `beats` AXI transfers *after* receiving the first response flit. `(26 + beats)`
2. **The Flit Bottleneck:** How long it takes the entire network stream of `df` flits to arrive, plus the final processing time to emit the last beat.

Because these tasks run in parallel, the total latency is exactly `MAX(Beat Bottleneck, Flit Bottleneck)`. 

## Phase 3: Nailing the Pipelined Constants (The Last Mile)

To perfect the Flit Bottleneck equation, we needed the exact timing of the NSU flit emission and the NMU processing. 

### The `ceil(df / 4)` Gap Insight
The C++ implementation had a `FLITS_PER_BURST` rule injecting a 1-cycle penalty into the network every 4 flits. Initially, we calculated this as `df // 4`. However, to achieve 100% mathematical correlation with 32B boundary cases (like `32x3` vs `32x4`), we discovered the gap calculation must round UP: `math.ceil(df / 4)`. This accurately modeled when the gap stalled the pipeline *before* the last flit arrived.

### NMU Processing Alignments
The final puzzle piece was `NMU_response`—the specific number of cycles the NMU needs to emit the final AXI beat after the last network flit arrives. Through residual analysis, we found:
- **64B:** Constant **10 cycles** (waits for a full 4-flit 64B block).
- **32B:** Alternating **7 / 8 cycles**, depending on if the beat count was even or odd. This alternating pattern perfectly accounted for how 2-flit 32B blocks aligned with the 4-flit rate-limiting gaps injected by the NSU!
- **16B:** A repeating **7-6-5 cycle** pattern. The NMU processes 12 flits continuously, then stalls for 3 cycles, creating a repeating block-alignment effect.

Plugging these exact, interlocking mathematical patterns into the dual-bottleneck equation yielded exactly **100.0% accuracy** against the complete Vivado dataset for all isolated (tx=1) read transactions.

## Phase 4: Multi-Transaction Anomalies

Finally, we analyzed sweeps with dozens of transactions (`tx=50`, `tx=200`). We observed two distinct phenomena:

1. **Massive Minimum Latency Drops:** Sweeps would occasionally report `read_latency_min` values 10-20 cycles lower than physically possible for the configured size. We proved this occurs *exclusively* when a requested transaction spans a 4KB chunk boundary in memory. The Traffic Generator splits the read across the boundary, creating a tiny, fast transaction whose latency becomes the sweep's minimum.
2. **Sticky Gap R-MAX Drift:** The C++ model includes a `STICKY_GAP_THRESHOLD` of 16 flits. We observed that this global counter causes the maximum latency (`read_latency_max`) of sweeps to drift higher by 1-2 cycles as prior transactions bleed pipeline bubbles into subsequent ones. The NoC pipelining and traffic generator backpressure prevent this from scaling linearly to infinity, acting as a natural system throttle.
