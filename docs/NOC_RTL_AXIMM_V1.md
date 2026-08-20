# AXI-MM RTL wrapper V1 contract

The manifest-driven RTL flow keeps topology, placement, clock domains, and
address ranges in user-authored JSON.  Generated C++ wrappers only bridge a
validated Verilated XPM endpoint to the existing gem5 AXI-MM NoC state.

## V1 scope

V1 supports one `xpm_nsu_mm` endpoint per generated node.  The endpoint is a
NoC destination: gem5 drives the RTL AXI-MM request channels and the RTL
returns read and write responses.  It is sufficient for a memory-mapped
peripheral or a small control/data slave.

The bridge reuses `AXIMMHandler`, `mmNocSlaveUnit`, `aximmMasterState`, and
`aximmSlaveState`; it does not reimplement NoC packetization, CDC, or AXI-ID
ordering.

## Supported behavior

- One clock and active-low reset per RTL node.
- One AXI-MM slave endpoint, with 32- to 512-bit data widths.
- AW-before-W writes, including full-width and partial `WSTRB` beats.
- One-beat reads and writes for the first validation target.
- `AWREADY`, `WREADY`, `ARREADY`, `BVALID/BREADY`, and `RVALID/RREADY`
  backpressure propagation.
- One outstanding write and one outstanding read in the wrapper. The existing
  NoC AXI-MM layer continues to own its supported ID/order behavior.

## Deliberately unsupported in V1

- W-before-AW admission.
- Multi-beat or burst RTL transactions.
- More than one AXI-MM XPM endpoint per generated node.
- Concurrent response buffering beyond one B and one R response.
- Automatic placement, clock, or address selection.

The manifest must declare `gem5_wrapper.clock_signal`,
`gem5_wrapper.reset_signal`, `gem5_wrapper.data_width`,
`gem5_wrapper.id_width`, and `gem5_wrapper.addr_width`. The generator rejects
missing or invalid values and rejects AXI-MM master (`xpm_nmu_mm`), mixed, or
multi-endpoint plans rather than emitting a potentially miswired wrapper.

Any expanded behavior must first gain a deterministic regression, then be
added to this contract and generator validation.

## Reference validation target

The reference target is the in-tree AXI-MM memory-like RTL fixture. External
hardware repositories are outside this portable validation contract.
