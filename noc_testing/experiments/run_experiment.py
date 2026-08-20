#!/usr/bin/env python3
"""Discover and run maintained NoC experiment campaigns.

This wrapper intentionally owns campaign selection, prerequisite reporting, and
the caller-selected output directory.  It does not duplicate the simulation
logic in the existing campaign drivers.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"
EXTERNAL_REQUIREMENTS = {"vivado", "external-rtl"}


def _load_manifests() -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as source:
            manifest = json.load(source)
        required = {"schema_version", "id", "title", "status", "runner", "requires"}
        missing = required - manifest.keys()
        if missing:
            raise ValueError(f"{path}: missing required fields: {sorted(missing)}")
        if manifest["schema_version"] != 1:
            raise ValueError(f"{path}: unsupported schema version")
        if manifest["id"] in manifests:
            raise ValueError(f"duplicate experiment id: {manifest['id']}")
        manifest["_path"] = path
        manifests[manifest["id"]] = manifest
    return manifests


def _repo_path(value: str) -> Path:
    path = (REPO_ROOT / value).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as error:
        raise ValueError(f"path escapes repository: {value}") from error
    return path


def _missing_prerequisites(manifest: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for requirement in manifest["requires"]:
        if requirement == "gem5-null" and not (REPO_ROOT / "build/NULL/gem5.opt").exists():
            missing.append("build/NULL/gem5.opt (build with: scons build/NULL/gem5.opt -j$(nproc))")
        elif requirement == "gem5-x86" and not (REPO_ROOT / "build/X86/gem5.opt").exists():
            missing.append("build/X86/gem5.opt (build the documented X86 target)")
        elif requirement == "vivado" and shutil.which("vivado") is None:
            missing.append("vivado on PATH (licensed Vivado environment required)")
        elif requirement == "external-rtl" and not (REPO_ROOT / "src/noc/external/rtl").exists():
            missing.append("src/noc/external/rtl (initialize the external RTL dependency)")
        elif requirement.startswith("python-"):
            module = requirement.removeprefix("python-").replace("-", "_")
            if importlib.util.find_spec(module) is None:
                missing.append(
                    f"Python module '{module}' (install with: python3 -m pip install -r requirements.txt)"
                )
    return missing


def _validate_paths(manifest: dict[str, Any]) -> list[str]:
    missing = []
    for value in [manifest["runner"], *manifest.get("inputs", []), *manifest.get("reference_paths", [])]:
        if value and not _repo_path(value).exists():
            missing.append(value)
    return missing


def _command(manifest: dict[str, Any], output: Path | None) -> list[str]:
    if not manifest["runner"]:
        return []
    runner = _repo_path(manifest["runner"])
    command = [sys.executable, str(runner), *manifest.get("default_args", [])]
    if output is not None and manifest.get("output_argument"):
        command.extend([manifest["output_argument"], str(output)])
    return command


def _display(manifest: dict[str, Any], output: Path | None, include_prerequisites: bool) -> int:
    print(f"Campaign: {manifest['id']} — {manifest['title']}")
    print(f"Status: {manifest['status']}")
    command = _command(manifest, output)
    print("Command:", " ".join(command) if command else "not yet implemented")
    if manifest.get("validation"):
        print("Validation:", manifest["validation"])
    if include_prerequisites:
        missing = _missing_prerequisites(manifest)
        if missing:
            print("Missing prerequisites:")
            for item in missing:
                print(f"  - {item}")
        else:
            print("Prerequisites: available")
    missing_paths = _validate_paths(manifest)
    if missing_paths:
        print("Missing tracked inputs/references:")
        for item in missing_paths:
            print(f"  - {item}")
        return 2
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list maintained campaigns")
    parser.add_argument(
        "--dry-run-all",
        action="store_true",
        help="validate every manifest's tracked inputs without running campaigns",
    )
    parser.add_argument("--id", help="campaign identifier from --list")
    parser.add_argument("--dry-run", action="store_true", help="show command and validate tracked inputs")
    parser.add_argument("--run", action="store_true", help="execute the campaign driver")
    parser.add_argument("--output", type=Path, help="caller-owned output directory required by --run")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="allow licensed Vivado or external-RTL campaign execution",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifests = _load_manifests()
    if args.dry_run_all:
        if any((args.list, args.id, args.dry_run, args.run, args.output, args.allow_external)):
            raise SystemExit("--dry-run-all cannot be combined with other campaign options")
        return max(
            _display(manifest, None, include_prerequisites=False)
            for manifest in manifests.values()
        )
    if args.list:
        if any((args.id, args.dry_run, args.run, args.output, args.allow_external)):
            raise SystemExit("--list cannot be combined with other campaign options")
        for campaign in manifests.values():
            print(f"{campaign['id']:32} {campaign['status']:11} {campaign['title']}")
        return 0
    if not args.id or args.id not in manifests:
        raise SystemExit("select a campaign with --id (see --list)")
    if args.dry_run == args.run:
        raise SystemExit("select exactly one of --dry-run or --run")
    if args.run and args.output is None:
        raise SystemExit("--run requires --output <directory>")

    manifest = manifests[args.id]
    output = args.output.resolve() if args.output else None
    result = _display(manifest, output, include_prerequisites=args.run)
    if result or args.dry_run:
        return result
    if manifest["status"] == "planned" or not manifest["runner"]:
        print("This campaign is planned and has no checked-in runnable driver.", file=sys.stderr)
        return 2
    external = EXTERNAL_REQUIREMENTS.intersection(manifest["requires"])
    if external and not args.allow_external:
        print("Refusing external campaign; re-run with --allow-external.", file=sys.stderr)
        return 2
    missing = _missing_prerequisites(manifest)
    if missing:
        return 2
    output.mkdir(parents=True, exist_ok=True)
    command = _command(manifest, output)
    (output / "manifest.json").write_text(
        json.dumps({key: value for key, value in manifest.items() if key != "_path"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
    working_directory = _repo_path(manifest.get("working_directory", "."))
    return subprocess.run(command, cwd=working_directory, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
