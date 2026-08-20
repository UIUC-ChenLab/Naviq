#!/usr/bin/env python3
"""Generate Figure 10: latency-throughput design-space scatter plot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


SCRIPT_DIR = Path(__file__).resolve().parent
NOC_TESTING_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = NOC_TESTING_DIR / "plots" / "chapter3"


@dataclass(frozen=True)
class DesignPoint:
    config: str
    family: str
    worst_p99_cycles: int
    mean_bw_mbps: float
    label: str


POINTS = [
    DesignPoint("compact 4-to-4", "Exp1 distributed", 1346, 26080.25, "compact 4-4"),
    DesignPoint("far 4-to-4", "Exp1 distributed", 2167, 21358.56, "far 4-4"),
    DesignPoint("compact 4-to-1", "Exp1 incast", 6656, 6862.34, "compact 4-1"),
    DesignPoint("far 4-to-1", "Exp1 incast", 6421, 6764.84, "far 4-1"),
    DesignPoint("near single target", "Exp4 single target", 6254, 7062.32, "near single"),
    DesignPoint("far single target", "Exp4 single target", 7185, 6760.72, "far single"),
    DesignPoint(
        "spread single target",
        "Exp4 single target",
        6461,
        6975.65,
        "spread single",
    ),
    DesignPoint(
        "near distributed targets",
        "Exp4 distributed targets",
        1346,
        25952.14,
        "near dist.",
    ),
    DesignPoint(
        "far distributed targets",
        "Exp4 distributed targets",
        2128,
        21357.29,
        "far dist.",
    ),
    DesignPoint(
        "spread distributed targets",
        "Exp4 distributed targets",
        2127,
        23711.74,
        "spread dist.",
    ),
]

FAMILY_COLORS = {
    "Exp1 distributed": "#1f77b4",
    "Exp1 incast": "#d62728",
    "Exp4 single target": "#9467bd",
    "Exp4 distributed targets": "#2ca02c",
}

LABEL_OFFSETS = {
    "compact 4-4": (-8, 12, "right"),
    "near dist.": (8, -14, "left"),
    "far 4-4": (8, -15, "left"),
    "far dist.": (-8, 9, "right"),
    "spread dist.": (8, 8, "left"),
    "near single": (-10, 15, "right"),
    "far single": (7, -12, "left"),
    "spread single": (9, 8, "left"),
    "compact 4-1": (7, -18, "left"),
    "far 4-1": (-9, -15, "right"),
}


def is_non_dominated(candidate: DesignPoint, points: list[DesignPoint]) -> bool:
    for other in points:
        if other is candidate:
            continue
        no_worse_latency = other.worst_p99_cycles <= candidate.worst_p99_cycles
        no_worse_bandwidth = other.mean_bw_mbps >= candidate.mean_bw_mbps
        strictly_better = (
            other.worst_p99_cycles < candidate.worst_p99_cycles
            or other.mean_bw_mbps > candidate.mean_bw_mbps
        )
        if no_worse_latency and no_worse_bandwidth and strictly_better:
            return False
    return True


def make_plot() -> plt.Figure:
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 8.5,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )

    fig, ax = plt.subplots(figsize=(6.7, 4.45))

    for family, color in FAMILY_COLORS.items():
        family_points = [point for point in POINTS if point.family == family]
        ax.scatter(
            [point.worst_p99_cycles for point in family_points],
            [point.mean_bw_mbps for point in family_points],
            s=52,
            color=color,
            edgecolor="white",
            linewidth=0.8,
            label=family,
            zorder=3,
        )

    non_dominated = [point for point in POINTS if is_non_dominated(point, POINTS)]
    ax.scatter(
        [point.worst_p99_cycles for point in non_dominated],
        [point.mean_bw_mbps for point in non_dominated],
        s=112,
        facecolor="none",
        edgecolor="black",
        linewidth=1.2,
        zorder=4,
    )

    for point in POINTS:
        dx, dy, ha = LABEL_OFFSETS[point.label]
        ax.annotate(
            point.label,
            xy=(point.worst_p99_cycles, point.mean_bw_mbps),
            xytext=(dx, dy),
            textcoords="offset points",
            ha=ha,
            va="center",
            fontsize=8.2,
            bbox={
                "boxstyle": "round,pad=0.12",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.82,
            },
            zorder=5,
        )

    ax.annotate(
        "better",
        xy=(1750, 24800),
        xytext=(3450, 17700),
        arrowprops={
            "arrowstyle": "->",
            "color": "#555555",
            "linewidth": 1.0,
            "shrinkA": 3,
            "shrinkB": 3,
        },
        color="#555555",
        fontsize=9,
        ha="center",
    )

    ax.set_xlabel("Worst P99 latency (cycles)")
    ax.set_ylabel("Mean bandwidth (MB/s)")
    ax.set_xlim(900, 7600)
    ax.set_ylim(5200, 27600)
    ax.set_xticks([1000, 2000, 3000, 4000, 5000, 6000, 7000])
    ax.set_yticks([5000, 10000, 15000, 20000, 25000])
    ax.grid(True, color="#d9d9d9", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markerfacecolor=color,
            markeredgecolor="white",
            markersize=7,
            label=family,
        )
        for family, color in FAMILY_COLORS.items()
    ]
    handles.append(
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markerfacecolor="none",
            markeredgecolor="black",
            markersize=8,
            label="non-dominated",
        )
    )
    ax.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=3,
        frameon=False,
        columnspacing=1.0,
        handletextpad=0.45,
    )

    fig.tight_layout()
    return fig


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig = make_plot()
    for extension in ("pdf", "svg"):
        output_path = OUTPUT_DIR / f"figure10_latency_throughput_tradeoff.{extension}"
        fig.savefig(output_path, bbox_inches="tight")
        print(f"Saved plot to: {output_path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
