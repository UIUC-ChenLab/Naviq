# AXIS receive packet eligibility

`NocNetworkInterface` buffers incoming flits separately for each input port and
VC. An AXIS packet becomes eligible for its shared protocol drain only when the
entire first NoC packet (NPP) is present in that queue. Incomplete packets keep
their flits and credits while the arbiter considers other queues. Once selected,
the existing shared drain lock remains held until the tail is accepted, including
when the protocol output applies backpressure.

This changes no router ownership locks. Each router's output VC remains owned by
one input queue from head through tail. Flits from a different source must never
enter that output VC before the previous packet's tail. Other VCs can progress
independently. The NPP is a native NoC packet of at most 64 bytes, not the entire
AXI4-Stream frame reconstructed by an endpoint.

The old receive arbiter could select a partial AXIS NPP and hold the shared drain
while waiting for its tail. Another VC's complete packets could then retain all
of their credits and fill an upstream shared bridge buffer needed by that tail.
Complete-NPP eligibility removes this particular dependency. It does not remove
cycles through packet-engine backpressure or claim general network deadlock
freedom.

`NppReceive.hh` validates only the first queued NPP: packet identity, source NI,
VC, consecutive flit indices, declared length, and head/tail boundaries. Another
packet may already follow its tail in the same queue. Invalid prefixes fail
explicitly. Eligibility inspection never removes flits or returns credits.

Native AXIS NPPs contain one to four 16-byte flits. They must fit both the existing
seven-flit receive assembler and the actual credit window advertised by the
attaching router. The lookup uses that router's type and honors explicit VC-depth
overrides, matching the external output link configuration. An insufficient
window or unknown attaching router fails explicitly; this fix does not enlarge
buffers or credits. Direct AXIS wires bypass this NI path.

AXI memory-mapped traffic retains its existing streaming selection and control
bypass. Memory write packets can contain 17 flits (header plus 16 data flits),
read-data packets 16, and grouped read requests seven, exceeding the usual
five-credit VNOC window. Applying this AXIS
completion gate to those packets would introduce a separate deadlock. Fixing
receive scheduling for those longer packets would require a separate bounded
streaming design.

Run the unit tests from the Naviq repository with:

```sh
src/noc/testing/run_noc_gtests.sh
```

`noc_npp_receive.test` exercises the exact production prefix checker, including
all native packet lengths, a complete VC beside an incomplete VC, queued following
packets, malformed ownership/order/boundaries, and insufficient receive windows.
These tests do not replace routed integration tests: those must also check exact
delivered bytes and packet counts, same-VC source ownership through every tail,
credit conservation, downstream backpressure, drain completion, and the existing
AXI memory-mapped/control regressions. Preserve original Vivado paths and VCs when
comparing the fix with the original receive behavior.
