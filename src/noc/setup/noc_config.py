import json
import os
import sys
from pathlib import Path

NOC_ROOT = Path(__file__).resolve().parents[1]
SETUP_DIR = Path(__file__).resolve().parent
REPO_ROOT = NOC_ROOT.parents[1]
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

from math import log

from noc_network import *

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.objects import Port
from m5.util import addToPath
from m5.util.convert import toFrequency

import gem5
from gem5.components import *
if ("--print-paths" not in sys.argv) and ("--print-noc-probe-help" not in sys.argv):
    try:
        from noc_graphs import *
    except ModuleNotFoundError as e:
        if e.name not in {"matplotlib", "numpy", "pandas"}:
            raise

# so it can find topologies and network
addToPath(str(REPO_ROOT / "configs"))

# from noc_config_funcs import (
#     EndpointInfo,
#     TopologyInfo,
#     _get_endpoint_kwargs,
#     address_to_id,
#     configure_topology_tracing,
#     axis_tdest_name_to_id,
#     get_parser,
#     get_address_map,
#     build_hbm_settings_from_options,
#     source_address_to_id,
#     ins
# )
from noc_config_funcs import *
from noc_config_funcs import (
    _get_endpoint_kwargs,
    get_hbm_endpoint_kwargs,
    print_noc_interface_snooper_help,
)
from noc_hbm_config import configure_hbm
from noc_ddr_config import configure_ddr
from setup_schema import HBM_ENDPOINT_RE, ROLE_MASTER, ROLE_SLAVE, load_setup
from topologies.Mesh_XY import Mesh_XY
from topologies.NoC_Topology import NoC_Topology


class NodeConnection:
    """
    Structure representing a connection for a NoC node.

    Attributes:
        connectTo (str): Either "NMU" or "NSU".
        clock_domain (int): Clock frequency in MHz.
        connectLoc (str): Physical location (e.g. NOC_NMU512_X0Y0) from the NCR file.
        connectPort (str | None): Optional logical sub-port name for shared physical endpoints.
        protocol (str): "AXIMM" or "AXIS".
    """

    def __init__(
        self, connectTo, clock_domain, connectLoc, protocol, connectPort=None
    ):
        self.connectTo = connectTo  # str, should be either "NMU" or "NSU"
        self.clock_domain = clock_domain  # int, in MHz
        self.connectLoc = (
            connectLoc  # str, loc of the target NMU/NSU to connect to
        )
        self.connectPort = connectPort  # str|None, e.g. PORT0 for HBM/DDR multi-port endpoints
        self.protocol = protocol  # str, protocol of the connection either "AXIMM" or "AXIS"

    def __repr__(self):
        return (
            f"NodeConnection(connectTo='{self.connectTo}', clock_domain={self.clock_domain}, "
            f"connectLoc='{self.connectLoc}', connectPort='{self.connectPort}', protocol='{self.protocol}')"
        )


class Node:
    """
    Structure representing a NoC Node containing a list of NodeConnections.

    Attributes:
        node_type: Class to instantiate (e.g. AxisRandomTrafficGenerator).
        connections: List of NodeConnection.
        clock_domains (list of int): List of clock frequencies in MHz.
        parameters: Dict of constructor kwargs (from JSON); required when instantiating.
    """

    def __init__(self, node_type, connections=None, parameters=None):
        self.node_type = node_type
        self.clock_domains = []
        self.connections = connections if connections is not None else []
        self.parameters = parameters  # from JSON; used when instantiating

        for connection in connections:
            self.clock_domains.append(connection.clock_domain)

    def add_connection(self, node_connection):
        """Add a NodeConnection to this node's connections list."""
        self.connections.append(node_connection)
        self.clock_domains.append(node_connection.clock_domain)

    def getNumNSU(self):
        """Return the number of connections to NSU."""
        return sum(1 for conn in self.connections if conn.connectTo == "NSU")

    def getNumNMU(self):
        """Return the number of connections to NMU."""
        return sum(1 for conn in self.connections if conn.connectTo == "NMU")

    def __repr__(self):
        return f"Node( node_type={self.node_type}, clock_domains={self.clock_domains}, connections={self.connections} parameters={self.parameters} )\n"


# Map node_type string from JSON to Python class
NODE_TYPE_MAP = {
    "AxisRandomTrafficGenerator": AxisRandomTrafficGenerator,
    "AxisBuggyGenerator": AxisBuggyGenerator,
    "AxisSinkNode": AxisSinkNode,
    "AxiRandomTrafficGenerator": AxiRandomTrafficGenerator,
    "AxiHandshakeStressGenerator": AxiHandshakeStressGenerator,
    "AxisFifoNode": AxisFifoNode,
    "BramEndpoint": BramEndpoint,
    "BramBuggyNode": BramBuggyNode,
    "tileNSU_HBM": tileNSU_HBM,
    "SynchronizerNode": SynchronizerNode
}


def load_nodes_from_json(node_config_path, options=None, allow_invalid_noc_probes: bool = False):
    """Load node configuration from JSON.

    Returns:
        tuple: (nodes, record_nps, record_nps_gap_cycles,
        record_mode_interfaces, noc_probes). record_nps,
        record_nps_gap_cycles, and record_mode_interfaces come from optional
        top-level JSON keys (defaults 0, 200, and 0). Each node entry must
        have: node_type, parameters, and connections (list of connection
        objects with connectTo, clock_domain, connectLoc, protocol).
    """
    if not os.path.exists(node_config_path):
        m5.fatal(f"Node config file not found: {node_config_path}")
    with open(node_config_path) as f:
        data = json.load(f)
    record_nps = int(data.get("record_nps", 0))
    record_nps_gap_cycles = int(data.get("record_nps_gap_cycles", 200))
    record_mode_interfaces = int(data.get("record_mode_interfaces", 0))
    nodes = []
    for entry in data.get("nodes", []):
        node_type_str = entry.get("node_type")
        if node_type_str not in NODE_TYPE_MAP:
            m5.fatal(
                "Unknown node_type '{}' in config. Known: {}".format(
                    node_type_str, list(NODE_TYPE_MAP.keys())
                )
            )
        node_type = NODE_TYPE_MAP[node_type_str]
        parameters = dict(entry.get("parameters") or {})
        if options is not None:
            packet_count = max(int(getattr(options, "num_packets", 0)), 0)
            if (
                node_type_str in ("AxisRandomTrafficGenerator", "AxisBuggyNode")
                and packet_count > 0
            ):
                parameters["max_packets"] = packet_count
            elif node_type_str in (
                "AxiRandomTrafficGenerator",
                "AxiHandshakeStressGenerator",
            ) and packet_count > 0:
                parameters["max_write_commands"] = packet_count
            elif node_type_str in ("AxisSinkNode", "AxisFifoNode") and packet_count > 0:
                parameters["expected_packets"] = packet_count
        conn_list = entry.get("connections")
        if not conn_list:
            m5.fatal(
                "Missing 'connections' (list) for node_type '{}' in config. "
                "Each connection must have: connectTo, clock_domain, connectLoc, protocol.".format(
                    node_type_str
                )
            )
        connections = []
        for conn_entry in conn_list:
            for key in ("connectTo", "clock_domain", "connectLoc", "protocol"):
                if key not in conn_entry:
                    m5.fatal(
                        "Connection for node_type '{}' must have '{}'.".format(
                            node_type_str, key
                        )
                    )
            connections.append(
                NodeConnection(
                    connectTo=conn_entry["connectTo"],
                    clock_domain=conn_entry["clock_domain"],
                    connectLoc=conn_entry["connectLoc"],
                    connectPort=conn_entry.get("connectPort"),
                    protocol=conn_entry["protocol"],
                )
            )
        nodes.append(
            Node(
                node_type=node_type,
                connections=connections,
                parameters=parameters,
            )
        )
    # NOTE: `--print-paths` is a structural introspection mode and should still
    # run even if noc_probes entries are invalid. In that case we return the raw
    # value and defer reporting to a non-fatal validator.
    noc_probes = data.get("noc_probes", [])
    if noc_probes is None:
        noc_probes = []
    if noc_probes is not None and not isinstance(noc_probes, list):
        if allow_invalid_noc_probes:
            # Keep the raw invalid value so print-paths can report it.
            return nodes, record_nps, record_nps_gap_cycles, record_mode_interfaces, noc_probes
        m5.fatal("'noc_probes' must be a list when present.")
    return nodes, record_nps, record_nps_gap_cycles, record_mode_interfaces, noc_probes


