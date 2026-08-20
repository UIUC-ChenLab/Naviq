# NoC Read Latency Prediction Model

This document outlines the cycle-accurate prediction model for read transactions over the Versal NoC. Unlike write transactions which are primarily constrained by NMU preparation and BRAM response times, read transactions are bound by a **dual-bottleneck pipeline** where network flit emission overlaps directly with NMU R-beat generation.

## 1. Core Architecture Pipeline

A read transaction's latency is determined by the maximum of two parallel pipelines. Once the initial request reaches the NSU, the NSU begins emitting read response flits. The NMU receives these flits and simultaneously begins pumping out AXI R-beats to the master.

```
Total Latency = MAX(Flit Bottleneck, Beat Bottleneck)
```

### 1.1 Fixed Overhead Constants

Every single read transaction has a base structural delay of **18 cycles** before the first read response flit can be emitted by the NSU:
- NMU AXI AR-channel processing & request emission: **6 cycles**
- NPS forward traversal (2 hops): **4 cycles**
- NSU request processing: **1 cycle**
- BRAM read access time: **3 cycles**
- NPS return traversal (2 hops): **4 cycles**

**Total Base Structural Delay = 18 cycles**

---

## 2. Pipelined Bottlenecks

### 2.1 The Beat Bottleneck (Small Transactions)
For transactions where the AXI Master requests many beats but the actual byte size translates to very few network flits (e.g., `2B x 16 beats = 32B`, which is only 2 flits but 16 beats), the NMU's ability to pump out AXI R-beats is the limiting factor.

Because the NMU starts processing immediately after the first flit arrives, the total time is simply the fixed structural overhead + the time for the first flit to arrive + the continuous emission of beats.

**`Beat Bottleneck = 26 + beats`**
*(Derivation: 18 base + 1 NSU start + 7 cycles base NMU processing for the first flit + `beats`)*

### 2.2 The Flit Bottleneck (Large Transactions)
For larger transactions (e.g., `64B x 4 beats = 256B`, which is 16 flits but only 4 beats), the network bandwidth and NSU emission rate become the bottleneck. The NMU has to wait for all the flits to arrive across the network before it can finish pumping out the final beats.

**`Flit Bottleneck = 18 + 1 + (data_flits - 1) + burst_gaps + NMU_response`**

Where the components are:
* **`18`**: Base structural delay.
* **`1`**: NSU internal start delay for the first response flit.
* **`(data_flits - 1)`**: The serial emission time of the remaining flits (1 cycle per flit).
* **`burst_gaps`**: The NSU injects a 1-cycle pipeline bubble after every 4th flit. This acts as a rate limiter.
  * Formula: `math.ceil(data_flits / 4)`. (Rounding up is critical).
* **`NMU_response`**: The time it takes the NMU to process the flit stream and emit the final beats after the last flit arrives. This is highly dependent on how the AXI burst size aligns with the 16B NoC flit size.

---

## 3. NMU Response Time Constants (`NMU_response`)

The NMU processes the incoming flit stream differently depending on the AXI `ARSIZE`.

### Size 64B (`ARSIZE = 6`)
Each beat requires exactly 4 flits. The NMU waits for complete 64B groups. 
* **`NMU_response = 10 cycles`** (Constant for all 64B transactions).

### Size 32B (`ARSIZE = 5`)
Each beat requires exactly 2 flits. The NMU processes them in groups, but the alignment with the NSU's 4-flit `burst_gaps` causes an alternating pattern based on whether the total number of beats is even or odd.
* **Even Beats** (e.g., 4, 6, 8): **`NMU_response = 7 cycles`**
* **Odd Beats** (e.g., 3, 5, 7): **`NMU_response = 8 cycles`**

### Size 16B (`ARSIZE = 4`)
Each beat is exactly 1 flit. The NMU emits beats almost as fast as flits arrive, but its internal FIFO causes a distinct repeating pipeline reset pattern. It emits 12 beats continuously, then stalls for 3 cycles. This translates to an effective processing time that cycles through 7, 6, and 5 depending on the flit group.
* group = `(data_flits - 1) // 4`
* **`NMU_response = 7 - (group % 3) cycles`**

### Sizes 8B, 4B, 2B
Since these sizes always fall under the **Beat Bottleneck**, their `NMU_response` time does not impact the final latency and can be ignored for prediction purposes.

---

## 4. Multi-Transaction Edge Cases

When predicting sweeps with hundreds of back-to-back read transactions, two physical hardware effects cause the maximum observed latency (`read_latency_max`) to drift:

### 4.1 The 4KB Boundary Chop
AXI Masters (like the Traffic Generator) are strictly forbidden from crossing a 4KB address boundary in a single burst. If a sweep generates a transaction that naturally crosses a 4KB boundary, the Traffic Generator will silently chop it into two smaller, independent transactions.
* **Impact**: The minimum latency (`read_latency_min`) reported for the sweep will plummet, as it records the latency of the tiny chopped tail-end transaction.

### 4.2 The 16-Flit Sticky Gap
The NSU maintains a long-term flit counter. After every 16th accumulated flit, it injects a "sticky" 1-cycle gap into the response pipeline to prevent network saturation.
* **Impact**: In a multi-transaction sweep, this causes the maximum latency (`read_latency_max`) to drift slightly higher (usually +1 or +2 cycles) over time, as downstream transactions inherit the pipeline bubbles generated by earlier transactions.
