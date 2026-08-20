# NoC Write Latency Discovery Process

This document describes how each rule in `write_latency_model.md` was discovered,
the methodology used, and the key waveform observations that confirmed each finding.
It serves as a research journal for anyone continuing this work.

---

## Phase 1: Initial Formula from CSV Data

### Starting Point
We began with the Vivado NoC simulation CSV (`latency_tests.csv`) containing 1080
data points across AXI sizes 2–64B, beats 1–17, and transaction counts 1–200.

### First Discovery: The Three-Term Structure
By analyzing `tx=1` rows (single transactions, no address effects), we noticed that
write latency grows linearly with flit count. Plotting `latency - flits` revealed a
constant offset that decomposed into two parts:

```
Write_Latency = [something] + Total_Flits + [constant]
```

The constant turned out to be **16**, which we later decomposed via waveforms into
the response path: 8 (NPS round trip) + 4 (NMU W resp) + 1 (NSU W req) + 1 (BRAM) +
2 (NSU W resp) = 16. This was later refined to **15** when we decomposed it into
the three-component model (NMU_Prep absorbs 1 cycle).

### Second Discovery: NMU_Prep = 9 + MAX(Beats, Data_Flits)
By subtracting total flits and 16 from the observed latency, we found the NMU
processing time varied with both beats and data_flits. The formula
`8 + MAX(Beats, MIN(Data_Flits, 15))` fit all tx=1 single-NPP data.

This was later refined to `9 + MAX(Beats, Data_Flits)` when we decomposed the
constant into `Response_Time = 15` (shifting 1 cycle from the constant into NMU_Prep).

**Validation:** 67/67 tx=1 single-NPP rows matched perfectly.

---

## Phase 2: Multi-NPP Formula

### Discovery: 256-Byte Address-Aligned Chopping
The Xilinx documentation states the NMU chops at 256-byte address-aligned boundaries.
We verified by checking that `ceil(Total_Bytes / 256)` correctly predicted the number
of header flits in the waveform.

### Formula Extension
For multi-NPP (`Total_Bytes > 256`), the first NPP is always a full 256B when
starting at address 0, so `NMU_Prep = 24`. The formula `24 + Total_Flits + 15`
matched all tx=1 multi-NPP data (sizes 64×5 through 64×17).

---

## Phase 3: The 256B Full-NPP Anomaly

### Problem
`size=16, beats=16` (exactly 256B) predicted **57** but actual was **56**. This was
the only tx=1 mismatch.

### Investigation
The old formula gave `16 + (8 + MAX(16, MIN(16, 15))) + 17 = 16 + 23 + 17 = 56`...
wait, that actually works? No — the issue was `MIN(Data_Flits, 15)` capped at 15
when data_flits was exactly 16. This gave `8 + MAX(16, 15) = 24`, then `16 + 24 + 17
= 57`. But actual was 56.

### Resolution
We observed in the waveform that for a full 256B NPP, the NMU prep is exactly **24
clock cycles**, not 25. This led to the rule: when `Data_Flits == 16`, fix
`NMU_Prep = 24` (instead of the formula giving `9 + 16 = 25`).

The user then generalized this: rather than treating it as a special case for 16×16,
this is a natural property of full NPPs. The "fill an entire NPP" optimization saves
1 cycle. This observation also applies universally to NPP processing within the NMU
pipeline.

### Three-Component Refactoring
This discovery motivated refactoring the formula into three waveform-observable stages:
```
Write_Latency = NMU_Prep + Total_Flits + Response_Time
```
Where `Response_Time = 15` and `NMU_Prep` is either 24 (full NPP) or
`9 + MAX(Beats, Data_Flits)`. This achieved **67/67** on all tx=1 single-NPP data.

---

## Phase 4: Per-Transaction Address Effects

### Discovery: Latency Drops on Subsequent Transactions
When running multiple transactions with incrementing addresses, `tx=2` often showed
lower `min_lat` than `tx=1`. We hypothesized this was NMU pipelining from 256B
boundary chopping.

### The Drop Formula
For single-NPP transactions that cross a 256B boundary:
```
drop = MIN(Data_Flits(Part1), Data_Flits(Part2)) - 1
```

