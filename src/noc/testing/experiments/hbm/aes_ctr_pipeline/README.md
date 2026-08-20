# HBM AES-CTR Pipeline Experiment

Status: planned, not implemented.

## Goal

Build a realistic standalone HBM offload experiment using AES-CTR engines in the
PL datapath:

```text
HBM -> DMA -> AES-CTR -> DMA -> HBM
```

The intended scale is 32 AES-CTR engines. Each engine should connect to two NMUs
across the top of the NoC: one DMA path reads plaintext/ciphertext data from HBM
and the other DMA path writes the transformed data back to HBM. The CPU configures
the initial key/vector state for each engine before starting the pipelines.

This is meant to exercise PL RTL, NoC routing, HBM bandwidth, DMA behavior, and
processor-side control in one experiment while using the same top-level offload
interfaces as the other SmartNIC/PPE modules.

## Why This Experiment Matters

- More realistic than synthetic AXIS backpressure or packet limiter-only tests.
- Produces a clear accelerator workload: encrypt/decrypt contents of HBM.
- Uses both memory read and memory write traffic through DMA.
- Keeps CPU involvement meaningful through per-engine key/vector programming.
- Can scale from one AES engine to 32 engines to expose NoC/HBM bottlenecks.

## Planned Steps

1. Locate and inventory the AES-CTR RTL/offload interface.
   - Identify source files, top module, AXIS/AXI-MM/AXI-Lite ports, reset/clocking, and any existing simulation wrapper.
   - Confirm whether it already has a Verilator manifest or needs one added.

2. Build a single-engine smoke test first.
   - Instantiate one AES-CTR engine between DMA read and DMA write paths.
   - Program key/vector state from the CPU.
   - Move a small HBM buffer through the pipeline.
   - Validate output bytes against known AES-CTR test vectors or a software reference.

3. Define the topology shape.
   - Start with one engine and two NMUs.
   - Expand to 4, 8, 16, then 32 engines.
   - Keep each engine paired with read/write DMA endpoints so traffic shape stays
     representative of the final experiment.

4. Add CPU-side orchestration.
   - Allocate/init HBM source buffers.
   - Program AES key/vector registers per engine.
   - Program DMA descriptors for HBM read and HBM write.
   - Start engines and poll/check completion.

5. Add correctness metrics.
   - `engines_configured`
   - `engines_completed`
   - `bytes_read_from_hbm`
   - `bytes_written_to_hbm`
   - `output_mismatch_count`
   - per-engine completion/status fields

6. Add performance metrics.
   - aggregate throughput
   - per-engine throughput
   - DMA read/write latency
   - HBM channel utilization
   - NoC hotspot/route overlap indicators
   - CPU configuration time versus datapath time

7. Create comparison cases.
   - direct DMA copy baseline: `HBM -> DMA -> DMA -> HBM`
   - 1 AES engine
   - 4 AES engines
   - 8 AES engines
   - 16 AES engines
   - 32 AES engines

8. Validate scaling.
   - Confirm all bytes are preserved/transformed correctly.
   - Check whether throughput scales until AES, DMA, NoC, or HBM becomes the limiter.
   - Compare the 32-engine case against the direct DMA copy baseline.

## Result Criteria

The experiment should not be considered usable until:

- CPU key/vector programming is visible in the run setup.
- At least one AES engine passes byte-level correctness against a software reference.
- Multi-engine runs preserve completion and correctness for every engine.
- The 32-engine case reports a clear throughput and bottleneck story.
- Results distinguish AES datapath cost from direct DMA copy behavior.

## Open Questions

- Where is the current AES-CTR RTL/offload source located?
- Does the AES offload already have an AXI-Lite control plane and status registers?
- Does it expose AXIS input/output, AXI-MM DMA-facing ports, or a different wrapper?
- Is the reported 100 Gbps per AES core measured in RTL sim, FPGA, or another setup?
- Are keys/vectors fixed-size and per-engine independent?
- Should this experiment use the existing SmartNIC/PPE topology style or a new
  HBM-specific AES topology?

## Initial Implementation Target

The first useful milestone should be:

```text
1 AES engine, 1 HBM source buffer, 1 HBM destination buffer,
CPU-programmed key/vector, byte-correct output, and a direct DMA copy baseline.
```

After that works, scaling to 32 engines becomes a topology and orchestration
problem instead of a correctness/debugging problem.
