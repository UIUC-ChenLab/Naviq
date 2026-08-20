import json
import re
import sys
from pathlib import Path

import m5
import m5.objects as m5_objects
from m5.defines import buildEnv
from m5.objects import *
from m5.util import addToPath
from m5.util.convert import toFrequency

NOC_ROOT = Path(__file__).resolve().parents[1]
SETUP_DIR = Path(__file__).resolve().parent
REPO_ROOT = NOC_ROOT.parents[1]
WORKSPACE_ROOT = NOC_ROOT.parents[2]
for _path in (
    SETUP_DIR / "include",
    NOC_ROOT / "testing",
    NOC_ROOT / "ddr" / "setup",
    NOC_ROOT / "hbm" / "setup",
    REPO_ROOT / "configs",
):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)
addToPath(str(REPO_ROOT / "configs"))

from noc_config_funcs import (
    address_to_id,
    axis_tdest_name_to_id,
    build_hbm_settings_from_options,
    configure_topology_tracing,
    get_address_map,
    get_hbm_endpoint_kwargs,
    get_parser,
    source_address_to_id,
)
from noc_network import _has_simobject_param, create_network, init_network
from topologies.NoC_Topology import NoC_Topology


def get_hbm_configurator():
    try:
        from noc_hbm_config import configure_hbm
    except (ImportError, ModuleNotFoundError) as exc:
        fatal(
            "This topology contains HBM channels, but noc_hbm_config.py is "
            f"not importable in the current gem5 build: {exc}"
        )
    return configure_hbm


try:
    from noc_ddr_config import configure_ddr
except ModuleNotFoundError:
    configure_ddr = None


from setup_schema import ROLE_MASTER, load_setup, parse_param_overrides


buildEnv["PROTOCOL"] = "Garnet_standalone"


def repo_path(path_str):
    path = Path(path_str)
    if path.is_absolute():
        return path
    workspace_relative = WORKSPACE_ROOT / path
    if workspace_relative.exists():
        return workspace_relative
    repo_relative = REPO_ROOT / path
    if repo_relative.exists():
        return repo_relative
    return Path.cwd() / path


def setup_protocol_to_topology_protocol(protocol):
    return "AXI_STRM" if protocol == "axis" else "AXI_MM"


def setup_role_to_topology_role(role):
    return "Master" if role == ROLE_MASTER else "Slave"


def fatal(message):
    m5.fatal(message)


def parse_declared_hbm_endpoint(endpoint_ref):
    component_id = endpoint_ref.split(".", 1)[0]
    match = re.fullmatch(r"hbm(\d+)_port([0-3])", component_id)
    if not match:
        return None
    controller_id = int(match.group(1))
    port_id = int(match.group(2))
    return controller_id, port_id, port_id // 2


def axis_widths(params):
    return (
        int(params.get("data_width", 512)),
        int(params.get("tid_width", params.get("id_width", 16))),
        int(params.get("tdest_width", params.get("dest_width", 12))),
    )


def make_controller(controller_id, endpoint_name, ep, params, noc, record_mode):
    if ep.protocol == "AXI_STRM":
        data_width, id_width, dest_width = axis_widths(params)
        return NocInterface(
            id=controller_id,
            version=controller_id,
            endpoint_name=endpoint_name,
            protocol="AXIS",
            role=ep.role,
            noc_system=noc,
            axis_data_width=data_width,
            axis_id_width=id_width,
            axis_dest_width=dest_width,
            record_mode=record_mode,
        )

    return NocInterface(
        id=controller_id,
        version=controller_id,
        endpoint_name=endpoint_name,
        protocol="AXIMM",
        role=ep.role,
        noc_system=noc,
        record_mode=record_mode,
    )


def resolved_setup_paths(options):
    missing = []
    if not options.connections_json:
        missing.append("--connections-json")
    if not options.placement_json:
        missing.append("--placement-json")
    if not options.noc_topology:
        missing.append("--noc-topology")
    if missing:
        fatal("Missing required option(s): " + ", ".join(missing))

    connections_path = repo_path(options.connections_json)
    placement_path = repo_path(options.placement_json)
    if not connections_path.exists():
        fatal(f"--connections-json does not exist: {connections_path}")
    if not placement_path.exists():
        fatal(f"--placement-json does not exist: {placement_path}")
    return connections_path, placement_path


