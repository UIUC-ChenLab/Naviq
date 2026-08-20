"""
Helper module to get topologys.

"""

import json
import re
from pathlib import Path
from typing import Dict

# --- Defaults ---
# Default topology counts if not specified in JSON or CSV
TOPOLOGY_DEFAULTS = {
    "num_aximm_tg": 0,
    "num_aximm_bram": 0,
    "num_axis_tg": 0,
    "num_axis_end": 0,
    "num_hbm_ports": 0,
    "num_ddr_ports": 0,
}

# --- Tcl Aliases ---
# Keys the Tcl script checks for a JSON topology
# See: _json_from_row in noc_plan_csv.tcl
JSON_TOPOLOGY_KEYS = [
    "connections_json",
    "topology_json",
    "topology",
    "topology_file",
    "connection_json",
    "connection_file",
]

# Aliases for CSV column names, mapping to the canonical key
# See: _topology_from_row in noc_plan_csv.tcl
CSV_COUNT_ALIASES = {
    "num_aximm_tg": ["num_aximm_tg", "num_axi_tg"],
    "num_aximm_bram": ["num_aximm_bram", "num_axi_bram"],
    "num_axis_tg": ["num_axis_tg"],
    "num_axis_end": ["num_axis_end", "num_axis_endpoints"],
    "num_hbm_ports": ["num_hbm_ports", "num_hbm", "hbm_ports"],
    "num_ddr_ports": ["num_ddr_ports", "num_ddr", "ddr_ports"],
}

V2_CONNECTION_KIND = "naviq.connections"


