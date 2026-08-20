#!/usr/bin/env python3
"""
Draw schematic routed-topology maps for Experiment 3 route strategies.

Experiment 3 compares routing strategies for a fixed workload. This script
reuses the schematic route drawing used for Experiment 2, but lays cases out as
workload rows and route-strategy columns.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

import plot_topology_experiment_diagrams as topo
import plot_topology_schematic_routes as schematic


DEFAULT_OUTPUT_DIR = (
    topo.NOC_TESTING_DIR
    / "plots"
    / "experiments"
    / "evaluation"
    / "experiment3_schematic_routes"
)
DEFAULT_MANIFEST = (
    topo.NOC_TESTING_DIR
    / "experiments"
    / "evaluation"
    / "artifacts"
    / "exp3_tornado_all_routers"
    / "manifest.json"
)

STRATEGY_ORDER = [
    "exp3_shortest",
    "exp3_bad_path",
    "exp3_high_overlap",
    "exp3_path_diverse",
]
STRATEGY_LABELS = {
    "exp3_shortest": "Shortest",
    "exp3_bad_path": "Bad Path",
    "exp3_high_overlap": "High Overlap",
    "exp3_path_diverse": "Path Diverse",
}
WORKLOAD_LABELS = {
    "exp1_4to1_far": "Exp1 4-to-1 Far",
    "exp2_reverse_high_overlap": "Exp2 Reverse",
    "exp2_tornado": "Exp2 Tornado",
}
ASSET_WORKLOADS = {
    "exp1_4to1_far": {
        "connection_json": "noc_testing/topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_aximm.conn.json",
        "placement_json": "noc_testing/topology_jsons/multi_endpoint/4nmu_to_1nsu_incast_spread.place.json",
    },
    "exp2_reverse_high_overlap": {
        "connection_json": "noc_testing/topology_jsons/multi_endpoint/exp2_4nmu_to_4nsu_reverse_aximm.conn.json",
        "placement_json": "noc_testing/topology_jsons/multi_endpoint/exp2_reverse.place.json",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def case_from_validation(name: str, validation: dict[str, Any]) -> topo.CaseDiagram:
    return topo.CaseDiagram(
        experiment="experiment3",
        case_name=STRATEGY_LABELS.get(name, name),
        connection_json=topo.resolve_path(validation["connection_json"]),
        placement_json=topo.resolve_path(validation["placement_json"]),
        ncr_path=topo.resolve_path(
            validation.get("route_source_path") or validation["ncr"]
        ),
        pattern_family=str(validation.get("workload_case", "")),
        overlap_class=str(validation.get("strategy_class", "")),
    )


def cases_from_manifest(manifest_path: Path) -> dict[str, dict[str, topo.CaseDiagram]]:
    if not manifest_path.exists():
        return {}

    manifest = load_json(manifest_path)
    grouped: dict[str, dict[str, topo.CaseDiagram]] = defaultdict(dict)
    for case_name, validation in manifest.get("case_validation", {}).items():
        workload = str(validation.get("workload_case", "experiment3"))
        grouped[workload][case_name] = case_from_validation(case_name, validation)
    return grouped


def cases_from_assets() -> dict[str, dict[str, topo.CaseDiagram]]:
    grouped: dict[str, dict[str, topo.CaseDiagram]] = defaultdict(dict)
    asset_root = (
        topo.NOC_TESTING_DIR / "experiments" / "evaluation" / "assets" / "experiment3"
    )

    for workload, paths in ASSET_WORKLOADS.items():
        workload_dir = asset_root / workload
        if not workload_dir.exists():
            continue

        for strategy in STRATEGY_ORDER:
            ncr_path = workload_dir / strategy / "noc_subsystem.ncr"
            if not ncr_path.exists():
                continue
            grouped[workload][strategy] = topo.CaseDiagram(
                experiment="experiment3",
                case_name=STRATEGY_LABELS.get(strategy, strategy),
                connection_json=topo.resolve_path(paths["connection_json"]),
                placement_json=topo.resolve_path(paths["placement_json"]),
                ncr_path=ncr_path,
                pattern_family=workload,
                overlap_class=strategy.replace("exp3_", ""),
            )

    return grouped


def merge_grouped_cases(
    *groups: dict[str, dict[str, topo.CaseDiagram]],
) -> dict[str, dict[str, topo.CaseDiagram]]:
    merged: dict[str, dict[str, topo.CaseDiagram]] = defaultdict(dict)
    for group in groups:
        for workload, cases in group.items():
            merged[workload].update(cases)
    return dict(merged)


def workload_sort_key(workload: str) -> tuple[int, str]:
    order = {
        "exp1_4to1_far": 0,
        "exp2_reverse_high_overlap": 1,
        "exp2_tornado": 2,
    }
    return order.get(workload, 99), workload


def draw_case(
    ax: plt.Axes,
    case: topo.CaseDiagram,
    *,
    show_legend: bool,
    tension_profile: str,
) -> None:
    schematic.draw_schematic_case(
        ax,
        case,
        show_legend=show_legend,
        show_flow_labels=False,
        layout_style="relaxed_links",
        apply_exp2_spacing=True,
        tension_profile=tension_profile,
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


def make_combined_montage(
    grouped_cases: dict[str, dict[str, topo.CaseDiagram]],
    output_dir: Path,
    formats: list[str],
    tension_profile: str,
) -> None:
    workloads = sorted(grouped_cases, key=workload_sort_key)
    fig, axes = plt.subplots(
        len(workloads),
        len(STRATEGY_ORDER),
        figsize=(16.0, 4.0 * max(1, len(workloads))),
        squeeze=False,
    )

    for row_index, workload in enumerate(workloads):
        cases = grouped_cases[workload]
        for col_index, strategy in enumerate(STRATEGY_ORDER):
            ax = axes[row_index][col_index]
            case = cases.get(strategy)
            if case is None:
                ax.axis("off")
                continue
            draw_case(
                ax,
                case,
                show_legend=(row_index == 0 and col_index == len(STRATEGY_ORDER) - 1),
                tension_profile=tension_profile,
            )
            if col_index == 0:
                ax.text(
                    -0.10,
                    0.5,
                    WORKLOAD_LABELS.get(workload, workload),
                    transform=ax.transAxes,
                    rotation=90,
                    ha="center",
                    va="center",
                    fontsize=11,
                    fontweight="bold",
                )

    fig.suptitle(
        f"Experiment 3 Schematic WRITE Routes ({tension_profile})",
        fontsize=15,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    save_figure(fig, output_dir, "experiment3_schematic_routes", formats)


def make_workload_montages(
    grouped_cases: dict[str, dict[str, topo.CaseDiagram]],
    output_dir: Path,
    formats: list[str],
    tension_profile: str,
) -> None:
    individual_dir = output_dir / "workloads"
    for workload in sorted(grouped_cases, key=workload_sort_key):
        cases = grouped_cases[workload]
        strategies = [strategy for strategy in STRATEGY_ORDER if strategy in cases]
        if not strategies:
            continue

        fig, axes = plt.subplots(
            1,
            len(strategies),
            figsize=(4.6 * len(strategies), 4.3),
            squeeze=False,
        )
        for col_index, strategy in enumerate(strategies):
            draw_case(
                axes[0][col_index],
                cases[strategy],
                show_legend=(col_index == len(strategies) - 1),
                tension_profile=tension_profile,
            )

        fig.suptitle(
            f"{WORKLOAD_LABELS.get(workload, workload)} WRITE Routes",
            fontsize=13,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save_figure(fig, individual_dir, f"{workload}_schematic_routes", formats)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draw schematic route maps for Experiment 3 route strategies."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Experiment 3 manifest (default: {DEFAULT_MANIFEST})",
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
        "--tension-profile",
        choices=list(schematic.TENSION_PROFILES),
        default="extra_taut",
        help="Schematic tautness profile (default: extra_taut).",
    )
    parser.add_argument(
        "--no-assets",
        action="store_true",
        help="Only use the manifest workload; skip checked-in Experiment 3 assets.",
    )
    args = parser.parse_args()

    grouped_cases = cases_from_manifest(args.manifest)
    if not args.no_assets:
        grouped_cases = merge_grouped_cases(cases_from_assets(), grouped_cases)

    if not grouped_cases:
        raise SystemExit("No Experiment 3 route cases found.")

    topo.validate_cases(
        [case for cases in grouped_cases.values() for case in cases.values()]
    )
    make_combined_montage(
        grouped_cases,
        args.output_dir,
        args.formats,
        args.tension_profile,
    )
    make_workload_montages(
        grouped_cases,
        args.output_dir,
        args.formats,
        args.tension_profile,
    )

    total_cases = sum(len(cases) for cases in grouped_cases.values())
    print()
    print(
        f"Rendered Experiment 3 schematic routes for "
        f"{total_cases} cases across {len(grouped_cases)} workloads."
    )


if __name__ == "__main__":
    main()
