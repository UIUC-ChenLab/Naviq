from collections import defaultdict
import re


AXIMM = "aximm"
AXIS = "axis"
HBM_CHANNELS_PER_STACK = 8


def classify_endpoint(name):
    if "NMU512" in name or "NMU128" in name:
        return "nmu"
    if "NSU512" in name or "NSU128" in name:
        return "nsu"
    if "DDRMC" in name:
        return "ddrmc"
    if "HBM_MC" in name:
        return "hbm"
    if "NMU_HBM2E" in name:
        return "nmu_hbm"
    return "unknown"


def _add_endpoint_protocol(protocols, name, protocol, role):
    existing = protocols.get(name)
    if existing is not None and existing != protocol:
        raise ValueError(
            f"Endpoint '{name}' is listed as both {existing} and {protocol} {role}."
        )
    protocols[name] = protocol


def get_endpoint_protocols(connections_json):
    master_protocols = {}
    slave_protocols = {}

    for protocol, master_key, slave_key in (
        (AXIMM, "aximm_masters", "aximm_slaves"),
        (AXIS, "axis_masters", "axis_slaves"),
    ):
        for master in connections_json.get(master_key, []):
            _add_endpoint_protocol(master_protocols, master["name"], protocol, "master")
        for slave in connections_json.get(slave_key, []):
            _add_endpoint_protocol(slave_protocols, slave["name"], protocol, "slave")

    if not master_protocols and not slave_protocols:
        for master_name, targets in connections_json.get("connections", {}).items():
            master_protocols[master_name] = AXIMM
            for target in targets:
                slave_protocols[target["to"]] = AXIMM

    return master_protocols, slave_protocols


def get_full_protocol_maps(connections_json):
    master_protocols, slave_protocols = get_endpoint_protocols(connections_json)
    for master_name, targets in connections_json.get("connections", {}).items():
        master_protocol = master_protocols.setdefault(master_name, AXIMM)
        for target in targets:
            slave_protocols.setdefault(target["to"], master_protocol)
    return master_protocols, slave_protocols


def _get_protocol_indices(placement, protocols):
    counters = defaultdict(int)
    indices = {}
    for name in placement:
        protocol = protocols.get(name, AXIMM)
        indices[name] = counters[protocol]
        counters[protocol] += 1
    return indices


def _get_nmu_logical_name(master_idx, protocol=AXIMM):
    if protocol == AXIS:
        return f"axis_noc_0/inst/S{master_idx:02d}_AXIS_nmu"
    return f"axi_noc_0/inst/S{master_idx:02d}_AXI_nmu"


def _split_endpoint_ref(endpoint_name):
    if "." in endpoint_name:
        return endpoint_name.split(".", 1)[0]
    return endpoint_name


def _parse_hbm_endpoint(endpoint_name):
    component_id = _split_endpoint_ref(endpoint_name)
    match = re.fullmatch(r"hbm(\d+)_port([0-3])", component_id)
    if not match:
        return None
    controller_idx = int(match.group(1))
    port_idx = int(match.group(2))
    stack_idx = controller_idx // HBM_CHANNELS_PER_STACK
    channel_idx = controller_idx % HBM_CHANNELS_PER_STACK
    return controller_idx, stack_idx, channel_idx, port_idx


def _get_hbm_logical_name(controller_idx):
    stack_idx = controller_idx // HBM_CHANNELS_PER_STACK
    channel_idx = controller_idx % HBM_CHANNELS_PER_STACK
    return f"axi_noc_0/inst/MC_hbmc/inst/hbm_st{stack_idx}/I_hbm_chnl{channel_idx}"


def _get_nsu_logical_name(slave_idx, phy_type, protocol=AXIMM, endpoint_name=None):
    if protocol == AXIS:
        return f"axis_noc_0/inst/M{slave_idx:02d}_AXIS_nsu"
    if phy_type == "ddrmc":
        return f"axi_noc_0/inst/MC{slave_idx}_ddrc"
    if phy_type == "hbm":
        parsed = _parse_hbm_endpoint(endpoint_name or "")
        if parsed:
            controller_idx, _, _, _ = parsed
            return _get_hbm_logical_name(controller_idx)
        return _get_hbm_logical_name(slave_idx)
    return f"axi_noc_0/inst/M{slave_idx:02d}_AXI_nsu"


def build_logical_name_maps(connections_json, placement_json):
    master_protocols, slave_protocols = get_full_protocol_maps(connections_json)
    master_placement = placement_json["master_placement"]
    slave_placement = placement_json["slave_placement"]
    master_indices = _get_protocol_indices(master_placement, master_protocols)
    slave_indices = _get_protocol_indices(slave_placement, slave_protocols)

    master_names = {}
    for name in master_placement:
        protocol = master_protocols.get(name, AXIMM)
        master_names[name] = _get_nmu_logical_name(master_indices[name], protocol)

    slave_names = {}
    for name, phy_node in slave_placement.items():
        protocol = slave_protocols.get(name, AXIMM)
        slave_names[name] = _get_nsu_logical_name(
            slave_indices[name], classify_endpoint(phy_node), protocol, name)

    return master_names, slave_names
