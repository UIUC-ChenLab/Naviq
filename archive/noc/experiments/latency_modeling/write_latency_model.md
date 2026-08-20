# NoC Write Latency Model

A cycle-accurate model of write latency through the Versal NoC, derived from Vivado
simulation data (`latency_tests.csv`) and waveform analysis. This document provides
everything needed to implement cycle-accurate NMU and NSU behavior in a simulator.

**Model accuracy:** 952/1080 (88.1%) exact matches against all CSV test points.
Remaining mismatches are BRAM endpoint drift (not a NoC issue) and 4KB AXI page splits.

---

## 1. Core Concepts

### 1.1 Latency Components

Every write transaction's latency decomposes into three observable pipeline stages:

```text
Write_Latency = NMU_Prep + Flit_Emission + Response_Time
```

| Component | Description | Observable in Waveform |
|-----------|-------------|----------------------|
| **NMU_Prep** | Time from AXI request until the first header flit is emitted | AW valid → first NI flit |
| **Flit_Emission** | Time to emit all flits (headers + data) onto the NoC | First flit → last flit |
| **Response_Time** | Network traversal + NSU processing + BRAM write + return path | Last flit → B valid |

**Response_Time = 15 clock cycles** (constant for single-hop BRAM endpoint).

### 1.2 Breakdown of Response_Time (15 Cycles)

The 15-cycle constant delay is the sum of the following component latencies in the response path:

| Path Component | Cycles | Description |
|:--- |:---:|:--- |
| **NoC Traversal (Round-trip)** | 8 | 4 cycles forward (NMU $\rightarrow$ NSU) + 4 cycles back (NSU $\rightarrow$ NMU) |
| **NSU Request Handling** | 1 | Time for NSU to depacketize flit and send request to BRAM |
| **BRAM Processing** | 1 | Base latency for the BRAM endpoint to process the write |
| **NSU Response Handling** | 2 | Time for NSU to receive BRAM response and emit flits to NoC |
| **NMU Response Processing**| 3 | Time for NMU to receive flits and notify the Master Tile |
| **Total** | **15** | Observable delay from last flit emission to Master B-valid |

> [!NOTE]
> This breakdown assumes a "single-hop" or "short path" configuration common in verification examples. Variations in NoC topology will primarily affect the NoC Traversal component.

### 1.3 NPP Chopping (256-Byte Address-Aligned)

The NMU chops every AXI burst into **NoC Protocol Packets (NPPs)** at 256-byte
*address-aligned* boundaries. Each NPP gets its own header flit.

```text
NPP boundaries: 0x000, 0x100, 0x200, 0x300, ...
```

> **Example:** A 320-byte burst starting at address 0 creates 2 NPPs:
> - NPP 0: [0, 255] = 256B (16 data flits)
> - NPP 1: [256, 319] = 64B (4 data flits)
>
> The same 320-byte burst starting at address 320 creates 2 NPPs:
> - NPP 0: [320, 511] = 192B (12 data flits)
> - NPP 1: [512, 639] = 128B (8 data flits)

### 1.3 Flit Packing (16-Byte Address-Aligned)

Each data flit carries up to 16 bytes at 16-byte *address-aligned* boundaries:

```text
Data_Flits = floor((end_addr) / 16) - floor(start_addr / 16) + 1
```

If a transaction's data range straddles a 16-byte boundary, it requires an extra flit
even if the total byte count would fit in fewer flits.

---

## 2. NMU Prep Time

The NMU prep time determines when the first header flit is emitted after the AXI
request is accepted.

### 2.1 Formula

```text
If data_flits >= 16 (full 256B NPP):
    NMU_Prep = 24

Otherwise:
    NMU_Prep = 9 + MAX(beats, data_flits)
```

Where:
- `beats` = number of AXI W-channel beats for this NPP
- `data_flits` = number of 16-byte data flits in this NPP

The `MAX(beats, data_flits)` term reflects that the NMU must wait for whichever
takes longer: receiving all AXI beats or packing all data flits.

### 2.2 Full-NPP Optimization

When an NPP contains exactly 16 data flits (a full 256B), the NMU prep is fixed at
**24 cycles** instead of the expected `9 + 16 = 25`. This 1-cycle optimization
applies universally whenever an NPP is completely full.

> **Implementation note:** The -1 optimization for full NPPs is consistent across
> all observed waveforms. When implementing the NMU, treat `df == 16` as a special
> case with `NMU_Prep = 24`.

---

## 3. NMU Pipeline Model for Multi-NPP Transactions

When a transaction is chopped into multiple NPPs, the NMU processes them through an
internal pipeline. Each NPP has two timing constraints:

### 3.1 Readiness Formula

For NPP `i` (where `i > 0`):

