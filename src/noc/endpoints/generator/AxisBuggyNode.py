from m5.params import *
from m5.proxy import *
from m5.objects import NocNode


class AxisBuggyGenerator(NocNode):
    type = "AxisBuggyGenerator"
    cxx_header = "noc/endpoints/generator/AxisBuggyNode.hh"
    cxx_class = "gem5::noc::AxisBuggyGenerator"

    # optional hook-ins for consistency with other test nodes
    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    # AXIS interface widths
    data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    tid_width = Param.UInt32(16, "AXIS TID width")
    tdest_width = Param.UInt32(12, "AXIS TDEST width")
    tuser_width = Param.UInt32(0, "AXIS TUSER width (bits)")

    # Random strategy configuration (mirrors AxisRandomTrafficGenerator)
    seed = Param.Unsigned(0, "RNG seed (0 = time-based)")

    packet_size_distribution = Param.String(
        "UNIFORM", "Distribution for packet size: UNIFORM|BINOMIAL|FIXED|INCREMENT"
    )
    min_packet_size_bytes = Param.Unsigned(64, "Minimum bytes per packet")
    max_packet_size_bytes = Param.Unsigned(1500, "Maximum bytes per packet")
    packet_size_binomial_probability = Param.Float(
        0.5, "Probability (0..1) for binomial packet size"
    )

    gap_distribution = Param.String(
        "UNIFORM", "Distribution for inter-packet gap: UNIFORM|BINOMIAL|FIXED|INCREMENT"
    )
    min_gap_cycles = Param.Unsigned(0, "Minimum idle cycles between packets")
    max_gap_cycles = Param.Unsigned(10, "Maximum idle cycles between packets")
    gap_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial gap")

    tid_distribution = Param.String(
        "UNIFORM", "Distribution for TID: UNIFORM|BINOMIAL|FIXED|INCREMENT"
    )
    min_tid = Param.Unsigned(0, "Minimum TID value")
    max_tid = Param.Unsigned(0xFFFF, "Maximum TID value")
    tid_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial TID")

    tdest_distribution = Param.String(
        "UNIFORM", "Distribution for TDEST: UNIFORM|BINOMIAL|FIXED|INCREMENT"
    )
    min_tdest = Param.Unsigned(0, "Minimum TDEST value")
    max_tdest = Param.Unsigned(0xFFF, "Maximum TDEST value")
    tdest_binomial_probability = Param.Float(
        0.5, "Probability (0..1) for binomial TDEST"
    )

    max_packets = Param.Unsigned(100, "Maximum number of packets to send (0 = unlimited)")

    valid_percent = Param.UInt8(
        100,
        "When throttling applies: percent of cycles asserting TVALID (0-100); "
        "see valid_percent_start_fraction.",
    )
    valid_percent_start_fraction = Param.Float(
        0.0,
        "Apply valid_percent only after this fraction (0..1) of max_packets TLAST "
        "handshakes observed on the link (0 = from first packet; max_packets=0 => "
        "same as 0). Before that, TVALID follows the generator.",
    )

    # Optional second AXIS master. Existing unprefixed parameters configure
    # master 0; these prefixed parameters configure master 1 when enabled.
    second_master_enable = Param.Bool(False, "Enable optional second AXIS master port")
    second_data_width = Param.UInt32(512, "Second AXIS TDATA width (bits)")
    second_tid_width = Param.UInt32(16, "Second AXIS TID width")
    second_tdest_width = Param.UInt32(12, "Second AXIS TDEST width")
    second_tuser_width = Param.UInt32(0, "Second AXIS TUSER width (bits)")

    second_seed = Param.Unsigned(0, "Second master RNG seed (0 = time-based)")

    second_packet_size_distribution = Param.String(
        "UNIFORM", "Second master packet size distribution: UNIFORM|BINOMIAL|FIXED|INCREMENT"
    )
    second_min_packet_size_bytes = Param.Unsigned(64, "Second master minimum bytes per packet")
    second_max_packet_size_bytes = Param.Unsigned(1500, "Second master maximum bytes per packet")
    second_packet_size_binomial_probability = Param.Float(
        0.5, "Second master probability (0..1) for binomial packet size"
    )

    second_gap_distribution = Param.String(
        "UNIFORM", "Second master inter-packet gap distribution: UNIFORM|BINOMIAL|FIXED|INCREMENT"
    )
    second_min_gap_cycles = Param.Unsigned(0, "Second master minimum idle cycles between packets")
    second_max_gap_cycles = Param.Unsigned(10, "Second master maximum idle cycles between packets")
    second_gap_binomial_probability = Param.Float(
        0.5, "Second master probability (0..1) for binomial gap"
    )

    second_tid_distribution = Param.String(
        "UNIFORM", "Second master TID distribution: UNIFORM|BINOMIAL|FIXED|INCREMENT"
    )
    second_min_tid = Param.Unsigned(0, "Second master minimum TID value")
    second_max_tid = Param.Unsigned(0xFFFF, "Second master maximum TID value")
    second_tid_binomial_probability = Param.Float(
        0.5, "Second master probability (0..1) for binomial TID"
    )

    second_tdest_distribution = Param.String(
        "UNIFORM", "Second master TDEST distribution: UNIFORM|BINOMIAL|FIXED|INCREMENT"
    )
    second_min_tdest = Param.Unsigned(0, "Second master minimum TDEST value")
    second_max_tdest = Param.Unsigned(0xFFF, "Second master maximum TDEST value")
    second_tdest_binomial_probability = Param.Float(
        0.5, "Second master probability (0..1) for binomial TDEST"
    )

    second_max_packets = Param.Unsigned(
        100, "Second master maximum number of packets to send (0 = unlimited)"
    )

    second_valid_percent = Param.UInt8(
        100,
        "Second master percent of cycles asserting TVALID when throttling applies",
    )
    second_valid_percent_start_fraction = Param.Float(
        0.0,
        "Second master fraction (0..1) of max_packets before applying valid_percent",
    )

    # --- Bug injection knobs ---
    tid_corrupt_enable = Param.Bool(
        False, "Randomly corrupt exactly one outgoing beat's TID"
    )
    tid_corrupt_chance = Param.Float(
        0.001,
        "Probability per valid beat to become the single corrupted beat (0..1)",
    )

    # Stall-triggered injections (armed on tvalid & ~tready, applied next cycle)
    stall_drop_tvalid_enable = Param.Bool(
        False,
        "Each stalled cycle (tvalid & ~tready): with stall_drop_tvalid_chance, "
        "arm dropping tvalid on the following cycle",
    )
    stall_drop_tvalid_chance = Param.Float(
        1.0, "Probability per stalled beat to arm drop-tvalid (0..1)"
    )

    stall_mutate_payload_enable = Param.Bool(
        False,
        "Each stalled cycle (tvalid & ~tready): with stall_mutate_payload_chance, "
        "arm payload mutation on the following cycle",
    )
    stall_mutate_payload_chance = Param.Float(
        1.0, "Probability per stalled beat to arm mutate-payload (0..1)"
    )

    stall_drop_tlast_enable = Param.Bool(
        False,
        "Each stalled TLAST beat (tvalid&tlast & ~tready): with stall_drop_tlast_chance, "
        "arm deasserting tlast on the following cycle",
    )
    stall_drop_tlast_chance = Param.Float(
        1.0, "Probability per stalled TLAST beat to arm drop-tlast (0..1)"
    )

    second_tid_corrupt_enable = Param.Bool(
        False, "Second master: randomly corrupt exactly one outgoing beat's TID"
    )
    second_tid_corrupt_chance = Param.Float(
        0.001,
        "Second master probability per valid beat to become the single corrupted beat",
    )
    second_stall_drop_tvalid_enable = Param.Bool(
        False, "Second master: arm dropping tvalid on the cycle after a stalled beat"
    )
    second_stall_drop_tvalid_chance = Param.Float(
        1.0, "Second master probability per stalled beat to arm drop-tvalid"
    )
    second_stall_mutate_payload_enable = Param.Bool(
        False, "Second master: arm payload mutation on the cycle after a stalled beat"
    )
    second_stall_mutate_payload_chance = Param.Float(
        1.0, "Second master probability per stalled beat to arm mutate-payload"
    )
    second_stall_drop_tlast_enable = Param.Bool(
        False, "Second master: arm deasserting tlast on the cycle after a stalled TLAST"
    )
    second_stall_drop_tlast_chance = Param.Float(
        1.0, "Second master probability per stalled TLAST beat to arm drop-tlast"
    )

