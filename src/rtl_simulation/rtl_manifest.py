#!/usr/bin/env python3
"""Validate declarative RTL-to-NoC integration manifests.

The Verilator hierarchy tells us what XPM endpoints exist.  This module keeps
the remaining policy explicit: which physical NoC endpoint an RTL interface
uses, its clock-domain label, and its future generated gem5 wrapper contract.
It deliberately emits a configuration *plan*, not an executable gem5 config;
the latter requires a compiled C++ factory for the selected Verilated model.
"""

import argparse
import json
import os
import re
from pathlib import Path


SCHEMA_VERSION = 1
REQUIRED_CONNECTION_FIELDS = ("connect_to", "connect_loc", "clock_domain")
GEM5_WRAPPER_FIELDS = {
    "clock_signal",
    "reset_signal",
    "data_width",
    "id_width",
    "addr_width",
}
CPP_MEMBER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ManifestError(ValueError):
    """A user-facing manifest or endpoint-map validation error."""


def _validate_gem5_wrapper(data):
    """Validate optional explicit RTL signal and width metadata for a wrapper."""
    wrapper = data.get("gem5_wrapper")
    if wrapper is None:
        return
    if not isinstance(wrapper, dict):
        raise ManifestError("manifest 'gem5_wrapper' must be an object")
    unknown = sorted(set(wrapper) - GEM5_WRAPPER_FIELDS)
    if unknown:
        raise ManifestError(
            "manifest 'gem5_wrapper' has unsupported field(s): {}".format(
                ", ".join(unknown)
            )
        )
    for field in ("clock_signal", "reset_signal"):
        value = wrapper.get(field)
        if value is not None and (
            not isinstance(value, str) or not CPP_MEMBER_NAME.fullmatch(value)
        ):
            raise ManifestError(
                "gem5_wrapper.{} must be a simple Verilator root member name".format(
                    field
                )
            )
    ranges = {
        "data_width": (32, 512, 8),
        "id_width": (1, 32, 1),
        "addr_width": (1, 64, 1),
    }
    for field, (minimum, maximum, multiple) in ranges.items():
        value = wrapper.get(field)
        if value is None:
            continue
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
            or value > maximum
            or value % multiple
        ):
            detail = "between {} and {}".format(minimum, maximum)
            if multiple > 1:
                detail += " and divisible by {}".format(multiple)
            raise ManifestError(
                "gem5_wrapper.{} must be an integer {}".format(field, detail)
            )


def _read_json(path):
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def load_manifest(path):
    """Load and structurally validate an RTL integration manifest."""
    manifest_path = Path(path).resolve()
    data = _read_json(manifest_path)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(
            "unsupported manifest schema_version {}; expected {}".format(
                data.get("schema_version"), SCHEMA_VERSION
            )
        )
    for field in ("design", "top_module", "sources", "endpoints"):
        if field not in data:
            raise ManifestError("manifest is missing required field '{}'".format(field))
    if not isinstance(data["sources"], list) or not data["sources"]:
        raise ManifestError("manifest 'sources' must be a non-empty list")
    if not isinstance(data["endpoints"], list):
        raise ManifestError("manifest 'endpoints' must be a list")
    _validate_gem5_wrapper(data)

    instance_paths = set()
    for endpoint in data["endpoints"]:
        instance_path = endpoint.get("instance_path")
        if not isinstance(instance_path, str) or not instance_path:
            raise ManifestError("every endpoint needs a non-empty instance_path")
        if instance_path in instance_paths:
            raise ManifestError("duplicate endpoint instance_path '{}'".format(instance_path))
        instance_paths.add(instance_path)
        connections = endpoint.get("connections")
        if not isinstance(connections, list) or not connections:
            raise ManifestError(
                "endpoint '{}' needs a non-empty connections list".format(instance_path)
            )
        for connection in connections:
            missing = [
                field for field in REQUIRED_CONNECTION_FIELDS if field not in connection
            ]
            if missing:
                raise ManifestError(
                    "endpoint '{}' connection is missing {}".format(
                        instance_path, ", ".join(missing)
                    )
                )
    data["_path"] = str(manifest_path)
    return data


def build_spec(manifest):
    """Convert a manifest into the build_rtl_models.py design-spec shape."""
    manifest_dir = Path(manifest["_path"]).parent

    def resolve_all(paths):
        resolved = []
        for path in paths:
            expanded = os.path.expandvars(path)
            if "$" in expanded:
                raise ManifestError(
                    "unresolved environment variable in path '{}'".format(path)
                )
            candidate = Path(expanded)
            if not candidate.is_absolute():
                candidate = manifest_dir / candidate
            resolved.append(str(candidate.resolve()))
        return resolved

    return {
        "name": manifest["design"],
        "top_module": manifest["top_module"],
        "sources": resolve_all(manifest["sources"]),
        "include_dirs": resolve_all(manifest.get("include_dirs", [])),
        "extra_args": list(manifest.get("extra_args", [])),
        "manifest": manifest,
    }


def _wrapper_contract(endpoint):
    """Name the role-aware C++ bridge contract selected by an endpoint."""
    return "{}_{}".format(endpoint["protocol"], endpoint["role"])


def build_gem5_plan(manifest, endpoint_map):
    """Validate discovered RTL against policy and return a deterministic plan."""
    if endpoint_map.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError("unsupported endpoint-map schema_version")
    if endpoint_map.get("design") != manifest["design"]:
        raise ManifestError(
            "manifest design '{}' does not match endpoint-map design '{}'".format(
                manifest["design"], endpoint_map.get("design")
            )
        )

    discovered = {
        endpoint["instance_path"]: endpoint
        for endpoint in endpoint_map.get("endpoints", [])
    }
    declared = {endpoint["instance_path"]: endpoint for endpoint in manifest["endpoints"]}
    missing = sorted(set(declared) - set(discovered))
    unexpected = sorted(set(discovered) - set(declared))
    if missing or unexpected:
        details = []
        if missing:
            details.append("not discovered: {}".format(", ".join(missing)))
        if unexpected:
            details.append("not declared: {}".format(", ".join(unexpected)))
        raise ManifestError("endpoint declaration mismatch ({})".format("; ".join(details)))

    nodes = []
    # Manifest order is intentional configuration order (and is stable in
    # version control), so preserve it in the emitted gem5 connection plan.
    for declared_endpoint in manifest["endpoints"]:
        instance_path = declared_endpoint["instance_path"]
        discovered_endpoint = discovered[instance_path]
        for field in ("protocol", "role"):
            expected = declared_endpoint.get(field)
            if expected is not None and expected != discovered_endpoint[field]:
                raise ManifestError(
                    "endpoint '{}' declares {}='{}', but RTL discovered '{}'".format(
                        instance_path, field, expected, discovered_endpoint[field]
                    )
                )
        nodes.append(
            {
                "name": declared_endpoint.get("name", instance_path),
                "wrapper_contract": _wrapper_contract(discovered_endpoint),
                "endpoint": discovered_endpoint,
                "connections": declared_endpoint["connections"],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "design": manifest["design"],
        "top_module": manifest["top_module"],
        "gem5_wrapper": manifest.get("gem5_wrapper", {}),
        "nodes": nodes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="RTL integration manifest JSON")
    parser.add_argument("endpoint_map", help="generated <design>_noc_endpoints.json")
    parser.add_argument(
        "--output", help="write the validated gem5 connection plan to this path"
    )
    args = parser.parse_args()
    try:
        plan = build_gem5_plan(load_manifest(args.manifest), _read_json(args.endpoint_map))
    except (ManifestError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    rendered = json.dumps(plan, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
