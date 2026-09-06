# AdaptNIC13PE RTL snapshot

This is the dependency closure of the thirteen implicit-hash experiment PEs.
`snapshot/` contains copied RTL and PE manifests; `SOURCES.json` records the
original AdaptNIC-relative filenames and their content hashes. Shared RTL is
copied once. `instances.json` records every configured instance and port.

Each `<instance>.rtl.json` builds a separate model with Naviq's existing RTL
builder. `build.py` checks timestamps, builds changed models, and emits the
small typed gem5 declarations into `src/noc/endpoints/rtl/generated/` using
the validated XPM endpoint maps. No source paths resolve outside Naviq.

The simulation XPM stubs in `../../include/` accept both Naviq's existing
parameter names and the copied Versal wrappers' names. Packet lanes and control
ports share one DUT clock/reset and one gem5 node per PE.

The host fabric is a fourteenth model. Its direct AXIS connections carry a
one-bit TUSER for the H2C NMU selection; physical XPM stream bindings have no
TUSER pins. The host fabric consumes the selection before NoC transmission.
USO input and URO output attach directly to this fabric.

Next-hop words retain their 32-bit control interface and four-byte stride.
Bits 9:0 select TDEST, bit 10 selects the path-local output NMU, and software
writes zeros above bit 10. A destination-only word selects lane 0. Both hash
and header steering hold this routing pair for the whole packet. Reassigning
active flows requires draining their traffic first.

See `src/noc/testing/smartnic/pe13/README.md` for build/run commands and the
editable packet/control scenario. The snapshot deliberately does not contain
the board top, CIPS, PCIe, or generated Vivado project files.

## Snapshot refresh

Refresh canonical generated wrappers first, then import their dependency
closure with `sync_snapshot.py --adapt-nic-root <AdaptNIC checkout>
--wrapper-manifest <generated wrapper/manifest.json>`. This is a maintenance
step; normal builds require only Naviq. The import validates all 13 control
apertures, 512-bit packets, 4096-entry tables, rebuilders, and reserved TID pairs.
The canonical wrappers use `AXIMM_AUSER_WIDTH` (16) for the internal AXI-Lite
interface, matching each PE control crossbar.