def _parse_intlike(value):
    if isinstance(value, bool):
        fatal(f"Address values must be integer-like, got boolean {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            fatal(f"Address values must be integer-like, got {value!r}")
    fatal(f"Address values must be integer-like, got {value!r}")


def _first_config_value(config, keys):
    for key in keys:
        value = config.get(key)
        if value not in (None, ""):
            return value
    return None


def _apply_aximm_master_address_config(params, component):
    for port in component.ports:
        if port.role != ROLE_MASTER or port.protocol != "aximm":
            continue

        config = port.config
        base = _first_config_value(
            config,
            (
                "base_addr",
                "base_address",
                "write_base_addr",
                "write_base_address",
            ),
        )
        high = _first_config_value(
            config,
            (
                "max_addr",
                "max_address",
                "high_addr",
                "high_address",
                "write_high_addr",
                "write_high_address",
            ),
        )
        size = _first_config_value(config, ("size", "address_size"))

        if base is not None:
            base_int = _parse_intlike(base)
            params.setdefault("base_addr", base_int)
            if high is not None:
                params.setdefault("max_addr", _parse_intlike(high))
            elif size is not None:
                params.setdefault("max_addr", base_int + _parse_intlike(size) - 1)

    for key in ("base_addr", "max_addr"):
        if key in params:
            params[key] = _parse_intlike(params[key])


def _fixed_transaction_increment(params, fallback):
    min_size = params.get("min_transaction_size_bytes")
    max_size = params.get("max_transaction_size_bytes")
    if min_size is None or max_size is None:
        return fallback

    min_size = _parse_intlike(min_size)
    max_size = _parse_intlike(max_size)
    if min_size > 0 and min_size == max_size:
        return min_size
    return fallback


def _apply_aximm_slave_address_config(params, component):
    for port in component.ports:
        if port.role == ROLE_MASTER or port.protocol != "aximm":
            continue

        config = port.config
        base = _first_config_value(config, ("base_addr", "base_address"))
        size = _first_config_value(
            config,
            ("memory_size", "size", "address_size"),
        )
        high = _first_config_value(
            config,
            ("high_addr", "high_address", "max_addr", "max_address"),
        )

        if base is not None:
            params.setdefault("base_addr", _parse_intlike(base))
        if size is not None:
            params.setdefault("memory_size", _parse_intlike(size))
        elif base is not None and high is not None:
            base_int = _parse_intlike(base)
            params.setdefault("memory_size", _parse_intlike(high) - base_int + 1)

    for key in ("base_addr", "memory_size"):
        if key in params:
            params[key] = _parse_intlike(params[key])


def _target_windows_for_master(component_id, addrs, params):
    windows = list(zip(addrs[::2], addrs[1::2]))
    if not windows:
        return [], []

    if "base_addr" not in params and "max_addr" not in params:
        return [start for start, _ in windows], [size for _, size in windows]

    master_base = _parse_intlike(params.get("base_addr", windows[0][0]))
    raw_max = params.get("max_addr")
    if raw_max is None:
        master_high = max(start + size - 1 for start, size in windows)
    else:
        master_high = _parse_intlike(raw_max)

    clipped_starts = []
    clipped_sizes = []
    for start, size in windows:
        window_high = start + size - 1
        clipped_start = max(start, master_base)
        clipped_high = min(window_high, master_high)
        if clipped_start <= clipped_high:
            clipped_starts.append(clipped_start)
            clipped_sizes.append(clipped_high - clipped_start + 1)

    if not clipped_starts:
        fatal(
            f"AxiRandomTrafficGenerator '{component_id}' address range "
            f"[0x{master_base:x}, 0x{master_high:x}] does not overlap any "
            "target NSU address window."
        )

    return clipped_starts, clipped_sizes


def build_system_from_setup(options, setup, topology, ncr_filename):
    system = System()
    tiles = []
    name_to_id = {}
    endpoint_to_tile_index = {}
    node_conn_names = []
    endpoint_records = []
    noc_clock_mhz = int(toFrequency(options.noc_clock) / 1e6)

    def add_component_node(component, endpoint_infos, port_clock_domains):
        node_cls = getattr(m5_objects, component.node_type, None)
        if node_cls is None:
            fatal(f"Unknown runtime node type '{component.node_type}' in m5.objects")

        if endpoint_infos and all(ep.comp_type == "DDRC" for ep in endpoint_infos):
            node_cls = getattr(m5_objects, "tileNSU_HBM", node_cls)

        params = dict(component.params)
        params.pop("clock_domain_mhz", None)

        if component.node_type in (
            "AxiRandomTrafficGenerator",
            "AxiHandshakeStressGenerator",
        ):
            _apply_aximm_master_address_config(params, component)

            data_width_bits = int(params.get("data_width", 512))
            beat_size_bytes = int(params.get("beat_size_bytes", 0))
            if beat_size_bytes <= 0:
                beat_size_bytes = max(1, data_width_bits // 8)

            # HBM NMUs only accept 32..256-bit AXI beats (4..32 bytes).
            if any(ep.comp_type == "HBM_NMU" for ep in endpoint_infos):
                if beat_size_bytes < 4 or beat_size_bytes > 32:
                    fatal(
                        f"AxiRandomTrafficGenerator '{component.component_id}' targets an HBM NMU, "
                        f"but beat_size_bytes={beat_size_bytes} is outside [4, 32] "
                        f"(i.e., 32..256-bit beats)."
                    )

            increment = _fixed_transaction_increment(params, beat_size_bytes)
            params.setdefault("address_distribution", "INCREMENT")
            params.setdefault("align_addresses", increment != beat_size_bytes)
            params.setdefault("address_increment", increment)
        elif component.node_type == "BramEndpoint":
            _apply_aximm_slave_address_config(params, component)

        for endpoint_info in endpoint_infos:
            if endpoint_info.protocol == "AXI_MM" and endpoint_info.role == "Master":
                addrs = topology.src_addr_options.get(endpoint_info.logical_name, [])
                if addrs and "nsu_min_addrs" not in params and "nsu_address_spaces" not in params:
                    starts, sizes = _target_windows_for_master(
                        component.component_id,
                        addrs,
                        params,
                    )
                    params["nsu_min_addrs"] = starts
                    params["nsu_address_spaces"] = sizes
                    params.setdefault("base_addr", starts[0])
                    params.setdefault("max_addr", starts[0] + sizes[0] - 1)
            if endpoint_info.comp_type == "HBMMC":
                if len(endpoint_infos) != 1:
                    fatal(
                        f"HBM runtime nodes currently require one endpoint per component; "
                        f"'{component.component_id}' has {len(endpoint_infos)}."
                    )
                for key, value in get_hbm_endpoint_kwargs(endpoint_info, topology).items():
                    params.setdefault(key, value)

        params["clockDomains"] = port_clock_domains
        params["port_endpoint_names"] = [ep.logical_name for ep in endpoint_infos]

        tile_obj = node_cls(**params)
        tiles.append(tile_obj)
        tile_index = len(tiles) - 1
        for ep in endpoint_infos:
            endpoint_to_tile_index[ep.logical_name] = tile_index
        node_conn_names.append([ep.logical_name for ep in endpoint_infos])
        return tile_obj

    controller_id = 0
    for component in setup.components:
        endpoint_infos = []
        port_clock_domains = []
        for port in component.ports:
            physical = setup.placement_for(port.endpoint)
            if not physical:
                fatal(f"No placement found for endpoint '{port.endpoint}'")

            declared_hbm = parse_declared_hbm_endpoint(port.endpoint)
            if declared_hbm is not None:
                declared_controller, declared_port, declared_pc = declared_hbm
                ep = topology.get_hbm_endpoint(
                    physical,
                    declared_controller,
                    f"PORT{declared_port}",
                )
            else:
                ep = topology.get_endpoint_by_physical(physical)
            if ep is None:
                fatal(
                    f"Placement for '{port.endpoint}' uses physical endpoint '{physical}', "
                    "but that endpoint was not found in the generated NTS/NCR topology."
                )

            expected_protocol = setup_protocol_to_topology_protocol(port.protocol)
            expected_role = setup_role_to_topology_role(port.role)
            if ep.protocol != expected_protocol or ep.role != expected_role:
                fatal(
                    f"Endpoint '{port.endpoint}' was declared as {expected_role} "
                    f"{expected_protocol}, but placement '{physical}' maps to "
                    f"{ep.role} {ep.protocol} ({ep.logical_name})."
                )

            if declared_hbm is not None:
                declared_controller, declared_port, declared_pc = declared_hbm
                if ep.controller_index != declared_controller or ep.port_name != f"PORT{declared_port}":
                    fatal(
                        f"HBM endpoint '{port.endpoint}' expected controller {declared_controller} "
                        f"port {declared_port}, but placement '{physical}' resolved to "
                        f"{ep.controller_name or '<unknown>'} {ep.port_name or '<unknown>'}."
                    )
                if ep.pseudo_channel != declared_pc:
                    fatal(
                        f"HBM endpoint '{port.endpoint}' expected pseudo channel {declared_pc}, "
                        f"but topology resolved pseudo channel {ep.pseudo_channel}."
                    )

            if ep.logical_name in name_to_id:
                fatal(
                    f"Logical endpoint '{ep.logical_name}' is already assigned. "
                    "Each NoC endpoint can only be connected once."
                )

            name_to_id[ep.logical_name] = controller_id
            endpoint_records.append((ep.logical_name, ep, component.params))
            endpoint_infos.append(ep)
            port_clock_domains.append(int(port.config.get(
                "clock_domain_mhz",
                component.params.get("clock_domain_mhz", noc_clock_mhz),
            )))
            controller_id += 1

        add_component_node(component, endpoint_infos, port_clock_domains)

    system.cpu = tiles

    num_aximm_nsu = len([name for name in name_to_id if name in topology.aximm_nsu])
    num_aximm_nmu = len([name for name in name_to_id if name in topology.aximm_nmu])
    num_axis_nsu = len([name for name in name_to_id if name in topology.axis_nsu])
    num_axis_nmu = len([name for name in name_to_id if name in topology.axis_nmu])
    num_hbm_nsu = len([name for name in name_to_id if name in topology.hbm_nsu])
    num_hbm_nmu = len([name for name in name_to_id if name in topology.hbm_nmu])
    num_ddr_nsu = len([name for name in name_to_id if name in topology.ddr_nsu])
    total_num_aximm_nsu = num_aximm_nsu + num_hbm_nsu + num_ddr_nsu
    total_num_aximm_nmu = num_aximm_nmu + num_hbm_nmu

    print(
        "Num aximm nsu:", num_aximm_nsu,
        "aximm nmu:", num_aximm_nmu,
        "axis nsu:", num_axis_nsu,
        "axis nmu:", num_axis_nmu,
        "hbm nsu:", num_hbm_nsu,
        "hbm nmu:", num_hbm_nmu,
        "ddr nsu:", num_ddr_nsu,
    )

    if topology.hbm_channels:
        hbm_tile_indices = [
            endpoint_to_tile_index[name]
            for name in name_to_id
            if name in topology.hbm_nsu
        ]
        configure_hbm = get_hbm_configurator()
        configure_hbm(
            system,
            topology.hbm_channels,
            num_hbm_nsu,
            num_aximm_nsu,
            hbm_tile_indices=hbm_tile_indices,
        )

    if topology.ddr_channels:
        if configure_ddr is None:
            fatal(
                "This topology contains DDR channels, but noc_ddr_config.py is "
                "not importable in the current worktree."
            )
        ddr_nsu_start_idx = num_aximm_nsu + num_hbm_nsu
        ddr_tile_indices = [
            endpoint_to_tile_index[name]
            for name in name_to_id
            if name in topology.ddr_nsu
        ]
        configure_ddr(
            system,
            topology.ddr_channels,
            num_ddr_nsu,
            ddr_nsu_start_idx,
            ddr_tile_indices=ddr_tile_indices,
        )

    system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)
    system.clk_domain = SrcClockDomain(
        clock=options.sys_clock,
        voltage_domain=system.voltage_domain,
    )

    system.noc = NocSystem()
    noc = system.noc
    network, IntLinkClass, ExtLinkClass, RouterClass = create_network(options, noc)
    noc.network = network
    network.routing_algorithm = options.routing_algorithm
    network.number_of_virtual_networks = options.number_of_virtual_networks
    if _has_simobject_param(network.__class__, "enable_detailed_metrics"):
        network.enable_detailed_metrics = not getattr(
            options, "disable_detailed_metrics", False
        )

    filtered_address_map = [
        entry for entry in topology.address_name_map if entry[2] in name_to_id
    ]
    network.address_map_json = json.dumps(address_to_id(filtered_address_map, name_to_id))
    filtered_source_routes = {
        src: [route for route in routes if route[2] in name_to_id]
        for src, routes in topology.source_address_routes.items()
        if src in name_to_id
    }
    network.source_address_map_json = json.dumps(
        source_address_to_id(filtered_source_routes, name_to_id)
    )
    axis_tdest_id_map = axis_tdest_name_to_id(topology.axis_nmu_to_dest_names, name_to_id)
    print("\n=== AXIS TDEST Mapping Summary ===")
    print(f"Raw name mapping: {topology.axis_nmu_to_dest_names}")
    print(f"ID-based mapping: {axis_tdest_id_map}")
    for nmu_id, tdest_map in axis_tdest_id_map.items():
        print(f"  NMU {nmu_id}: tdest -> dest_ni = {tdest_map}")
    print("===================================\n")
    network.axis_tdest_map_json = json.dumps(axis_tdest_id_map)

    controllers = []
    for endpoint_name, ep, params in endpoint_records:
        controller_id = name_to_id[endpoint_name]
        controllers.append(
            make_controller(controller_id, endpoint_name, ep, params, noc, options.record_mode)
        )

    noc.tile_controllers = controllers

    topology_helper = NoC_Topology(controllers)
    topology_helper.set_file_path(ncr_filename)
    topology_helper.set_node_dict(name_to_id)
    configure_topology_tracing(topology_helper, options)
    topology_helper.makeTopology(options, network, IntLinkClass, ExtLinkClass, RouterClass)

    init_network(
        options,
        network,
        num_aximm_nsu,
        num_aximm_nmu,
        num_hbm_nsu,
        num_hbm_nmu,
        num_axis_nsu,
        num_axis_nmu,
        num_ddr_nsu,
        controllers=controllers,
    )

    noc.num_of_sequencers = 0
    noc.number_of_virtual_networks = 5
    network.num_aximm_nmu = total_num_aximm_nmu
    network.num_aximm_nsu = total_num_aximm_nsu

    for tile, conn_names in zip(tiles, node_conn_names):
        if "tile_controller" in getattr(tile, "_params", {}) and conn_names:
            tile.tile_controller = controllers[name_to_id[conn_names[0]]]

    adjacency_list = []
    adjacency_index = []
    for conn_names in node_conn_names:
        adjacency_index.append(len(adjacency_list))
        for ni_name in conn_names:
            adjacency_list.append(name_to_id[ni_name])

    system.control = Control(
        noc_interfaces=controllers,
        nodes=tiles,
        adjacency_list=adjacency_list,
        adjacency_index=adjacency_index,
        sim_cycles=options.sim_cycles,
        noc_clock_domain_mhz=noc_clock_mhz,
    )

    system.noc.clk_domain = SrcClockDomain(
        clock=options.noc_clock,
        voltage_domain=system.voltage_domain,
    )
    for tile in system.cpu:
        tile.clk_domain = system.clk_domain

    return system


def main():
    options = get_parser()
    if options.network != "nocgarnet":
        fatal(f"Unsupported network type: {options.network}")

    connections_path, placement_path = resolved_setup_paths(options)
    param_overrides = parse_param_overrides(options.param)
    setup = load_setup(str(connections_path), str(placement_path), param_overrides)

    # Topology inputs: default to --noc-topology basename, but allow explicit overrides.
    topology_base = options.noc_topology
    nts_filename = options.nts_file or (topology_base + ".nts")
    ncr_filename = options.ncr_file or (topology_base + ".ncr")
    if not Path(nts_filename).exists():
        fatal(f"No NTS file found: {nts_filename}")
    if not Path(ncr_filename).exists():
        fatal(f"No NCR file found: {ncr_filename}")

    topology = get_address_map(
        nts_filename,
        ncr_filename,
        build_hbm_settings_from_options(options, setup.global_settings.get("hbm_settings")),
    )
    system = build_system_from_setup(options, setup, topology, ncr_filename)

    root = Root(full_system=False, system=system)
    root.system.mem_mode = "timing"
    m5.ticks.setGlobalFrequency("1ps")
    m5.instantiate()
    exit_event = m5.simulate(options.abs_max_tick)
    print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())


main()
