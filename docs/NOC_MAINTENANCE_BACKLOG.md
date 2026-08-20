# NoC maintenance backlog

This register classifies source-level TODO and FIXME markers found during the
public-release cleanup. It prevents ambiguous in-code notes from being mistaken
for supported behavior or silently discarded.

## Correctness and protocol fidelity

- **P1 — AXI-MM channel semantics:** add pending-W ownership before supporting
  W-before-AW; include exact W-buffer admission at the 512-byte limit. The
  corresponding deterministic tests are already listed in
  `src/noc/testing/TEST_TODO.md`.
- **P1 — endpoint backpressure:** model AXI-MM R-channel backpressure rather
  than assuming a continuously ready consumer in `AXIMMHandler`.
- **P1 — packet/burst accounting:** validate RROB entry calculations, AXIS
  flit-size timing, and HBM burst-length assumptions with boundary tests.
- **P1 — message timing:** resolve the documented arrival-time ordering case
  in `NocMessageBuffer` before changing message scheduling behavior.

## Model calibration and feature work

- **P2 — timing calibration:** replace provisional AXIS write-delay constants
  and BRAM/HBM queue heuristics only with Vivado/XSim evidence and a pinned
  acceptance case.
- **P2 — stream bounds and sidebands:** decide whether to enforce an AXIS
  outstanding-packet limit and complete any intentionally unsupported sideband
  propagation before advertising it.
- **P2 — DDR configuration:** map the requested DDR speed grade to a concrete
  memory model instead of relying on the current default.

## Maintainability-only items

- **P3 — naming and ownership:** clarify `NocTrafficMonitor` initiator/source
  naming, the temporary `NocInterface::update` alias, payload helper names,
  and the RROB temporary variable names while preserving serialized state.
- **P3 — construction cleanup:** replace endpoint-type conditionals in
  `Control` with an explicit endpoint interface only when a focused design and
  test cover every endpoint family.
- **P3 — diagnostics:** remove or replace disabled debug-only comments when
  their future behavior is specified; do not enable them merely to clear a
  TODO marker.

Every functional backlog item requires a deterministic reproducer, the quick
or C++ regression that proves it, and documentation if it changes a supported
AXI-MM, AXIS, HBM, or timing contract.
