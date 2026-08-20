#!/usr/bin/env python3
"""
Draw schematic routed-topology maps for topology experiments 1 and 2.

This is a route map rather than a physical floorplan. Endpoint positions are
fixed by logical endpoint name, while internal NCR route resources are laid out
as shared schematic nodes. This makes crossing, merging, and path shape visible
without pretending that every NCR component naming scheme uses one grid.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

import plot_topology_experiment_diagrams as topo


DEFAULT_OUTPUT_DIR = (
    topo.NOC_TESTING_DIR / "plots" / "experiments" / "evaluation" / "schematic_routes"
)

SOURCE_COLOR = topo.SOURCE_COLOR
TARGET_COLOR = topo.DEST_COLOR
UNIQUE_COLOR = "#ffd84d"
UNIQUE_EDGE_COLOR = "#8a6f00"
SHARED_COLORS = {
    1: UNIQUE_COLOR,
    2: "#fdae6b",
    3: "#fd8d3c",
    4: "#d7301f",
}
FLOW_COLORS = topo.FLOW_COLORS
LAYOUT_STYLES = ["spring", "even_links", "relaxed_links"]
TENSION_PROFILES = {
    "loose": {
        "spring_k": 0.52,
        "spring_iterations": 90,
        "initial_weight": 0.58,
        "relaxed_weight": 0.42,
        "scale_4to4": (0.72, 0.70),
        "scale_incast": (0.78, 0.78),
        "min_distance": 0.060,
        "separation_iterations": 12,
        "lane_offset": 0.026,
        "endpoint_anchor_strength": 0.45,
    },
    "balanced": {
        "spring_k": 0.38,
        "spring_iterations": 80,
        "initial_weight": 0.44,
        "relaxed_weight": 0.56,
        "scale_4to4": (0.64, 0.62),
        "scale_incast": (0.72, 0.72),
        "min_distance": 0.048,
        "separation_iterations": 10,
        "lane_offset": 0.022,
        "endpoint_anchor_strength": 0.60,
    },
    "taut": {
        "spring_k": 0.27,
        "spring_iterations": 100,
        "initial_weight": 0.34,
        "relaxed_weight": 0.66,
        "scale_4to4": (0.58, 0.56),
        "scale_incast": (0.66, 0.66),
        "min_distance": 0.036,
        "separation_iterations": 8,
        "lane_offset": 0.018,
        "endpoint_anchor_strength": 0.78,
    },
    "extra_taut": {
        "spring_k": 0.20,
        "spring_iterations": 120,
        "initial_weight": 0.25,
        "relaxed_weight": 0.75,
        "scale_4to4": (0.53, 0.51),
        "scale_incast": (0.60, 0.60),
        "min_distance": 0.028,
        "separation_iterations": 6,
        "lane_offset": 0.014,
        "endpoint_anchor_strength": 0.92,
    },
}


def endpoint_label(port: str) -> str:
    return topo.short_endpoint_label(port)


def endpoint_key(port: str) -> tuple[str, int]:
    component = topo.port_component(port)
    match = re.search(r"_(\d+)$", component)
    index = int(match.group(1)) if match else 0
    if component.startswith("tg_"):
        return "source", index
    return "target", index


def is_incast(flows: list[tuple[str, str]]) -> bool:
    return len({dst for _, dst in flows}) == 1


def endpoint_position(
    port: str,
    flows: list[tuple[str, str]],
    swap_left_pairs: bool = False,
) -> tuple[float, float]:
    role, index = endpoint_key(port)
    if is_incast(flows):
        source_y = {
            0: 2.05,
            1: 0.68,
            2: -0.68,
            3: -2.05,
        }
        if role == "source":
            return -2.55, source_y.get(index, 2.05 - index * 1.35)
        return 2.55, 0.0

    corner_by_index = {
        0: (-2.65, -2.0),
        1: (-2.65, 2.0),
        2: (2.65, 2.0),
        3: (2.65, -2.0),
    }
    corner_x, corner_y = corner_by_index.get(index, (0.0, 0.0))

    # Keep same-index TG/BRAM pairs side-by-side at the same corner.
    outward = -1 if corner_x < 0 else 1
    source_outward = not (swap_left_pairs and index in {0, 1})
    x_offset = 0.18 * outward if role == "source" else -0.18 * outward
    if not source_outward:
        x_offset *= -1
    return corner_x + x_offset, corner_y


def endpoint_label_style(
    port: str,
    flows: list[tuple[str, str]],
    swap_left_pairs: bool = False,
) -> tuple[float, float, str, str]:
    role, index = endpoint_key(port)
    if is_incast(flows):
        if role == "source":
            return -0.20, 0.0, "right", "center"
        return 0.20, 0.0, "left", "center"

    corner_x = {
        0: -1,
        1: -1,
        2: 1,
        3: 1,
    }.get(index, 1)
    outward = corner_x
    source_outward = not (swap_left_pairs and index in {0, 1})
    endpoint_outward = role == "source" if source_outward else role != "source"
    if endpoint_outward:
        return 0.24 * outward, 0.0, "left" if outward > 0 else "right", "center"
    return -0.24 * outward, 0.0, "right" if outward > 0 else "left", "center"


def instance_to_port_map(case: topo.CaseDiagram) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for port, instance in topo.placement_ports(case.placement_json).items():
        mapping[instance] = port
    return mapping


def logical_routes(case: topo.CaseDiagram) -> tuple[list[tuple[str, str]], list[list[str]]]:
    flows = topo.connection_flows(case.connection_json)
    physical_routes = topo.write_routes(case.ncr_path)
    endpoint_by_instance = instance_to_port_map(case)
    routes: list[list[str]] = []

    for flow, route in zip(flows, physical_routes):
        if not route:
            routes.append([flow[0], flow[1]])
            continue
        logical = []
        for node in route:
            logical.append(endpoint_by_instance.get(node, node))
        logical[0] = flow[0]
        logical[-1] = flow[1]
        routes.append(topo.collapse_adjacent(logical))

    return flows, routes


def resource_xy_hint(resource: str) -> tuple[float, float]:
    match = re.search(r"_X(-?\d+)Y(-?\d+)", resource)
    if not match:
        digest = hashlib.sha1(resource.encode("utf-8")).digest()
        return (digest[0] / 255.0 - 0.5, digest[1] / 255.0 - 0.5)

    raw_x = float(match.group(1))
    raw_y = float(match.group(2))
    prefix = resource.split("_X", 1)[0]

    if "NPS_VNOC" in prefix:
        return (raw_x - 0.5, (raw_y - 18.5) / 14.0)
    if "NPS7575" in prefix:
        return ((raw_x - 2.5) / 3.0, (raw_y - 3.5) / 3.5)
    if "NPP_RPTR" in prefix:
        return (raw_x - 0.5, (raw_y - 7.0) / 6.0)
    if "NIDB" in prefix:
        return (raw_x - 0.5, (raw_y - 3.5) / 3.5)
    if "NCRB_SSIT" in prefix:
        return ((raw_x - 1.5) / 2.0, (raw_y - 3.0) / 3.0)
    if "NPS5555" in prefix:
        return ((raw_x - 9.0) / 4.0, raw_y - 0.5)
    return ((raw_x - 1.5) / 4.0, (raw_y - 9.0) / 9.0)


def route_share_counts(routes: list[list[str]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for route in routes:
        counts.update(set(route[1:-1]))
    return counts


def curved_route_point(
    src_pos: tuple[float, float],
    dst_pos: tuple[float, float],
    flow_index: int,
    flow_count: int,
    t: float,
    bend_scale: float,
) -> tuple[float, float]:
    dx = dst_pos[0] - src_pos[0]
    dy = dst_pos[1] - src_pos[1]
    length = max(math.hypot(dx, dy), 0.001)
    perp_x = -dy / length
    perp_y = dx / length
    centered_index = flow_index - (flow_count - 1) / 2
    bend = centered_index * bend_scale

    # Cubic Bezier with symmetric controls keeps hop spacing calmer than the
    # force-directed placement while still allowing routes to fan apart.
    c1 = (
        src_pos[0] + dx * 0.34 + perp_x * bend,
        src_pos[1] + dy * 0.34 + perp_y * bend,
    )
    c2 = (
        src_pos[0] + dx * 0.66 + perp_x * bend,
        src_pos[1] + dy * 0.66 + perp_y * bend,
    )
    mt = 1.0 - t
    x = (
        mt**3 * src_pos[0]
        + 3 * mt**2 * t * c1[0]
        + 3 * mt * t**2 * c2[0]
        + t**3 * dst_pos[0]
    )
    y = (
        mt**3 * src_pos[1]
        + 3 * mt**2 * t * c1[1]
        + 3 * mt * t**2 * c2[1]
        + t**3 * dst_pos[1]
    )
    return x, y


def layout_from_occurrences(
    flows: list[tuple[str, str]],
    routes: list[list[str]],
    endpoint_nodes: set[str],
    style: str,
    swap_left_pairs: bool = False,
) -> dict[str, tuple[float, float]]:
    occurrence_positions: defaultdict[str, list[tuple[float, float]]] = defaultdict(list)
    bend_scale = 0.16 if is_incast(flows) else 0.28

    for flow_index, (flow, route) in enumerate(zip(flows, routes)):
        src_pos = endpoint_position(flow[0], flows, swap_left_pairs)
        dst_pos = endpoint_position(flow[1], flows, swap_left_pairs)
        denom = max(1, len(route) - 1)

        for hop_index, node in enumerate(route):
            if node in endpoint_nodes:
                continue
            t = hop_index / denom
            if style == "spring":
                x = (1 - t) * src_pos[0] + t * dst_pos[0]
                y = (1 - t) * src_pos[1] + t * dst_pos[1]
                hint_x, hint_y = resource_xy_hint(node)
                flow_bend = (flow_index - (len(flows) - 1) / 2) * 0.12
                occurrence_positions[node].append(
                    (
                        x + 0.34 * hint_x,
                        y + 0.46 * hint_y + flow_bend,
                    )
                )
            else:
                x, y = curved_route_point(
                    src_pos,
                    dst_pos,
                    flow_index,
                    len(flows),
                    t,
                    bend_scale,
                )
                hint_x, hint_y = resource_xy_hint(node)
                occurrence_positions[node].append(
                    (
                        x + 0.03 * hint_x,
                        y + 0.03 * hint_y,
                    )
                )

    initial_pos: dict[str, tuple[float, float]] = {}
    for src, dst in flows:
        initial_pos[src] = endpoint_position(src, flows, swap_left_pairs)
        initial_pos[dst] = endpoint_position(dst, flows, swap_left_pairs)

    for route in routes:
        for node in route:
            if node in endpoint_nodes or node in initial_pos:
                continue
            positions = occurrence_positions.get(node)
            if positions:
                initial_pos[node] = (
                    sum(pos[0] for pos in positions) / len(positions),
                    sum(pos[1] for pos in positions) / len(positions),
                )
            else:
                initial_pos[node] = resource_xy_hint(node)

    return initial_pos


def bound_internal_nodes(
    layout: dict[str, tuple[float, float]],
    endpoint_nodes: set[str],
    flows: list[tuple[str, str]],
    internal_scale: tuple[float, float],
) -> dict[str, tuple[float, float]]:
    min_x, max_x, min_y, max_y = internal_bounds_for(flows)
    bounded = dict(layout)
    for node, pos in layout.items():
        if node in endpoint_nodes:
            continue
        x = float(pos[0]) * internal_scale[0]
        y = float(pos[1]) * internal_scale[1]
        bounded[node] = (
            min(max(x, min_x), max_x),
            min(max(y, min_y), max_y),
        )
    return bounded


def internal_bounds_for(flows: list[tuple[str, str]]) -> tuple[float, float, float, float]:
    return (
        (-2.34, 2.34, -1.72, 1.72)
        if not is_incast(flows)
        else (-2.28, 2.28, -2.16, 2.16)
    )


def clamp_to_internal_bounds(
    point: tuple[float, float],
    flows: list[tuple[str, str]],
) -> tuple[float, float]:
    min_x, max_x, min_y, max_y = internal_bounds_for(flows)
    return (
        min(max(float(point[0]), min_x), max_x),
        min(max(float(point[1]), min_y), max_y),
    )


def separate_close_internal_nodes(
    layout: dict[str, tuple[float, float]],
    endpoint_nodes: set[str],
    flows: list[tuple[str, str]],
    min_distance: float,
    iterations: int = 18,
    fixed_internal_nodes: set[str] | None = None,
) -> dict[str, tuple[float, float]]:
    fixed_internal_nodes = fixed_internal_nodes or set()
    nodes = [
        node
        for node in layout
        if node not in endpoint_nodes and node not in fixed_internal_nodes
    ]
    separated = {node: (float(pos[0]), float(pos[1])) for node, pos in layout.items()}
    min_x, max_x, min_y, max_y = internal_bounds_for(flows)

    for _ in range(iterations):
        moved = False
        deltas = {node: [0.0, 0.0] for node in nodes}
        for left_index, left in enumerate(nodes):
            left_x, left_y = separated[left]
            for right in nodes[left_index + 1 :]:
                right_x, right_y = separated[right]
                dx = right_x - left_x
                dy = right_y - left_y
                dist = math.hypot(dx, dy)
                if dist >= min_distance:
                    continue
                if dist < 0.001:
                    angle_seed = hashlib.sha1(f"{left}|{right}".encode("utf-8")).digest()
                    angle = angle_seed[0] / 255.0 * math.tau
                    dx = math.cos(angle) * 0.001
                    dy = math.sin(angle) * 0.001
                    dist = 0.001
                push = (min_distance - dist) * 0.5
                unit_x = dx / dist
                unit_y = dy / dist
                deltas[left][0] -= unit_x * push
                deltas[left][1] -= unit_y * push
                deltas[right][0] += unit_x * push
                deltas[right][1] += unit_y * push
                moved = True

        if not moved:
            break
        for node in nodes:
            x, y = separated[node]
            dx, dy = deltas[node]
            separated[node] = (
                min(max(x + dx, min_x), max_x),
                min(max(y + dy, min_y), max_y),
            )

    return separated


def endpoint_adjacent_nodes(routes: list[list[str]], endpoint_nodes: set[str]) -> set[str]:
    adjacent = set()
    for route in routes:
        if len(route) >= 3 and route[0] in endpoint_nodes:
            adjacent.add(route[1])
        if len(route) >= 3 and route[-1] in endpoint_nodes:
            adjacent.add(route[-2])
    return adjacent


def anchor_endpoint_adjacent_nodes(
    layout: dict[str, tuple[float, float]],
    routes: list[list[str]],
    endpoint_nodes: set[str],
    flows: list[tuple[str, str]],
    strength: float,
) -> dict[str, tuple[float, float]]:
    if strength <= 0.0:
        return layout

    desired_positions: defaultdict[str, list[tuple[float, float]]] = defaultdict(list)
    endpoint_gap = 0.42 if not is_incast(flows) else 0.36

    for route in routes:
        if len(route) < 3:
            continue

        for endpoint_index, adjacent_index in ((0, 1), (-1, -2)):
            endpoint = route[endpoint_index]
            adjacent = route[adjacent_index]
            if endpoint not in endpoint_nodes or adjacent in endpoint_nodes:
                continue
            endpoint_pos = layout[endpoint]
            current_pos = layout[adjacent]
            dx = current_pos[0] - endpoint_pos[0]
            dy = current_pos[1] - endpoint_pos[1]
            dist = math.hypot(dx, dy)
            if dist < 0.001:
                continue
            desired = (
                endpoint_pos[0] + dx / dist * endpoint_gap,
                endpoint_pos[1] + dy / dist * endpoint_gap,
            )
            desired_positions[adjacent].append(clamp_to_internal_bounds(desired, flows))

    anchored = dict(layout)
    for node, positions in desired_positions.items():
        if not positions:
            continue
        target = (
            sum(pos[0] for pos in positions) / len(positions),
            sum(pos[1] for pos in positions) / len(positions),
        )
        current = layout[node]
        anchored[node] = clamp_to_internal_bounds(
            (
                (1.0 - strength) * current[0] + strength * target[0],
                (1.0 - strength) * current[1] + strength * target[1],
            ),
            flows,
        )

    return anchored


def build_layout(
    flows: list[tuple[str, str]],
    routes: list[list[str]],
    layout_style: str,
    apply_exp2_spacing: bool,
    tension_profile: str,
) -> tuple[nx.Graph, dict[str, tuple[float, float]], set[str], Counter[str]]:
    graph = nx.Graph()
    endpoint_nodes = set()
    share_counts = route_share_counts(routes)

    for src, dst in flows:
        endpoint_nodes.add(src)
        endpoint_nodes.add(dst)
        graph.add_node(src)
        graph.add_node(dst)

    for route in routes:
        graph.add_nodes_from(route)
        graph.add_edges_from(zip(route, route[1:]))

    if layout_style not in LAYOUT_STYLES:
        raise ValueError(
            f"Unknown layout style {layout_style!r}; expected one of {LAYOUT_STYLES}"
        )
    if tension_profile not in TENSION_PROFILES:
        raise ValueError(
            f"Unknown tension profile {tension_profile!r}; "
            f"expected one of {list(TENSION_PROFILES)}"
        )
    tension = TENSION_PROFILES[tension_profile]

    initial_pos = layout_from_occurrences(
        flows,
        routes,
        endpoint_nodes,
        "spring" if layout_style == "spring" else "even_links",
        swap_left_pairs=apply_exp2_spacing,
    )

    if layout_style == "even_links":
        layout = bound_internal_nodes(
            initial_pos,
            endpoint_nodes,
            flows,
            (0.82, 0.80) if not is_incast(flows) else (0.86, 0.88),
        )
    else:
        layout = nx.spring_layout(
            graph,
            pos=initial_pos,
            fixed=list(endpoint_nodes),
            seed=17,
            iterations=(
                180
                if layout_style == "spring"
                else int(tension["spring_iterations"])
            ),
            k=0.30 if layout_style == "spring" else float(tension["spring_k"]),
            weight=None,
        )
        internal_scale = (
            (0.46, 0.44)
            if layout_style == "spring" and not is_incast(flows)
            else (0.62, 0.54)
            if layout_style == "spring"
            else tension["scale_4to4"]
            if not is_incast(flows)
            else tension["scale_incast"]
        )
        if layout_style == "relaxed_links":
            # Blend toward the uniform-hop initialization so the relaxation can
            # shorten awkward edges without reintroducing force-layout jitter.
            blended = {}
            initial_weight = float(tension["initial_weight"])
            relaxed_weight = float(tension["relaxed_weight"])
            for node in graph.nodes:
                if node in endpoint_nodes:
                    blended[node] = initial_pos[node]
                    continue
                relaxed = layout[node]
                initial = initial_pos[node]
                blended[node] = (
                    initial_weight * float(initial[0])
                    + relaxed_weight * float(relaxed[0]),
                    initial_weight * float(initial[1])
                    + relaxed_weight * float(relaxed[1]),
                )
            layout = blended
        layout = bound_internal_nodes(layout, endpoint_nodes, flows, internal_scale)

    if apply_exp2_spacing:
        layout = anchor_endpoint_adjacent_nodes(
            layout,
            routes,
            endpoint_nodes,
            flows,
            strength=float(tension["endpoint_anchor_strength"]),
        )
        fixed_internal_nodes = endpoint_adjacent_nodes(routes, endpoint_nodes)
        min_distance = (
            float(tension["min_distance"]) if layout_style != "spring" else 0.04
        )
        layout = separate_close_internal_nodes(
            layout,
            endpoint_nodes,
            flows,
            min_distance=min_distance,
            iterations=int(tension["separation_iterations"]),
            fixed_internal_nodes=fixed_internal_nodes,
        )

    return graph, layout, endpoint_nodes, share_counts


def hop_counts_text(routes: list[list[str]]) -> str:
    counts = [str(max(0, len(route) - 1)) for route in routes]
    return "hops " + "/".join(counts)


def shared_summary(share_counts: Counter[str]) -> str:
    shared = sum(1 for count in share_counts.values() if count >= 2)
    max_share = max(share_counts.values(), default=0)
    return f"shared {shared}, max {max_share}"


def lane_offset_route_coords(
    coords: list[tuple[float, float]],
    flow_index: int,
    flow_count: int,
    base_offset: float,
) -> list[tuple[float, float]]:
    if len(coords) <= 2 or flow_count <= 1:
        return coords

    centered_index = flow_index - (flow_count - 1) / 2
    lane_offset = centered_index * base_offset
    offset_coords = []
    denom = max(1, len(coords) - 1)

    for index, (x, y) in enumerate(coords):
        if index == 0 or index == len(coords) - 1:
            offset_coords.append((x, y))
            continue

        prev_x, prev_y = coords[index - 1]
        next_x, next_y = coords[index + 1]
        dx = next_x - prev_x
        dy = next_y - prev_y
        length = math.hypot(dx, dy)
        if length < 0.001:
            offset_coords.append((x, y))
            continue

        taper = math.sin(math.pi * index / denom)
        perp_x = -dy / length
        perp_y = dx / length
        offset_coords.append(
            (
                x + perp_x * lane_offset * taper,
                y + perp_y * lane_offset * taper,
            )
        )

    return offset_coords


def flows_share_endpoint(
    left: tuple[str, str],
    right: tuple[str, str],
) -> bool:
    return bool({left[0], left[1]} & {right[0], right[1]})


def separate_nonshared_route_lanes(
    route_coords: list[list[tuple[float, float]]],
    flows: list[tuple[str, str]],
    min_distance: float = 0.105,
    iterations: int = 14,
) -> list[list[tuple[float, float]]]:
    separated = [
        [(float(x), float(y)) for x, y in coords]
        for coords in route_coords
    ]

    for _ in range(iterations):
        moved = False
        deltas = [
            [[0.0, 0.0] for _ in coords]
            for coords in separated
        ]

        for left_index, left_flow in enumerate(flows):
            for right_index in range(left_index + 1, len(flows)):
                if flows_share_endpoint(left_flow, flows[right_index]):
                    continue

                left_coords = separated[left_index]
                right_coords = separated[right_index]
                for left_point in range(1, max(1, len(left_coords) - 1)):
                    lx, ly = left_coords[left_point]
                    for right_point in range(1, max(1, len(right_coords) - 1)):
                        rx, ry = right_coords[right_point]
                        dx = rx - lx
                        dy = ry - ly
                        dist = math.hypot(dx, dy)
                        if dist >= min_distance:
                            continue

                        if dist < 0.001:
                            digest = hashlib.sha1(
                                f"{left_index}:{right_index}:{left_point}:{right_point}".encode(
                                    "utf-8"
                                )
                            ).digest()
                            angle = digest[0] / 255.0 * math.tau
                            dx = math.cos(angle) * 0.001
                            dy = math.sin(angle) * 0.001
                            dist = 0.001

                        push = (min_distance - dist) * 0.18
                        unit_x = dx / dist
                        unit_y = dy / dist
                        deltas[left_index][left_point][0] -= unit_x * push
                        deltas[left_index][left_point][1] -= unit_y * push
                        deltas[right_index][right_point][0] += unit_x * push
                        deltas[right_index][right_point][1] += unit_y * push
                        moved = True

        if not moved:
            break

        for route_index, coords in enumerate(separated):
            for point_index in range(1, max(1, len(coords) - 1)):
                x, y = coords[point_index]
                dx, dy = deltas[route_index][point_index]
                separated[route_index][point_index] = (x + dx, y + dy)

    return separated


def draw_schematic_case(
    ax: plt.Axes,
    case: topo.CaseDiagram,
    show_legend: bool,
    show_flow_labels: bool,
    layout_style: str,
    apply_exp2_spacing: bool,
    tension_profile: str,
) -> None:
    flows, routes = logical_routes(case)
    _, pos, endpoint_nodes, share_counts = build_layout(
        flows,
        routes,
        layout_style,
        apply_exp2_spacing,
        tension_profile,
    )

    route_draw_coords = []
    for flow_index, route in enumerate(routes):
        coords = [pos[node] for node in route if node in pos]
        if len(coords) < 2:
            route_draw_coords.append([])
            continue
        if apply_exp2_spacing:
            coords = lane_offset_route_coords(
                coords,
                flow_index,
                len(routes),
                float(TENSION_PROFILES[tension_profile]["lane_offset"]),
            )
        route_draw_coords.append(coords)

    if apply_exp2_spacing and not is_incast(flows):
        route_draw_coords = separate_nonshared_route_lanes(route_draw_coords, flows)

    for flow_index, coords in enumerate(route_draw_coords):
        if len(coords) < 2:
            continue
        xs = [coord[0] for coord in coords]
        ys = [coord[1] for coord in coords]
        color = FLOW_COLORS[flow_index % len(FLOW_COLORS)]
        ax.plot(
            xs,
            ys,
            color=color,
            linewidth=2.2,
            alpha=0.70,
            solid_capstyle="round",
            zorder=1,
        )

    unique_xs = []
    unique_ys = []
    shared_by_count: defaultdict[int, list[tuple[float, float]]] = defaultdict(list)
    for node, count in share_counts.items():
        if node not in pos:
            continue
        if count <= 1:
            unique_xs.append(pos[node][0])
            unique_ys.append(pos[node][1])
        else:
            shared_by_count[min(count, 4)].append(pos[node])

    if unique_xs:
        ax.scatter(
            unique_xs,
            unique_ys,
            s=23,
            color=UNIQUE_COLOR,
            edgecolor=UNIQUE_EDGE_COLOR,
            linewidth=0.35,
            zorder=2,
        )

    for count, points in sorted(shared_by_count.items()):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        ax.scatter(
            xs,
            ys,
            s=36 + count * 12,
            color=SHARED_COLORS.get(count, SHARED_COLORS[4]),
            edgecolor="black",
            linewidth=0.45,
            zorder=3,
        )

    for node in endpoint_nodes:
        if node not in pos:
            continue
        role, _ = endpoint_key(node)
        marker = "s" if role == "source" else "D"
        color = SOURCE_COLOR if role == "source" else TARGET_COLOR
        ax.scatter(
            [pos[node][0]],
            [pos[node][1]],
            marker=marker,
            s=92,
            facecolor=color,
            edgecolor="black",
            linewidth=0.9,
            zorder=5,
        )
        dx, dy, ha, va = endpoint_label_style(
            node,
            flows,
            swap_left_pairs=apply_exp2_spacing,
        )
        ax.text(
            pos[node][0] + dx,
            pos[node][1] + dy,
            endpoint_label(node),
            fontsize=7.2,
            ha=ha,
            va=va,
            zorder=6,
        )

    if show_flow_labels:
        for flow_index, (flow, route) in enumerate(zip(flows, routes)):
            color = FLOW_COLORS[flow_index % len(FLOW_COLORS)]
            src = flow[0]
            if src not in pos:
                continue
            ax.text(
                pos[src][0] - 0.06,
                pos[src][1] - 0.16,
                f"{endpoint_label(flow[0])}->{endpoint_label(flow[1])}, "
                f"{max(0, len(route) - 1)}h",
                fontsize=6.4,
                color=color,
                ha="right",
                va="top",
            )

    title = topo.title_for_case(case)
    ax.set_title(title, fontsize=8.8)
    ax.set_axis_off()
    ax.set_aspect("equal", adjustable="box")
    if is_incast(flows):
        ax.set_xlim(-3.75, 3.75)
        ax.set_ylim(-2.45, 2.45)
    else:
        ax.set_xlim(-4.05, 4.05)
        ax.set_ylim(-2.45, 2.45)

    ax.add_patch(
        Rectangle(
            (0, 0),
            1,
            1,
            transform=ax.transAxes,
            fill=False,
            edgecolor="#c7c7c7",
            linewidth=0.75,
            zorder=20,
            clip_on=False,
        )
    )

    if show_legend:
        ax.legend(
            handles=legend_handles(),
            fontsize=7,
            loc="lower center",
            frameon=True,
            framealpha=0.95,
            ncol=2,
        )


def legend_handles() -> list[Line2D]:
    return [
        Line2D(
            [0],
            [0],
            marker="s",
            color="none",
            markerfacecolor=SOURCE_COLOR,
            markeredgecolor="black",
            markersize=9,
            label="source",
        ),
        Line2D(
            [0],
            [0],
            marker="D",
            color="none",
            markerfacecolor=TARGET_COLOR,
            markeredgecolor="black",
            markersize=9,
            label="target",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=UNIQUE_COLOR,
            markeredgecolor=UNIQUE_EDGE_COLOR,
            markersize=9,
            label="noc switch",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=SHARED_COLORS[2],
            markeredgecolor="black",
            markersize=9,
            label="2x shared noc switch",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=SHARED_COLORS[4],
            markeredgecolor="black",
            markersize=9,
            label="4x shared noc switch",
        ),
    ]


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


def make_exp1_montage(
    cases: list[topo.CaseDiagram],
    output_dir: Path,
    formats: list[str],
    layout_style: str,
    tension_profile: str,
    basename: str = "experiment1_schematic_routes",
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(10.8, 8.4))
    for ax, case in zip(axes.ravel(), cases):
        draw_schematic_case(
            ax,
            case,
            show_legend=False,
            show_flow_labels=False,
            layout_style=layout_style,
            apply_exp2_spacing=False,
            tension_profile=tension_profile,
        )
    for ax in axes.ravel()[len(cases) :]:
        ax.axis("off")
    fig.suptitle(f"Experiment 1 Schematic WRITE Routes ({layout_style})", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    save_figure(fig, output_dir, basename, formats)


def make_exp2_montage(
    cases: list[topo.CaseDiagram],
    output_dir: Path,
    formats: list[str],
    layout_style: str,
    tension_profile: str,
    basename: str = "experiment2_schematic_routes",
) -> None:
    case_by_key = {(case.pattern_family, case.overlap_class): case for case in cases}
    rows = ["shift", "reverse", "tornado", "hotspot"]
    cols = ["low_overlap", "high_overlap"]
    fig, axes = plt.subplots(len(rows), len(cols), figsize=(9.8, 13.0))

    for row_index, family in enumerate(rows):
        for col_index, overlap in enumerate(cols):
            ax = axes[row_index][col_index]
            case = case_by_key.get((family, overlap))
            if case is None:
                ax.axis("off")
                continue
            draw_schematic_case(
                ax,
                case,
                show_legend=False,
                show_flow_labels=False,
                layout_style=layout_style,
                apply_exp2_spacing=True,
                tension_profile=tension_profile,
            )

    fig.suptitle("Experiment 2 Routes", fontsize=14)
    fig.legend(
        handles=legend_handles(),
        loc="lower center",
        bbox_to_anchor=(0.5, 0.012),
        ncol=5,
        fontsize=9.5,
        frameon=True,
        framealpha=0.95,
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.97))
    save_figure(fig, output_dir, basename, formats)


def make_individual_diagrams(
    cases: list[topo.CaseDiagram],
    output_dir: Path,
    formats: list[str],
    exp1_layout_style: str,
    exp2_layout_style: str,
    tension_profile: str,
) -> None:
    individual_dir = output_dir / "individual" / exp2_layout_style
    for case in cases:
        layout_style = (
            exp2_layout_style if case.experiment == "experiment2" else exp1_layout_style
        )
        fig, ax = plt.subplots(figsize=(7.0, 5.0))
        draw_schematic_case(
            ax,
            case,
            show_legend=True,
            show_flow_labels=True,
            layout_style=layout_style,
            apply_exp2_spacing=(case.experiment == "experiment2"),
            tension_profile=tension_profile,
        )
        fig.suptitle(f"{case.case_name} ({layout_style})", fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save_figure(fig, individual_dir, f"{case.case_name}_schematic_routes", formats)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draw schematic routed-topology maps for experiments 1 and 2."
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
        "--layout-style",
        choices=LAYOUT_STYLES,
        default="relaxed_links",
        help="Internal route-resource placement style (default: relaxed_links).",
    )
    parser.add_argument(
        "--tension-profile",
        choices=list(TENSION_PROFILES),
        default="balanced",
        help="Relaxed-link tautness/evenness profile (default: balanced).",
    )
    parser.add_argument(
        "--layout-options",
        action="store_true",
        help="Write Experiment 2 montage candidates for all layout styles.",
    )
    parser.add_argument(
        "--tension-options",
        action="store_true",
        help="Write Experiment 2 relaxed-link candidates for all tension profiles.",
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

    if args.layout_options:
        option_dir = args.output_dir / "layout_options"
        for layout_style in LAYOUT_STYLES:
            make_exp2_montage(
                exp2_cases,
                option_dir,
                args.formats,
                layout_style=layout_style,
                tension_profile=args.tension_profile,
                basename=f"experiment2_schematic_routes_{layout_style}",
            )
        print()
        print(
            f"Rendered {len(LAYOUT_STYLES)} Experiment 2 layout candidates "
            f"to {option_dir}."
        )
        return

    if args.tension_options:
        option_dir = args.output_dir / "tension_options"
        for tension_profile in TENSION_PROFILES:
            make_exp2_montage(
                exp2_cases,
                option_dir,
                args.formats,
                layout_style="relaxed_links",
                tension_profile=tension_profile,
                basename=f"experiment2_schematic_routes_relaxed_{tension_profile}",
            )
        print()
        print(
            f"Rendered {len(TENSION_PROFILES)} Experiment 2 tension candidates "
            f"to {option_dir}."
        )
        return

    make_exp1_montage(
        exp1_cases,
        args.output_dir,
        args.formats,
        layout_style="spring",
        tension_profile=args.tension_profile,
    )
    make_exp2_montage(
        exp2_cases,
        args.output_dir,
        args.formats,
        layout_style=args.layout_style,
        tension_profile=args.tension_profile,
    )

    if not args.skip_individual:
        make_individual_diagrams(
            exp1_cases + exp2_cases,
            args.output_dir,
            args.formats,
            exp1_layout_style="spring",
            exp2_layout_style=args.layout_style,
            tension_profile=args.tension_profile,
        )

    print()
    print(
        f"Rendered schematic routes for {len(exp1_cases)} Experiment 1 cases "
        f"and {len(exp2_cases)} Experiment 2 cases."
    )


if __name__ == "__main__":
    main()
