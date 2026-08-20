# NoC source guide

This directory contains the supported Naviq NoC extension.  It is organized
by responsibility rather than by individual experiment.

| Path | Responsibility |
| --- | --- |
| `core/interface/` | Endpoint-facing protocol handlers, CDC queues, and the network-interface boundary. |
| `core/network/` | Garnet-derived routed transport, routers, links, and NMU/NSU endpoint units. |
| `core/network/nmu_types/` | Source endpoints: AXI-MM (`mmNocMasterUnit`) and AXIS (`sNocMasterUnit`). |
| `core/network/nsu_types/` | Destination endpoints: AXI-MM (`mmNocSlaveUnit`) and AXIS (`sNocSlaveUnit`). |
| `lib/axi/` | Protocol payload types plus AXI-MM and AXIS packetization buffers. |
| `setup/` | Supported topology/configuration construction. |
| `testing/` | Runnable local scenarios, deterministic fixtures, and NoC C++ tests. |

Historical code and topology inputs are intentionally outside this supported
source tree under `archive/noc/`; see its index before reviewing or retiring
older material.

## Data paths

For AXI-MM, an endpoint's `AXIMMHandler` converts AR/AW/W/R/B state into a CDC
entry.  `mmNocMasterUnit` packetizes source requests and combines responses;
`mmNocSlaveUnit` reconstructs requests and packetizes responses.  The
`NocGarnetNetwork` supplies routes and virtual channels but does not own AXI
ordering semantics.

For AXIS, `AXISHandler` transfers TDATA/TKEEP/TID/TDEST/TLAST through the CDC
boundary.  `sNocMasterUnit` groups accepted bytes into NoC packets and
`sNocSlaveUnit` reconstructs them at the destination.

## Maintainer invariants

- A NoC packet payload (NPP) is at most 256 bytes.  Packetization must split
  larger AXI-MM requests and AXIS packets instead of making a larger NPP.
- AXIS packet identity is defined by TID, TDEST, and TLAST.  Packet assembly
  must remain packet-scoped because independent sources can interleave at an
  NSU.
- AXI-MM response order is preserved per AXI ID.  The released interface
  supports the tested AW-before-W association; W-before-AW needs a dedicated
  pending-W design and regression before it can be claimed as supported.
- CDC queues own their entries until dequeue.  A stalled ready/valid transfer
  must keep its payload stable.

See [the architecture guide](../../docs/NOC_ARCHITECTURE.md) for the public
component model and [the test guide](testing/README.md) before changing these
paths. The setup-support module map is in [setup/include/README.md](setup/include/README.md),
and outstanding source-maintenance work is tracked in
[NOC_MAINTENANCE_BACKLOG.md](../../docs/NOC_MAINTENANCE_BACKLOG.md).
