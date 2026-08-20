# DDR Configuration Module
# This module contains functions to configure DDR memory for the NoC simulation

from math import log

from m5.objects import (
    DRAMInterface,
    MemInterface,
    AddrRange,
    MemCtrl,
    SystemXBar,
    DDR4_2400_8x8,
)


def configure_ddr(
    system, ddr_channels, num_ddr_nsu, ddr_nsu_start_idx, endpoint_tiles=None
):
    """
    Configure DDR memory controllers from NTS parameters.

    Args:
        system: The gem5 System object
        ddr_channels: Dictionary of DDR channel configurations from NTS parsing
                      Format: {channel_name: {"addresses": [(start, size), ...],
                                              "memory_params": {...}}}
        num_ddr_nsu: Number of DDR NSU tiles
        ddr_nsu_start_idx: Starting index of DDR NSU tiles in the endpoint-tile list
        endpoint_tiles: Optional list with one entry per NoC endpoint (see
            configure_hbm). If None, uses system.cpu or system.noc_tiles when set.
    """
    NUM_CHANNELS = len(ddr_channels)
    
    if NUM_CHANNELS == 0:
        return
    
    print(f"\n=== Configuring DDR Memory ===")
    print(f"Number of DDR channels: {NUM_CHANNELS}")
    
    # Create DDR crossbar (reuse HBM crossbar type for now)
    system.membus = SystemXBar()
    
    # Create DDR memory controllers
    ddr_mem_ctrls = []
    
    for i, (channel_name, info) in enumerate(ddr_channels.items()):
        addrs = info["addresses"]
        memory_params = info.get("memory_params", {})
        
        controller_type = memory_params.get("controller_type", "DDR4_SDRAM")
        speed_grade = memory_params.get("speed_grade", "DDR4-3200AC(24-24-24)")
        data_width = memory_params.get("data_width", 64)
        
        print(f"DDR Channel {channel_name}: type={controller_type}, speed={speed_grade}, width={data_width}")
        
        # Create DRAM interface
        # For now, use DDR4_2400_8x8 as the default. TODO: map speed_grade to correct type
        dram = DDR4_2400_8x8()
        
        # Create memory controller
        mem_ctrl = MemCtrl()
        mem_ctrl.dram = dram
        
        # Assign address range from parsed NTS data
        if len(addrs) >= 1:
            start_addr, size = addrs[0]
            mem_ctrl.dram.range = AddrRange(start=start_addr, size=size)
            print(f"  Address range: start={hex(start_addr)}, size={hex(size)}")
        
        # Attach to the system explicitly so the C++ SimObject tree knows the parent
        setattr(system, f"mem_ctrl_{i}", mem_ctrl)
        ddr_mem_ctrls.append(mem_ctrl)
    
    # Connect controllers to memory bus. Note: we don't use `system.mem_ctrls = ddr_mem_ctrls`
    # because assigning a raw python list to a SimObject that wasn't declared to have that
    # vector parameter causes an AttributeError. We already handled parenting with `setattr`.

    # Connect system port to membus (for loading binaries)
    system.system_port = system.membus.cpu_side_ports
    
    for ctrl in ddr_mem_ctrls:
        ctrl.port = system.membus.mem_side_ports
    
    # Build memory ranges from all controllers
    system.mem_ranges = [ctrl.dram.range for ctrl in ddr_mem_ctrls]
    
    tiles = endpoint_tiles
    if tiles is None:
        if hasattr(system, "noc_tiles"):
            tiles = system.noc_tiles
        else:
            c = system.cpu
            tiles = list(c) if isinstance(c, (list, tuple)) else [c]

    # Connect DDR NSU tiles to crossbar
    # Note: DDR NSUs use tileNSU_HBM since the port interface is identical
    for i in range(num_ddr_nsu):
        tile_idx = ddr_nsu_start_idx + i
        ddr_nsu_tile = tiles[tile_idx]
        ddr_nsu_tile.noc_hbm_port = system.membus.cpu_side_ports
        print(f"  Connected DDR NSU tile {tile_idx} to crossbar port (auto)")
    
    print(f"=== DDR Configuration Complete ===\n")
