# DDR Configuration Module
# This module contains functions to configure DDR memory for the NoC simulation

from m5.objects import (
    AddrRange,
    DDR3_1600_8x8,
    DDR3_2133_8x8,
    DDR4_2400_4x16,
    DDR4_2400_8x8,
    DDR4_2400_16x4,
    LPDDR3_1600_1x32,
    MemCtrl,
    SystemXBar,
)


def _select_dram_model(memory_params):
    controller_type = str(memory_params.get("controller_type", "DDR4_SDRAM")).upper()
    speed_grade = str(memory_params.get("speed_grade", "DDR4-3200AC(24-24-24)")).upper()
    data_width = int(memory_params.get("data_width", 64))

    if "LPDDR3" in controller_type:
        return LPDDR3_1600_1x32, "LPDDR3_1600_1x32"

    if "DDR3" in controller_type:
        if "2133" in speed_grade:
            return DDR3_2133_8x8, "DDR3_2133_8x8"
        return DDR3_1600_8x8, "DDR3_1600_8x8"

    if "DDR4" in controller_type:
        if data_width <= 32:
            return DDR4_2400_16x4, "DDR4_2400_16x4"
        if data_width >= 128:
            return DDR4_2400_4x16, "DDR4_2400_4x16"
        return DDR4_2400_8x8, "DDR4_2400_8x8"

    return DDR4_2400_8x8, "DDR4_2400_8x8"


def configure_ddr(system, ddr_channels, num_ddr_nsu, ddr_nsu_start_idx,
                  ddr_tile_indices=None, ddr_memctrl_clk_domain=None,
                  ddr_memctrl_clock_label=None):
    """
    Configure DDR memory controllers from NTS parameters.
    
    Args:
        system: The gem5 System object
        ddr_channels: Dictionary of DDR channel configurations from NTS parsing
                      Format: {channel_name: {"addresses": [(start, size), ...], 
                                              "memory_params": {...}}}
        num_ddr_nsu: Number of DDR NSU tiles
        ddr_nsu_start_idx: Starting index of DDR NSU tiles in system.cpu list
        ddr_tile_indices: Optional explicit list of system.cpu indices for DDR tiles
    """
    num_channels = len(ddr_channels)

    if num_channels == 0:
        return

    print(f"\n=== Configuring DDR Memory ===")
    print(f"Number of DDR channels: {num_channels}")

    system.membus = SystemXBar()
    if ddr_memctrl_clk_domain is not None:
        system.membus.clk_domain = ddr_memctrl_clk_domain
        print(
            f"DDR membus clock: "
            f"{ddr_memctrl_clock_label if ddr_memctrl_clock_label is not None else system.membus.clk_domain.clock}"
        )
    ddr_mem_ctrls = []

    for i, (channel_name, info) in enumerate(ddr_channels.items()):
        addrs = info["addresses"]
        memory_params = info.get("memory_params", {})

        controller_type = memory_params.get("controller_type", "DDR4_SDRAM")
        speed_grade = memory_params.get("speed_grade", "DDR4-3200AC(24-24-24)")
        data_width = memory_params.get("data_width", 64)

        dram_cls, dram_name = _select_dram_model(memory_params)
        print(
            f"DDR Channel {channel_name}: type={controller_type}, "
            f"speed={speed_grade}, width={data_width}, model={dram_name}"
        )

        dram = dram_cls()
        mem_ctrl = MemCtrl()
        mem_ctrl.dram = dram
        if ddr_memctrl_clk_domain is not None:
            mem_ctrl.clk_domain = ddr_memctrl_clk_domain
            print(
                f"  MemCtrl clock: "
                f"{ddr_memctrl_clock_label if ddr_memctrl_clock_label is not None else mem_ctrl.clk_domain.clock}"
            )

        if len(addrs) >= 1:
            start_addr, size = addrs[0]
            mem_ctrl.dram.range = AddrRange(start=start_addr, size=size)
            print(f"  Address range: start={hex(start_addr)}, size={hex(size)}")

        setattr(system, f"mem_ctrl_{i}", mem_ctrl)
        ddr_mem_ctrls.append(mem_ctrl)

    for ctrl in ddr_mem_ctrls:
        ctrl.port = system.membus.mem_side_ports

    system.mem_ranges = [ctrl.dram.range for ctrl in ddr_mem_ctrls]

    tile_indices = (
        list(ddr_tile_indices)
        if ddr_tile_indices is not None
        else [ddr_nsu_start_idx + i for i in range(num_ddr_nsu)]
    )

    if len(tile_indices) != num_ddr_nsu:
        raise ValueError(
            f"configure_ddr expected {num_ddr_nsu} DDR tile indices, got {len(tile_indices)}"
        )

    tile_container = getattr(system, "cpu", None)
    if tile_container is None:
        tile_container = getattr(system, "noc_tiles", None)
    if tile_container is None:
        raise AttributeError(
            "configure_ddr requires system.cpu or system.noc_tiles to locate DDR tiles"
        )

    for i, tile_idx in enumerate(tile_indices):
        ddr_nsu_tile = tile_container[tile_idx]
        ddr_nsu_tile.noc_hbm_port = system.membus.cpu_side_ports[i]
        print(f"  Connected DDR NSU tile {tile_idx} to crossbar port (auto)")

    print(f"=== DDR Configuration Complete ===\n")
