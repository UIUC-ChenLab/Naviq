import sys
from pathlib import Path
import json


GENERIC_DIR = Path(__file__).resolve().parents[1] / "generic"
if str(GENERIC_DIR) not in sys.path:
    sys.path.insert(0, str(GENERIC_DIR))

from generic_v3_smoke_common import build_aximm_param_overrides, run_v3_smoke


def _workspace_root() -> Path:
    """Directory that contains noc_testing/ (sibling to src/), not .../src."""
    here = Path(__file__).resolve()
    for d in (here.parent, *here.parents):
        if (d / "noc_testing").is_dir():
            return d
    return here.parents[3]


num_tgs = 32
HBM_SAT_TGS = [f"hbm_sat_tg_{idx:02d}" for idx in range(num_tgs)]

REPO_ROOT = _workspace_root()
TOPOLOGY_BUNDLE = REPO_ROOT / "src/noc/topology/topologies/hbm_1stack_16GB"
TOPOLOGY_DIR = TOPOLOGY_BUNDLE / "full"
STEM = "hbm_1stack_16GB"
CONNECTIONS_JSON = TOPOLOGY_DIR / f"{STEM}.conn.json"
PLACEMENT_JSON = TOPOLOGY_DIR / f"{STEM}.place.json"
NTS_FILE = TOPOLOGY_DIR / f"{STEM}.nts"
NCR_FILE = TOPOLOGY_DIR / f"{STEM}.ncr"

HBM_ROW_MISS_LATENCY_CYCLES = 15
HBM_READ_LATENCY_CYCLES = 25
HBM_WRITE_LATENCY_CYCLES = 15
HBM_RESP_LATENCY_CYCLES = 4

HBM_BASE_ADDR = 0x4000000000
HBM_CHANNEL_STRIDE = 0x80000000
HBM_PC_SIZE = 0x40000000
HBM_TRANSACTION_SIZE_BYTES = 512
HBM_PORT_BANK_SKEW_BYTES = 256
HBM_ADDRESS_STRIPES_PER_TG = 2
HBM_ADDRESS_STRIPE_PHASE_BYTES = 256


def _redirect_legacy_topology_args() -> None:
    """Keep old command lines working after moving this topology into a bundle."""
    replacements = {
        "src/noc/topology/topologies/hbm/hbm_full_1_stack_16GB.nts": str(NTS_FILE),
        "src/noc/topology/topologies/hbm/hbm_full_1_stack_16GB.ncr": str(NCR_FILE),
        "src/noc/topology/topologies/hbm/hbm_full_1_stack_16GB.nc": str(NCR_FILE),
    }

    rewritten = [sys.argv[0]]
    for arg in sys.argv[1:]:
        if arg in replacements:
            rewritten.append(replacements[arg])
            continue

        if arg.startswith("--nts-file="):
            value = arg.split("=", 1)[1]
            rewritten.append(f"--nts-file={replacements.get(value, value)}")
            continue

        if arg.startswith("--ncr-file="):
            value = arg.split("=", 1)[1]
            rewritten.append(f"--ncr-file={replacements.get(value, value)}")
            continue

        rewritten.append(arg)

    sys.argv = rewritten


def _filtered_connections_json_for_num_tgs(num_tgs: int) -> str:
    if num_tgs <= 0:
        raise ValueError(f"num_tgs must be >= 1 (got {num_tgs})")

    src_path = Path(CONNECTIONS_JSON)
    data = json.loads(src_path.read_text())

    keep_components = set()
    for idx in range(num_tgs):
        keep_components.add(f"hbm_sat_tg_{idx:02d}")
        hbm_idx = idx // 4
        port_idx = idx % 4
        keep_components.add(f"hbm{hbm_idx}_port{port_idx}")

    components = data.get("components", {})
    filtered_components = {
        comp_id: comp_def
        for comp_id, comp_def in components.items()
        if comp_id in keep_components
    }

    for comp_def in filtered_components.values():
        comp_id = comp_def.get("id")
        node_type = comp_def.get("node_type")
        comp_def.setdefault("params", {})
        if node_type == "tileNSU_HBM":
            comp_def["params"]["clock_domain_mhz"] = 1600
            comp_def["params"]["row_miss_latency_cycles"] = HBM_ROW_MISS_LATENCY_CYCLES
            comp_def["params"]["read_latency_cycles"] = HBM_READ_LATENCY_CYCLES
            comp_def["params"]["write_latency_cycles"] = HBM_WRITE_LATENCY_CYCLES
            comp_def["params"]["resp_latency_cycles"] = HBM_RESP_LATENCY_CYCLES
            # comp_def["params"]["hbm_trace_tile_index"] = int(comp_id.rsplit("_", 1)[1])
        elif node_type == "AxiRandomTrafficGenerator":
            comp_def["params"]["clock_domain_mhz"] = 500

    data["components"] = filtered_components

    def _comp_from_endpoint(endpoint: str) -> str:
        # "component.port" -> "component"
        return endpoint.split(".", 1)[0]

    connections = data.get("connections", [])
    data["connections"] = [
        c
        for c in connections
        if _comp_from_endpoint(c.get("from", "")) in keep_components
        and _comp_from_endpoint(c.get("to", "")) in keep_components
    ]

    out_name = src_path.name.replace(".conn.json", f".num_tgs_{num_tgs}.conn.json")
    out_path = src_path.with_name(out_name)
    out_path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
    return str(out_path)