def _clean_stem(path_text: str) -> str:
    name = Path(path_text).name
    for suffix in (".conn.json", ".place.json", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _get_val_from_row(row: Dict, key_list: list, default_val: int) -> int:
    """
    Helper to find the first valid integer from a list of possible row keys.
    """
    for csv_key in key_list:
        val = str(row.get(csv_key) or "").strip()
        if val.isdigit():
            return int(val)
    return default_val


def _get_placement_suffix(row: Dict) -> str:
    """
    Helper to get the placement suffix for the topology key.
    """
    placement_key_list = ["placement_json", "placement", "placement_file"]
    for key in placement_key_list:
        path_in_row = str(row.get(key) or "").strip()
        if path_in_row:
             return "__" + _clean_stem(path_in_row)
    return ""


def _resolve_json_path(path_str: str, workspace_root: Path) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    candidates = [
        workspace_root / path,
        workspace_root.parent / path,
        Path.cwd() / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (workspace_root / path).resolve()


def _is_endpoint_kind(component: Dict, port: Dict, needle: str) -> bool:
    haystack = " ".join([
        str(component.get("node_type", "")),
        str(component.get("type", "")),
        str(port.get("type", "")),
        str(port.get("physical_type", "")),
    ]).lower()
    return needle in haystack


def _counts_from_v2(topo_data: Dict) -> Dict[str, int]:
    counts = dict(TOPOLOGY_DEFAULTS)
    for component in topo_data.get("components", {}).values():
        node_type = str(component.get("node_type", ""))
        for port in component.get("ports", {}).values():
            role = str(port.get("role", "")).lower()
            protocol = str(port.get("protocol", "")).lower()
            if role == "master" and protocol == "aximm":
                counts["num_aximm_tg"] += 1
            elif role == "master" and protocol == "axis":
                counts["num_axis_tg"] += 1
            elif role == "slave" and protocol == "axis":
                counts["num_axis_end"] += 1
            elif role == "slave" and protocol == "aximm":
                if _is_endpoint_kind(component, port, "hbm"):
                    counts["num_hbm_ports"] += 1
                elif _is_endpoint_kind(component, port, "ddr"):
                    counts["num_ddr_ports"] += 1
                else:
                    counts["num_aximm_bram"] += 1
    return counts


def get_topology_from_row(row: Dict, workspace_root: Path) -> Dict:
    """
    Gets topology component counts from the CSV row, following a
    specific priority order to match the Tcl sweep scripts.

    Priority 1: A valid `topology_json` file is found and parsed.
    Priority 2: Count values (e.g., `num_aximm_tg`) are in the CSV row.
    Priority 3: The defaults defined in `TOPOLOGY_DEFAULTS`.
    """
    # --- Priority 1: Check for a JSON topology file ---
    topo_key = ""
    json_path_str = None
    for key in JSON_TOPOLOGY_KEYS:
        path_in_row = str(row.get(key) or "").strip()
        if path_in_row:
            json_path_str = path_in_row
            break

    if json_path_str:
        # Resolve the path relative to the workspace root
        # See: _parse_topology_from_json in noc_helpers.tcl
        full_json_path = _resolve_json_path(json_path_str, workspace_root)

        if not full_json_path.exists():
            print(f"    [WARN] Topology JSON specified but not found: {full_json_path}")
        else:
            try:
                with full_json_path.open("r") as f:
                    topo_data = json.load(f)

                if topo_data.get("kind") == V2_CONNECTION_KIND:
                    counts = _counts_from_v2(topo_data)
                    topo_key = _clean_stem(str(full_json_path)) + _get_placement_suffix(row)
                    if not _get_placement_suffix(row):
                        topo_key += "__auto_place"
                else:
                    # Get counts by measuring the length of the master/slave lists
                    # This mirrors _build_bd_from_topology in noc_project.tcl
                    counts = {
                        "num_aximm_tg": len(topo_data.get("aximm_masters", [])),
                        "num_aximm_bram": len(topo_data.get("aximm_slaves", [])),
                        "num_axis_tg": len(topo_data.get("axis_masters", [])),
                        "num_axis_end": len(topo_data.get("axis_slaves", [])),
                        "num_hbm_ports": len(topo_data.get("hbm_ports", topo_data.get("hbm_slaves", []))),
                        "num_ddr_ports": len(topo_data.get("ddr_ports", topo_data.get("ddr_slaves", []))),
                    }
                    topo_key = full_json_path.stem + _get_placement_suffix(row)
                print("     Populating counts from JSON file...")
                return counts, topo_key  # Return immediately on successful JSON parse
                # return {'key': topo_key, 'counts': counts}

            except Exception as e:
                print(f"    [WARN] Failed to parse JSON topology: {full_json_path}\n    Error: {e}")
                # Falls through to Priority 2/3

    # --- Priority 2 & 3: Check CSV row or use defaults ---
    print("     Populating counts from CSV row/defaults...")

    counts = {
        "num_aximm_tg": _get_val_from_row(
            row,
            CSV_COUNT_ALIASES["num_aximm_tg"],
            TOPOLOGY_DEFAULTS["num_aximm_tg"]
        ),
        "num_aximm_bram": _get_val_from_row(
            row,
            CSV_COUNT_ALIASES["num_aximm_bram"],
            TOPOLOGY_DEFAULTS["num_aximm_bram"]
        ),
        "num_axis_tg": _get_val_from_row(
            row,
            CSV_COUNT_ALIASES["num_axis_tg"],
            TOPOLOGY_DEFAULTS["num_axis_tg"]
        ),
        "num_axis_end": _get_val_from_row(
            row,
            CSV_COUNT_ALIASES["num_axis_end"],
            TOPOLOGY_DEFAULTS["num_axis_end"]
        ),
        "num_hbm_ports": _get_val_from_row(
            row,
            CSV_COUNT_ALIASES["num_hbm_ports"],
            TOPOLOGY_DEFAULTS["num_hbm_ports"]
        ),
        "num_ddr_ports": _get_val_from_row(
            row,
            CSV_COUNT_ALIASES["num_ddr_ports"],
            TOPOLOGY_DEFAULTS["num_ddr_ports"]
        ),
    }

    topo_key = (
        f"mm_tg={counts['num_aximm_tg']}_"
        f"bram={counts['num_aximm_bram']}_"
        f"axis_tg={counts['num_axis_tg']}_"
        f"end={counts['num_axis_end']}_"
        f"hbm={counts['num_hbm_ports']}_"
        f"ddr={counts['num_ddr_ports']}"
    ) + _get_placement_suffix(row)

    # return {'key': topo_key, 'counts': counts}

    return counts, topo_key
