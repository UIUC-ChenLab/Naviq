# NoC Architecture Guide

The extension layers NoC behavior on gem5 Garnet while keeping protocol-facing
logic separate from endpoint models.

- `src/noc/core/control` schedules endpoint and NoC clock domains.
- `src/noc/core/interface` bridges AXIS and AXI-MM channel state through CDC
  queues and protocol handlers.
- `src/noc/core/network` packetizes requests into NoC flits and reconstructs
  endpoint transactions. AXIS and AXI-MM specialized NMU/NSU implementations
  live below this layer.
- `src/noc/endpoints` provides traffic generators, memory/sink models, CPU
  bridges, and optional RTL adapters.
- `src/noc/lib` provides shared AXI data types, write-buffer/reorder helpers,
  messages, and topology utilities.

Important invariants are intentionally enforced close to the relevant code and
tests: NoC packets are at most 256 bytes of payload, AXIS state is scoped to a
packet, AXI-MM responses preserve per-ID ordering, and write strobes survive
all packetization boundaries.
