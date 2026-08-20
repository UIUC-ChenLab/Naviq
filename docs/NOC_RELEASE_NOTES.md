# Naviq Release Notes (Draft)

## Release scope

Naviq is a gem5-derived, cycle-level NoC simulator supporting AXIS and AXI-MM
traffic, BRAM, DDR, HBM, CPU integration, and optional RTL experiments. The
required SystemVerilogAXI C++ sources are vendored directly so the repository
does not depend on a private submodule.

## Candidate verification

The current self-contained source tree has passed:

- `scons --no-compress-debug build/NULL/gem5.opt -j8`
- 43 focused NoC C++ tests through `src/noc/testing/run_noc_gtests.sh`
- 32 portable quick NoC TestLib checks

These results must be repeated from the final committed tree in a clean clone
before the first public tag. The release record should include the final commit
and the vendored SystemVerilogAXI revision documented in
`src/noc/lib/external/SystemVerilogAXI/README.naviq.md`.

## Correctness coverage

- AXIS NSU wide-beat reconstruction is packet-scoped, preventing fan-in data
  corruption.
- AXI-MM full-width WSTRB handling is covered for 64B, 128B, and 256B writes.
- AXIS MTU-sized packetization emits only 256B-or-smaller NPPs.
- Finite AXIS FIFO traffic terminates without outstanding writes.
- AXI-MM multi-ID interleaved readback drains all reads while preserving
  per-ID response order.
- The supported AXI-MM AW-before-W behavior has deterministic C++ coverage.

## Reproducibility limits

The checked-in Vivado acceptance data verifies a pinned comparison without
launching Vivado. Reproducing the complete Vivado sweep requires the documented
external Vivado installation and licenses; generated waves and large artifacts
are intentionally excluded.

## Known implementation limitations

The AXI-MM model supports the tested AW-before-W subset. W-before-AW is not
retained by a pending-W queue and must not be presented as general AXI
independent-channel support.

W-channel backpressure currently checks existing write-buffer occupancy. A
future improvement should also include the queued beat size so an accepted beat
cannot exceed the modeled 512-byte buffer capacity. Other maintenance and
model-fidelity follow-ups are listed in `docs/NOC_MAINTENANCE_BACKLOG.md`.

## Publication metadata

- Project owner and maintainer: Professor Deming Chen
- Copyright holder: University of Illinois Urbana-Champaign
- Paper/publication citation: not yet available