def resolve_topology_bundle(topology_path):
    """Resolve paths for a topology bundle directory.

    Default layout: ``<bundle>/<basename>`` where bundle directory name equals
    the file stem (``my_topo/my_topo.conn.json``).

    Alternate layout allowed: bundle directory contain exactly one ``*.conn.json``
    whose stem differs from the directory name (e.g. ``hbm_1stack_16GB/full/``
    holding ``hbm_1stack_16GB.conn.json``).
    """
    folder = Path(topology_path)
    if not folder.is_dir():
        m5.fatal(
            f"--noc-topology must be an existing directory: {topology_path}"
        )

    basename = folder.name

    conn_default = folder / f"{basename}.conn.json"
    if not conn_default.is_file():
        conn_candidates = sorted(folder.glob("*.conn.json"))
        if len(conn_candidates) != 1:
            choices = conn_default
            fatal_extra = ""
            if len(conn_candidates) > 1:
                fatal_extra = (
                    f"; found multiple *.conn.json in {folder}: "
                    f"{[p.name for p in conn_candidates]}"
                )
            m5.fatal(
                "Missing required topology file: "
                f"{choices}"
                + fatal_extra
            )
        conn_name = conn_candidates[0].name
        if not conn_name.endswith(".conn.json"):
            m5.fatal(f"Unsupported connections filename shape: {conn_name}")
        basename = conn_name[: -len(".conn.json")]

    def require_file(suffix):
        path = folder / f"{basename}{suffix}"
        if not path.is_file():
            m5.fatal(f"Missing required topology file: {path}")
        return os.fspath(path)

    opts_path = folder / f"{basename}.opts.json"
    opts_json_path = os.fspath(opts_path) if opts_path.is_file() else None

    return (
        require_file(".conn.json"),
        require_file(".place.json"),
        require_file(".nts"),
        require_file(".ncr"),
        opts_json_path,
    )


