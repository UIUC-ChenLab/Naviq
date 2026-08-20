#!/usr/bin/env python3

from __future__ import annotations

import argparse
import collections
import csv
import re
from pathlib import Path


TIME_SCALE_NS = {
    "fs": 1e-6,
    "ps": 1e-3,
    "ns": 1.0,
    "us": 1_000.0,
    "ms": 1_000_000.0,
    "s": 1_000_000_000.0,
}


def time_ns(text: str) -> float:
    match = re.fullmatch(r"([0-9]+)([fpnum]?s)", text.strip())
    if not match:
        raise ValueError(f"unsupported time literal: {text!r}")
    return int(match.group(1)) * TIME_SCALE_NS[match.group(2)]


def summarize_vivado(args: argparse.Namespace) -> None:
    wanted_values = {int(v, 0) for v in args.values.split(",") if v}
    samples: dict[tuple[int, str, str], list[float]] = collections.defaultdict(list)

    with args.csv.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("signal") != "valid":
                continue
            if args.nps and row.get("nps_name") != args.nps:
                continue
            raw = (row.get("value") or "").strip()
            if not raw.isdigit():
                continue
            value = int(raw)
            if value not in wanted_values:
                continue
            t_ns = time_ns(row["time"])
            if not (args.start_ns <= t_ns <= args.end_ns):
                continue
            obj = (row.get("object") or "").split("/")[-1]
            samples[(value, row.get("nps_name", ""), obj)].append(t_ns)

    for key, times in sorted(samples.items(), key=lambda item: min(item[1])):
        times = sorted(set(times))
        groups: list[list[float]] = []
        current: list[float] = []
        for t_ns in times:
            if not current or t_ns - current[-1] <= args.group_gap_ns:
                current.append(t_ns)
            else:
                groups.append(current)
                current = [t_ns]
        if current:
            groups.append(current)

        for group in groups:
            if len(group) < args.min_samples:
                continue
            gaps = collections.Counter(
                round(group[i + 1] - group[i]) for i in range(len(group) - 1)
            )
            print(
                f"value={key[0]} nps={key[1]} signal={key[2]} "
                f"+{group[0] - args.origin_ns:.0f}..+{group[-1] - args.origin_ns:.0f} "
                f"samples={len(group)} gaps={dict(gaps)}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--kind", choices=["vivado"], default="vivado")
    parser.add_argument("--nps", default="")
    parser.add_argument("--values", default="4,64")
    parser.add_argument("--origin-ns", type=float, default=1000.0)
    parser.add_argument("--start-ns", type=float, default=1000.0)
    parser.add_argument("--end-ns", type=float, default=2000.0)
    parser.add_argument("--group-gap-ns", type=float, default=3.0)
    parser.add_argument("--min-samples", type=int, default=4)
    args = parser.parse_args()

    summarize_vivado(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
