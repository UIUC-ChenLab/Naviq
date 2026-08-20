import runpy
import sys
from pathlib import Path


def _flag_present(args, flag):
    return any(arg == flag or arg.startswith(flag + "=") for arg in args)


def _infer_placement_path(connections_json):
    path = Path(connections_json)
    name = path.name
    if name.endswith(".conn.json"):
        candidate = path.with_name(name[: -len(".conn.json")] + ".place.json")
        if candidate.exists():
            return str(candidate)
    return None


def _append_default_arg(argv, user_args, flag, value):
    if value is None or _flag_present(user_args, flag):
        return
    argv.extend([flag, str(value)])


def build_aximm_param_overrides(
    component_ids,
    *,
    num_transactions=8,
    beat_size_bytes=64,
    transaction_size_bytes=None,
    bandwidth_MBps=800,
    read_write_mode="WRITE_ONLY",
    data_width_bits=512,
    max_outstanding_writes=4,
    align_addresses=False,
    address_distribution="INCREMENT",
    address_increment_bytes=None,
    awid_distribution="FIXED",
    min_awid=0,
    max_awid=15,
):
    transaction_size = transaction_size_bytes or beat_size_bytes
    address_increment = (
        address_increment_bytes
        if address_increment_bytes is not None
        else beat_size_bytes
    )
    params = []
    for component_id in component_ids:
        params.extend(
            [
                f"{component_id}.data_width={data_width_bits}",
                f"{component_id}.beat_size_bytes={beat_size_bytes}",
                f"{component_id}.min_transaction_size_bytes={transaction_size}",
                f"{component_id}.max_transaction_size_bytes={transaction_size}",
                f"{component_id}.transaction_size_distribution=FIXED",
                f"{component_id}.read_write_mode={read_write_mode}",
                f"{component_id}.max_write_commands={num_transactions}",
                f"{component_id}.max_write_bandwidth_mbps={bandwidth_MBps}",
                f"{component_id}.max_read_bandwidth_mbps={bandwidth_MBps}",
                f"{component_id}.min_gap_cycles=0",
                f"{component_id}.max_gap_cycles=0",
                f"{component_id}.max_outstanding_writes={max_outstanding_writes}",
                f"{component_id}.awid_distribution={awid_distribution}",
                f"{component_id}.min_awid={min_awid}",
                f"{component_id}.max_awid={max_awid}",
                f"{component_id}.address_distribution={address_distribution}",
                f"{component_id}.address_increment={address_increment}",
                f"{component_id}.align_addresses={'true' if align_addresses else 'false'}",
            ]
        )
    return params


def build_axis_source_param_overrides(
    component_ids,
    *,
    packets=8,
    packet_size_bytes=64,
    data_width_bits=512,
    max_tdest=0,
):
    params = []
    for component_id in component_ids:
        params.extend(
            [
                f"{component_id}.data_width={data_width_bits}",
                f"{component_id}.min_packet_size_bytes={packet_size_bytes}",
                f"{component_id}.max_packet_size_bytes={packet_size_bytes}",
                f"{component_id}.packet_size_distribution=FIXED",
                f"{component_id}.max_gap_cycles=0",
                f"{component_id}.max_packets={packets}",
                f"{component_id}.max_tdest={max_tdest}",
            ]
        )
    return params


def build_expected_packet_overrides(expected_packets_by_component):
    params = []
    for component_id, expected_packets in expected_packets_by_component.items():
        params.append(f"{component_id}.expected_packets={expected_packets}")
    return params


def run_v3_smoke(
    *,
    label,
    noc_topology,
    connections_json,
    placement_json=None,
    default_args=None,
    param_overrides=None,
):
    setup_dir = Path(__file__).resolve().parents[2] / "setup"
    user_args = list(sys.argv[1:])
    placement = placement_json or _infer_placement_path(connections_json)
    if placement is None and not _flag_present(user_args, "--placement-json"):
        raise RuntimeError(
            f"[{label}] no default placement JSON found for {connections_json}; "
            "pass --placement-json explicitly."
        )

    argv = [sys.argv[0]]
    _append_default_arg(argv, user_args, "--noc-topology", noc_topology)
    _append_default_arg(argv, user_args, "--connections-json", connections_json)
    _append_default_arg(argv, user_args, "--placement-json", placement)

    for arg in default_args or []:
        argv.append(str(arg))

    if not _flag_present(user_args, "--param"):
        for override in param_overrides or []:
            argv.extend(["--param", override])
    else:
        for override in param_overrides or []:
            argv.extend(["--param", override])

    argv.extend(user_args)
    sys.argv = argv
    print(f"[{label}] argv={' '.join(sys.argv[1:])}")
    # v3 smokes use the Naviq v2-style setup pipeline (connections + placement JSON).
    runpy.run_path(str(setup_dir / "noc_setup_config.py"), run_name="__main__")
