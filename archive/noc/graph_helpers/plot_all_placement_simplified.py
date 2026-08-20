#!/usr/bin/env python3
"""
Plot placement sweep timing data from all_placement_simplified.csv.

Default input:
  noc_testing/results/all_placement_simplified.csv

Default output:
  src/noc/out/graphs/all_placement_simplified_plots/
  (summary CSV: src/noc/out/csv/all_placement_simplified_summary.csv)
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


NAME_RE = re.compile(
    r"^(?P<config>[^_]+)_(?P<hops>\d+)hop_(?P<packets>\d+)pkt_(?P<mode>.+)$"
)


@dataclass(frozen=True)
class PlacementRow:
    name: str
    config: str
    mode: str
    hops: int
    packets: int
    sim_time_s: float
    num_sources: int
    num_dests: int
    total_packets: int

    @property
    def packets_per_s(self) -> float:
        return self.total_packets / self.sim_time_s if self.sim_time_s > 0 else 0.0

    @property
    def seconds_per_packet(self) -> float:
        return self.sim_time_s / self.total_packets if self.total_packets > 0 else math.nan


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    root = repo_root()
    default_input = root / "noc_testing/results/all_placement_simplified.csv"
    default_output = root / "src" / "noc" / "out" / "graphs" / "all_placement_simplified_plots"

    parser = argparse.ArgumentParser(
        description="Generate clean plots for all_placement_simplified.csv."
    )
    parser.add_argument("--input", type=Path, default=default_input)
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument(
        "--show-points",
        action="store_true",
        help="Annotate each plotted point with its value.",
    )
    return parser.parse_args()


def read_rows(path: Path) -> list[PlacementRow]:
    rows: list[PlacementRow] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "name",
            "config",
            "sim_time_s",
            "num_write_trans_cfg",
            "num_sources",
            "num_dests",
            "total_packets",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing required columns: {sorted(missing)}")

        for raw in reader:
            match = NAME_RE.match(raw["name"])
            if not match:
                raise ValueError(
                    f"Could not parse name {raw['name']!r}; expected "
                    "<config>_<hops>hop_<packets>pkt_<mode>"
                )

            rows.append(
                PlacementRow(
                    name=raw["name"],
                    config=raw["config"],
                    mode=match.group("mode"),
                    hops=int(match.group("hops")),
                    packets=int(raw["num_write_trans_cfg"]),
                    sim_time_s=float(raw["sim_time_s"]),
                    num_sources=int(raw["num_sources"]),
                    num_dests=int(raw["num_dests"]),
                    total_packets=int(raw["total_packets"]),
                )
            )
    return rows


def collapse_config(rows: list[PlacementRow]) -> list[PlacementRow]:
    """Ignore the config column and average duplicate mode/hop/packet rows."""
    buckets = grouped(rows, "mode", "hops", "packets")
    collapsed: list[PlacementRow] = []
    for (mode, hops, packets), bucket in buckets.items():
        sim_time_s = sum(row.sim_time_s for row in bucket) / len(bucket)
        total_packets = round(sum(row.total_packets for row in bucket) / len(bucket))
        num_sources = round(sum(row.num_sources for row in bucket) / len(bucket))
        num_dests = round(sum(row.num_dests for row in bucket) / len(bucket))
        collapsed.append(
            PlacementRow(
                name=f"{hops}hop_{packets}pkt_{mode}",
                config="ignored",
                mode=mode,
                hops=hops,
                packets=packets,
                sim_time_s=sim_time_s,
                num_sources=num_sources,
                num_dests=num_dests,
                total_packets=total_packets,
            )
        )
    return sorted(collapsed, key=lambda row: (row.mode, row.hops, row.packets))


def set_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#9aa0a6",
            "axes.grid": True,
            "grid.color": "#e6e8eb",
            "grid.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.size": 10,
            "axes.titleweight": "semibold",
            "axes.labelcolor": "#202124",
            "xtick.color": "#3c4043",
            "ytick.color": "#3c4043",
            "legend.frameon": False,
        }
    )


def sorted_unique(rows: list[PlacementRow], attr: str):
    return sorted({getattr(row, attr) for row in rows})


def grouped(rows: list[PlacementRow], *attrs: str):
    out = defaultdict(list)
    for row in rows:
        out[tuple(getattr(row, attr) for attr in attrs)].append(row)
    return out


def save(fig, output_dir: Path, name: str, dpi: int, tight: bool = True) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / name
    if tight:
        fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def maybe_annotate(ax, xs, ys, fmt: str, enabled: bool) -> None:
    if not enabled:
        return
    for x, y in zip(xs, ys):
        ax.annotate(
            fmt.format(y),
            (x, y),
            textcoords="offset points",
            xytext=(0, 5),
            ha="center",
            fontsize=7,
            color="#5f6368",
        )


def plot_runtime_vs_packets(
    rows: list[PlacementRow], output_dir: Path, dpi: int, annotate: bool
) -> Path:
    modes = sorted_unique(rows, "mode")
    by_mode = grouped(rows, "mode")

    # Stack vertically (1 column, N rows) to prevent extreme width
    fig, axes = plt.subplots(
        len(modes), 1,
        figsize=(6, 4 * len(modes)),
        sharex=True,
        sharey=False,
    )
    if len(modes) == 1:
        axes = [axes]

    hop_colors = {2: "#1a73e8", 8: "#188038", 16: "#f29900", 32: "#d93025"}
    for c, mode in enumerate(modes):
        ax = axes[c]
        subset = by_mode[(mode,)]
        for hop in sorted_unique(subset, "hops"):
            points = sorted(
                [row for row in subset if row.hops == hop],
                key=lambda row: row.packets,
            )
            xs = [row.packets for row in points]
            ys = [row.sim_time_s for row in points]
            ax.plot(
                xs,
                ys,
                marker="o",
                linewidth=2,
                markersize=4,
                color=hop_colors.get(hop),
                label=f"{hop} hop",
            )
            maybe_annotate(ax, xs, ys, "{:.0f}s", annotate)
        ax.set_title(mode.upper())
        ax.set_xscale("log", base=2)
        ax.set_xlabel("Write transactions")
        ax.set_ylabel("Simulation time (s)")
        ax.legend(loc="upper left", fontsize=8)

    fig.suptitle("Simulation Time vs Write Count", fontsize=14, fontweight="semibold")
    return save(fig, output_dir, "runtime_vs_packets_by_hop.png", dpi)


def plot_runtime_vs_hops(
    rows: list[PlacementRow], output_dir: Path, dpi: int, annotate: bool
) -> Path:
    modes = sorted_unique(rows, "mode")
    packets = sorted_unique(rows, "packets")
    by_mode = grouped(rows, "mode")

    fig, axes = plt.subplots(
        len(modes), 1,
        figsize=(6, 4 * len(modes)),
        sharex=True,
        sharey=False,
    )
    if len(modes) == 1:
        axes = [axes]

    packet_colors = {64: "#1a73e8", 256: "#188038", 1024: "#f29900", 2048: "#d93025"}
    for c, mode in enumerate(modes):
        ax = axes[c]
        subset = by_mode[(mode,)]
        for pkt in packets:
            points = sorted(
                [row for row in subset if row.packets == pkt],
                key=lambda row: row.hops,
            )
            xs = [row.hops for row in points]
            ys = [row.sim_time_s for row in points]
            ax.plot(
                xs,
                ys,
                marker="o",
                linewidth=2,
                markersize=4,
                color=packet_colors.get(pkt),
                label=f"{pkt} pkt",
            )
            maybe_annotate(ax, xs, ys, "{:.0f}s", annotate)
        ax.set_title(mode.upper())
        ax.set_xticks(sorted_unique(rows, "hops"))
        ax.set_xlabel("Hop count")
        ax.set_ylabel("Simulation time (s)")
        ax.legend(loc="upper left", fontsize=8)

    fig.suptitle("Simulation Time vs Hop Count", fontsize=14, fontweight="semibold")
    return save(fig, output_dir, "runtime_vs_hops_by_packet_count.png", dpi)


def plot_throughput_heatmaps(rows: list[PlacementRow], output_dir: Path, dpi: int) -> Path:
    modes = sorted_unique(rows, "mode")
    hops = sorted_unique(rows, "hops")
    packets = sorted_unique(rows, "packets")
    by_key = {(row.mode, row.hops, row.packets): row for row in rows}

    fig, axes = plt.subplots(
        len(modes), 1,
        figsize=(6, 4.5 * len(modes)),
        sharex=True,
        sharey=True,
    )
    if len(modes) == 1:
        axes = [axes]

    values = [row.packets_per_s for row in rows]
    vmin, vmax = min(values), max(values)

    for c, mode in enumerate(modes):
        ax = axes[c]
        matrix = [[by_key[(mode, hop, pkt)].packets_per_s for pkt in packets] for hop in hops]
        im = ax.imshow(matrix, cmap="viridis", vmin=vmin, vmax=vmax, aspect="auto")
        ax.set_title(mode.upper())
        ax.set_xticks(range(len(packets)), [str(p) for p in packets])
        ax.set_yticks(range(len(hops)), [str(h) for h in hops])
        ax.set_xlabel("Write transactions")
        ax.set_ylabel("Hops")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("Pkts/sec")
        for y, hop in enumerate(hops):
            for x, pkt in enumerate(packets):
                val = by_key[(mode, hop, pkt)].packets_per_s
                ax.text(x, y, f"{val:.1f}", ha="center", va="center",
                        color="white" if val > (vmin + vmax) / 2 else "black", fontsize=8)

    fig.suptitle("Throughput Heatmap", fontsize=14, fontweight="semibold")
    return save(fig, output_dir, "throughput_packets_per_second_heatmap.png", dpi)


def plot_mode_comparison(rows: list[PlacementRow], output_dir: Path, dpi: int) -> Path:
    hops = sorted_unique(rows, "hops")
    packets = sorted_unique(rows, "packets")
    modes = sorted_unique(rows, "mode")
    by_key = {(row.mode, row.hops, row.packets): row for row in rows}

    fig, axes = plt.subplots(
        len(packets), 1,
        figsize=(7, 3.5 * len(packets)),
        sharex=True,
        sharey=False,
    )
    if len(packets) == 1:
        axes = [axes]

    width = 0.2
    offsets = {mode: (idx - (len(modes) - 1) / 2.0) * width for idx, mode in enumerate(modes)}
    colors = {"rtl": "#1a73e8", "tlm": "#188038", "gem5": "#d93025"}

    for c, pkt in enumerate(packets):
        ax = axes[c]
        xbase = list(range(len(hops)))
        for mode in modes:
            ys = [by_key.get((mode, h, pkt), PlacementRow("", "", "", 0, 0, 0, 0, 0, 0)).sim_time_s for h in hops]
            xs = [x + offsets[mode] for x in xbase]
            bars = ax.bar(xs, ys, width=width, label=mode.upper(), color=colors.get(mode, "#9aa0a6"))
            ax.bar_label(bars, fmt="%.0f", padding=3, fontsize=7)
        ax.set_title(f"{pkt} Transactions")
        ax.set_xticks(xbase, [str(h) for h in hops])
        ax.set_xlabel("Hops")
        ax.set_ylabel("Sim Time (s)")
        ax.legend(fontsize=8, loc="upper left")

    fig.suptitle("Mode Comparison", fontsize=14, fontweight="semibold")
    return save(fig, output_dir, "mode_comparison_runtime_bars.png", dpi)


def write_summary(rows: list[PlacementRow], csv_dir: Path) -> Path:
    csv_dir.mkdir(parents=True, exist_ok=True)
    path = csv_dir / "all_placement_simplified_summary.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "mode",
                "hops",
                "packets",
                "sim_time_s",
                "packets_per_s",
                "seconds_per_packet",
                "name",
            ]
        )
        for row in sorted(rows, key=lambda r: (r.mode, r.hops, r.packets)):
            writer.writerow(
                [
                    row.mode,
                    row.hops,
                    row.packets,
                    f"{row.sim_time_s:.6g}",
                    f"{row.packets_per_s:.6g}",
                    f"{row.seconds_per_packet:.6g}",
                    row.name,
                ]
            )
    return path


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input)
    if not rows:
        raise SystemExit(f"No rows found in {args.input}")
    rows = collapse_config(rows)

    set_style()
    csv_dir = repo_root() / "src" / "noc" / "out" / "csv"
    outputs = [
        write_summary(rows, csv_dir),
        plot_runtime_vs_packets(rows, args.output_dir, args.dpi, args.show_points),
        plot_runtime_vs_hops(rows, args.output_dir, args.dpi, args.show_points),
        plot_throughput_heatmaps(rows, args.output_dir, args.dpi),
        plot_mode_comparison(rows, args.output_dir, args.dpi),
    ]

    print("Generated:")
    for path in outputs:
        print(f"  {path}")


if __name__ == "__main__":
    main()