Verified on examples like `16×13` (208B):
- Tx 1 (addr 0): no boundary → drop = 0, latency = 51
- Tx 2 (addr 208): crosses 256B, Part1=48B(3f), Part2=160B(10f) → drop = 2, latency = 49
- Tx 3 (addr 416): crosses 512B, Part1=96B(6f), Part2=112B(7f) → drop = 5, latency = 46

### 16-Byte Flit Boundary Effects
Some tx=2 configurations showed `max_lat` +1 instead of a drop. Analysis revealed
this was caused by the 16-byte flit boundary alignment — when `tx=2` starts at an
address that straddles a 16-byte boundary, an extra data flit is needed.

The address-aware flit formula handles this:
```
Data_Flits = floor(end_addr / 16) - floor(start_addr / 16) + 1
```

---

## Phase 5: Multi-NPP Inter-NPP Gap

### Problem
For `size=64, beats=7` (448B), tx=2 showed a consistent +1 cycle increase over tx=1.

### Waveform Discovery
Opening the waveform for `64×7` revealed:

**Tx 1 (addr 0):** 2 NPPs (256B + 192B). The NMU emitted all 30 flits back-to-back
with **no gap** between NPPs. The 24-cycle NMU prep overlapped entirely with NPP 1's
16-flit emission time.

**Tx 2 (addr 448):** 3 NPPs (64B + 256B + 128B). The first NPP only had 4 data
flits. The NMU finished emitting those 5 flits (header + 4 data) in 5 cycles, but
the internal pipeline needed more time to prepare NPP 2. This created a **12-cycle
gap** before NPP 2's header appeared.

### Key Insight
When the first NPP's emission time is shorter than the internal pipeline's prep time
for the next NPP, a stall gap appears. This is the fundamental mechanism behind
multi-NPP latency variation.

---

## Phase 6: Multi-NPP Min Latency Clamping

### Problem
For `size=64, beats=5` (320B), the model predicted increasingly low min latencies
for later transactions (Tx2=54, Tx3=50), but actual min stayed flat at **58**.

### Waveform Confirmation
The user confirmed: Tx1 (192B+128B, no gap) achieved 58. Tx2 (128B+192B) and Tx3
(64B+256B) both showed inter-NPP gaps that completely absorbed the NMU_Prep savings.
The min latency was clamped at the Tx1 value.

### Physical Explanation
The NMU_Prep savings from a smaller first NPP are exactly offset by the inter-NPP
gap that appears when the first NPP is too small to overlap with the pipeline's
internal prep. Below a threshold, savings stop accumulating.

---

## Phase 7: BRAM Back-to-Back Response Penalty

### Problem
Multi-NPP configs like `32×11` (352B) showed `max_lat` +1 at `tx=3-10`, too early
for the long-run BRAM drift (which starts at tx≥50).

### Waveform Discovery
The user examined `32×11` tx=3 and found:**Two separate +1 sources:**
1. The BRAM endpoint took an extra clock cycle to respond to the last NPP when it
   arrived back-to-back. The last NPP (2 data flits + 1 header = 3 total flits)
   arrived in only 3 cycles, but the BRAM needs a minimum of 4 cycles to process it.
2. The NMU processing time for the gap case also showed +1 (see Phase 9).

### Rule
The BRAM penalty is always exactly **+1 cycle** when the last NPP has fewer than 4
total flits AND arrives back-to-back (no gap). The penalty does NOT scale with NPP
size — it's always exactly 1, never 2.

Initial hypothesis was `max(0, 4 - total_flits)`, but waveform verification showed
the penalty is simply 1 or 0.

---

## Phase 8: Beat-Arrival-Based NMU Prep

### Problem
For small AXI sizes (2B, 4B, 8B), the per-transaction drop formula predicted much
larger drops than actually occurred. Example: `4×12` tx=6 predicted min=34 but
actual stayed at 40.

### Waveform Discovery
The user examined `4×12` tx=5 (addr 240, crosses 256B boundary → 16B + 32B):

