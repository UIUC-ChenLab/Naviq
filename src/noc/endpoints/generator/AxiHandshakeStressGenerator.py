from m5.params import *

from .AXIMMTrafficGenerator import AxiRandomTrafficGenerator


class AxiHandshakeStressGenerator(AxiRandomTrafficGenerator):
    """AXI-MM traffic source with deterministic, legal handshake stalls.

    This generator never changes an AXI payload.  It probabilistically holds
    outgoing VALID signals and incoming B/R READY signals to exercise
    backpressure and ordering paths in the NoC implementation.
    """

    type = "AxiHandshakeStressGenerator"
    cxx_header = "noc/endpoints/generator/AxiHandshakeStressGenerator.hh"
    cxx_class = "gem5::noc::AxiHandshakeStressGenerator"

    fault_seed = Param.Unsigned(
        1,
        "RNG seed for handshake gating (0 = time-based); set explicitly for reproducible runs",
    )
    aw_valid_percent = Param.UInt8(
        100, "Percent of cycles that allow an asserted AWVALID through"
    )
    w_valid_percent = Param.UInt8(
        100, "Percent of cycles that allow an asserted WVALID through"
    )
    ar_valid_percent = Param.UInt8(
        100, "Percent of cycles that allow an asserted ARVALID through"
    )
    b_ready_percent = Param.UInt8(
        100, "Percent of cycles that assert BREADY toward the NoC"
    )
    r_ready_percent = Param.UInt8(
        100, "Percent of cycles that assert RREADY toward the NoC"
    )
