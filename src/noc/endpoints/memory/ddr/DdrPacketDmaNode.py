from m5.objects import NocNode
from m5.params import *
from m5.proxy import *


class DdrPacketDmaNode(NocNode):
    type = "DdrPacketDmaNode"
    cxx_header = "noc/endpoints/memory/ddr/DdrPacketDmaNode.hh"
    cxx_class = "gem5::noc::DdrPacketDmaNode"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")

    descriptor_base = Param.Addr(0x00000000, "DDR descriptor table base")
    packet_base = Param.Addr(0x00100000, "DDR packet buffer base")
    control_base = Param.Addr(0x40000000, "CPU-visible DMA control register base")
    packet_stride = Param.UInt32(2048, "Bytes between packet buffers")
    packet_count = Param.UInt32(4, "Number of descriptors/packets to DMA")
    max_read_burst_beats = Param.UInt32(16, "Maximum 64-byte AXI-MM read burst length")
    max_outstanding_reads = Param.UInt32(16, "Maximum pipelined AXI-MM reads")
    descriptor_prefetch_depth = Param.UInt32(64, "Number of descriptors to prefetch ahead of AXIS emission")
    packet_prefetch_depth = Param.UInt32(16, "Number of packet payloads to prefetch ahead of AXIS emission")
    start_delay_cycles = Param.UInt32(0, "Cycles to wait before issuing DDR accesses")
    post_preload_read_delay_cycles = Param.UInt32(0, "Diagnostic cycles to idle after preload writes before issuing DMA reads")
    packet_gap_cycles = Param.UInt32(0, "Cycles to wait between streamed packets")
    descriptor_flags = Param.UInt16(0x1, "Flags ORed into generated descriptors")
    stop_on_eoc = Param.Bool(False, "Set EOC on the final generated descriptor and report it")
    preload_ddr = Param.Bool(True, "Write generated descriptors and packets into DDR before reading them")
    preload_descriptors = Param.Bool(True, "Preload generated descriptors into DDR")
    preload_packets = Param.Bool(True, "Preload generated packet bytes into DDR")
    functional_preload_packets = Param.Bool(False, "Initialize generated packet bytes through functional memory instead of timed AXI writes")
    preload_memory = Param.NocNode(NULL, "Functional memory endpoint used for functional packet preload")
    wait_for_control_start = Param.Bool(False, "Wait for CPU control START before emitting packets")
    print_summary = Param.Bool(True, "Print final DMA summary")
    metrics_output_path = Param.String("", "Optional JSON metrics fragment output path")

    data_width = Param.UInt32(512, "AXIS TDATA width in bits")
    tid_width = Param.UInt32(16, "AXIS TID width")
    tdest_width = Param.UInt32(12, "AXIS TDEST width")
    tuser_width = Param.UInt32(16, "AXIS TUSER width")
    axi_id = Param.UInt32(0, "AXI ID used for DMA preload and DDR read requests")
    profile = Param.String("mixed_tcp_udp", "Generated packet profile")
    seed = Param.UInt32(1, "Generated packet payload-length seed")
    min_payload_bytes = Param.UInt32(16, "Minimum L4 payload bytes")
    max_payload_bytes = Param.UInt32(64, "Maximum L4 payload bytes")
    payload_sizes = Param.String("", "Comma-separated exact L4 payload sizes; empty uses min/max/seed")
    flow_count = Param.UInt32(4, "Number of deterministic IPv4/L4 flows")
    tid = Param.UInt32(0, "AXIS TID to emit from descriptors")
    tdest = Param.UInt32(0, "AXIS TDEST to emit from descriptors")
    tuser = Param.UInt32(0, "AXIS TUSER to emit from descriptors")
    src_ip = Param.String("192.168.1.100", "Base source IPv4 address")
    dst_ip = Param.String("8.8.8.8", "Base destination IPv4 address")
    src_port = Param.UInt16(12345, "Base source L4 port")
    dst_port = Param.UInt16(80, "Base destination L4 port")
    corrupt_ipv4_checksum = Param.Bool(False, "Corrupt generated IPv4 checksums before DDR preload")
    corrupt_l4_checksum = Param.Bool(False, "Corrupt generated TCP/UDP checksums before DDR preload")
    prefix_bytes = Param.UInt32(0, "Number of little-endian prefix bytes to prepend to each packet")
    prefix_value = Param.UInt32(0, "Little-endian prefix value to prepend to each packet")
