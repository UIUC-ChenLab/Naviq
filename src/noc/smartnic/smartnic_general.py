import json
import sys
from pathlib import Path

import m5
from m5.objects import (
    AxisFifoRtlNode,
    AxisPacketCheckerSink,
    AxisPacketTrafficGenerator,
    ChecksumRtlNode,
    OverloadedNatRtlNode,
    PacketRateLimiterRtlNode,
    PacketRateLimiterThrottleRtlNode,
    SegmentationOffloadRtlNode,
    TelemetryRtlNode,
)

NOC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = NOC_ROOT.parents[1]
for _path in (
    NOC_ROOT / "setup",
    NOC_ROOT / "testing" / "smartnic" / "common",
):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from noc_config_funcs import get_parser
from smartnic_common import (
    AXIS_DATA_WIDTH,
    AXIS_TDEST_WIDTH,
    AXIS_TID_WIDTH,
    AXIS_TUSER_WIDTH,
    run_axis_test,
)

TOPOLOGY_GENERATION_DIR = REPO_ROOT / "noc_testing" / "topology_generation"
if str(TOPOLOGY_GENERATION_DIR) not in sys.path:
    sys.path.insert(0, str(TOPOLOGY_GENERATION_DIR))

from logical_names import build_logical_name_maps  # noqa: E402


DEFAULT_TOPOLOGY = "src/noc/topology/topologies/1_to_1_far"
MODULE_REGISTRY = {
    "checksum": ChecksumRtlNode,
    "telemetry": TelemetryRtlNode,
    "rate_limiter": PacketRateLimiterRtlNode,
    "rate_limiter_throttle": PacketRateLimiterThrottleRtlNode,
    "segmentation": SegmentationOffloadRtlNode,
    "nat": OverloadedNatRtlNode,
    "fifo": AxisFifoRtlNode,
}


def repo_path(path_str):
    path = Path(path_str)
    if path.is_absolute():
        return path
    repo_relative = REPO_ROOT / path
    if repo_relative.exists():
        return repo_relative
    return Path.cwd() / path


def load_json(path_str, label):
    if not path_str:
        m5.fatal(f"Missing required {label}")
    path = repo_path(path_str)
    if not path.exists():
        m5.fatal(f"{label} does not exist: {path}")
    with path.open() as f:
        return json.load(f)


def short_interface_name(logical_name):
    return logical_name.split("/")[-1]