def load_topology_opts(opts_json_path):
    """Load optional simulation/tracing options from <basename>.opts.json."""
    if opts_json_path is None:
        return {}
    with open(opts_json_path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        m5.fatal(f"opts JSON must be an object: {opts_json_path}")
    return data


def load_simulation_opts(opts_data, allow_invalid_noc_probes: bool = False):
    """Tracing / probe settings formerly stored at the top of node_config JSON."""
    record_nps = int(opts_data.get("record_nps", 0))
    record_nps_gap_cycles = int(opts_data.get("record_nps_gap_cycles", 200))
    record_mode_interfaces = int(opts_data.get("record_mode_interfaces", 0))
    record_hbm = int(opts_data.get("record_hbm", 0))
    record_hbm_gap_cycles = int(
        opts_data.get("record_hbm_gap_cycles", record_nps_gap_cycles)
    )
    noc_probes = opts_data.get("noc_probes", [])
    if noc_probes is None:
        noc_probes = []
    if noc_probes is not None and not isinstance(noc_probes, list):
        if allow_invalid_noc_probes:
            return (
                record_nps,
                record_nps_gap_cycles,
                record_mode_interfaces,
                record_hbm,
                record_hbm_gap_cycles,
                noc_probes,
            )
        m5.fatal("'noc_probes' must be a list when present in the opts JSON.")
    return (
        record_nps,
        record_nps_gap_cycles,
        record_mode_interfaces,
        record_hbm,
        record_hbm_gap_cycles,
        noc_probes,
    )


def apply_hbm_stats_recording(nodes, record_hbm, record_hbm_gap_cycles):
    """Enable per-port HBM stats CSV on tileNSU_HBM nodes when record_hbm is set."""
    if not record_hbm:
        return
    from noc_trace_paths import runtime_trace_artifact_path

    stats_path = runtime_trace_artifact_path("hbm_stats.csv")
    for node in nodes:
        if node.node_type != tileNSU_HBM:
            continue
        node.parameters["hbm_stats_csv_path"] = stats_path
        node.parameters["hbm_stats_sample_gap_cycles"] = int(record_hbm_gap_cycles)


def _setup_protocol_to_connection_protocol(protocol):
    normalized = str(protocol).lower()
    if normalized == "axis":
        return "AXIS"
    if normalized == "aximm":
        return "AXIMM"
    m5.fatal(
        f"Unsupported setup port protocol '{protocol}'. Expected 'axis' or 'aximm'."
    )


def _hbm_connect_port_for_component(component_id: str) -> str | None:
    """Map hbm<ctrl>_port<N> component ids to NCR/NTS port names (PORT0..PORT3)."""
    match = HBM_ENDPOINT_RE.fullmatch(component_id)
    if not match:
        return None
    return f"PORT{match.group(2)}"


def _parse_intlike_setup_value(value):
    if isinstance(value, bool):
        m5.fatal(f"Address values must be integer-like, got boolean {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            m5.fatal(f"Address values must be integer-like, got {value!r}")
    m5.fatal(f"Address values must be integer-like, got {value!r}")


def _first_setup_config_value(config, keys):
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
        base = _first_setup_config_value(
            config,
            (
                "base_addr",
                "base_address",
                "write_base_addr",
                "write_base_address",
            ),
        )
        high = _first_setup_config_value(
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
        size = _first_setup_config_value(config, ("size", "address_size"))

        if base is not None:
            base_int = _parse_intlike_setup_value(base)
            params.setdefault("base_addr", base_int)
            if high is not None:
                params.setdefault("max_addr", _parse_intlike_setup_value(high))
            elif size is not None:
                params.setdefault(
                    "max_addr",
                    base_int + _parse_intlike_setup_value(size) - 1,
                )

    for key in ("base_addr", "max_addr"):
        if key in params:
            params[key] = _parse_intlike_setup_value(params[key])


def _apply_aximm_slave_address_config(params, component):
    for port in component.ports:
        if port.role == ROLE_MASTER or port.protocol != "aximm":
            continue

        config = port.config
        base = _first_setup_config_value(config, ("base_addr", "base_address"))
        size = _first_setup_config_value(
            config,
            ("memory_size", "size", "address_size"),
        )
        high = _first_setup_config_value(
            config,
            ("high_addr", "high_address", "max_addr", "max_address"),
        )

        if base is not None:
            params.setdefault("base_addr", _parse_intlike_setup_value(base))
        if size is not None:
            params.setdefault("memory_size", _parse_intlike_setup_value(size))
        elif base is not None and high is not None:
            base_int = _parse_intlike_setup_value(base)
            params.setdefault(
                "memory_size",
                _parse_intlike_setup_value(high) - base_int + 1,
            )

    for key in ("base_addr", "memory_size"):
        if key in params:
            params[key] = _parse_intlike_setup_value(params[key])


def _target_windows_for_master(component_id, addr_info, parameters):
    windows = list(zip(addr_info[::2], addr_info[1::2]))
    if not windows:
        return [], []

    if "base_addr" not in parameters and "max_addr" not in parameters:
        return [start for start, _ in windows], [size for _, size in windows]

    master_base = _parse_intlike_setup_value(
        parameters.get("base_addr", windows[0][0])
    )
    raw_max = parameters.get("max_addr")
    if raw_max is None:
        master_high = max(start + size - 1 for start, size in windows)
    else:
        master_high = _parse_intlike_setup_value(raw_max)

    starts = []
    sizes = []
    for start, size in windows:
        window_high = start + size - 1
        clipped_start = max(start, master_base)
        clipped_high = min(window_high, master_high)
        if clipped_start <= clipped_high:
            starts.append(clipped_start)
            sizes.append(clipped_high - clipped_start + 1)

    if not starts:
        m5.fatal(
            "AxiRandomTrafficGenerator '{}' address range [0x{:x}, 0x{:x}] "
            "does not overlap any target NSU address window.".format(
                component_id,
                master_base,
                master_high,
            )
        )

    return starts, sizes


def _endpoint_pairing_key(ep, conn) -> str | tuple:
    """
    Unique key for one NMU/NSU hookup. HBM_MC tiles expose multiple AXI ports at
    the same physical location; pair on (tile, port) instead of logical name alone.
    """
    if conn.connectLoc.startswith("HBM_MC_"):
        if conn.connectPort:
            return (conn.connectLoc, conn.connectPort)
        return ep.logical_name
    return ep.logical_name


def load_nodes_from_setup(setup, topology=None, options=None):
    """Build runtime Node objects from a v2 conn/place setup description."""
    noc_clock_mhz = 500
    if options is not None:
        noc_clock_mhz = int(toFrequency(options.noc_clock) / 1e6)

    nodes = []
    for component in setup.components:
        node_type_str = component.node_type
        if node_type_str not in NODE_TYPE_MAP:
            m5.fatal(
                "Unknown node_type '{}' in connections JSON. Known: {}".format(
                    node_type_str, list(NODE_TYPE_MAP.keys())
                )
            )
        node_type = NODE_TYPE_MAP[node_type_str]
        parameters = dict(component.params)
        parameters.pop("clock_domain_mhz", None)
        if node_type in (AxiRandomTrafficGenerator, AxiHandshakeStressGenerator):
            _apply_aximm_master_address_config(parameters, component)
        if node_type is BramEndpoint:
            _apply_aximm_slave_address_config(parameters, component)

        connections = []
        endpoint_infos = []
        for port in component.ports:
            physical = setup.placement_for(port.endpoint)
            if not physical:
                m5.fatal(
                    f"No placement found for endpoint '{port.endpoint}' in placement JSON."
                )
            connect_to = "NMU" if port.role == ROLE_MASTER else "NSU"
            protocol = _setup_protocol_to_connection_protocol(port.protocol)
            clock_domain_mhz = int(
                port.config.get(
                    "clock_domain_mhz",
                    component.params.get("clock_domain_mhz", noc_clock_mhz),
                )
            )
            connect_port = None
            if physical.startswith("HBM_MC_"):
                connect_port = _hbm_connect_port_for_component(
                    component.component_id
                )
                if connect_port is None:
                    m5.fatal(
                        "Component '{}' is placed on {} but does not follow the "
                        "hbm<controller>_port<0..3> naming rule required to select "
                        "PORT0..PORT3 on a shared HBM_MC tile.".format(
                            component.component_id, physical
                        )
                    )
            connections.append(
                NodeConnection(
                    connectTo=connect_to,
                    clock_domain=clock_domain_mhz,
                    connectLoc=physical,
                    connectPort=connect_port,
                    protocol=protocol,
                )
            )
            if topology is not None:
                endpoint_infos.append(
                    _resolve_connection_endpoint(topology, connections[-1])
                )

        if not connections:
            m5.fatal(
                f"Component '{component.component_id}' has no ports in connections JSON."
            )

        for ep in endpoint_infos:
            if ep.protocol == "AXI_MM" and ep.role == "Master":
                addr_info = topology.src_addr_options.get(ep.logical_name, [])
                if (
                    addr_info
                    and "nsu_min_addrs" not in parameters
                    and "nsu_address_spaces" not in parameters
                ):
                    starts, sizes = _target_windows_for_master(
                        component.component_id,
                        addr_info,
                        parameters,
                    )
                    parameters["nsu_min_addrs"] = starts
                    parameters["nsu_address_spaces"] = sizes
                    parameters.setdefault("base_addr", starts[0])
                    parameters.setdefault(
                        "max_addr", starts[0] + sizes[0] - 1
                    )
            if ep.comp_type == "HBMMC":
                if len(endpoint_infos) != 1:
                    m5.fatal(
                        "HBM runtime nodes currently require one endpoint per component; "
                        "'{}' has {}.".format(
                            component.component_id, len(endpoint_infos)
                        )
                    )
                for key, value in get_hbm_endpoint_kwargs(ep, topology).items():
                    parameters.setdefault(key, value)

        nodes.append(
            Node(
                node_type=node_type,
                connections=connections,
                parameters=parameters,
            )
        )

    return nodes


def _resolve_connection_endpoint(topology, conn):
    if not topology.has_physical_endpoint(conn.connectLoc):
        m5.fatal(
            "connectLoc '{}' is not a valid physical endpoint in the topology (NCR).".format(
                conn.connectLoc
            )
        )

    if conn.connectPort:
        matches = [
            ep
            for ep in topology.endpoints.values()
            if ep.physical_name == conn.connectLoc
            and ep.port_name == conn.connectPort
        ]
        if not matches:
            m5.fatal(
                "connectLoc '{}' with connectPort '{}' could not be resolved to an endpoint.".format(
                    conn.connectLoc, conn.connectPort
                )
            )
        if len(matches) > 1:
            m5.fatal(
                "connectLoc '{}' with connectPort '{}' matched multiple endpoints: {}.".format(
                    conn.connectLoc,
                    conn.connectPort,
                    [ep.logical_name for ep in matches],
                )
            )
        return matches[0]

    if conn.connectLoc.startswith("HBM_MC_"):
        m5.fatal(
            "connectLoc '{}' is an HBM_MC tile with multiple AXI ports; set "
            "connectPort to PORT0..PORT3 (v2 placement uses hbm<ctrl>_port<N> "
            "component names to infer the port).".format(conn.connectLoc)
        )

    ep = topology.get_endpoint_by_physical(conn.connectLoc)
    if not ep:
        m5.fatal(
            "connectLoc '{}' could not be resolved to an endpoint.".format(
                conn.connectLoc
            )
        )
    return ep


def _default_node_type_for_endpoint(ep):
    if ep.comp_type in ("PL_NMU", "HBM_NMU") and ep.protocol == "AXI_MM":
        return AxiRandomTrafficGenerator
    if ep.comp_type == "PL_NMU" and ep.protocol == "AXI_STRM":
        return AxisRandomTrafficGenerator
    if ep.comp_type == "PL_NSU" and ep.protocol == "AXI_STRM":
        return AxisSinkNode
    if ep.comp_type == "HBMMC":
        return tileNSU_HBM
    if ep.comp_type == "DDRC":
        return tileNSU_HBM
    if ep.comp_type == "PL_NSU" and ep.protocol == "AXI_MM":
        return BramEndpoint
    return None


def synthesize_nodes_from_topology(
    topology, options, missing_node_config_path
):
    nodes = []
    hbm_idx = [0]
    ddr_idx = [0]
    noc_clock_mhz = int(toFrequency(options.noc_clock) / 1e6)

    for ep in topology.endpoints_in_order:
        node_type = _default_node_type_for_endpoint(ep)
        if node_type is None:
            m5.fatal(
                "No synthesized node mapping exists for endpoint %s (%s %s).",
                ep.logical_name,
                ep.comp_type,
                ep.protocol,
            )
        if not ep.physical_name:
            m5.fatal(
                "Cannot synthesize a node for endpoint %s because it has no physical placement in the topology.",
                ep.logical_name,
            )
        params = _get_endpoint_kwargs(ep, options, topology, hbm_idx, ddr_idx)
        conn = NodeConnection(
            connectTo="NMU" if ep.role == "Master" else "NSU",
            clock_domain=noc_clock_mhz,
            connectLoc=ep.physical_name,
            connectPort=ep.port_name,
            protocol="AXIS" if ep.protocol == "AXI_STRM" else "AXIMM",
        )
        nodes.append(
            Node(node_type=node_type, connections=[conn], parameters=params)
        )

    print(
        f"Info: synthesized {len(nodes)} runtime node(s) from topology because "
        f"'{missing_node_config_path}' was not present."
    )
    return nodes


# ******************************************************************* #

# create json

# Get paths we might need.  It's expected this file is in m5/configs/example.
config_path = "/home/mlanz2/gem5/configs/example"
src_root = os.path.dirname(config_path)
gem5_root = os.path.dirname(src_root)

# I think this should be set automatically when doing garnet standalone build but...
# Garnet_standalone.py errored
buildEnv["PROTOCOL"] = "Garnet_standalone"


# create default options
options = get_parser()

if getattr(options, "print_noc_probe_help", False) and not getattr(
    options, "print_paths", False
):
    print_noc_interface_snooper_help()
    raise SystemExit(0)

if options.network != "nocgarnet":
    m5.fatal(f"Unsupported network type: {options.network}")

(
    conn_json_path,
    place_json_path,
    nts_filename,
    ncr_filename,
    opts_json_path,
) = resolve_topology_bundle(options.noc_topology)

topology = get_address_map(
    nts_filename,
    ncr_filename,
    build_hbm_settings_from_options(options),
)

setup = load_setup(conn_json_path, place_json_path)
opts_data = load_topology_opts(opts_json_path)
nodes = load_nodes_from_setup(setup, topology, options)
(
    record_nps,
    record_nps_gap_cycles,
    record_mode_interfaces,
    record_hbm,
    record_hbm_gap_cycles,
    noc_probes,
) = load_simulation_opts(
    opts_data,
    allow_invalid_noc_probes=getattr(options, "print_paths", False),
)
apply_hbm_stats_recording(nodes, record_hbm, record_hbm_gap_cycles)

# Backward-compat aliases from TopologyInfo
aximm_nsu = topology.aximm_nsu
aximm_nmu = topology.aximm_nmu
axis_nsu = topology.axis_nsu
axis_nmu = topology.axis_nmu
hbm_nsu = topology.hbm_nsu
hbm_nmu = topology.hbm_nmu
ddr_nsu = topology.ddr_nsu
address_name_map = topology.address_name_map
hbm_channels = topology.hbm_channels
ddr_channels = topology.ddr_channels
src_addr_options = topology.src_addr_options
axis_nmu_to_dest_names = topology.axis_nmu_to_dest_names
# num_* counts are recomputed after node creation (printed below)

instantiated_nodes = []
nameToID = {}  # Maps NMU/NSU name -> Controller Index (0..N-1)
address_ID_map = []  # Maps (start, end) -> Controller Index

n = 0
numAxisPackets = 100
node_conn_names = []

if not nodes:
    m5.fatal(
        "nodes list is empty. You must define at least one Node with connections."
    )


def _ansi_red_bold(s: str) -> str:
    return "\033[1;31m" + s + "\033[0m"


def _warn_unseeded_random_tgs_when_checkpoint_requested():
    """
    If the run intends to take periodic checkpoints, warn loudly when random
    traffic generators are configured with seed==0 (time-based).
    """
    if not getattr(options, "checkpoint_interval_noc_cycles", 0):
        return

    # instantiated_nodes is populated per endpoint; de-dup on object identity
    unique_nodes = []
    seen = set()
    for obj in instantiated_nodes:
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        unique_nodes.append(obj)

    offenders = []
    for obj in unique_nodes:
        # The random TG SimObjects define a `seed` param (default 0 = time-based).
        if hasattr(obj, "seed"):
            try:
                if int(obj.seed) == 0:
                    offenders.append(obj)
            except Exception:
                # If seed isn't directly castable, fall back to string compare.
                if str(getattr(obj, "seed", "")).strip() in ("0", "0u", "0U"):
                    offenders.append(obj)

    if not offenders:
        return

    # Try to provide identifying info (port_endpoint_names is passed from JSON).
    details = []
    for obj in offenders:
        ep_names = getattr(obj, "port_endpoint_names", None)
        if ep_names:
            details.append(f"{obj.__class__.__name__}(endpoints={list(ep_names)})")
        else:
            details.append(obj.__class__.__name__)

    msg = (
        "WARNING: periodic checkpointing is enabled, but one or more random "
        "traffic generators have seed=0 (time-based). After restoring from a checkpoint, "
        "their behavior will NOT be reproducible.\n"
        "  Fix: set a non-zero \"seed\" in the node config JSON for each random TG.\n"
        "  Offenders: " + ", ".join(details)
    )
    print(_ansi_red_bold(msg))


def _unique_system_cpus_from_endpoints(endpoint_nodes):
    """
    One System.cpu entry per distinct SimObject (gem5 stats require unique
    children under system). Multi-port logical nodes still appear once per
    endpoint in endpoint_nodes for controllers and Control.
    """
    seen = set()
    unique = []
    for obj in endpoint_nodes:
        k = id(obj)
        if k in seen:
            continue
        seen.add(k)
        unique.append(obj)
    return unique


def _create_node(node, port_endpoint_names):
    """Create one NocNode instance per node"""
    try:
        params = dict(node.parameters)
        params["clockDomains"] = list(node.clock_domains)
        params["port_endpoint_names"] = list(port_endpoint_names)

        # Flat JSON like BramEndpoint: build inner BramEndpoint, then wrapper.
        if node.node_type is BramBuggyNode:
            kw = dict(params)
            aw = kw.pop("awready_percentage", 100)
            ww = kw.pop("wready_percentage", 100)
            ar = kw.pop("arready_percentage", 100)
            mutate_response_axi_id_percentage = kw.pop(
                "mutate_response_axi_id_percentage", 0
            )
            mutate_axi_id_val = kw.pop("mutate_axi_id_val", 0)
            inner = BramEndpoint(**kw)
            return BramBuggyNode(
                bram=inner,
                awready_percentage=aw,
                wready_percentage=ww,
                arready_percentage=ar,
                mutate_response_axi_id_percentage=mutate_response_axi_id_percentage,
                mutate_axi_id_val=mutate_axi_id_val,
                **kw,
            )

        if node.node_type is SynchronizerNode:
            kw = dict(params)
            if len(kw.get("clockDomains", [])) != 2 or len(
                kw.get("port_endpoint_names", [])
            ) != 2:
                m5.fatal(
                    "SynchronizerNode requires exactly two connections: first AXIS "
                    "(sink), then AXIMM (BRAM)."
                )
            # JSON configs usually omit noc_system (Param defaults to Parent.any);
            # do not require kw["noc_system"] here.
            common = {"sim_cycles": kw.get("sim_cycles", 1000)}
            if "noc_system" in kw:
                common["noc_system"] = kw["noc_system"]
            inner_axis = AxisSinkNode(
                **common,
                clockDomains=[kw["clockDomains"][0]],
                port_endpoint_names=[kw["port_endpoint_names"][0]],
                ready_percent=kw.get("ready_percent", 80),
                ready_percent_start_fraction=kw.get(
                    "ready_percent_start_fraction", 0.0
                ),
                print_data=kw.get("print_data", True),
                data_width=kw.get("data_width", 512),
                id_width=kw.get("id_width", 6),
                dest_width=kw.get("dest_width", 4),
                expected_packets=kw.get("expected_packets", 0),
            )
            bram_port_kw = {
                **common,
                "clockDomains": [kw["clockDomains"][1]],
                "port_endpoint_names": [kw["port_endpoint_names"][1]],
                "base_addr": kw.get("base_addr", 0),
                "memory_size": kw.get("memory_size", 65536),
                "read_latency": kw.get("read_latency", 1),
                "write_latency": kw.get("write_latency", 1),
            }
            if "tile_controller" in kw:
                bram_port_kw["tile_controller"] = kw["tile_controller"]
            inner_ep = BramEndpoint(**bram_port_kw)
            inner_bram = BramBuggyNode(
                bram=inner_ep,
                awready_percentage=kw.get("awready_percentage", 100),
                wready_percentage=kw.get("wready_percentage", 100),
                arready_percentage=kw.get("arready_percentage", 100),
                mutate_response_axi_id_percentage=kw.get(
                    "mutate_response_axi_id_percentage", 0
                ),
                mutate_axi_id_val=kw.get("mutate_axi_id_val", 0),
                **bram_port_kw,
            )
            return SynchronizerNode(
                axis_sink=inner_axis,
                bram=inner_bram,
                **kw,
            )

        return node.node_type(**params)
    except TypeError as e:
        m5.fatal(
            "Failed to instantiate %s: %s. "
            "Check that parameters in node config match the constructor.",
            node.node_type.__name__,
            e,
        )


seen_pairing_keys = (
    set()
)  # each NMU/NSU hookup once; HBM_MC uses (tile, PORTn) because logical names differ per port
for node in nodes:
    # Validate all connections and collect endpoints
    endpoints = []
    for conn in node.connections:
        ep = _resolve_connection_endpoint(topology, conn)
        pairing_key = _endpoint_pairing_key(ep, conn)
        if pairing_key in seen_pairing_keys:
            port_hint = (
                f", port {conn.connectPort}" if conn.connectPort else ""
            )
            m5.fatal(
                "Endpoint {} (physical: {}{}) is already paired with another node. "
                "Each NMU/NSU can only be connected to one node.".format(
                    ep.logical_name, conn.connectLoc, port_hint
                )
            )
        seen_pairing_keys.add(pairing_key)
        endpoints.append(ep)

    # Create one NocNode instance per node
    port_endpoint_names = [ep.logical_name for ep in endpoints]
    node_obj = _create_node(node, port_endpoint_names)
    if not node_obj:
        m5.fatal("failed to create node")

    # Register each endpoint; append same node_obj so len(instantiated_nodes) matches controllers
    for ep in endpoints:
        instantiated_nodes.append(node_obj)
        nameToID[ep.logical_name] = n
        node_conn_names.append([ep.logical_name])
        n += 1

for ep in topology.endpoints.values():
    if ep.logical_name not in nameToID:
        ident = ep.physical_name or ep.logical_name
        role = "NMU" if ep.role == "Master" else "NSU"
        print(
            f"Warning: {role} {ident} (logical: {ep.logical_name}) in topology is not connected to any Node."
        )

_warn_unseeded_random_tgs_when_checkpoint_requested()

# Recompute counts based on instantiated nodes
num_aximm_nsu = len([n for n in nameToID if n in topology.aximm_nsu])
num_aximm_nmu = len([n for n in nameToID if n in topology.aximm_nmu])
num_axis_nsu = len([n for n in nameToID if n in topology.axis_nsu])
num_axis_nmu = len([n for n in nameToID if n in topology.axis_nmu])
num_hbm_nsu = len([n for n in nameToID if n in topology.hbm_nsu])
num_hbm_nmu = len([n for n in nameToID if n in topology.hbm_nmu])
num_ddr_nsu = len([n for n in nameToID if n in topology.ddr_nsu])
total_num_aximm_nsu = num_aximm_nsu + num_hbm_nsu + num_ddr_nsu
total_num_aximm_nmu = num_aximm_nmu + num_hbm_nmu
final_num_nodes = len(instantiated_nodes)
print(
    "Num aximm nsu: ",
    num_aximm_nsu,
    " aximm nmu: ",
    num_aximm_nmu,
    " axis nsu: ",
    num_axis_nsu,
    " axis nmu: ",
    num_axis_nmu,
    " hbm nsu: ",
    num_hbm_nsu,
    " hbm nmu: ",
    num_hbm_nmu,
    " ddr nsu: ",
    num_ddr_nsu,
)
print(
    "Total num aximm nsu: ",
    total_num_aximm_nsu,
    " nmu: ",
    total_num_aximm_nmu,
    " nodes: ",
    final_num_nodes,
)

system = System(cpu=_unique_system_cpus_from_endpoints(instantiated_nodes))

# Configure HBM if there are HBM channels
if len(hbm_channels) > 0:
    hbm_tile_indices = [
        nameToID[name]
        for name in sorted(nameToID, key=nameToID.get)
        if name in topology.hbm_nsu
    ]
    configure_hbm(
        system,
        hbm_channels,
        num_hbm_nsu,
        num_aximm_nsu,
        hbm_tile_indices=hbm_tile_indices,
    )

# Configure DDR if there are DDR channels
if len(ddr_channels) > 0:
    # DDR NSU nodes start after aximm_nsu + hbm_nsu
    ddr_nsu_start_idx = num_aximm_nsu + num_hbm_nsu
    ddr_tile_indices = [
        nameToID[name] for name in nameToID if name in topology.ddr_nsu
    ]
    configure_ddr(
        system,
        ddr_channels,
        num_ddr_nsu,
        ddr_nsu_start_idx,
        ddr_tile_indices=ddr_tile_indices,
    )


# Create a top-level voltage domain and clock domain
system.voltage_domain = VoltageDomain(voltage=options.sys_voltage)

system.clk_domain = SrcClockDomain(
    clock=options.sys_clock, voltage_domain=system.voltage_domain
)

# create_system(system, options)
system.noc = NocSystem()
noc = system.noc
(
    network,
    IntLinkClass,
    ExtLinkClass,
    RouterClass,
) = create_network(options, noc)
noc.network = network
network.routing_algorithm = options.routing_algorithm  # Set routing algorithm
network.number_of_virtual_networks = options.number_of_virtual_networks

address_ID_map = address_to_id(address_name_map, nameToID)
# Pass address map to network param
address_map_json_string = json.dumps(address_ID_map)
network.address_map_json = address_map_json_string
network.source_address_map_json = json.dumps(
    source_address_to_id(topology.source_address_routes, nameToID)
)

# Create AXIS tdest-to-dest_ni mapping and pass to network
axis_tdest_id_map = axis_tdest_name_to_id(axis_nmu_to_dest_names, nameToID)
print(f"\\n=== AXIS TDEST Mapping Summary ===")
print(f"Raw name mapping: {axis_nmu_to_dest_names}")
print(f"ID-based mapping: {axis_tdest_id_map}")
for nmu_id, tdest_map in axis_tdest_id_map.items():
    print(f"  NMU {nmu_id}: tdest -> dest_ni = {tdest_map}")
print(f"===================================\\n")
axis_tdest_map_json_string = json.dumps(axis_tdest_id_map)
network.axis_tdest_map_json = axis_tdest_map_json_string

controllers = []
record = options.record_mode
for node in nodes:
    for conn in node.connections:
        ep = _resolve_connection_endpoint(topology, conn)
        ni_name = ep.logical_name
        n = nameToID[ni_name]
        is_axis = ep.protocol == "AXI_STRM"
        is_ddr = ep.comp_type == "DDRC"
        rec_mode = 1 if is_ddr else record_mode_interfaces
        if is_axis:
            newController = NocInterface(
                id=n,
                version=n,
                endpoint_name=ni_name,
                protocol="AXIS",
                role=ep.role,
                noc_system=noc,
                axis_data_width=512,
                axis_id_width=16,
                axis_dest_width=12,
                record_mode=rec_mode,
            )
        else:
            newController = NocInterface(
                id=n,
                version=n,
                endpoint_name=ni_name,
                protocol="AXIMM",
                role=ep.role,
                noc_system=noc,
                record_mode=rec_mode,
            )
        controllers.append(newController)

noc.tile_controllers = controllers

topology_helper = NoC_Topology(controllers)
# topology_helper = Mesh_XY(controllers)
topology_helper.set_file_path(ncr_filename)  # Set path previously stored
topology_helper.set_node_dict(nameToID)  # Give it name->ID map
configure_topology_tracing(
    topology_helper,
    options,
    legacy_record_nps=record_nps,
    legacy_record_nps_gap_cycles=record_nps_gap_cycles,
)

print("Calling topology_helper.makeTopology...")
topology_helper.makeTopology(
    options, network, IntLinkClass, ExtLinkClass, RouterClass
)
# init_network(options, network, NMUClass, NSUClass, total_num_aximm_nmu, total_num_aximm_nsu)
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

# `--print-paths` is a structural introspection mode. It should still run even
# if noc_probes entries are invalid, since probes are not required for printing
# topology travel paths.
if not getattr(options, "print_paths", False):
    instantiate_and_wire_noc_probes(noc_probes, system, noc)

noc.num_of_sequencers = 0
noc.number_of_virtual_networks = 5

# connect new tile controller to its tile (indexed by endpoint, not system.cpu).
for i in range(final_num_nodes):
    ep_node = instantiated_nodes[i]
    tc = system.noc.tile_controllers[i]
    ep_node.tile_controller = tc
    inner_bram = getattr(ep_node, "bram", None)
    if inner_bram is not None:
        inner_bram.tile_controller = tc
        inner_inner = getattr(inner_bram, "bram", None)
        if inner_inner is not None:
            inner_inner.tile_controller = tc

network.num_aximm_nmu = total_num_aximm_nmu
network.num_aximm_nsu = total_num_aximm_nsu

# Build flattened adjacency list from node connection names
adjacency_list = []
adjacency_index = []
for conn_names in node_conn_names:
    adjacency_index.append(len(adjacency_list))
    for ni_name in conn_names:
        adjacency_list.append(nameToID[ni_name])

# create the control object which advances time
system.control = Control(
    noc_interfaces=controllers,
    nodes=instantiated_nodes,
    adjacency_list=adjacency_list,
    adjacency_index=adjacency_index,
    sim_cycles=options.sim_cycles,
    noc_clock_domain_mhz=int(toFrequency(options.noc_clock) / 1e6),
)

# Create a seperate clock domain for Ruby
# system.ruby.clk_domain = SrcClockDomain(
#     clock=options.ruby_clock, voltage_domain=system.voltage_domain
system.noc.clk_domain = SrcClockDomain(
    clock=options.noc_clock, voltage_domain=system.voltage_domain
)

for t in system.cpu:
    t.clk_domain = system.clk_domain


# -----------------------
# run simulation
# -----------------------

root = Root(full_system=False, system=system)

# # print all the objects in the system
# for obj in root.descendants():
#     print(type(obj).__name__, obj.path())

def _label(obj, kind: str, idx: int) -> str:
    return f"{type(obj).__name__} ({kind}{idx})"


def _print_flow_components_in_travel_order(root_obj):
    """
    Print per-flow ordered travel paths using the constructed topology objects.
    Also renders a bidirectional graph with phart if available.
    """
    # Resolve the main NoC objects.
    try:
        net = root_obj.system.noc.network
    except Exception:
        print("No system.noc.network; cannot print NoC paths.")
        return

    controllers = list(getattr(root_obj.system.noc, "tile_controllers", []) or [])
    netifs = list(getattr(net, "netifs", []) or [])
    routers = list(getattr(net, "routers", []) or [])
    ext_links = list(getattr(net, "ext_links", []) or [])
    int_links = list(getattr(net, "int_links", []) or [])

    # Index maps for stable labels.
    node_to_idx = {id(obj): i for i, obj in enumerate(getattr(root_obj.system, "cpu", []) or [])}
    ctrl_to_idx = {id(obj): int(getattr(obj, "id", i)) for i, obj in enumerate(controllers)}
    netif_to_idx = {id(obj): int(getattr(obj, "id", i)) for i, obj in enumerate(netifs)}
    router_to_idx = {id(obj): int(getattr(obj, "router_id", i)) for i, obj in enumerate(routers)}
    extlink_to_idx = {id(obj): int(getattr(obj, "link_id", i)) for i, obj in enumerate(ext_links)}
    intlink_to_idx = {id(obj): int(getattr(obj, "link_id", i)) for i, obj in enumerate(int_links)}

    # Endpoint name -> controller, and controller id -> node(s) connected to that endpoint.
    ctrl_by_endpoint = {str(getattr(c, "endpoint_name", "")): c for c in controllers}
    nodes_by_endpoint = {}
    for i, node in enumerate(getattr(root_obj.system, "cpu", []) or []):
        eps = list(getattr(node, "port_endpoint_names", []) or [])
        for ep in eps:
            nodes_by_endpoint.setdefault(str(ep), []).append(node)

    # Build a directed graph of the fabric using link objects for routing.
    # Nodes are controllers and routers (by object identity).
    fabric_adj = {}  # obj -> list[obj]
    edge_obj = {}    # (u,v) -> link-like object

    def add_dir_edge(u, v, via):
        fabric_adj.setdefault(u, []).append(v)
        edge_obj[(u, v)] = via

    # ext_links: controller <-> router (treat as both directions for pathfinding)
    for el in ext_links:
        c = getattr(el, "ext_node", None)
        r = getattr(el, "int_node", None)
        if c is None or r is None:
            continue
        add_dir_edge(c, r, el)
        add_dir_edge(r, c, el)

    # int_links: router -> router (directed), also add reverse for "double sided" view
    for il in int_links:
        s = getattr(il, "src_node", None)
        d = getattr(il, "dst_node", None)
        if s is None or d is None:
            continue
        add_dir_edge(s, d, il)
        add_dir_edge(d, s, il)

    def shortest_path_objs(src, dst):
        # BFS over object graph
        from collections import deque
        q = deque([src])
        prev = {src: None}
        while q:
            u = q.popleft()
            if u is dst:
                break
            for v in fabric_adj.get(u, []):
                if v in prev:
                    continue
                prev[v] = u
                q.append(v)
        if dst not in prev:
            return None
        # reconstruct
        path = []
        cur = dst
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        return list(reversed(path))

    # Determine logical flows:
    # - AXIS: from axis_tdest_id_map (tdest -> dest NI)
    # - AXIMM: from src_addr_options (NMU -> target address windows) resolved via
    #   address_name_map (same source as runtime address decode)
    flows = []
    if "axis_tdest_id_map" in globals():
        for src_id, tdest_map in axis_tdest_id_map.items():
            for _, dst_id in tdest_map.items():
                flows.append((int(src_id), int(dst_id), "AXIS"))

    flow_keys = {(s, d, p) for s, d, p in flows}
    if (
        "topology" in globals()
        and "nameToID" in globals()
        and "src_addr_options" in globals()
        and "address_name_map" in globals()
    ):
        for nmu_name in getattr(topology, "aximm_nmu", ()) or ():
            if nmu_name not in nameToID:
                continue
            nmu_id = int(nameToID[nmu_name])
            addrs = src_addr_options.get(nmu_name, []) or []
            for i in range(0, len(addrs), 2):
                if i + 1 >= len(addrs):
                    break
                start = int(addrs[i])
                dest_name = None
                for map_start, map_end, ep_name in address_name_map:
                    if map_start <= start < map_end:
                        dest_name = ep_name
                        break
                if not dest_name or dest_name not in nameToID:
                    continue
                dst_id = int(nameToID[dest_name])
                key = (nmu_id, dst_id, "AXIMM")
                if key in flow_keys:
                    continue
                flow_keys.add(key)
                flows.append((nmu_id, dst_id, "AXIMM"))

    # If no flows were found, still print what we can.
    if not flows:
        print("No flows discovered (no AXIS tdest map and no AXIMM address routes).")
        return

    # Helper to label an object.
    def L(obj):
        if obj in controllers:
            return _label(obj, "nocinterface", ctrl_to_idx[id(obj)])
        if obj in netifs:
            return _label(obj, "netif", netif_to_idx[id(obj)])
        if obj in routers:
            return _label(obj, "router", router_to_idx[id(obj)])
        if obj in ext_links:
            return _label(obj, "extlink", extlink_to_idx[id(obj)])
        if obj in int_links:
            return _label(obj, "intlink", intlink_to_idx[id(obj)])
        # end nodes:
        if id(obj) in node_to_idx:
            return _label(obj, "node", node_to_idx[id(obj)])
        return type(obj).__name__

    def _is_hook_component(obj):
        """Components that can be targeted by probe hook points."""
        return (
            obj in controllers or
            obj in netifs or
            obj in routers or
            obj in ext_links or
            obj in int_links
        )

    # Map controller id -> controller object quickly.
    ctrl_by_id = {int(getattr(c, "id", i)): c for i, c in enumerate(controllers)}
    netif_by_id = {int(getattr(nf, "id", i)): nf for i, nf in enumerate(netifs)}

    print("\n=== Traffic flow components (travel order) ===")
    rendered_paths = []
    for (src_id, dst_id, proto) in flows:
        src_ctrl = ctrl_by_id.get(src_id)
        dst_ctrl = ctrl_by_id.get(dst_id)
        if not src_ctrl or not dst_ctrl:
            continue
        src_ep = str(getattr(src_ctrl, "endpoint_name", f"id{src_id}"))
        dst_ep = str(getattr(dst_ctrl, "endpoint_name", f"id{dst_id}"))
        src_nodes = nodes_by_endpoint.get(src_ep, [])
        dst_nodes = nodes_by_endpoint.get(dst_ep, [])

        # Find router/controller path in the fabric.
        obj_path = shortest_path_objs(src_ctrl, dst_ctrl)
        if not obj_path:
            print(f"- Flow {proto} {src_ep}(id={src_id}) -> {dst_ep}(id={dst_id}): NO PATH")
            continue

        # Expand into a travel sequence:
        # node -> controller -> netif -> (links/routers...) -> netif -> controller -> node
        seq = []
        if src_nodes:
            seq.append(src_nodes[0])
        seq.append(src_ctrl)
        if src_id in netif_by_id:
            seq.append(netif_by_id[src_id])

        for u, v in zip(obj_path, obj_path[1:]):
            via = edge_obj.get((u, v))
            if via is not None:
                seq.append(via)
            seq.append(v)

        # obj_path ends at dst_ctrl (already appended). Insert dst netif *before*
        # that dst controller in the displayed travel order.
        if dst_id in netif_by_id:
            dst_netif_obj = netif_by_id[dst_id]
            if seq and seq[-1] is dst_ctrl:
                seq.pop()
                seq.append(dst_netif_obj)
                seq.append(dst_ctrl)
        if dst_nodes:
            seq.append(dst_nodes[0])

        # Keep only components that expose probe hook points, but re-add only
        # the end nodes (traffic generator / sink) at the ends for readability.
        hookable_seq = [obj for obj in seq if _is_hook_component(obj)]

        # Dedup immediate repeats (common when controller appears in obj_path then appended again).
        compact_hook_objs = []
        for x in hookable_seq:
            if not compact_hook_objs or compact_hook_objs[-1] is not x:
                compact_hook_objs.append(x)

        compact_objs = []
        if src_nodes:
            compact_objs.append(src_nodes[0])
        compact_objs.extend(compact_hook_objs)
        if dst_nodes:
            compact_objs.append(dst_nodes[0])

        # Final dedup in case endpoints overlap with hook list somehow.
        compact_final = []
        for x in compact_objs:
            if not compact_final or compact_final[-1] is not x:
                compact_final.append(x)

        compact = [L(obj) for obj in compact_final]
        rendered_paths.append(compact)

        print(f"\nFlow {proto}: {src_ep}(id={src_id}) -> {dst_ep}(id={dst_id})")
        for step in compact:
            print(f"  - {step}")

    print("\n=== Hook ID prefix -> connectLoc kind ===")
    print("  - router.* -> router<N> (NocGarnetRouter)")
    print("  - link.*   -> intlink<N> / extlink<N> (NocNetworkLink in those links)")
    print("  - ni.*     -> netif<N> (NocGarnetNetworkInterface)")
    print("  - noc_if.* -> nocinterface<N> (NocInterface)")

    print("\n=== Hook ID -> observed item type (what NocProbe receives) ===")
    print("  - router.flit.*            -> flit")
    print("  - link.flit.*              -> flit")
    print("  - ni.flit.*                -> flit")
    print("  - ni.msg.*                 -> message")
    print("  - noc_if.state.*           -> State (comparator only)")
    print("  - noc_if.state.node_side   -> ProbeData (snooper only)")
    print("  - noc_if.state.noc_side    -> ProbeData (snooper only)")
    print("  - noc_if.cdc.*             -> State")
    print("  - noc_if.net.*             -> State")
    print("  - noc_if.node.to_cdc       -> message (special case; other noc_if.node.* hooks are State)")
    print("Note: probe_mode=snooper is NocInterface-only (see NocInterface section below).")
    print("      In comparator mode, hook_id_0 and hook_id_1 must observe the same item type.")

    # Build a bidirectional graph out of all rendered paths and render with phart (example code style).
    try:
        import networkx as nx
        from phart import ASCIIRenderer, NodeStyle
    except Exception:
        print("\n(phart/networkx not available; skipping diagram render)")
        return

    G = nx.DiGraph()
    for path in rendered_paths:
        for n in path:
            G.add_node(n)
        for u, v in zip(path, path[1:]):
            G.add_edge(u, v)
            G.add_edge(v, u)  # double-sided arrows by adding both directions

    # renderer = ASCIIRenderer(G, node_style=NodeStyle.SQUARE)
    # print("\n=== Flow diagram (phart) ===")
    # print(renderer.render())


if getattr(options, "print_paths", False):
    # Report whether the current JSON noc_probes section is legal without
    # aborting print-paths.
    ok, errs = validate_noc_probes(noc_probes, system, noc)
    if ok:
        print("\n=== noc_probes validation ===")
        print("noc_probes: OK")
    else:
        print("\n=== noc_probes validation ===")
        print("noc_probes: INVALID")
        for e in errs:
            print(f"  - {e}")

    # print("\n=== Supported NocProbe snooper field IDs (flat list, NocInterface hooks) ===")
    # for fid in sorted(_noc_probe_supported_snooper_field_ids()):
    #     print(f"  - {fid}")
    print_noc_interface_snooper_help()
    _print_flow_components_in_travel_order(root)
    raise SystemExit(0)

root.system.mem_mode = "timing"

# Not much point in this being higher than the L1 latency
m5.ticks.setGlobalFrequency("1ps")

print("calling m5.instantiate")

# Restore from an existing checkpoint directory if requested.
if getattr(options, "checkpoint_dir", ""):
    print("Restoring from checkpoint", options.checkpoint_dir)
    m5.instantiate(options.checkpoint_dir)
else:
    m5.instantiate()

def _compute_ticks_per_noc_cycle() -> int:
    """
    Convert the configured NoC clock period into ticks, using the fixed global
    tick frequency (set above via m5.ticks.setGlobalFrequency()).
    """
    import _m5.core

    ticks_per_second = int(_m5.core.getClockFrequency())
    noc_hz = int(toFrequency(options.noc_clock))
    if noc_hz <= 0:
        m5.fatal(f"Invalid --noc-clock frequency: {options.noc_clock}")
    tpc = int(round(ticks_per_second / noc_hz))
    if tpc <= 0:
        m5.fatal(
            f"Computed ticks-per-NoC-cycle is {tpc} (ticks_per_second={ticks_per_second}, noc_hz={noc_hz})"
        )
    return tpc


def _periodic_checkpoint_run():
    interval_cycles = int(getattr(options, "checkpoint_interval_noc_cycles", 0) or 0)
    write_dir = str(getattr(options, "checkpoint_write_dir", "") or "").strip()

    if interval_cycles <= 0:
        exit_event = m5.simulate(options.abs_max_tick)
        print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
        return

    if not write_dir:
        m5.fatal("--checkpoint-interval-noc-cycles requires --checkpoint-write-dir")

    ticks_per_cycle = _compute_ticks_per_noc_cycle()
    interval_ticks = interval_cycles * ticks_per_cycle
    if interval_ticks <= 0:
        m5.fatal(
            f"Invalid checkpoint interval: {interval_cycles} cycles * {ticks_per_cycle} ticks/cycle"
        )

    # Ensure the base directory exists; individual checkpoints go into cpt_<tick>.
    os.makedirs(write_dir, exist_ok=True)

    cpt_verbose = int(getattr(options, "checkpoint_verbose", 0) or 0) != 0
    # Only print "Entering event queue..." on the first chunk unless verbose.
    announce_sim_entry = True

    while True:
        now = int(m5.curTick())
        if now >= int(options.abs_max_tick):
            break

        # Next checkpoint strictly after 'now', aligned to interval_ticks.
        next_cpt_tick = ((now // interval_ticks) + 1) * interval_ticks

        # Don't simulate past abs_max_tick.
        target = min(next_cpt_tick, int(options.abs_max_tick))
        delta = int(target - now)
        if delta <= 0:
            break

        exit_event = m5.simulate(
            delta,
            announce_entry=(announce_sim_entry or cpt_verbose),
        )
        announce_sim_entry = False
        cause = exit_event.getCause()
        cur = int(m5.curTick())

        # If we stopped exactly at the requested simulate limit and reached a
        # checkpoint boundary, write a checkpoint and continue.
        if (
            cur == next_cpt_tick
            and cause == "simulate() limit reached"
            and cur <= int(options.abs_max_tick)
        ):
            cpt_path = os.path.join(write_dir, f"cpt_{cur}")
            m5.checkpoint(cpt_path, verbose=cpt_verbose)
            if cpt_verbose:
                print("Checkpoint written to", cpt_path, "at tick", cur)
            continue

        # Otherwise the run ended for a real reason (or abs_max_tick).
        print("Exiting @ tick", cur, "because", cause)
        break


_periodic_checkpoint_run()

dir = 'src/noc/out/csv'

if record_mode_interfaces > 0:
    plot_aximm_outstanding_writes_over_time(dir)

if record_hbm:
    plot_hbm_stats(dir, window_cycles=100)
    plot_hbm_stats(dir, window_cycles=700)
    plot_hbm_stats(dir, window_cycles=5000)
    

# plot_nps_heatmap(dir)
# plot_nps_avg_buffer_occupancy_heatmap(dir)
# plot_nps_data_movement(dir)
# plot_average_bandwidth(dir, 5)
# plot_windowed_avg_bandwidth(dir, 100)
# plot_windowed_avg_bandwidth(dir, 700)
# plot_windowed_avg_bandwidth(dir, 5000)
# plot_bytes_transferred_per_link(dir)
# plot_axis_tlast_counts_over_time(dir)
# plot_axis_tlast_diff_over_time(dir)
# # plot_latency_boxplots(dir)
# # plot_latency_histograms(dir)
# # plot_latency_ecdf(dir)
# # plot_latency_percentiles(dir)
# # plot_ready_valid_pct(dir)
# # plot_ready_valid_timeline(dir)les(dir)
# plot_ready_valid_pct(dir)
# plot_ready_valid_timeline(dir)
