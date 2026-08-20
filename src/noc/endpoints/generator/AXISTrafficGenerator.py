from m5.params import *

from .TrafficGenerator import TrafficGenerator


class AXISTrafficGenerator(TrafficGenerator):
    type = "AXISTrafficGenerator"
    cxx_header = "noc/endpoints/generator/AXISTrafficGenerator.hh"
    cxx_class = "gem5::noc::AXISTrafficGenerator"

    def __init__(self, **kwargs):
        kwargs.setdefault("protocol", "AXIS")
        super().__init__(**kwargs)


class AxisRandomTrafficGenerator(AXISTrafficGenerator):
    type = "AxisRandomTrafficGenerator"
    cxx_header = "noc/endpoints/generator/AxisRandomTrafficGenerator.hh"
    cxx_class = "gem5::noc::AxisRandomTrafficGenerator"

    seed = Param.Unsigned(0, "RNG seed (0 = time-based)")

    packet_size_distribution = Param.String("UNIFORM", "Distribution for packet size: UNIFORM|BINOMIAL|FIXED|INCREMENT")
    min_packet_size_bytes = Param.Unsigned(64, "Minimum bytes per packet")
    max_packet_size_bytes = Param.Unsigned(1500, "Maximum bytes per packet")
    packet_size_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial packet size")

    gap_distribution = Param.String("UNIFORM", "Distribution for inter-packet gap: UNIFORM|BINOMIAL|FIXED|INCREMENT")
    min_gap_cycles = Param.Unsigned(0, "Minimum idle cycles between packets")
    max_gap_cycles = Param.Unsigned(10, "Maximum idle cycles between packets")
    gap_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial gap")

    tid_distribution = Param.String("UNIFORM", "Distribution for TID: UNIFORM|BINOMIAL|FIXED|INCREMENT")
    min_tid = Param.Unsigned(0, "Minimum TID value")
    max_tid = Param.Unsigned(0xFFFF, "Maximum TID value")
    tid_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial TID")

    tdest_distribution = Param.String("UNIFORM", "Distribution for TDEST: UNIFORM|BINOMIAL|FIXED|INCREMENT")
    min_tdest = Param.Unsigned(0, "Minimum TDEST value")
    max_tdest = Param.Unsigned(0xFFF, "Maximum TDEST value")
    tdest_binomial_probability = Param.Float(0.5, "Probability (0..1) for binomial TDEST")

    max_packets = Param.Unsigned(100, "Maximum number of packets to send (0 = unlimited)")


class AxisPcapTrafficGenerator(AXISTrafficGenerator):
    type = "AxisPcapTrafficGenerator"
    cxx_header = "noc/endpoints/generator/AxisPcapTrafficGenerator.hh"
    cxx_class = "gem5::noc::AxisPcapTrafficGenerator"

    pcap_file_path = Param.String("", "Path to PCAP file to replay")
    speed_multiplier = Param.Float(1.0, "Temporal speed multiplier (1.0 = real-time)")
    preserve_timestamps = Param.Bool(True, "Preserve original packet timings")
    max_packets = Param.Unsigned(0, "Maximum packets to replay (0 = all)")
    clock_period_ns = Param.Unsigned(1, "Clock period in nanoseconds")
    tdest = Param.UInt64(0, "tdest for all packets")


class AxisPacketTrafficGenerator(AXISTrafficGenerator):
    type = "AxisPacketTrafficGenerator"
    cxx_header = "noc/endpoints/generator/AxisPacketTrafficGenerator.hh"
    cxx_class = "gem5::noc::AxisPacketTrafficGenerator"

    profile = Param.String("mixed_tcp_udp", "Traffic profile: ipv4_udp, ipv4_tcp, mixed_tcp_udp")
    max_packets = Param.UInt32(16, "Number of packets to emit")
    seed = Param.UInt32(1, "Deterministic payload-length seed")
    min_payload_bytes = Param.UInt32(16, "Minimum L4 payload bytes")
    max_payload_bytes = Param.UInt32(64, "Maximum L4 payload bytes")
    flow_count = Param.UInt32(1, "Number of deterministic IPv4/L4 flows")
    min_gap_cycles = Param.UInt32(0, "Minimum idle cycles between packets")
    max_gap_cycles = Param.UInt32(0, "Maximum idle cycles between packets")
    initial_gap_cycles = Param.UInt32(0, "Initial idle cycles before first packet")

    tid = Param.UInt32(0, "TID value for all beats")
    tdest = Param.UInt32(0, "TDEST value for all beats")
    tuser = Param.UInt32(0, "TUSER value for all beats")
    src_ip = Param.String("192.168.1.100", "Base source IPv4 address")
    dst_ip = Param.String("8.8.8.8", "Base destination IPv4 address")
    src_port = Param.UInt16(12345, "Base source L4 port")
    dst_port = Param.UInt16(80, "Base destination L4 port")
    corrupt_ipv4_checksum = Param.Bool(False, "Emit packets with intentionally bad IPv4 header checksums")
    corrupt_l4_checksum = Param.Bool(False, "Emit packets with intentionally bad TCP/UDP checksums")
    prefix_bytes = Param.UInt32(0, "Number of little-endian prefix bytes before each packet")
    prefix_value = Param.UInt32(0, "Little-endian prefix value to emit before each packet")
