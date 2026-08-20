#!/usr/bin/env python3
"""
Draw routed topology diagrams for topology experiments 1 and 2.

The diagrams are generated from experiment manifests and NCR WRITE routes.
Outputs are written under noc_testing/plots/experiments/evaluation/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


SCRIPT_DIR = Path(__file__).resolve().parent
NOC_TESTING_DIR = SCRIPT_DIR.parent
REPO_ROOT = NOC_TESTING_DIR.parent
DEFAULT_EXP1_MANIFEST = (
    NOC_TESTING_DIR
    / "experiments"
    / "evaluation"
    / "artifacts"
    / "exp1_evaluation_1"
    / "manifest.json"
)
DEFAULT_EXP2_MANIFEST = (
    NOC_TESTING_DIR
    / "experiments"
    / "evaluation"
    / "artifacts"
    / "exp2_evaluation"
    / "manifest.json"
)
DEFAULT_OUTPUT_DIR = NOC_TESTING_DIR / "plots" / "experiments" / "evaluation"

FLOW_COLORS = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#9467bd",
    "#ff7f0e",
    "#17becf",
]
SOURCE_COLOR = "#1f77b4"
DEST_COLOR = "#d62728"
RESOURCE_COLOR = "#d9d9d9"


@dataclass(frozen=True)
class CaseDiagram:
    experiment: str
    case_name: str
    connection_json: Path
    placement_json: Path
    ncr_path: Path
    pattern_family: str = ""
    overlap_class: str = ""


def resolve_path(path_text: str | Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    if str(path).startswith("noc_testing/"):
        return REPO_ROOT / path
    return NOC_TESTING_DIR / path


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def xy_from_instance(instance: str) -> tuple[float, float] | None:
    match = re.search(r"_X(-?\d+)Y(-?\d+)", instance)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def port_component(port: str) -> str:
    return port.split(".", 1)[0]


def short_endpoint_label(port: str) -> str:
    component = port_component(port)
    return component.replace("tg_", "TG").replace("bram_", "BRAM")


def collapse_adjacent(nodes: list[str]) -> list[str]:
    collapsed: list[str] = []
    for node in nodes:
        if not collapsed or collapsed[-1] != node:
            collapsed.append(node)
    return collapsed


def load_exp1_cases(manifest_path: Path) -> list[CaseDiagram]:
    manifest = load_json(manifest_path)
    repeat_outputs = manifest.get("repeat_outputs", [])
    if not repeat_outputs:
        raise ValueError(f"No repeat_outputs found in {manifest_path}")

    cases: list[CaseDiagram] = []
    for case in repeat_outputs[0].get("cases", []):
        cases.append(
            CaseDiagram(
                experiment="experiment1",
                case_name=str(case["case_name"]),
                connection_json=resolve_path(case["connection_json"]),
                placement_json=resolve_path(case["placement_json"]),
                ncr_path=resolve_path(case["route_source_path"]),
            )
        )
    return cases


def load_exp2_cases(manifest_path: Path) -> list[CaseDiagram]:
    manifest = load_json(manifest_path)
    validations = manifest.get("case_validation", {})
    cases: list[CaseDiagram] = []
    for case_name, case in validations.items():
        ncr_path = case.get("route_source_path") or case.get("ncr")
        cases.append(
            CaseDiagram(
                experiment="experiment2",
                case_name=str(case_name),
                connection_json=resolve_path(case["connection_json"]),
                placement_json=resolve_path(case["placement_json"]),
                ncr_path=resolve_path(ncr_path),
                pattern_family=str(case.get("pattern_family", "")),
                overlap_class=str(case.get("overlap_class", "")),
            )
        )

    order = {"shift": 0, "reverse": 1, "tornado": 2, "hotspot": 3}
    overlap_order = {"low_overlap": 0, "high_overlap": 1}
    return sorted(
        cases,
        key=lambda c: (
            order.get(c.pattern_family, 99),
            overlap_order.get(c.overlap_class, 99),
            c.case_name,
        ),
    )


def connection_flows(connection_json: Path) -> list[tuple[str, str]]:
    data = load_json(connection_json)
    return [
        (str(entry["from"]), str(entry["to"]))
        for entry in data.get("connections", [])
    ]


def placement_ports(placement_json: Path) -> dict[str, str]:
    return {
        str(port): str(instance)
        for port, instance in load_json(placement_json).get("placements", {}).items()
    }


def write_routes(ncr_path: Path) -> list[list[str]]:
    data = load_json(ncr_path)
    routes: list[list[str]] = []
    for path in data.get("Paths", []):
        write_net = next(
            (
                net
                for net in path.get("Nets", [])
                if str(net.get("CommType", "")).upper() == "WRITE"
            ),
            None,
        )
        if write_net is None:
            routes.append([])
            continue
        routes.append(collapse_adjacent(list(write_net.get("Connections", []))[0::2]))
    return routes


def case_points(case: CaseDiagram) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for instance in placement_ports(case.placement_json).values():
        xy = xy_from_instance(instance)
        if xy:
            points.append(xy)
    for route in write_routes(case.ncr_path):
        for node in route:
            xy = xy_from_instance(node)
            if xy:
                points.append(xy)
    return points


def bounds_for_cases(cases: list[CaseDiagram]) -> tuple[float, float, float, float]:
    points = [point for case in cases for point in case_points(case)]
    if not points:
        return -1, 1, -1, 1
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_pad = max(0.8, (max(xs) - min(xs)) * 0.04)
    y_pad = max(1.0, (max(ys) - min(ys)) * 0.04)
    return min(xs) - x_pad, max(xs) + x_pad, min(ys) - y_pad, max(ys) + y_pad


def title_for_case(case: CaseDiagram) -> str:
    if case.experiment == "experiment2":
        pattern = case.pattern_family.title()
        overlap = case.overlap_class.replace("_", " ").title()
        return f"{pattern}: {overlap}"
    return case.case_name.replace("exp1_", "").replace("_", " ").title()


def draw_case(
    ax: plt.Axes,
    case: CaseDiagram,
    bounds: tuple[float, float, float, float],
    show_endpoint_labels: bool,
    show_legend: bool,
) -> None:
    placements = placement_ports(case.placement_json)
    flows = connection_flows(case.connection_json)
    routes = write_routes(case.ncr_path)

    resource_points = set()
    for route in routes:
        for node in route:
            xy = xy_from_instance(node)
            if xy:
                resource_points.add(xy)
    if resource_points:
        xs, ys = zip(*sorted(resource_points))
        ax.scatter(
            xs,
            ys,
            s=8,
            color=RESOURCE_COLOR,
            edgecolor="none",
            zorder=1,
        )

    for flow_index, route in enumerate(routes):
        coords = [xy_from_instance(node) for node in route]
        coords = [coord for coord in coords if coord is not None]
        if len(coords) < 2:
            continue
        xs = [coord[0] for coord in coords]
        ys = [coord[1] for coord in coords]
        color = FLOW_COLORS[flow_index % len(FLOW_COLORS)]
        ax.plot(
            xs,
            ys,
            color=color,
            linewidth=1.9,
            alpha=0.78,
            solid_capstyle="round",
            zorder=2,
        )

    for flow_index, (src, dst) in enumerate(flows):
        color = FLOW_COLORS[flow_index % len(FLOW_COLORS)]
        for port, role, marker, dx, dy in [
            (src, "source", "s", -0.13, 0.20),
            (dst, "dest", "D", 0.13, -0.20),
        ]:
            instance = placements.get(port)
            if instance is None:
                continue
            xy = xy_from_instance(instance)
            if xy is None:
                continue
            x, y = xy
            face = SOURCE_COLOR if role == "source" else DEST_COLOR
            ax.scatter(
                [x + dx],
                [y + dy],
                marker=marker,
                s=74,
                facecolor=face,
                edgecolor="black",
                linewidth=0.8,
                zorder=4,
            )
            if show_endpoint_labels:
                va = "bottom" if role == "source" else "top"
                ax.text(
                    x + dx,
                    y + dy + (0.22 if role == "source" else -0.22),
                    short_endpoint_label(port),
                    fontsize=7,
                    ha="center",
                    va=va,
                    color="black",
                    zorder=5,
                )

        src_label = short_endpoint_label(src)
        dst_label = short_endpoint_label(dst)
        if show_legend:
            ax.plot([], [], color=color, linewidth=2, label=f"{src_label} -> {dst_label}")

    ax.set_title(title_for_case(case), fontsize=10)
    ax.set_xlim(bounds[0], bounds[1])
    ax.set_ylim(bounds[2], bounds[3])
    ax.set_xlabel("NoC X", fontsize=8)
    ax.set_ylabel("NoC Y", fontsize=8)
    ax.tick_params(axis="both", labelsize=7)
    ax.grid(True, alpha=0.22, linestyle="--", linewidth=0.6)
    ax.set_aspect("auto")

    if show_legend:
        flow_legend = ax.legend(
            title="WRITE flows",
            fontsize=6.8,
            title_fontsize=7,
            loc="upper right",
            frameon=True,
            framealpha=0.92,
        )
        ax.add_artist(flow_legend)

    endpoint_handles = [
        Line2D(
            [0],
            [0],
            marker="s",
            color="none",
            markerfacecolor=SOURCE_COLOR,
            markeredgecolor="black",
            markersize=7,
            label="NMU source",
        ),
        Line2D(
            [0],
            [0],
            marker="D",
            color="none",
            markerfacecolor=DEST_COLOR,
            markeredgecolor="black",
            markersize=7,
            label="NSU target",
        ),
    ]
    ax.legend(
        handles=endpoint_handles,
        fontsize=6.8,
        loc="lower right",
        frameon=True,
        framealpha=0.92,
    )


def save_figure(
    fig: plt.Figure,
    output_dir: Path,
    basename: str,
    formats: list[str],
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for fmt in formats:
        path = output_dir / f"{basename}.{fmt}"
        fig.savefig(path, bbox_inches="tight", dpi=300)
        paths.append(path)
        print(f"Saved plot to: {path}")
    plt.close(fig)
    return paths


def make_individual_diagrams(
    cases: list[CaseDiagram],
    output_dir: Path,
    formats: list[str],
    fixed_bounds: tuple[float, float, float, float] | None = None,
) -> None:
    individual_dir = output_dir / "individual"
    for case in cases:
        fig, ax = plt.subplots(figsize=(5.8, 4.6))
        bounds = fixed_bounds or bounds_for_cases([case])
        draw_case(
            ax,
            case,
            bounds,
            show_endpoint_labels=True,
            show_legend=True,
        )
        fig.suptitle(case.case_name, fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save_figure(fig, individual_dir, case.case_name, formats)


def make_exp1_montage(
    cases: list[CaseDiagram],
    output_dir: Path,
    formats: list[str],
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(10.8, 8.2))
    for ax, case in zip(axes.ravel(), cases):
        draw_case(
            ax,
            case,
            bounds_for_cases([case]),
            show_endpoint_labels=True,
            show_legend=False,
        )
    for ax in axes.ravel()[len(cases) :]:
        ax.axis("off")
    fig.suptitle("Experiment 1 Topologies", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    save_figure(fig, output_dir, "experiment1_topologies", formats)


def make_exp2_montage(
    cases: list[CaseDiagram],
    output_dir: Path,
    formats: list[str],
    bounds: tuple[float, float, float, float],
) -> None:
    case_by_key = {(case.pattern_family, case.overlap_class): case for case in cases}
    rows = ["shift", "reverse", "tornado", "hotspot"]
    cols = ["low_overlap", "high_overlap"]
    fig, axes = plt.subplots(
        len(rows),
        len(cols),
        figsize=(9.8, 13.0),
        sharex=True,
        sharey=True,
    )

    for row_index, family in enumerate(rows):
        for col_index, overlap in enumerate(cols):
            ax = axes[row_index][col_index]
            case = case_by_key.get((family, overlap))
            if case is None:
                ax.axis("off")
                continue
            draw_case(
                ax,
                case,
                bounds,
                show_endpoint_labels=True,
                show_legend=False,
            )

    fig.suptitle(
        "Experiment 2 Topologies (fixed endpoint coordinate frame)",
        fontsize=14,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    save_figure(fig, output_dir, "experiment2_topologies", formats)


def validate_cases(cases: list[CaseDiagram]) -> None:
    for case in cases:
        for path in [case.connection_json, case.placement_json, case.ncr_path]:
            if not path.exists():
                raise ValueError(f"Missing input for {case.case_name}: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draw topology diagrams for experiments 1 and 2."
    )
    parser.add_argument(
        "--exp1-manifest",
        type=Path,
        default=DEFAULT_EXP1_MANIFEST,
        help=f"Experiment 1 manifest (default: {DEFAULT_EXP1_MANIFEST})",
    )
    parser.add_argument(
        "--exp2-manifest",
        type=Path,
        default=DEFAULT_EXP2_MANIFEST,
        help=f"Experiment 2 manifest (default: {DEFAULT_EXP2_MANIFEST})",
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

    for manifest in [args.exp1_manifest, args.exp2_manifest]:
        if not manifest.exists():
            print(f"Error: manifest not found: {manifest}", file=sys.stderr)
            sys.exit(1)

    try:
        exp1_cases = load_exp1_cases(args.exp1_manifest)
        exp2_cases = load_exp2_cases(args.exp2_manifest)
        validate_cases(exp1_cases + exp2_cases)

        exp1_bounds = bounds_for_cases(exp1_cases)
        exp2_bounds = bounds_for_cases(exp2_cases)

        make_exp1_montage(exp1_cases, args.output_dir, args.formats)
        make_exp2_montage(exp2_cases, args.output_dir, args.formats, exp2_bounds)

        if not args.skip_individual:
            make_individual_diagrams(
                exp1_cases,
                args.output_dir,
                args.formats,
            )
            make_individual_diagrams(
                exp2_cases,
                args.output_dir,
                args.formats,
                fixed_bounds=exp2_bounds,
            )
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    print()
    print(
        f"Rendered {len(exp1_cases)} Experiment 1 cases and "
        f"{len(exp2_cases)} Experiment 2 cases."
    )
    print(f"Experiment 2 diagrams share bounds: {exp2_bounds}")


if __name__ == "__main__":
    main()
