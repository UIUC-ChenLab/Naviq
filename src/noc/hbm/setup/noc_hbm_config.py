# HBM Configuration Module
# This module contains functions to configure HBM memory for the NoC simulation

from math import log

from m5.objects import (
    DRAMInterface,
    MemInterface,
    AddrRange,
    HBM_3200_4H_1x64,
    HBMCtrl,
    MemCtrl,
    NoC_HBMXBar,
    DDR4_2400_8x8,
)



def configure_hbm(system, hbm_channels, num_hbm_nsu, hbm_nsu_start_idx, hbm_tile_indices=None):
    """
    Configure HBM memory controllers and connect them to the system.
    
    Args:
        system: The gem5 System object
        hbm_channels: Dictionary of HBM channel configurations from NTS parsing
        num_hbm_nsu: Number of HBM NSU tiles
        hbm_nsu_start_idx: Starting index of HBM NSU tiles in system.cpu list
        hbm_tile_indices: Optional explicit list of system.cpu indices for HBM tiles
    """
    ordered_channels = sorted(
        hbm_channels.items(),
        key=lambda item: item[1].get("controller_index", 0),
    )
    NUM_CHANNELS = len(ordered_channels)
    
    if NUM_CHANNELS == 0:
        return
    
    # Create HBM crossbar
    system.membus = NoC_HBMXBar()
    
    ADDR_MAPPING = "RoCoRaBaCh"
    DEFAULT_PC_SIZE = 1 * (2**30)  # 1GB default

    # Versal HBM2e controllers run up to 1600 MHz / 3200 MT/s. Model each
    # pseudo-channel with a 64-bit HBM2e-style interface to match the V80
    # operating point more closely than the legacy 2 Gbps profile.
    dram_a = [HBM_3200_4H_1x64(addr_mapping=ADDR_MAPPING) for _ in range(NUM_CHANNELS)]
    dram_b = [HBM_3200_4H_1x64(addr_mapping=ADDR_MAPPING) for _ in range(NUM_CHANNELS)]

    # Determine pseudo_channel_interleaving_bit from first channel's address size
    first_channel = ordered_channels[0][1]
    if first_channel["addresses"]:
        pc_size = first_channel["addresses"][0][1]  # Size of first pseudo-channel
    else:
        pc_size = DEFAULT_PC_SIZE

    # Create HBM memory controllers
    HBM_mem_ctrl = [
        HBMCtrl(
            dram=dram_a[i],
            dram_2=dram_b[i],
            disable_sanity_check=True,
            pseudo_channel_interleaving_bit=int(log(pc_size, 2))
        )
        for i in range(NUM_CHANNELS)
    ]

    # Assign address ranges from parsed NTS data
    for i, (channel_name, info) in enumerate(ordered_channels):
        addrs = info["addresses"]
        ctrl = HBM_mem_ctrl[i]
        dummy_pc_base = 0x800000000000 + (i * 0x2000)
        
        # Pseudo-channel 0 (dram)
        if len(addrs) >= 1:
            start_addr, size = addrs[0]
            ctrl.dram.range = AddrRange(start=start_addr, size=size)
            print(f"HBM Channel {channel_name} PC0: start={hex(start_addr)}, size={hex(size)}")
        
        # Pseudo-channel 1 (dram_2)
        if len(addrs) >= 2:
            start_addr, size = addrs[1]
            ctrl.dram_2.range = AddrRange(start=start_addr, size=size)
            print(f"HBM Channel {channel_name} PC1: start={hex(start_addr)}, size={hex(size)}")
        else:
            # Some Vivado topologies expose only one pseudo channel for a controller.
            # Give the unused backend channel a unique dummy range so gem5 does not
            # assign colliding defaults when multiple such controllers exist.
            ctrl.dram_2.range = AddrRange(start=dummy_pc_base, size=0x1000)

    # Connect controllers to memory bus. Do not use a python list literal to prevent `_parent` conflicts.
    for i, ctrl in enumerate(HBM_mem_ctrl):
        setattr(system, f"mem_ctrl_hbm_{i}", ctrl)
        ctrl.port = system.membus.mem_side_ports

    # Connect HBM NSU tiles to crossbar
    tile_indices = (
        list(hbm_tile_indices)
        if hbm_tile_indices is not None
        else [hbm_nsu_start_idx + i for i in range(num_hbm_nsu)]
    )

    if len(tile_indices) != num_hbm_nsu:
        raise ValueError(
            f"configure_hbm expected {num_hbm_nsu} HBM tile indices, got {len(tile_indices)}"
        )

    if hbm_tile_indices is not None and hasattr(system, "noc_tiles"):
        tile_container = system.noc_tiles
    else:
        tile_container = system.cpu

    for i, tile_idx in enumerate(tile_indices):
        hbm_nsu_tile = tile_container[tile_idx]
        hbm_nsu_tile.noc_hbm_port = system.membus.cpu_side_ports[i]
