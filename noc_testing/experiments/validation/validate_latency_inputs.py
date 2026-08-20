#!/usr/bin/env python3
"""Validate latency-sweep inputs before treating results as final.

This script checks the input-side rules that are easy to violate accidentally:

* final runs use same-base AXI-MM TG address windows unless explicitly allowed;
* fixed-size rows use deterministic fixed-zero TG command gaps;
* TG seeds are fixed and nonzero;
* explicit address increments, when present, match the transaction size;
* final input plans do not carry manual NSU read-response pacing overrides.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]


def _repo_path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / "noc_testing" / p
        if not p.exists():
            p = REPO_ROOT / path
    return p


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _intlike(value: Any) -> int:
    text = _clean(value)
    if not text:
        raise ValueError("empty integer value")
    return int(text, 0)


def _tx_bytes(row: dict[str, str]) -> int | None:
    direct = _clean(row.get("transaction_bytes"))
    if direct:
        return _intlike(direct)

    beat_count = _clean(row.get("beat_count"))
    beat_bytes = _clean(row.get("beat_bytes"))
    if beat_count and beat_bytes:
        return (_intlike(beat_count) + 1) * _intlike(beat_bytes)
    return None


def _components(conn_json: Path) -> dict[str, dict[str, Any]]:
    with conn_json.open() as f:
        data = json.load(f)
    components = data.get("components", {})
    if not isinstance(components, dict):
        raise ValueError(f"{conn_json}: components must be an object")
    return components


def _aximm_tgs(components: dict[str, dict[str, Any]]) -> list[str]:
    out = []
    for comp_id, comp in components.items():
        if comp.get("node_type") != "AxiRandomTrafficGenerator":
            continue
        ports = comp.get("ports", {})
        for port in ports.values():
            if (
                isinstance(port, dict)
                and port.get("role") == "master"
                and port.get("protocol") == "aximm"
            ):
                out.append(comp_id)
                break
    return sorted(out)


def _tg_bases(components: dict[str, dict[str, Any]], tg_ids: list[str]) -> dict[str, int]:
    bases: dict[str, int] = {}
    for tg_id in tg_ids:
        ports = components[tg_id].get("ports", {})
        for port in ports.values():
            if (
                isinstance(port, dict)
                and port.get("role") == "master"
                and port.get("protocol") == "aximm"
            ):
                value = (
                    port.get("base_address")
                    or port.get("base_addr")
                    or port.get("write_base_address")
                    or port.get("write_base_addr")
                )
                if value is None:
                    raise ValueError(f"{tg_id}: missing AXI-MM master base address")
                bases[tg_id] = _intlike(value)
                break
    return bases


def _validate_row(
    row: dict[str, str],
    row_num: int,
    allow_staggered_bases: bool,
    allow_manual_nsu_pacing: bool,
) -> list[str]:
    errors: list[str] = []
    row_name = _clean(row.get("name")) or f"row{row_num}"

    conn_ref = _clean(row.get("connections_json"))
    if not conn_ref:
        return [f"{row_name}: missing connections_json"]

    conn_path = _repo_path(conn_ref)
    if not conn_path.exists():
        return [f"{row_name}: connections_json not found: {conn_path}"]

    try:
        components = _components(conn_path)
        tg_ids = _aximm_tgs(components)
        bases = _tg_bases(components, tg_ids)
    except Exception as exc:
        return [f"{row_name}: {exc}"]

    if not tg_ids:
        errors.append(f"{row_name}: no AXI-MM TG components found in {conn_ref}")

    if not allow_staggered_bases and len(set(bases.values())) > 1:
        pretty = ", ".join(f"{tg}=0x{base:x}" for tg, base in sorted(bases.items()))
        errors.append(
            f"{row_name}: final inputs require same-base TG addresses; got {pretty}"
        )

    tx_bytes = _tx_bytes(row)
    if tx_bytes is None:
        errors.append(f"{row_name}: cannot derive transaction size")

    for tg_id in tg_ids:
        prefix = f"param.{tg_id}."
        gap_dist = _clean(row.get(prefix + "gap_distribution")).upper()
        min_gap = _clean(row.get(prefix + "min_gap_cycles"))
        max_gap = _clean(row.get(prefix + "max_gap_cycles"))
        seed = _clean(row.get(prefix + "seed"))
        addr_inc = _clean(row.get(prefix + "address_increment"))

        if gap_dist != "FIXED":
            errors.append(f"{row_name}: {tg_id} gap_distribution must be FIXED")
        if min_gap != "0" or max_gap != "0":
            errors.append(
                f"{row_name}: {tg_id} gap range must be 0..0, got {min_gap}..{max_gap}"
            )
        if not seed or _intlike(seed) == 0:
            errors.append(f"{row_name}: {tg_id} seed must be fixed and nonzero")
        if addr_inc and tx_bytes is not None and _intlike(addr_inc) != tx_bytes:
            errors.append(
                f"{row_name}: {tg_id} address_increment={addr_inc} "
                f"must match transaction size {tx_bytes}"
            )

    if not allow_manual_nsu_pacing:
        manual_fields = (
            "nsu_read_response_half_rate",
            "nsu_read_response_gap_cycles",
            "nsu_read_response_per_flit_gap_cycles",
        )
        for field in manual_fields:
            value = _clean(row.get(field))
            if value and _intlike(value) != 0:
                errors.append(
                    f"{row_name}: final inputs should not set manual {field}={value}"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate final latency sweep input invariants."
    )
    parser.add_argument("plan", type=Path, help="CSV sweep plan to validate")
    parser.add_argument(
        "--allow-staggered-bases",
        action="store_true",
        help="Allow intentionally staggered/debug TG base addresses.",
    )
    parser.add_argument(
        "--allow-manual-nsu-pacing",
        action="store_true",
        help="Allow row-level NSU read-response pacing overrides.",
    )
    args = parser.parse_args()

    plan = args.plan if args.plan.is_absolute() else REPO_ROOT / args.plan
    with plan.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    errors: list[str] = []
    for i, row in enumerate(rows, start=1):
        errors.extend(
            _validate_row(
                row,
                i,
                allow_staggered_bases=args.allow_staggered_bases,
                allow_manual_nsu_pacing=args.allow_manual_nsu_pacing,
            )
        )

    if errors:
        print(f"FAIL: {plan}")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"PASS: {plan} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
