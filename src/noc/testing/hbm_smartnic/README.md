# Legacy HBM SmartNIC Helpers

This directory is intentionally small. The maintained HBM SmartNIC experiment
campaigns live under `src/noc/testing/experiments/hbm/`:

- `limiter_backpressure/`: real RTL packet-rate-limiter backpressure experiment
- `ppe_dma_pipeline/`: HBM -> DMA direct/PPE datapath comparison

`cpuwrite_hbm_common.py` remains here as shared setup code for HBM CPU-write DMA
scenarios. Avoid adding new one-off experiment scripts here; put named
campaigns under `experiments/hbm/` instead.
