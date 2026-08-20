#!/usr/bin/env python3
"""Generate Chapter 4 Figure 12: DDR stress-intensity sweep."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt


SCRIPT_DIR = Path(__file__).resolve().parent
NOC_TESTING_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = NOC_TESTING_DIR / "plots" / "chapter4"

STRESS_LABELS = ["0x", "1x", "2x", "4x"]
OVERLAP_KIB = [0.0, 22.5, 44.0, 90.0]
DMA_READ_P99_CYCLES = [199, 230, 263, 359]
PACKET_THROUGHPUT_GBPS = [2.704, 2.653, 2.474, 2.172]

LATENCY_COLOR = "#1f77b4"
THROUGHPUT_COLOR = "#c51b29"
GRID_COLOR = "#d9d9d9"


def stress_tick_labels() -> list[str]:
    labels = []
    for stress, kib in zip(STRESS_LABELS, OVERLAP_KIB):
        overlap = "0 KiB" if kib == 0 else f"{kib:.1f} KiB"
        labels.append(f"{stress}\n{overlap}")
    return labels


def make_plot() -> plt.Figure:
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )

    x_positions = list(range(len(STRESS_LABELS)))
    fig, ax_latency = plt.subplots(figsize=(6.4, 3.8))
    ax_throughput = ax_latency.twinx()

    latency_line = ax_latency.plot(
        x_positions,
        DMA_READ_P99_CYCLES,
        color=LATENCY_COLOR,
        marker="o",
        markersize=6.5,
        linewidth=2.1,
        label="DMA read P99 latency (cycles)",
        zorder=3,
    )[0]
    throughput_line = ax_throughput.plot(
        x_positions,
        PACKET_THROUGHPUT_GBPS,
        color=THROUGHPUT_COLOR,
        marker="s",
        markersize=6.0,
        linewidth=2.1,
        linestyle="--",
        label="Packet throughput (Gb/s)",
        zorder=3,
    )[0]

    ax_latency.set_xlabel("CPU DDR overlap stress level")
    ax_latency.set_ylabel("DMA read P99 latency (cycles)")
    ax_throughput.set_ylabel("AXI4-Stream packet throughput (Gb/s)")

    ax_latency.set_xticks(x_positions)
    ax_latency.set_xticklabels(stress_tick_labels())
    ax_latency.set_xlim(-0.25, len(x_positions) - 0.75)
    ax_latency.set_ylim(0, 400)
    ax_latency.set_yticks([0, 100, 200, 300, 400])
    ax_throughput.set_ylim(0, 3.0)
    ax_throughput.set_yticks([0.0, 1.0, 2.0, 3.0])

    ax_latency.tick_params(axis="y", colors="black")
    ax_throughput.tick_params(axis="y", colors="black")
    ax_latency.spines["left"].set_color("black")
    ax_throughput.spines["right"].set_color("black")

    ax_latency.grid(True, axis="y", color=GRID_COLOR, linewidth=0.7)
    ax_latency.grid(True, axis="x", color=GRID_COLOR, linewidth=0.55, alpha=0.65)
    ax_latency.set_axisbelow(True)
    ax_latency.spines["top"].set_visible(False)
    ax_throughput.spines["top"].set_visible(False)

    latency_label_offsets = [(0, 8), (0, 8), (0, 8), (0, 8)]
    for x, value, offset in zip(
        x_positions,
        DMA_READ_P99_CYCLES,
        latency_label_offsets,
    ):
        ax_latency.annotate(
            f"{value}",
            xy=(x, value),
            xytext=offset,
            textcoords="offset points",
            ha="center",
            va="bottom",
            color=LATENCY_COLOR,
            fontsize=8.5,
        )

    throughput_label_offsets = [(0, 8), (0, 8), (0, 8), (0, 8)]
    for x, value, offset in zip(
        x_positions,
        PACKET_THROUGHPUT_GBPS,
        throughput_label_offsets,
    ):
        ax_throughput.annotate(
            f"{value:.3f}",
            xy=(x, value),
            xytext=offset,
            textcoords="offset points",
            ha="center",
            va="bottom",
            color=THROUGHPUT_COLOR,
            fontsize=8.5,
        )

    fig.legend(
        handles=[latency_line, throughput_line],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.995),
        ncol=2,
        frameon=False,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    return fig


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig = make_plot()
    for extension in ("pdf", "svg"):
        output_path = OUTPUT_DIR / f"figure12_ddr_stress_sweep.{extension}"
        fig.savefig(output_path, bbox_inches="tight")
        print(f"Saved plot to: {output_path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
