from m5.params import *
from m5.proxy import *
from m5.SimObject import SimObject
from m5.objects import (
    Port,
)
from m5.objects import BramEndpoint


class tileNSU_HBM(BramEndpoint):
    type = "tileNSU_HBM"
    cxx_header = "noc/endpoints/memory/hbm/tileNSU_HBM.hh"
    cxx_class = "gem5::noc::tileNSU_HBM"

    noc_system = Param.NocSystem(Parent.any, "")
    sim_cycles = Param.UInt64(1000, "Number of simulation cycles")
    requestorId = Param.UInt16(0, "ID for Requesting Port")
    hbm_controller_id = Param.UInt32(0, "HBM controller index backing this port")
    hbm_port_id = Param.UInt32(0, "HBM ingress port index (0..3)")
    hbm_pseudo_channel_id = Param.UInt32(0, "HBM pseudo-channel index (0..1)")
    hbm_pseudo_channel_base_addr = Param.Addr(0, "Base address of the backing pseudo-channel window")
    hbm_pseudo_channel_size = Param.UInt64(0, "Size of the backing pseudo-channel window in bytes")
    read_latency_cycles = Param.UInt32(30, "Front-end read admission latency in cycles")
    write_latency_cycles = Param.UInt32(20, "Front-end write admission latency in cycles")
    resp_latency_cycles = Param.UInt32(8, "Front-end response latency after backend completion")
    port_queue_depth = Param.UInt32(96, "Maximum queued commands per HBM port")
    max_outstanding_reads = Param.UInt32(64, "Maximum outstanding reads per HBM port")
    max_outstanding_writes = Param.UInt32(32, "Maximum outstanding writes per HBM port")
    issue_interval_cycles = Param.UInt32(0, "Minimum cycles between issues across the shared HBM controller frontend; set to 0 to rely on the bandwidth cap")
    shared_bw_MBps = Param.UInt64(51200, "Shared HBM controller frontend bandwidth cap in MB/s")
    nmu_bw_MBps = Param.UInt64(12000, "Per-HBM-NMU AXI link bandwidth cap in MB/s")
    banks_per_pseudo_channel = Param.UInt32(16, "Modeled number of banks in each HBM pseudo channel")
    row_hit_latency_cycles = Param.UInt32(4, "Additional scheduler delay for a row hit")
    row_miss_latency_cycles = Param.UInt32(18, "Additional scheduler delay for a row miss")
    bank_busy_cycles = Param.UInt32(12, "How long a bank remains busy after an issued command")
    cmd_bus_cycles = Param.UInt32(2, "How long the shared controller command path remains occupied after an issue")
    page_policy = Param.String("open_page", "HBM page policy: open_page or closed_page")
    hbm_trace_csv_path = Param.String(
        "",
        "If non-empty, append per-tick HBM NSU AXI trace CSV to this path "
        "(see ms,tile_hbm,request_num,axi_type,event,data_bytes,address)",
    )
    hbm_trace_tile_index = Param.UInt32(
        0xFFFFFFFF,
        "Tile id column in HBM trace CSV; use 0xFFFFFFFF to use requestorId",
    )
    hbm_stats_csv_path = Param.String(
        "",
        "If non-empty, append periodic HBM port/pseudo-channel stats to this CSV "
        "(see ms,controller_id,port_id,pseudo_channel_id,... in hbm_stats.csv).",
    )
    hbm_stats_sample_gap_cycles = Param.UInt32(
        100,
        "Sample HBM stats CSV every this many cycles when hbm_stats_csv_path is set",
    )

    noc_hbm_port = RequestPort("Port connecting to HBM or crossbar")