def _split_pc_address_overrides(component_ids) -> list[str]:
    half_pc_size = HBM_PC_SIZE // 2
    stripe_region_size = half_pc_size // HBM_ADDRESS_STRIPES_PER_TG
    params = []

    for component_id in component_ids:
        tg_idx = int(component_id.rsplit("_", 1)[1])
        hbm_idx = tg_idx // 4
        port_idx = tg_idx % 4
        pc_idx = port_idx // 2
        port_in_pc = port_idx % 2

        pc_base = (
            HBM_BASE_ADDR
            + hbm_idx * HBM_CHANNEL_STRIDE
            + pc_idx * HBM_PC_SIZE
        )
        half_base = pc_base + port_in_pc * half_pc_size

        # Ports 0/1 share pseudo-channel 0 and ports 2/3 share pseudo-channel 1.
        # Skew the second port by one 256B NPP, then expose two 256B-aligned
        # address windows per TG. The random strategy round-robins these windows,
        # alternating which half of the modeled bank pair is touched first while
        # avoiding partial-NPP writes in the current splitter path.
        port_skew = port_in_pc * HBM_PORT_BANK_SKEW_BYTES
        stripe_bases = []
        stripe_spaces = []
        for stripe_idx in range(HBM_ADDRESS_STRIPES_PER_TG):
            stripe_phase = stripe_idx * HBM_ADDRESS_STRIPE_PHASE_BYTES
            stripe_base = (
                half_base
                + stripe_idx * stripe_region_size
                + port_skew
                + stripe_phase
            )
            stripe_end = half_base + (stripe_idx + 1) * stripe_region_size - 1
            stripe_space = stripe_end - stripe_base + 1
            if stripe_space >= HBM_TRANSACTION_SIZE_BYTES:
                stripe_bases.append(stripe_base)
                stripe_spaces.append(stripe_space)

        base_addr = stripe_bases[0]
        max_addr = half_base + half_pc_size - 1

        params.extend(
            [
                f"{component_id}.base_addr={base_addr}",
                f"{component_id}.max_addr={max_addr}",
                f"{component_id}.nsu_min_addrs={stripe_bases}",
                f"{component_id}.nsu_address_spaces={stripe_spaces}",
                f"{component_id}.nsu_selection=INTERLEAVE",
            ]
        )

    return params


# gem5 commonly executes config scripts with __name__ == "__m5_main__".
# Keep this file importable without triggering a sim run.
if __name__ in ("__main__", "__m5_main__"):
    _redirect_legacy_topology_args()
    run_v3_smoke(
        label="HBM full 1 stack 16GB smoke",
        noc_topology=TOPOLOGY_DIR,
        connections_json=_filtered_connections_json_for_num_tgs(num_tgs),
        placement_json=PLACEMENT_JSON,
        default_args=[
            "--nts-file",
            NTS_FILE,
            "--ncr-file",
            NCR_FILE,
            "--num-packets",
            "64",
            "--abs-max-tick",
            "10000000000",
        ],
        param_overrides=(
            build_aximm_param_overrides(
                HBM_SAT_TGS,
                num_transactions=100,
                # HBM NMUs only accept 32..256-bit beats (4..32 bytes).
                beat_size_bytes=32,
                transaction_size_bytes=HBM_TRANSACTION_SIZE_BYTES,
                bandwidth_MBps=0,
                max_outstanding_writes=32,
                align_addresses=False,
                address_distribution="INCREMENT",
                address_increment_bytes=HBM_TRANSACTION_SIZE_BYTES,
                awid_distribution="INCREMENT",
                min_awid=0,
                max_awid=3,
            )
            + _split_pc_address_overrides(HBM_SAT_TGS)
        ),
    )
