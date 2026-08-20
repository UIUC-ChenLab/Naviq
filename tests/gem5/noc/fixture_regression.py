"""Checks for pinned NoC topology fixtures used by fast TestLib smokes."""

import json
from dataclasses import dataclass
from pathlib import Path

from testlib import test_util


@dataclass(frozen=True)
class TopologyFixtureSpec:
    name: str
    connections_json: str
    placement_json: str
    nts: str
    ncr: str


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        test_util.fail(f"Could not read JSON fixture {path}: {exc}")


def _require_nonempty_list(path, document, key):
    value = document.get(key)
    if not isinstance(value, list) or not value:
        test_util.fail(f"{path} must contain a non-empty '{key}' list")


def run_topology_fixture_check(specs, params):
    """Validate fixture inputs and generated NoC descriptions without gem5."""
    for spec in specs:
        fixture_paths = (
            spec.connections_json,
            spec.placement_json,
            spec.nts,
            spec.ncr,
        )
        missing_sources = [
            path for path in fixture_paths if not Path(path).is_file()
        ]
        if missing_sources:
            test_util.fail(
                f"{spec.name} is missing fixture files: "
                + ", ".join(missing_sources)
            )

        connections = _read_json(spec.connections_json)
        placement = _read_json(spec.placement_json)
        nts = _read_json(spec.nts)
        ncr = _read_json(spec.ncr)

        components = connections.get("components")
        if not isinstance(components, dict) or not components:
            test_util.fail(
                f"{spec.connections_json} must contain non-empty components"
            )
        _require_nonempty_list(
            spec.connections_json, connections, "connections"
        )

        placements = placement.get("placements")
        if not isinstance(placements, dict) or not placements:
            test_util.fail(
                f"{spec.placement_json} must contain non-empty placements"
            )
        _require_nonempty_list(spec.nts, nts, "LogicalInstances")
        _require_nonempty_list(spec.nts, nts, "Paths")
        _require_nonempty_list(spec.ncr, ncr, "Paths")

        params.log.message(
            f"{spec.name}: {len(components)} components, "
            f"{len(nts['Paths'])} NTS paths, {len(ncr['Paths'])} NCR paths"
        )
