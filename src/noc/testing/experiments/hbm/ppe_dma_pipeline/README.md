# HBM DMA PPE Pipeline Experiment

Canonical driver:

```sh
python3 src/noc/testing/experiments/hbm/ppe_dma_pipeline/run_compare.py
```

This experiment preserves the useful HBM SmartNIC datapath cases from the old
`hbm_smartnic/` scratch area:

- `direct`: HBM -> DMA -> AXIS checker, no PPE
- `ppe`: HBM -> DMA -> PPE path -> AXIS checker

Both cases use the available 500-packet HBM CPU-write binary plus the DMA/NoC
tuning knobs that were used as the HBM DMA/PPE datapath baseline before the
limiter backpressure experiment. The comparison driver validates packet
preservation and reports the throughput and AXIS stream window for each path.
