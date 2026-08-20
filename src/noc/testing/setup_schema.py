import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


CONNECTIONS_KIND = "naviq.connections"
PLACEMENT_KIND = "naviq.placement"
SCHEMA_VERSION = 1

AXIMM = "aximm"
AXIS = "axis"
ROLE_MASTER = "master"
ROLE_SLAVE = "slave"
HBM_ENDPOINT_RE = re.compile(r"hbm(\d+)_port([0-3])$")
DDR_ENDPOINT_RE = re.compile(r"ddr(\d+)_port(\d+)$")


@dataclass(frozen=True)
class ParamOverride:
    component_id: str
    param: str
    value: Any


@dataclass
class PortRecord:
    component_id: str
    port_name: str
    endpoint: str
    role: str
    protocol: str
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentRecord:
    component_id: str
    node_type: str
    params: Dict[str, Any]
    ports: List[PortRecord]


@dataclass
class ConnectionRecord:
    source: str
    target: str
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SetupDescription:
    name: str
    components: List[ComponentRecord]
    connections: List[ConnectionRecord]
    placements: Dict[str, str]
    ports_by_endpoint: Dict[str, PortRecord]
    global_settings: Dict[str, Any] = field(default_factory=dict)

    def master_ports(self) -> List[PortRecord]:
        return [port for component in self.components for port in component.ports
                if port.role == ROLE_MASTER]

    def slave_ports(self) -> List[PortRecord]:
        return [port for component in self.components for port in component.ports
                if port.role == ROLE_SLAVE]

    def port(self, endpoint: str) -> PortRecord:
        return self.ports_by_endpoint[endpoint]

    def placement_for(self, endpoint: str) -> str:
        return self.placements[endpoint]


def is_v2_connections(data: Dict[str, Any]) -> bool:
    return data.get("kind") == CONNECTIONS_KIND


def is_v2_placement(data: Dict[str, Any]) -> bool:
    return data.get("kind") == PLACEMENT_KIND


def parse_param_override(text: str) -> ParamOverride:
    if "=" not in text:
        raise ValueError(
            f"Invalid --param override '{text}'. Expected component.param=value."
        )
    lhs, raw_value = text.split("=", 1)
    if "." not in lhs:
        raise ValueError(
            f"Invalid --param override '{text}'. Expected component.param=value."
        )
    component_id, param = lhs.split(".", 1)
    if not component_id or not param:
        raise ValueError(
            f"Invalid --param override '{text}'. Expected component.param=value."
        )

    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value

    return ParamOverride(component_id=component_id, param=param, value=value)


def parse_param_overrides(values: Iterable[str]) -> List[ParamOverride]:
    return [parse_param_override(value) for value in values]


def split_endpoint_ref(ref: str) -> Tuple[str, str]:
    if "." not in ref:
        raise ValueError(f"Endpoint reference '{ref}' must be component.port.")
    component_id, port_name = ref.split(".", 1)
    if not component_id or not port_name:
        raise ValueError(f"Endpoint reference '{ref}' must be component.port.")
    return component_id, port_name


def _endpoint_ref(component_id: str, port_name: str) -> str:
    return f"{component_id}.{port_name}"


def _check_header(data: Dict[str, Any], expected_kind: str) -> None:
    if data.get("kind") != expected_kind:
        raise ValueError(
            f"Expected kind '{expected_kind}', got '{data.get('kind', '<missing>')}'."
        )
    if data.get("version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported {expected_kind} version '{data.get('version')}'. "
            f"Supported version: {SCHEMA_VERSION}."
        )