The NMU doesn't start processing NPP 2 until NPP 2's data beats begin arriving.
The first 4 beats (belonging to NPP 1) take 5 cycles. Then beats 5-12 (belonging to
NPP 2) arrive, and the NMU independently computes `9 + MAX(8 beats, 2 df) = 17`
cycles of prep time starting from that point.

Total: `5 + 17 = 22` NMU cycles, then 3 flits + 15 response = **40**. ✓

### Generalization
For each NPP beyond the first, the readiness has two constraints:
```
ready[i] = MAX(
    pipeline_ready:   ready[i-1] + df[i],
    beat_arrival:     sum(beats_before_i) + 1 + 9 + MAX(npp_i_beats, npp_i_df)
)
```
The `MAX` ensures whichever constraint is tighter determines the result. This unified
formula handles both large sizes (where pipeline_ready dominates) and small sizes
(where beat_arrival dominates).

---

## Phase 9: +1 Gap Transition Overhead

### Problem
After all previous fixes, 74 cases remained where `min_lat` was +1 above prediction.
All were 32B/64B sizes with boundary crossings.

### Waveform Discovery
The user checked `32×6` tx=1 (64B + 128B split). The model predicted a 3-cycle gap,
but the waveform showed a **4-cycle gap**. The extra cycle is a transition overhead
when the NMU restarts emission after a stall.

### Refinement
A blanket +1 for all gap cases broke 165 other cases. Analysis showed:

- The +1 only applies when `pipeline_ready ≥ beat_arrival_ready` (internal prep is
  the bottleneck, not beat arrival).
- The +1 does NOT apply when the post-gap NPP is a full 256B NPP (`df ≥ 16`),
  because the full-NPP -1 optimization (Phase 3) absorbs the transition overhead.

With this three-condition rule, accuracy jumped to **952/1080 (88.1%)**.

---

## Phase 10: Final Validation

### Remaining 128 Mismatches

| Category | Count | Root Cause |
|----------|-------|------------|
| BRAM drift (tx≥50) | 109 | NSU BRAM occasionally takes 3 cycles instead of 2 for write response during long runs. Not a NoC issue. |
| Max +1/+2 (tx<50) | 14 | 4KB boundary effects causing extra NPP splits at high tx counts for large multi-NPP configs. |
| Bandwidth artifact | 5 | `2×4` (8B) configs had bandwidth set too high, causing early BRAM response anomalies. |

### Summary of Accuracy Progression

| Phase | Rule Added | Accuracy |
|-------|-----------|----------|
| 1 | Base formula: 16 + NMU_var + Total_Flits | 67/67 tx=1 |
| 2 | Multi-NPP extension | All tx=1 |
| 3 | Full-NPP NMU_Prep = 24 | 67/67 single-NPP tx=1 |
| 4 | Per-transaction drops | 569/804 single-NPP |
| 5-6 | Inter-NPP gap + clamping | Qualitative |
| 7 | BRAM back-to-back penalty | 878/1080 (81.3%) |
| 8 | Beat-arrival-based prep | 878/1080 (81.3%) |
| 9 | +1 gap transition | **952/1080 (88.1%)** |

---

## Methodology Notes

### Tools Used
- **Vivado ILA waveforms:** Primary source for cycle-exact timing of NMU flit
  emission, inter-NPP gaps, and BRAM response behavior.
- **CSV statistical analysis:** Python scripts to iterate all configurations and
  identify systematic patterns (e.g., "all +1 mismatches are 32B/64B with boundary
  crossings").
- **Per-transaction address simulation:** Python scripts that simulate incrementing
  addresses to compute each transaction's NPP structure and predict its latency.

### Key Lessons
1. **Start with tx=1:** Single-transaction data isolates the core formula without
   address effects. Get this right first.
2. **Categorize mismatches:** After each fix, re-validate and categorize remaining
   mismatches by (dm, dM) pattern. Systematic patterns (e.g., "all +1") indicate a
   missing rule, while scattered mismatches indicate noise.
3. **Waveforms are the ground truth:** Every formula refinement was confirmed by
   waveform observation before being generalized. Statistical patterns suggest
   hypotheses; waveforms confirm them.
4. **Decompose the formula:** Breaking latency into NMU_Prep + Flits + Response made
   each component independently verifiable on the waveform.
