#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_PLAN = Path("noc_testing/sweep_plans/validation/vivado_naviq_4to1_incast.csv")
LOAD_ORDER = ("low", "med", "uncapped")
MODE_PREFIXES = {
    "write": "write_only",
    "interleaved": "rw_interleaved",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _clean(value: object) -> str:
    return str(value if value is not None else "").strip()


def _float(row: dict[str, str], key: str) -> float | None:
    text = _clean(row.get(key))
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int(row: dict[str, str], key: str) -> int | None:
    value = _float(row, key)
    return None if value is None else int(value)


def _fmt(value: float | int | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _markdown_table(headers: list[str], rows: Iterable[list[object]]) -> str:
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        out.append("| " + " | ".join(_fmt(value) for value in row) + " |")
    return "\n".join(out)


def _load_from_name(name: str) -> str:
    for load in LOAD_ORDER:
        if name.endswith(f"_{load}"):
            return load
    return ""


def _mode_from_name(name: str) -> str:
    for prefix, mode in MODE_PREFIXES.items():
        if name.startswith(f"{prefix}_"):
            return mode
    return ""


def _index_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    indexed = {}
    for row in rows:
        key = (_clean(row.get("name")), _clean(row.get("src_id")))
        if key[0] and key[1]:
            indexed[key] = row
    return indexed


def _plan_rows_by_name(plan_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {_clean(row.get("name")): row for row in plan_rows if _clean(row.get("name"))}


def _status_is_pass(status: str) -> bool:
    return "PASS" in status.upper()


def _nonzero_count(row: dict[str, str], key: str) -> bool:
    value = _int(row, key)
    return value is not None and value > 0


def _series(
    pairs: dict[tuple[str, str], tuple[dict[str, str], dict[str, str]]],
    mode_prefix: str,
    src_id: str,
    vivado_key: str,
    gem5_key: str,
) -> tuple[list[float], list[float]]:
    vivado_values = []
    gem5_values = []
    for load in LOAD_ORDER:
        pair = pairs.get((f"{mode_prefix}_{load}", src_id))
        if not pair:
            continue
        vivado, gem5 = pair
        vivado_value = _float(vivado, vivado_key)
        gem5_value = _float(gem5, gem5_key)
        if vivado_value is not None:
            vivado_values.append(vivado_value)
        if gem5_value is not None:
            gem5_values.append(gem5_value)
    return vivado_values, gem5_values


def _mostly_non_decreasing(values: list[float], *, slack: float = 0.10) -> bool:
    if len(values) < 2:
        return False
    return all(values[i + 1] >= values[i] * (1.0 - slack) for i in range(len(values) - 1))


def _latency_rises(values: list[float]) -> bool:
    if len(values) < 2:
        return False
    return values[-1] >= values[0]


def _build_report(
    *,
    plan_path: Path,
    vivado_path: Path,
    gem5_path: Path,
    plan_rows: list[dict[str, str]],
    vivado_rows: list[dict[str, str]],
    gem5_rows: list[dict[str, str]],
) -> tuple[str, bool]:
    vivado_by_key = _index_rows(vivado_rows)
    gem5_by_key = _index_rows(gem5_rows)
    plan_by_name = _plan_rows_by_name(plan_rows)

    expected_names = list(plan_by_name)
    expected_src_ids = [str(i) for i in range(4)]
    pairs: dict[tuple[str, str], tuple[dict[str, str], dict[str, str]]] = {}
    hard_errors: list[str] = []
    warnings: list[str] = []

    for name in expected_names:
        for src_id in expected_src_ids:
            key = (name, src_id)
            vivado = vivado_by_key.get(key)
            gem5 = gem5_by_key.get(key)
            if vivado is None:
                hard_errors.append(f"missing Vivado row for {name} src_id={src_id}")
                continue
            if gem5 is None:
                hard_errors.append(f"missing Naviq row for {name} src_id={src_id}")
                continue
            pairs[key] = (vivado, gem5)

            if not _status_is_pass(_clean(vivado.get("test_status"))):
                hard_errors.append(
                    f"Vivado status not passing for {name} src_id={src_id}: "
                    f"{_clean(vivado.get('test_status'))}"
                )
            gem5_return = _int(gem5, "gem5_return_code")
            if gem5_return != 0:
                hard_errors.append(
                    f"Naviq return code not zero for {name} src_id={src_id}: {gem5_return}"
                )

            mode = _mode_from_name(name)
            if mode == "write_only":
                if not _nonzero_count(vivado, "write_req_total"):
                    hard_errors.append(f"missing Vivado write completions for {name} src_id={src_id}")
            elif mode == "rw_interleaved":
                if not _nonzero_count(vivado, "write_req_total"):
                    hard_errors.append(f"missing Vivado write completions for {name} src_id={src_id}")
                if not _nonzero_count(vivado, "read_req_total"):
                    hard_errors.append(f"missing Vivado read completions for {name} src_id={src_id}")

    for mode_prefix, mode in MODE_PREFIXES.items():
        for src_id in expected_src_ids:
            viv_bw, gem_bw = _series(
                pairs,
                mode_prefix,
                src_id,
                "achieved_write_bandwidth_MBps",
                "gem5_achieved_write_bw_MBps",
            )
            if not _mostly_non_decreasing(viv_bw):
                warnings.append(f"Vivado write bandwidth trend is weak for {mode} src_id={src_id}: {viv_bw}")
            if not _mostly_non_decreasing(gem_bw):
                warnings.append(f"Naviq write bandwidth trend is weak for {mode} src_id={src_id}: {gem_bw}")

            viv_lat, gem_lat = _series(
                pairs,
                mode_prefix,
                src_id,
                "write_latency_avg",
                "gem5_avg_write_lat_cycles",
            )
            if not _latency_rises(viv_lat):
                warnings.append(f"Vivado write average latency does not rise for {mode} src_id={src_id}: {viv_lat}")
            if not _latency_rises(gem_lat):
                warnings.append(f"Naviq write average latency does not rise for {mode} src_id={src_id}: {gem_lat}")

            if mode == "rw_interleaved":
                viv_read_bw, gem_read_bw = _series(
                    pairs,
                    mode_prefix,
                    src_id,
                    "achieved_read_bandwidth_MBps",
                    "gem5_achieved_read_bw_MBps",
                )
                if not _mostly_non_decreasing(viv_read_bw):
                    warnings.append(f"Vivado read bandwidth trend is weak for {mode} src_id={src_id}: {viv_read_bw}")
                if not _mostly_non_decreasing(gem_read_bw):
                    warnings.append(f"Naviq read bandwidth trend is weak for {mode} src_id={src_id}: {gem_read_bw}")

                viv_read_lat, gem_read_lat = _series(
                    pairs,
                    mode_prefix,
                    src_id,
                    "read_latency_avg",
                    "gem5_avg_read_lat_cycles",
                )
                if not _latency_rises(viv_read_lat):
                    warnings.append(f"Vivado read average latency does not rise for {mode} src_id={src_id}: {viv_read_lat}")
                if not _latency_rises(gem_read_lat):
                    warnings.append(f"Naviq read average latency does not rise for {mode} src_id={src_id}: {gem_read_lat}")

    def rows_for_mode(mode_prefix: str) -> list[list[object]]:
        rows = []
        for load in LOAD_ORDER:
            name = f"{mode_prefix}_{load}"
            for src_id in expected_src_ids:
                pair = pairs.get((name, src_id))
                if not pair:
                    continue
                vivado, gem5 = pair
                rows.append(
                    [
                        name,
                        src_id,
                        _float(vivado, "achieved_write_bandwidth_MBps"),
                        _float(gem5, "gem5_achieved_write_bw_MBps"),
                        _float(vivado, "write_latency_avg"),
                        _float(gem5, "gem5_avg_write_lat_cycles"),
                        _float(vivado, "write_latency_min"),
                        _float(gem5, "gem5_min_write_lat_cycles"),
                        _float(vivado, "write_latency_max"),
                        _float(gem5, "gem5_max_write_lat_cycles"),
                        _int(vivado, "write_req_total"),
                    ]
                )
        return rows

    def read_rows() -> list[list[object]]:
        rows = []
        for load in LOAD_ORDER:
            name = f"interleaved_{load}"
            for src_id in expected_src_ids:
                pair = pairs.get((name, src_id))
                if not pair:
                    continue
                vivado, gem5 = pair
                rows.append(
                    [
                        name,
                        src_id,
                        _float(vivado, "achieved_read_bandwidth_MBps"),
                        _float(gem5, "gem5_achieved_read_bw_MBps"),
                        _float(vivado, "read_latency_avg"),
                        _float(gem5, "gem5_avg_read_lat_cycles"),
                        _float(vivado, "read_latency_min"),
                        _float(gem5, "gem5_min_read_lat_cycles"),
                        _float(vivado, "read_latency_max"),
                        _float(gem5, "gem5_max_read_lat_cycles"),
                        _int(vivado, "read_req_total"),
                    ]
                )
        return rows

    lines = [
        "# Naviq vs Vivado 4-to-1 AXI-MM Incast Analysis",
        "",
        f"- Plan: `{plan_path}`",
        f"- Vivado CSV: `{vivado_path}`",
        f"- Naviq CSV: `{gem5_path}`",
        f"- Compared pairs: {len(pairs)}",
        f"- Hard errors: {len(hard_errors)}",
        f"- Trend warnings: {len(warnings)}",
        "",
        "## Write-Only Write Metrics",
        "",
        _markdown_table(
            [
                "name",
                "src",
                "viv_w_bw",
                "gem5_w_bw",
                "viv_w_avg",
                "gem5_w_avg",
                "viv_w_min",
                "gem5_w_min",
                "viv_w_max",
                "gem5_w_max",
                "viv_w_count",
            ],
            rows_for_mode("write"),
        ),
        "",
        "## Interleaved Write Metrics",
        "",
        _markdown_table(
            [
                "name",
                "src",
                "viv_w_bw",
                "gem5_w_bw",
                "viv_w_avg",
                "gem5_w_avg",
                "viv_w_min",
                "gem5_w_min",
                "viv_w_max",
                "gem5_w_max",
                "viv_w_count",
            ],
            rows_for_mode("interleaved"),
        ),
        "",
        "## Interleaved Read Metrics",
        "",
        _markdown_table(
            [
                "name",
                "src",
                "viv_r_bw",
                "gem5_r_bw",
                "viv_r_avg",
                "gem5_r_avg",
                "viv_r_min",
                "gem5_r_min",
                "viv_r_max",
                "gem5_r_max",
                "viv_r_count",
            ],
            read_rows(),
        ),
        "",
        "## Validation Notes",
        "",
    ]
    if hard_errors:
        lines.extend(["### Hard Errors", ""])
        lines.extend(f"- {error}" for error in hard_errors)
        lines.append("")
    if warnings:
        lines.extend(["### Trend Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    if not hard_errors and not warnings:
        lines.append("No hard errors or trend warnings were found.")
    elif not hard_errors:
        lines.append("No hard errors were found; review trend warnings before using results as evidence.")

    return "\n".join(lines) + "\n", not hard_errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a trend-based Vivado-vs-Naviq 4-to-1 incast comparison report."
    )
    parser.add_argument("--vivado", required=True, type=Path, help="Vivado result CSV")
    parser.add_argument("--gem5", required=True, type=Path, help="Naviq/gem5 result CSV")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN, help="Sweep plan CSV")
    parser.add_argument("--output", type=Path, help="Markdown report path")
    args = parser.parse_args()

    for path in (args.vivado, args.gem5, args.plan):
        if not path.exists():
            print(f"missing input: {path}", file=sys.stderr)
            return 2

    report, ok = _build_report(
        plan_path=args.plan,
        vivado_path=args.vivado,
        gem5_path=args.gem5,
        plan_rows=_read_csv(args.plan),
        vivado_rows=_read_csv(args.vivado),
        gem5_rows=_read_csv(args.gem5),
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
        print(f"wrote {args.output}")
    else:
        print(report)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