def _normalize_role(value: Any, *, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required and must be '{ROLE_MASTER}' or '{ROLE_SLAVE}'.")
    role = str(value).lower()
    if role not in (ROLE_MASTER, ROLE_SLAVE):
        raise ValueError(f"{field_name} must be '{ROLE_MASTER}' or '{ROLE_SLAVE}', got '{value}'.")
    return role


def _normalize_protocol(value: Any, *, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required and must be '{AXIMM}' or '{AXIS}'.")
    protocol = str(value).lower()
    if protocol not in (AXIMM, AXIS):
        raise ValueError(f"{field_name} must be '{AXIMM}' or '{AXIS}', got '{value}'.")
    return protocol


def _apply_overrides(
    components: List[ComponentRecord],
    overrides: Optional[Iterable[ParamOverride]],
) -> None:
    if not overrides:
        return

    by_id = {component.component_id: component for component in components}
    for override in overrides:
        component = by_id.get(override.component_id)
        if component is None:
            raise ValueError(
                f"--param references unknown component '{override.component_id}'. "
                f"Known components: {', '.join(sorted(by_id))}."
            )
        component.params[override.param] = override.value


def _load_components(
    data: Dict[str, Any],
    param_overrides: Optional[Iterable[ParamOverride]] = None,
) -> Tuple[List[ComponentRecord], Dict[str, PortRecord]]:
    raw_components = data.get("components")
    if not isinstance(raw_components, dict) or not raw_components:
        raise ValueError("connections JSON must contain a non-empty 'components' object.")

    components: List[ComponentRecord] = []
    ports_by_endpoint: Dict[str, PortRecord] = {}

    for component_id, component_data in raw_components.items():
        if not isinstance(component_data, dict):
            raise ValueError(f"Component '{component_id}' must be an object.")

        node_type = component_data.get("node_type")
        if not isinstance(node_type, str) or not node_type:
            raise ValueError(f"Component '{component_id}' must define a non-empty 'node_type'.")

        raw_params = component_data.get("params", {})
        if raw_params is None:
            raw_params = {}
        if not isinstance(raw_params, dict):
            raise ValueError(f"Component '{component_id}' params must be an object.")

        raw_ports = component_data.get("ports")
        if not isinstance(raw_ports, dict) or not raw_ports:
            raise ValueError(f"Component '{component_id}' must contain a non-empty 'ports' object.")

        port_records: List[PortRecord] = []
        for port_name, port_data in raw_ports.items():
            if not isinstance(port_data, dict):
                raise ValueError(f"Port '{component_id}.{port_name}' must be an object.")

            role = _normalize_role(
                port_data.get("role"),
                field_name=f"{component_id}.{port_name}.role",
            )
            protocol = _normalize_protocol(
                port_data.get("protocol"),
                field_name=f"{component_id}.{port_name}.protocol",
            )
            endpoint = _endpoint_ref(component_id, port_name)
            if endpoint in ports_by_endpoint:
                raise ValueError(f"Duplicate endpoint '{endpoint}'.")

            config = {
                key: copy.deepcopy(value)
                for key, value in port_data.items()
                if key not in ("role", "protocol")
            }
            record = PortRecord(
                component_id=component_id,
                port_name=port_name,
                endpoint=endpoint,
                role=role,
                protocol=protocol,
                config=config,
            )
            port_records.append(record)
            ports_by_endpoint[endpoint] = record

        components.append(
            ComponentRecord(
                component_id=component_id,
                node_type=node_type,
                params=copy.deepcopy(raw_params),
                ports=port_records,
            )
        )

    _apply_overrides(components, param_overrides)
    return components, ports_by_endpoint


def _parse_intlike(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer-like value, got boolean.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as exc:
            raise ValueError(
                f"{field_name} must be an integer-like value, got '{value}'."
            ) from exc
    raise ValueError(f"{field_name} must be an integer-like value, got '{value}'.")


def _memory_kind(port: PortRecord) -> Optional[str]:
    value = port.config.get("type")
    if value is None:
        return None
    kind = str(value).lower()
    if kind not in ("hbm", "ddr"):
        raise ValueError(
            f"{port.endpoint}.type uses unsupported memory kind '{value}'. "
            "Expected 'hbm' or 'ddr'."
        )
    return kind


def _validate_memory_endpoint_contract(
    components: List[ComponentRecord],
    global_settings: Dict[str, Any],
) -> None:
    hbm_ports: List[PortRecord] = []
    ddr_ports: List[PortRecord] = []

    for component in components:
        for port in component.ports:
            kind = _memory_kind(port)
            if kind is None:
                continue
            if port.role != ROLE_SLAVE or port.protocol != AXIMM:
                raise ValueError(
                    f"{port.endpoint} declares type '{kind}' but memory endpoints "
                    "must be AXI-MM slave ports."
                )
            if "base_address" not in port.config:
                raise ValueError(
                    f"{port.endpoint} ({kind}) is missing required 'base_address'."
                )
            if "size" not in port.config:
                raise ValueError(
                    f"{port.endpoint} ({kind}) is missing required 'size'."
                )
            _parse_intlike(port.config["base_address"], field_name=f"{port.endpoint}.base_address")
            size = _parse_intlike(port.config["size"], field_name=f"{port.endpoint}.size")
            if size <= 0:
                raise ValueError(f"{port.endpoint}.size must be positive, got {size}.")

            if kind == "hbm":
                hbm_ports.append(port)
            else:
                ddr_ports.append(port)

    hbm_by_controller: Dict[int, Dict[int, Tuple[int, int]]] = {}
    for port in hbm_ports:
        match = HBM_ENDPOINT_RE.fullmatch(port.component_id)
        if not match:
            raise ValueError(
                f"HBM endpoint component '{port.component_id}' must follow "
                "the naming rule hbm<controller>_port<0..3>."
            )
        controller_idx = int(match.group(1))
        port_idx = int(match.group(2))
        pseudo_channel_idx = port_idx // 2
        base = _parse_intlike(
            port.config["base_address"],
            field_name=f"{port.endpoint}.base_address",
        )
        size = _parse_intlike(
            port.config["size"],
            field_name=f"{port.endpoint}.size",
        )
        controller_map = hbm_by_controller.setdefault(controller_idx, {})
        existing = controller_map.get(pseudo_channel_idx)
        if existing is not None and existing != (base, size):
            raise ValueError(
                f"HBM controller {controller_idx} pseudo channel {pseudo_channel_idx} "
                f"has conflicting ranges {existing} and {(base, size)}."
            )
        controller_map[pseudo_channel_idx] = (base, size)

    ddr_settings = global_settings.get("ddr_settings", {})
    num_ports_per_mc = 1
    if "num_ports_per_mc" in ddr_settings:
        num_ports_per_mc = _parse_intlike(
            ddr_settings["num_ports_per_mc"],
            field_name="ddr_settings.num_ports_per_mc",
        )
    if num_ports_per_mc != 1:
        raise ValueError(
            "The current V2 DDR contract only supports one exposed port per DDR "
            f"controller, but ddr_settings.num_ports_per_mc={num_ports_per_mc}."
        )

    ddr_controllers = set()
    for port in ddr_ports:
        match = DDR_ENDPOINT_RE.fullmatch(port.component_id)
        if not match:
            raise ValueError(
                f"DDR endpoint component '{port.component_id}' must follow "
                "the naming rule ddr<controller>_port<port>."
            )
        controller_idx = int(match.group(1))
        port_idx = int(match.group(2))
        if port_idx != 0:
            raise ValueError(
                f"{port.endpoint} uses DDR port {port_idx}, but only ddr<controller>_port0 "
                "is currently supported by the V2 generator."
            )
        ddr_controllers.add(controller_idx)

    if "num_mc" in ddr_settings and ddr_ports:
        expected = _parse_intlike(ddr_settings["num_mc"], field_name="ddr_settings.num_mc")
        if expected != len(ddr_controllers):
            raise ValueError(
                f"ddr_settings.num_mc={expected}, but the JSON defines "
                f"{len(ddr_controllers)} DDR controller(s): {sorted(ddr_controllers)}."
            )


def _load_connections(
    data: Dict[str, Any],
    ports_by_endpoint: Dict[str, PortRecord],
) -> List[ConnectionRecord]:
    raw_connections = data.get("connections")
    if not isinstance(raw_connections, list):
        raise ValueError("connections JSON 'connections' must be a list.")

    connections: List[ConnectionRecord] = []
    for index, raw_connection in enumerate(raw_connections):
        if not isinstance(raw_connection, dict):
            raise ValueError(f"Connection #{index} must be an object.")

        source = raw_connection.get("from")
        target = raw_connection.get("to")
        if source not in ports_by_endpoint:
            raise ValueError(f"Connection #{index} references unknown source endpoint '{source}'.")
        if target not in ports_by_endpoint:
            raise ValueError(f"Connection #{index} references unknown target endpoint '{target}'.")

        source_port = ports_by_endpoint[source]
        target_port = ports_by_endpoint[target]
        if source_port.role != ROLE_MASTER:
            raise ValueError(f"Connection #{index} source '{source}' is not a master port.")
        if target_port.role != ROLE_SLAVE:
            raise ValueError(f"Connection #{index} target '{target}' is not a slave port.")
        if source_port.protocol != target_port.protocol:
            raise ValueError(
                f"Connection #{index} crosses protocols: "
                f"{source} is {source_port.protocol}, {target} is {target_port.protocol}."
            )

        attrs = {
            key: copy.deepcopy(value)
            for key, value in raw_connection.items()
            if key not in ("from", "to")
        }
        connections.append(ConnectionRecord(source=source, target=target, attrs=attrs))

    return connections


def _load_placements(
    data: Dict[str, Any],
    ports_by_endpoint: Dict[str, PortRecord],
) -> Dict[str, str]:
    _check_header(data, PLACEMENT_KIND)
    raw_placements = data.get("placements")
    if not isinstance(raw_placements, dict):
        raise ValueError("placement JSON must contain a 'placements' object.")

    missing = sorted(set(ports_by_endpoint) - set(raw_placements))
    if missing:
        raise ValueError(
            "Placement JSON is missing placements for endpoint(s): "
            + ", ".join(missing)
        )

    placements = {}
    for endpoint, physical in raw_placements.items():
        if not isinstance(physical, str) or not physical:
            raise ValueError(f"Placement for '{endpoint}' must be a physical endpoint string.")
        placements[endpoint] = physical
    return placements


def build_setup_description(
    connections_data: Dict[str, Any],
    placement_data: Optional[Dict[str, Any]] = None,
    param_overrides: Optional[Iterable[ParamOverride]] = None,
) -> SetupDescription:
    _check_header(connections_data, CONNECTIONS_KIND)
    components, ports_by_endpoint = _load_components(connections_data, param_overrides)
    connections = _load_connections(connections_data, ports_by_endpoint)
    global_settings = {
        key: copy.deepcopy(value)
        for key, value in connections_data.items()
        if key.endswith("_settings") and isinstance(value, dict)
    }
    _validate_memory_endpoint_contract(components, global_settings)
    placements = (
        _load_placements(placement_data, ports_by_endpoint)
        if placement_data is not None else {}
    )
    return SetupDescription(
        name=connections_data.get("name", ""),
        components=components,
        connections=connections,
        placements=placements,
        ports_by_endpoint=ports_by_endpoint,
        global_settings=global_settings,
    )


def load_setup(
    connections_path: str,
    placement_path: str,
    param_overrides: Optional[Iterable[ParamOverride]] = None,
) -> SetupDescription:
    with open(connections_path) as f:
        connections_data = json.load(f)
    with open(placement_path) as f:
        placement_data = json.load(f)
    return build_setup_description(connections_data, placement_data, param_overrides)
