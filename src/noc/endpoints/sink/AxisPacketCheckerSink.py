from m5.objects import NocNode
from m5.params import *
from m5.proxy import *


class AxisPacketCheckerSink(NocNode):
    type = "AxisPacketCheckerSink"
    cxx_header = "noc/endpoints/sink/AxisPacketCheckerSink.hh"
    cxx_class = "gem5::noc::AxisPacketCheckerSink"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    data_width = Param.UInt32(512, "AXIS TDATA width in bits")
    tid_width = Param.UInt32(16, "AXIS TID width")
    tdest_width = Param.UInt32(12, "AXIS TDEST width")
    tuser_width = Param.UInt32(16, "AXIS TUSER width")

    check_mode = Param.String("exact", "Check mode: exact, ipv4, nat_outbound")
    ready_percent = Param.UInt8(100, "Percent cycles asserting TREADY")
    expected_packets = Param.UInt32(16, "Number of TLAST packets expected")
    validate_ipv4_checksum = Param.Bool(True, "Validate IPv4 header checksums")
    validate_l4_checksum = Param.Bool(True, "Validate TCP/UDP checksums")
    print_summary = Param.Bool(True, "Print final packet checker summary")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")
    validation_skip_bytes = Param.UInt32(0, "Prefix bytes to skip before IPv4 validation")
    check_tdest = Param.Bool(False, "Check TDEST in all modes, not just exact mode")

    profile = Param.String("mixed_tcp_udp", "Expected traffic profile for exact mode")
    seed = Param.UInt32(1, "Expected stream seed for exact mode")
    min_payload_bytes = Param.UInt32(16, "Minimum expected L4 payload bytes")
    max_payload_bytes = Param.UInt32(64, "Maximum expected L4 payload bytes")
    payload_sizes = Param.String("", "Comma-separated exact L4 payload sizes; empty uses min/max/seed")
    flow_count = Param.UInt32(1, "Number of deterministic IPv4/L4 flows")

    tid = Param.UInt32(0, "Expected TID")
    tdest = Param.UInt32(0, "Expected TDEST")
    tuser = Param.UInt32(0, "Expected TUSER")
    src_ip = Param.String("192.168.1.100", "Base expected source IPv4 address")
    dst_ip = Param.String("8.8.8.8", "Base expected destination IPv4 address")
    src_port = Param.UInt16(12345, "Base expected source L4 port")
    dst_port = Param.UInt16(80, "Base expected destination L4 port")
    prefix_bytes = Param.UInt32(0, "Number of little-endian prefix bytes in exact expected packets")
    prefix_value = Param.UInt32(0, "Little-endian prefix value in exact expected packets")

    nat_public_ip = Param.String("10.0.0.1", "Expected NAT public IPv4 address")
    nat_base_port = Param.UInt16(40000, "Expected NAT translated base port")
    nat_port_count = Param.UInt16(256, "Expected NAT translated port range size")
