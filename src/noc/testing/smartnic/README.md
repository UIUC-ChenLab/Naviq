# SmartNIC Test Layout

This directory contains runnable SmartNIC/AXIS simulation scenarios plus shared
test helpers.

- `common/`: support code imported by the runnable scenarios
- `loopback/`: source-to-sink packet loopback scenarios
- `modules/`: single-module packet-processing scenarios
- `ppe/`: packet-processing-engine scenarios

Everything outside `common/` is intended to be runnable with gem5.