```text
ready[i] = MAX(pipeline_ready, beat_arrival_ready)
```

Where:
- **Pipeline-ready:** `ready[i-1] + df[i]` — the internal pipeline finishes
  preparing NPP `i` after processing `df[i]` flits worth of data since NPP `i-1`
  was ready.
- **Beat-arrival-ready:** `sum(beats_for_npps_0..i-1) + 1 + 9 + MAX(npp_i_beats, npp_i_df)`
  — the NMU can't start processing NPP `i` until all preceding beats have arrived,
  plus its own prep time.

For NPP 0:
```text
ready[0] = NMU_Prep  (from Section 2)
```

### 3.2 Emission Timing

```text
emit[i] = MAX(prev_emit_end, ready[i])
```

Where `prev_emit_end = emit[i-1] + 1 (header) + df[i-1] (data flits)`.

- If `emit[i] == prev_emit_end`: NPPs are emitted **back-to-back** (no gap).
- If `emit[i] > prev_emit_end`: there is an **inter-NPP gap** — the NMU had to
  stall because the next NPP wasn't ready yet.

### 3.3 Gap Transition Overhead (+1 Cycle)

When there IS an inter-NPP gap, and the following conditions are met:
1. `pipeline_ready >= beat_arrival_ready` (internal prep is the bottleneck)
2. The post-gap NPP is **not** a full 256B NPP (`df < 16`)

Then add +1 cycle to the emission time:
```text
emit[i] += 1
```

For full NPPs (`df >= 16`), the -1 full-NPP optimization (Section 2.2) absorbs
this transition overhead.

> **Implementation note:** In the NMU code, after emitting the last flit of an NPP,
> the NMU must wait `MAX(0, ready[i+1] - current_cycle)` cycles before starting the
> next NPP's header. This is the inter-NPP gap. The +1 overhead is a transition
> cost for restarting the emission pipeline after a stall.

### 3.4 Complete Cycle Calculation

```text
last_flit_cycle = emit[last_npp] + 1 (header) + df[last_npp] (data)
write_latency   = last_flit_cycle + Response_Time + BRAM_Penalty
```

---

## 4. BRAM Endpoint Behavior

### 4.1 Back-to-Back Response Penalty

When multiple NPPs arrive at the BRAM endpoint back-to-back (no inter-NPP gap),
the BRAM requires a minimum processing time per NPP. If the **last** NPP has fewer
than 4 total flits (1 header + data flits):

```text
BRAM_Penalty = 1   (if last NPP total flits < 4 AND back-to-back)
             = 0   (otherwise)
```

The penalty is always exactly **+1 cycle**, regardless of how small the NPP is.

### 4.2 Long-Run BRAM Drift

During extended simulations (50+ transactions), isolated transactions occasionally
show +1 or +2 cycle latency increases. This is caused by the NSU/BRAM taking an
extra cycle for the write response (3 cycles instead of 2). This is a BRAM endpoint
artifact and does not need to be modeled in the NoC.

### 4.3 4KB AXI Page Boundary

When cumulative addresses cross a 4096-byte boundary, the AXI traffic generator
splits the request into two separate AXI commands. The small residual burst completes
very fast, pulling down the global `min_lat` statistic. This is a traffic generator
artifact, not NoC behavior.

---

## 5. Per-Transaction Address Effects

When multiple transactions are issued with incrementing addresses, each transaction's
NPP structure depends on its start address.

### 5.1 Example: 64×5 (320 bytes)

| Tx | Start Addr | NPP Split | 1st NPP df | NMU_Prep | Latency |
|----|-----------|-----------|------------|----------|---------|
| 0  | 0         | 256B + 64B  | 16       | 24       | 61      |
| 1  | 320       | 192B + 128B | 12       | 21       | 58      |
| 2  | 640       | 128B + 192B | 8        | 17       | 58*     |
| 3  | 960       | 64B + 256B  | 4        | 13       | 58*     |
| 4  | 1280      | 256B + 64B  | 16       | 24       | 61      |

*Tx 2 and 3 have inter-NPP gaps that absorb the NMU_Prep savings, clamping the
effective minimum at 58. The pattern repeats every 4 transactions.

---

## 6. Validation Summary

| Category | Count | Status |
|----------|-------|--------|
| Perfect match | 952 | ✓ |
| BRAM drift (tx ≥ 50) | 109 | Expected, not a NoC issue |
| Max +1/+2 (tx < 50) | 19 | BRAM sensitivity + 4KB splits |
| **Total** | **1080** | |

All formulas verified against `latency_tests.csv` data covering:
- AXI sizes: 2, 4, 8, 16, 32, 64 bytes
- Beats: 1–17
- Transactions: 1–200
- Total bytes per transaction: 2–1088
