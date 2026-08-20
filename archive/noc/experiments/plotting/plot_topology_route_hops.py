#!/usr/bin/env python3
"""
Draw route-hop diagrams for topology experiments 1 and 2.

Unlike physical XY route plots, these figures show the ordered hop sequence
for each WRITE flow. Internal route resources are colored by sharing count so
route overlap is visible directly.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import plot_topology_experiment_diagrams as topo


DEFAULT_OUTPUT_DIR = topo.NOC_TESTING_DIR / "plots" / "experiments" / "evaluation" / "route_hops"

FLOW_COLORS = topo.FLOW_COLORS
UNIQUE_NODE = "#cfcfcf"
SHARE_COLORS = {
    1: UNIQUE_NODE,
    2: "#fdae6b",
    3: "#fd8d3c",
    4: "#e6550d",
}
SOURCE_COLOR = topo.SOURCE_COLOR
DEST_COLOR = topo.DEST_COLOR


def short_resource_label(resource_id: str) -> str:
    text = resource_id.replace("NOC_", "")
    text = text.replace("NPS_VNOC_", "VNOC_")
    text = text.replace("NPS7575_", "NPS_")
    text = text.replace("NPP_RPTR_", "RPTR_")
    text = text.replace("NCRB_SSIT_", "SSIT_")
    text = text.replace("NIDB_", "NIDB_")
    text = text.replace("NMU512_", "NMU_")
    text = text.replace("NSU512_", "NSU_")
    return text


def route_bundle(case: topo.CaseDiagram) -> tuple[list[tuple[str, str]], list[list[str]]]:
    return topo.connection_flows(case.connection_json), topo.write_routes(case.ncr_path)


def internal_resource_counts(routes: list[list[str]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for route in routes:
        counts.update(set(route[1:-1]))
    return counts


def flow_label(flow: tuple[str, str]) -> str:
    src, dst = flow
    return f"{topo.short_endpoint_label(src)} -> {topo.short_endpoint_label(dst)}"


def case_metrics(routes: list[list[str]]) -> tuple[float, int, int, int]:
    hop_counts = [max(0, len(route) - 1) for route in routes]
    counts = internal_resource_counts(routes)
    shared_count = sum(1 for count in counts.values() if count >= 2)
    max_share = max(counts.values(), default=0)
    avg_hops = sum(hop_counts) / len(hop_counts) if hop_counts else 0.0
    max_hops = max(hop_counts, default=0)
    return avg_hops, max_hops, shared_count, max_share


def draw_route_hop_case(
    ax: plt.Axes,
    case: topo.CaseDiagram,
    max_hops: int | None,
    annotate_shared: bool,
    show_legend: bool,
) -> None:
    flows, routes = route_bundle(case)
    counts = internal_resource_counts(routes)
    avg_hops, case_max_hops, shared_count, max_share = case_metrics(routes)
    limit_hops = max_hops if max_hops is not None else case_max_hops

    y_positions = list(reversed(range(len(routes))))
    for flow_index, (route, y) in enumerate(zip(routes, y_positions)):
        color = FLOW_COLORS[flow_index % len(FLOW_COLORS)]
        x_values = list(range(len(route)))
        y_values = [y] * len(route)
        ax.plot(
            x_values,
            y_values,
            color=color,
            linewidth=1.8,
            alpha=0.55,
            zorder=1,
        )

        for hop_index, resource in enumerate(route):
            if hop_index == 0:
                ax.scatter(
                    hop_index,
                    y,
                    marker="s",
                    s=44,
                    facecolor=SOURCE_COLOR,
                    edgecolor="black",
                    linewidth=0.6,
                    zorder=4,
                )
                continue
            if hop_index == len(route) - 1:
                ax.scatter(
                    hop_index,
                    y,
                    marker="D",
                    s=44,
                    facecolor=DEST_COLOR,
                    edgecolor="black",
                    linewidth=0.6,
                    zorder=4,
                )
                continue

            share_count = counts.get(resource, 1)
            node_color = SHARE_COLORS.get(share_count, SHARE_COLORS[4])
            size = 18 + min(share_count, 4) * 14
            ax.scatter(
                hop_index,
                y,
                marker="o",
                s=size,
                facecolor=node_color,
                edgecolor="black" if share_count >= 2 else "none",
                linewidth=0.45,
                zorder=3 if share_count >= 2 else 2,
            )

    if annotate_shared:
        top_shared = [
            resource
            for resource, count in counts.most_common(10)
            if count >= max(2, max_share)
        ]
        for resource in top_shared:
            labeled = False
            for route, y in zip(routes, y_positions):
                if resource not in route[1:-1]:
                    continue
                hop_index = route.index(resource)
                if labeled:
                    ax.plot(
                        [hop_index, hop_index],
                        [y - 0.12, y + 0.12],
                        color="#555555",
                        linewidth=0.7,
                        alpha=0.55,
                        zorder=5,
                    )
                    continue
                ax.text(
                    hop_index,
                    y + 0.18,
                    short_resource_label(resource),
                    fontsize=6.4,
                    ha="center",
                    va="bottom",
                    rotation=25,
                    color="#333333",
                    zorder=5,
                )
                labeled = True

    labels = []
    for flow, route in zip(flows, routes):
        labels.append(f"{flow_label(flow)} ({max(0, len(route) - 1)} hops)")
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlim(-0.8, max(1, limit_hops) + 0.8)
    ax.set_ylim(-0.65, len(routes) - 0.35)
    ax.set_xlabel("Hop Index", fontsize=8)
    ax.tick_params(axis="x", labelsize=7)
    ax.grid(True, axis="x", alpha=0.25, linestyle="--", linewidth=0.55)
    ax.grid(False, axis="y")

    title = topo.title_for_case(case)
    ax.set_title(
        f"{title}\nAvg {avg_hops:.1f} hops, shared resources {shared_count}, max share {max_share}",
        fontsize=8.6,
    )

    if show_legend:
        handles = [
            Line2D(
                [0],
                [0],
                marker="s",
                color="none",
                markerfacecolor=SOURCE_COLOR,
                markeredgecolor="black",
                markersize=6,
                label="source",
            ),
            Line2D(
                [0],
                [0],
                marker="D",
                color="none",
                markerfacecolor=DEST_COLOR,
                markeredgecolor="black",
                markersize=6,
                label="target",
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=UNIQUE_NODE,
                markersize=6,
                label="unique resource",
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=SHARE_COLORS[2],
                markeredgecolor="black",
                markersize=7,
                label="shared by 2 flows",
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=SHARE_COLORS[4],
                markeredgecolor="black",
                markersize=8,
                label="shared by 4 flows",
            ),
        ]
        ax.legend(
            handles=handles,
            fontsize=7,
            loc="lower right",
            frameon=True,
            framealpha=0.95,
        )


def save_figure(
    fig: plt.Figure,
    output_dir: Path,
    basename: str,
    formats: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for fmt in formats:
        path = output_dir / f"{basename}.{fmt}"
        fig.savefig(path, bbox_inches="tight", dpi=300)
        print(f"Saved plot to: {path}")
    plt.close(fig)


def max_hops_for_cases(cases: list[topo.CaseDiagram]) -> int:
    max_hops = 0
    for case in cases:
        _, routes = route_bundle(case)
        max_hops = max(max_hops, *(max(0, len(route) - 1) for route in routes))
    return max_hops


def make_exp1_montage(
    cases: list[topo.CaseDiagram],
    output_dir: Path,
    formats: list[str],
) -> None:
    max_hops = max_hops_for_cases(cases)
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 7.6), sharex=True)
    for ax, case in zip(axes.ravel(), cases):
        draw_route_hop_case(
            ax,
            case,
            max_hops=max_hops,
            annotate_shared=False,
            show_legend=False,
        )
    fig.suptitle("Experiment 1 WRITE Route Hop Sequences", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    save_figure(fig, output_dir, "experiment1_route_hops", formats)


def make_exp2_montage(
    cases: list[topo.CaseDiagram],
    output_dir: Path,
    formats: list[str],
) -> None:
    max_hops = max_hops_for_cases(cases)
    case_by_key = {(case.pattern_family, case.overlap_class): case for case in cases}
    rows = ["shift", "reverse", "tornado", "hotspot"]
    cols = ["low_overlap", "high_overlap"]
    fig, axes = plt.subplots(
        len(rows),
        len(cols),
        figsize=(13.0, 10.8),
        sharex=True,
    )

    for row_index, family in enumerate(rows):
        for col_index, overlap in enumerate(cols):
            ax = axes[row_index][col_index]
            case = case_by_key.get((family, overlap))
            if case is None:
                ax.axis("off")
                continue
            draw_route_hop_case(
                ax,
                case,
                max_hops=max_hops,
                annotate_shared=False,
                show_legend=(row_index == 0 and col_index == 1),
            )

    fig.suptitle("Experiment 2 WRITE Route Hop Sequences", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    save_figure(fig, output_dir, "experiment2_route_hops", formats)


def make_individual_diagrams(
    cases: list[topo.CaseDiagram],
    output_dir: Path,
    formats: list[str],
) -> None:
    individual_dir = output_dir / "individual"
    for case in cases:
        _, routes = route_bundle(case)
        max_hops = max((max(0, len(route) - 1) for route in routes), default=1)
        fig, ax = plt.subplots(figsize=(10.0, 3.8))
        draw_route_hop_case(
            ax,
            case,
            max_hops=max_hops,
            annotate_shared=True,
            show_legend=True,
        )
        fig.suptitle(case.case_name, fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, 0.92))
        save_figure(fig, individual_dir, f"{case.case_name}_route_hops", formats)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draw route-hop diagrams for topology experiments."
    )
    parser.add_argument(
        "--exp1-manifest",
        type=Path,
        default=topo.DEFAULT_EXP1_MANIFEST,
        help=f"Experiment 1 manifest (default: {topo.DEFAULT_EXP1_MANIFEST})",
    )
    parser.add_argument(
        "--exp2-manifest",
        type=Path,
        default=topo.DEFAULT_EXP2_MANIFEST,
        help=f"Experiment 2 manifest (default: {topo.DEFAULT_EXP2_MANIFEST})",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["pdf", "svg", "png"],
        choices=["pdf", "svg", "png"],
        help="Output formats to write (default: pdf svg png)",
    )
    parser.add_argument(
        "--skip-individual",
        action="store_true",
        help="Only write experiment montage figures.",
    )
    args = parser.parse_args()

    exp1_cases = topo.load_exp1_cases(args.exp1_manifest)
    exp2_cases = topo.load_exp2_cases(args.exp2_manifest)
    topo.validate_cases(exp1_cases + exp2_cases)

    make_exp1_montage(exp1_cases, args.output_dir, args.formats)
    make_exp2_montage(exp2_cases, args.output_dir, args.formats)

    if not args.skip_individual:
        make_individual_diagrams(exp1_cases + exp2_cases, args.output_dir, args.formats)

    print()
    print(
        f"Rendered route-hop diagrams for {len(exp1_cases)} Experiment 1 cases "
        f"and {len(exp2_cases)} Experiment 2 cases."
    )


if __name__ == "__main__":
    main()
