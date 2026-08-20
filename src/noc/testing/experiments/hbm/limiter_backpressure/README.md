# HBM Limiter Backpressure Experiment

Canonical driver:

```sh
python3 src/noc/testing/experiments/hbm/limiter_backpressure/run_compare.py
```

This experiment exercises the real Verilated packet-rate-limiter datapath in an
HBM DMA flow. The limiter is programmed through AXI-Lite, packets are preserved,
and output-ready gating is varied across `none`, `moderate`, and `strong`
backpressure cases.

The comparison driver requires:

- `PacketRateLimiterThrottleRtlNode`
- `csr_programmed_plus_axis_backpressure_v1`
- 100 input packets, 100 limiter output packets, and matching byte counts
- increasing backpressure counters from `none` to `moderate` to `strong`
- a useful throughput drop or AXIS stream-window increase for `strong`