class SmartNicJsonFactory:
    def __init__(self, connections_json, placement_json):
        self.connections_json = connections_json
        self.placement_json = placement_json
        self.sim_json = connections_json.get("smartnic_sim", {})
        if not self.sim_json:
            m5.fatal("SmartNIC connections JSON must contain a top-level smartnic_sim object")

        self.modules = self.sim_json.get("modules", {})
        self.endpoints = self.sim_json.get("endpoints", {})
        master_names, slave_names = build_logical_name_maps(connections_json, placement_json)
        self.nmu_to_endpoint = {
            short_interface_name(noc_name): endpoint
            for endpoint, noc_name in master_names.items()
        }
        self.nsu_to_endpoint = {
            short_interface_name(noc_name): endpoint
            for endpoint, noc_name in slave_names.items()
        }
        self.module_instances = {}

    def validate_interfaces(self, axis_nsu, axis_nmu, options):
        del options
        self._validate_role("AXIS NSU", set(axis_nsu), set(self.nsu_to_endpoint))
        self._validate_role("AXIS NMU", set(axis_nmu), set(self.nmu_to_endpoint))

        for endpoint in set(self.nsu_to_endpoint.values()) | set(self.nmu_to_endpoint.values()):
            if endpoint not in self.endpoints:
                m5.fatal(f"Missing smartnic_sim endpoint metadata for {endpoint}")

    def _validate_role(self, role, actual, expected):
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            m5.fatal(
                f"SmartNIC {role} interface mismatch. "
                f"missing_in_nts={sorted(missing)} extra_in_nts={sorted(extra)}"
            )

    def make_nsu(self, tile_name, options):
        return self._make_endpoint(tile_name, "slave", self.nsu_to_endpoint, options)

    def make_nmu(self, tile_name, options):
        return self._make_endpoint(tile_name, "master", self.nmu_to_endpoint, options)

    def _make_endpoint(self, tile_name, role, lookup, options):
        if tile_name not in lookup:
            m5.fatal(f"No SmartNIC JSON mapping for {role} interface {tile_name}")
        endpoint_name = lookup[tile_name]
        endpoint = self.endpoints.get(endpoint_name)
        if endpoint is None:
            m5.fatal(f"Missing smartnic_sim endpoint metadata for {endpoint_name}")

        kind = endpoint.get("kind")
        if kind == "axis_packet_source":
            if role != "master":
                m5.fatal(f"Endpoint {endpoint_name} is a packet source but is wired as {role}")
            return self._make_packet_source(endpoint, options)
        if kind == "axis_packet_checker":
            if role != "slave":
                m5.fatal(f"Endpoint {endpoint_name} is a packet checker but is wired as {role}")
            return self._make_packet_checker(endpoint, options)
        if kind == "rtl_module_port":
            return self._make_module_port(endpoint_name, endpoint, role, options)

        m5.fatal(f"Unsupported smartnic_sim endpoint kind for {endpoint_name}: {kind}")

    def _make_packet_source(self, endpoint, options):
        params = {
            "data_width": AXIS_DATA_WIDTH,
            "tid_width": AXIS_TID_WIDTH,
            "tdest_width": AXIS_TDEST_WIDTH,
            "tuser_width": AXIS_TUSER_WIDTH,
            "profile": "mixed_tcp_udp",
            "max_packets": max(options.num_packets, 1),
            "seed": 1,
            "min_payload_bytes": 16,
            "max_payload_bytes": 64,
            "flow_count": 4,
            "min_gap_cycles": 0,
            "max_gap_cycles": 0,
            "initial_gap_cycles": 16,
            "tid": 0,
            "tdest": 0,
            "tuser": 0,
            "src_ip": "192.168.1.100",
            "dst_ip": "8.8.8.8",
            "src_port": 12345,
            "dst_port": 80,
            "corrupt_ipv4_checksum": False,
            "corrupt_l4_checksum": False,
        }
        params.update(endpoint.get("params", {}))
        return AxisPacketTrafficGenerator(**params)

    def _make_packet_checker(self, endpoint, options):
        params = {
            "data_width": AXIS_DATA_WIDTH,
            "tid_width": AXIS_TID_WIDTH,
            "tdest_width": AXIS_TDEST_WIDTH,
            "tuser_width": AXIS_TUSER_WIDTH,
            "check_mode": "exact",
            "ready_percent": 100,
            "expected_packets": max(options.num_packets, 1),
            "validate_ipv4_checksum": True,
            "validate_l4_checksum": True,
            "print_summary": True,
            "profile": "mixed_tcp_udp",
            "seed": 1,
            "min_payload_bytes": 16,
            "max_payload_bytes": 64,
            "flow_count": 4,
            "tid": 0,
            "tdest": 0,
            "tuser": 0,
            "src_ip": "192.168.1.100",
            "dst_ip": "8.8.8.8",
            "src_port": 12345,
            "dst_port": 80,
            "nat_public_ip": "10.0.0.1",
            "nat_base_port": 40000,
            "nat_port_count": 256,
        }
        params.update(endpoint.get("params", {}))
        return AxisPacketCheckerSink(**params)

    def _make_module_port(self, endpoint_name, endpoint, role, options):
        expected_port = "slave" if role == "slave" else "master"
        port = endpoint.get("port")
        if port != expected_port:
            m5.fatal(
                f"Endpoint {endpoint_name} is wired as {role}, "
                f"but smartnic_sim declares port={port}"
            )
        module_id = endpoint.get("module")
        if not module_id:
            m5.fatal(f"Endpoint {endpoint_name} is missing rtl module ID")
        return self._get_module_instance(module_id, options)

    def _get_module_instance(self, module_id, options):
        if module_id in self.module_instances:
            return self.module_instances[module_id]

        module = self.modules.get(module_id)
        if module is None:
            m5.fatal(f"Missing smartnic_sim module metadata for {module_id}")
        kind = module.get("kind")
        if kind not in MODULE_REGISTRY:
            m5.fatal(f"Unsupported SmartNIC module kind for {module_id}: {kind}")

        params = {
            "sim_cycles": options.sim_cycles,
            "data_width": AXIS_DATA_WIDTH,
            "id_width": AXIS_TID_WIDTH,
            "dest_width": AXIS_TDEST_WIDTH,
            "user_width": 1 if kind == "fifo" else AXIS_TUSER_WIDTH,
            "expected_packets": max(options.num_packets, 1),
            "reset_cycles": 8,
        }
        params.update(module.get("params", {}))
        instance = MODULE_REGISTRY[kind](**params)
        self.module_instances[module_id] = instance
        return instance


options = get_parser()
if not options.smartnic_connections_json:
    m5.fatal("--smartnic-connections-json is required for smartnic_general.py")
if not options.smartnic_placement_json:
    m5.fatal("--smartnic-placement-json is required for smartnic_general.py")
if options.noc_topology == DEFAULT_TOPOLOGY:
    m5.fatal("--noc-topology must point to the generated SmartNIC topology base")

connections_json = load_json(options.smartnic_connections_json, "--smartnic-connections-json")
placement_json = load_json(options.smartnic_placement_json, "--smartnic-placement-json")
factory = SmartNicJsonFactory(connections_json, placement_json)

run_axis_test(
    options.noc_topology,
    factory.make_nsu,
    factory.make_nmu,
    interface_validator=factory.validate_interfaces,
)
