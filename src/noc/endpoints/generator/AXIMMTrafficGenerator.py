from m5.params import *

from .TrafficGenerator import TrafficGenerator


class AXIMMTrafficGenerator(TrafficGenerator):
    type = "AXIMMTrafficGenerator"
    cxx_header = "noc/endpoints/generator/AXIMMTrafficGenerator.hh"
    cxx_class = "gem5::noc::AXIMMTrafficGenerator"

    def __init__(self, **kwargs):
        kwargs.setdefault("protocol", "AXIMM")
        super().__init__(**kwargs)


class AxiRandomTrafficGenerator(AXIMMTrafficGenerator):
    type = "AxiRandomTrafficGenerator"
    cxx_header = "noc/endpoints/generator/AxiRandomTrafficGenerator.hh"
    cxx_class = "gem5::noc::AxiRandomTrafficGenerator"

    seed = Param.Unsigned(0, "RNG seed (0 = time-based)")

    base_addr = Param.UInt64(0, "Base address")
    max_addr = Param.UInt64(0xFFFFFFFF, "Maximum address")

    address_distribution = Param.String("UNIFORM", "UNIFORM|BINOMIAL|FIXED|INCREMENT")
    address_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial address selection")
    address_increment = Param.Unsigned(1, "Increment for INCREMENT distribution")

    transaction_size_distribution = Param.String("UNIFORM", "UNIFORM|BINOMIAL|FIXED|INCREMENT")
    min_transaction_size_bytes = Param.Unsigned(64, "Minimum bytes per transaction")
    max_transaction_size_bytes = Param.Unsigned(512, "Maximum bytes per transaction")
    transaction_size_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial transaction size")

    gap_distribution = Param.String("UNIFORM", "UNIFORM|BINOMIAL|FIXED|INCREMENT")
    min_gap_cycles = Param.Unsigned(0, "Minimum idle cycles between commands")
    max_gap_cycles = Param.Unsigned(10, "Maximum idle cycles between commands")
    gap_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial gap")

    awid_distribution = Param.String("FIXED", "UNIFORM|BINOMIAL|FIXED|INCREMENT")
    min_awid = Param.Unsigned(0, "Minimum AWID")
    max_awid = Param.Unsigned(15, "Maximum AWID")
    awid_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial AWID")

    arid_distribution = Param.String("FIXED", "UNIFORM|BINOMIAL|FIXED|INCREMENT")
    min_arid = Param.Unsigned(0, "Minimum ARID")
    max_arid = Param.Unsigned(15, "Maximum ARID")
    arid_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial ARID")

    read_write_mode = Param.String("WRITE_ONLY", "WRITE_ONLY|SEQUENTIAL|INTERLEAVED")
    max_outstanding_writes = Param.Unsigned(1, "Outstanding writes for INTERLEAVED mode")
    max_outstanding_reads = Param.Unsigned(0, "Max outstanding reads (0=unlimited); throttles read issue like real AXI masters")

    max_write_commands = Param.Unsigned(0, "Maximum number of write commands (0=unlimited)")
    beat_size_bytes = Param.Unsigned(
        0,
        "AXI beat size in bytes for AW/AR size encoding (0 derives from data_width / 8)",
    )

    # NSU list for AXIMM: set via inherited nsu_min_addrs and nsu_address_spaces (from TrafficGenerator base).
    # Example: nsu_min_addrs=[0x1000, 0x2000], nsu_address_spaces=[0x1000, 0x2000] for two NSUs.

    # NSU selection: how to choose which NSU to target per request
    nsu_selection = Param.String("INTERLEAVE", "INTERLEAVE|RANDOM|ROTATE")
    nsu_index_distribution = Param.String("UNIFORM", "For RANDOM NSU: UNIFORM|BINOMIAL|FIXED|INCREMENT")
    nsu_index_binomial_probability = Param.Float(0.5, "For RANDOM NSU with BINOMIAL: probability (0..1)")

    align_addresses = Param.Bool(True, "Align addresses to transaction size")
