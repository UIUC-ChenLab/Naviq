import json
import math
import os
from pathlib import Path

from noc_trace_paths import (
    NOC_CSV_OUTPUT_DIR,
    NOC_GRAPH_OUTPUT_DIR,
    runtime_trace_artifact_path,
)

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CLK_HZ = 1_000_000_000  # 1 GHz
# Latency values in CSV (AXIMM) are in ticks; convert to cycles using:
TICKS_PER_CYCLE = 1000

# TrafficMonitor may append synthetic idle rows (link_id < 0, num_bytes == 0).
# Most plots exclude them via _exclude_synthetic_traffic_csv_rows; plot_windowed_avg_bandwidth
# fans them out to every real link in the file so the rolling window sees time advancing.

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def _ensure_graph_dir() -> str:
    NOC_GRAPH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return os.fspath(NOC_GRAPH_OUTPUT_DIR)


def _graph_out(filename: str) -> str:
    return os.path.join(_ensure_graph_dir(), filename)


def _exclude_synthetic_traffic_csv_rows(df):
    """Keep only real link rows (link_id >= 0) for bandwidth/latency plots."""
    if df.empty or 'link_id' not in df.columns:
        return df
    return df.loc[df['link_id'] >= 0].copy()



def split_link_key(key):
    """
    key examples:
      AXIS:   link000
      AXIMM:  link000_read / link000_write
    returns: (base_link, subtype or None)
    """
    parts = key.split("_")
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def collect_latency_by_proto(dir):
    """
    Returns:
      latency_by_proto = {
        'AXIS':  { 'link000': np.array([...]), ... },
        'AXIMM': { 'link000_read': np.array([...]), ... }
      }
    """
    p = Path(dir)

    axis_pairs = {}  # link_id -> {'sender': [], 'receiver': []}
    axi_pairs = {}  # link_id -> {'read': [], 'write': []}

    for file_path in p.iterdir():
        if not (file_path.is_file() and file_path.name.startswith("nmu_")):
            continue

        parts = file_path.stem.split("_")
        proto = parts[2]
        subtype = parts[3]

        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: collect_latency_by_proto empty CSV skipped: {file_path}\033[0m"
            )
            continue
        if df.empty:
            print(
                f"\033[93mnoc_graphs.py: collect_latency_by_proto empty DataFrame skipped: {file_path}\033[0m"
            )
            continue

        df = _exclude_synthetic_traffic_csv_rows(df)
        if df.empty:
            continue

        if proto == 'AXIS':
            # Require timestamp column
            if "ms" not in df.columns:
                print(
                    f"\033[93mnoc_graphs.py: collect_latency_by_proto missing 'ms' for AXIS: {file_path}\033[0m"
                )
                continue
            df = df.sort_values("ms")
            df["cycle"] = (df["ms"] * 1e-3 * CLK_HZ).round().astype(int)

            # only TLAST
            if "end" in df.columns:
                df = df[df["end"] == 1]
            else:
                # Missing end flag; nothing to correlate
                print(
                    f"\033[93mnoc_graphs.py: collect_latency_by_proto missing 'end' column for AXIS: {file_path}\033[0m"
                )
                continue

            for link_id, g in df.groupby("link_id"):
                entry = axis_pairs.setdefault(link_id, {})
                entry.setdefault(subtype, []).extend(g["cycle"].to_numpy())

        elif proto == "AXIMM":
            # Require latency column
            if "latency" not in df.columns:
                print(
                    f"\033[93mnoc_graphs.py: collect_latency_by_proto missing 'latency' for AXIMM: {file_path}\033[0m"
                )
                continue
            for link_id, g in df.groupby("link_id"):
                entry = axi_pairs.setdefault(link_id, {})
                # Convert ticks -> cycles for plotting labeled in cycles
                lat_cycles = (
                    g["latency"].to_numpy(dtype=float) / TICKS_PER_CYCLE
                )
                entry.setdefault(subtype, []).extend(lat_cycles)

    latency_by_proto = {}

    # AXIS latency = receiver - sender
    axis_lat = {}
    for lid, sides in axis_pairs.items():
        if "sender" in sides and "receiver" in sides:
            n = min(len(sides["sender"]), len(sides["receiver"]))
            if n > 0:
                axis_lat[f"link{int(lid):03d}"] = np.asarray(
                    sides["receiver"][:n]
                ) - np.asarray(sides["sender"][:n])

    if axis_lat:
        latency_by_proto["AXIS"] = axis_lat

    # AXIMM latency already measured
    aximm_lat = {}
    for lid, kinds in axi_pairs.items():
        for kind, arr in kinds.items():
            if len(arr) > 0:
                aximm_lat[f"link{int(lid):03d}_{kind}"] = np.asarray(arr)

    if aximm_lat:
        latency_by_proto["AXIMM"] = aximm_lat

    return latency_by_proto


def annotate_stack(ax, x, heights, bottoms, threshold=3.0):
    """
    Annotate stacked bar segments with percentages.
    Only annotate if percentage >= threshold.
    """
    for xi, h, b in zip(x, heights, bottoms):
        if h >= threshold:
            ax.text(
                xi,
                b + h / 2,
                f"{h:.1f}%",
                ha="center",
                va="center",
                fontsize=9,
                color="black",
            )


STATE_COLORS = {
    (0, 0): "#95a5a6",  # neither
    (1, 0): "#4998e2",  # ready only
    (0, 1): "#e4d13d",  # valid only
    (1, 1): "#3abb70",  # both
}

STATE_LABELS = {
    (0, 0): "Neither",
    (1, 0): "Ready Only",
    (0, 1): "Valid Only",
    (1, 1): "Ready & Valid",
}


# ------------------------------------------------------------
# GRAPH 1: average bandwidth (AXIS vs AXIMM separated)
# ------------------------------------------------------------
def plot_average_bandwidth(dir, avg_window_size):
    p = Path(dir)

    ## first pass: find global max cycle PER PROTOCOL ##
    global_max_cycle = {}  # protocol -> max_cycle

    for file_path in p.iterdir():
        if not (file_path.is_file() and file_path.name.startswith("nmu_")):
            continue

        parts = file_path.stem.split("_")
        proto = parts[2]  # AXIS or AXIMM

        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: plot_average_bandwidth got empty data error reading csv file path {file_path}\033[0m"
            )
            continue
        if df.empty or "ms" not in df.columns:
            # Header-only or missing expected columns; skip
            if df.empty:
                print(
                    f"\033[93mnoc_graphs.py: plot_average_bandwidth empty DataFrame skipped: {file_path}\033[0m"
                )
            else:
                print(
                    f"\033[93mnoc_graphs.py: plot_average_bandwidth missing 'ms' column: {file_path}\033[0m"
                )
            continue

        df["cycle"] = (df["ms"] * 1e-3 * CLK_HZ).round().astype(int)
        if not df["cycle"].empty:
            max_cyc = int(df["cycle"].max())
            global_max_cycle[proto] = max(
                global_max_cycle.get(proto, 0), max_cyc
            )

    # build per-protocol padding indices
    full_cycle_index = {
        proto: pd.RangeIndex(0, max_cycle + 1)
        for proto, max_cycle in global_max_cycle.items()
    }

    ## plot setup (per protocol) ##
    figures = {}  # proto -> (fig, ax)
    link_colors = {}  # link_id -> color
    _color_list = list(plt.cm.tab10.colors)
    _color_index = 0

    def get_bw_axis(proto):
        if proto not in figures:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.set_title(f"{proto} Average Bandwidth per Link")
            ax.set_xlabel("Time (µs)")
            ax.set_ylabel("Bandwidth (MB/s)")
            ax.grid(True, alpha=0.3)
            figures[proto] = (fig, ax)
        return figures[proto][1]

    ## second pass: generate plots ##
    for file_path in p.iterdir():
        if not (file_path.is_file() and file_path.name.startswith("nmu_")):
            continue

        parts = file_path.stem.split("_")
        proto = parts[2]  # AXIS or AXIMM
        subtype = parts[3]  # sender/receiver or read/write

        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: plot_average_bandwidth got empty data error reading csv file path {file_path}\033[0m"
            )
            continue
        if df.empty or "ms" not in df.columns or "num_bytes" not in df.columns:
            # Header-only or missing expected columns; skip
            reason = (
                "empty DataFrame"
                if df.empty
                else "missing columns: "
                + ", ".join(
                    c for c in ["ms", "num_bytes"] if c not in df.columns
                )
            )
            print(
                f"\033[93mnoc_graphs.py: plot_average_bandwidth skipping {file_path}: {reason}\033[0m"
            )
            continue

        df = df.sort_values("ms")
        df = _exclude_synthetic_traffic_csv_rows(df)
        if df.empty:
            continue
        df["cycle"] = (df["ms"] * 1e-3 * CLK_HZ).round().astype(int)

        # get all the unique link_ids
        link_ids = df["link_id"].unique()

        for link_id in link_ids:
            # Use per-link time normalization (no global cycle padding)
            link_df = df[df["link_id"] == link_id].sort_values("ms").copy()

            # Cumulative bytes and elapsed time since first event for this link
            link_df["cumulative_bytes"] = link_df["num_bytes"].cumsum()
            elapsed_s = (link_df["ms"] - link_df["ms"].iloc[0]) / 1000.0
            # Avoid division by zero for the first sample
            denom = elapsed_s.replace(0, pd.NA)
            link_df["avg_bw_MBps"] = (
                link_df["cumulative_bytes"] / denom
            ) / 1e6
            link_df["avg_bw_MBps"] = link_df["avg_bw_MBps"].fillna(0.0)

            # Rolling mean over sample count (keeps API the same)
            link_df["rolling_avg"] = (
                link_df["avg_bw_MBps"]
                .rolling(window=avg_window_size, min_periods=1)
                .mean()
            )

            ax = get_bw_axis(proto)

            # same color per physical link
            if link_id not in link_colors:
                link_colors[link_id] = _color_list[
                    _color_index % len(_color_list)
                ]
                _color_index += 1
            color = link_colors[link_id]

            # linestyle by semantic role
            if proto == "AXIS":
                linestyle = "-" if subtype == "sender" else ":"
                label = f"Link {int(link_id)} {subtype}"
            elif proto == "AXIMM":
                linestyle = "-" if subtype == "read" else ":"
                label = f"Link {int(link_id)} {subtype}"
            else:
                print(
                    f"\033[93mnoc_graphs.py: plot_average_bandwidth unknown protocol from filepath {proto}\033[0m"
                )
                continue

            ax.plot(
                (link_df["ms"] - link_df["ms"].iloc[0])
                * 1000.0,  # µs since first event on this link
                link_df["rolling_avg"],
                color=color,
                linestyle=linestyle,
                linewidth=2,
                label=label,
            )

    ## save figures ##
    for proto, (fig, ax) in figures.items():
        ax.legend(ncol=2)
        fig.tight_layout()
        out_path = _graph_out(f"{proto}_average_bandwidth.png")
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 2: real averaged bandwidth
# ------------------------------------------------------------


def plot_windowed_avg_bandwidth(dir, window):
    """
    Compute windowed average (moving) bandwidth per link.
    - dir: directory containing CSVs generated by the TrafficMonitor
    - window: window size in cycles (at CLK_HZ)
    Bandwidth at time t is sum(bytes in last 'window' cycles) / (window / CLK_HZ) in MB/s.

    Idle heartbeats use link_id < 0 (e.g. -2). They carry zero bytes, but they still extend
    the sampled timeline so the plotted bandwidth decays toward zero during idle periods.

    CSV column `ms` is simulation time in milliseconds (not CPU cycles). The x-axis is
    plotted in those same milliseconds, from 0 to the latest logged timestamp.
    """
    if window is None or window <= 0:
        raise ValueError("window must be a positive integer (in cycles)")

    p = Path(dir)
    window_cycles = int(window)
    window_seconds = window_cycles / CLK_HZ

    def is_monitor_csv(file_path):
        return file_path.is_file() and file_path.name.startswith(("nmu_", "nsu_"))

    # Pass 1: max cycle per protocol for zero-padding and max simulation time for x-limits.
    # Include synthetic idle rows (link_id < 0): they are the monitor's heartbeat and
    # define how long the simulation ran even when no link transferred bytes.
    global_max_cycle = {}
    proto_max_ms = {}
    for file_path in p.iterdir():
        if not is_monitor_csv(file_path):
            continue
        parts = file_path.stem.split("_")
        if len(parts) < 4:
            continue
        proto = parts[2]  # AXIS or AXIMM
        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: plot_windowed_avg_bandwidth empty CSV skipped: {file_path}\033[0m"
            )
            continue
        if df.empty or "ms" not in df.columns:
            if df.empty:
                print(
                    f"\033[93mnoc_graphs.py: plot_windowed_avg_bandwidth empty DataFrame skipped: {file_path}\033[0m"
                )
            else:
                print(
                    f"\033[93mnoc_graphs.py: plot_windowed_avg_bandwidth missing 'ms' column: {file_path}\033[0m"
                )
            continue
        df = df.sort_values("ms")
        df["cycle"] = (df["ms"] * 1e-3 * CLK_HZ).round().astype(int)
        if not df["cycle"].empty:
            max_cycle = int(df['cycle'].max())
            global_max_cycle[proto] = max(
                global_max_cycle.get(proto, 0), max_cycle)
            cycle_max_ms = max_cycle / CLK_HZ * 1e3
            csv_max_ms = float(df["ms"].max())
            
            proto_max_ms[proto] = max(
                proto_max_ms.get(proto, 0.0),
                csv_max_ms,
                cycle_max_ms,
            )

    full_cycle_index = {
        proto: pd.RangeIndex(0, max_cycle + 1)
        for proto, max_cycle in global_max_cycle.items()
    }

    # Plot per protocol
    figures = {}  # proto -> (fig, ax)
    link_colors = {}
    colors = list(plt.cm.tab10.colors)
    color_idx = 0

    def get_axis(proto):
        if proto not in figures:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.set_title(
                f"{proto} Windowed Average Bandwidth (window={window} cycles)"
            )
            ax.set_xlabel("Simulation time (ms)")
            ax.set_ylabel("Bandwidth (MB/s)")
            ax.grid(True, alpha=0.3)
            figures[proto] = (fig, ax)
        return figures[proto][1]

    # Pass 2: compute and plot
    for file_path in p.iterdir():
        if not is_monitor_csv(file_path):
            continue

        parts = file_path.stem.split("_")
        if len(parts) < 4:
            continue
        proto = parts[2]  # AXIS or AXIMM
        subtype = parts[3]  # sender/receiver or read/write

        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: plot_windowed_avg_bandwidth empty CSV skipped: {file_path}\033[0m"
            )
            continue
        required_columns = ['ms', 'link_id', 'num_bytes']
        if df.empty or any(c not in df.columns for c in required_columns):
            reason = "empty DataFrame" if df.empty else "missing columns: " + ", ".join(c for c in required_columns if c not in df.columns)
            print(f"\033[93mnoc_graphs.py: plot_windowed_avg_bandwidth skipping {file_path}: {reason}\033[0m")
            continue

        df = df.sort_values('ms')
        df['cycle'] = (df['ms'] * 1e-3 * CLK_HZ).round().astype(int)
        idle_df = df.loc[df['link_id'] < 0, ['cycle', 'num_bytes']]
        traffic_df = df.loc[df['link_id'] >= 0]
        if traffic_df.empty:
            continue

        cycle_index = full_cycle_index.get(proto)
        if cycle_index is None or cycle_index.empty:
            continue

        for link_id, link_only in traffic_df.groupby('link_id'):
            # Fan out synthetic idle samples onto every real link so heartbeat-only time is
            # part of the same rolling window, then fill every cycle between 0 and max log time.
            link_rows = link_only[['cycle', 'num_bytes']]
            merged = pd.concat([link_rows, idle_df], ignore_index=True)
            per_cycle = merged.groupby('cycle')['num_bytes'].sum()
            bytes_per_cycle = per_cycle.reindex(cycle_index, fill_value=0)
            window_bytes = bytes_per_cycle.rolling(window=window_cycles, min_periods=1).sum()
            bw_MBps = (window_bytes / window_seconds) / 1e6

            ax = get_axis(proto)

            # color per physical link
            if link_id not in link_colors:
                link_colors[link_id] = colors[color_idx % len(colors)]
                color_idx += 1
            color = link_colors[link_id]

            # linestyle by role
            if proto == "AXIS":
                linestyle = "-" if subtype == "sender" else ":"
                label = f"Link {int(link_id)} {subtype}"
            elif proto == "AXIMM":
                linestyle = "-" if subtype == "read" else ":"
                label = f"Link {int(link_id)} {subtype}"
            else:
                continue

            x_ms = cycle_index.to_numpy(dtype=np.float64) / CLK_HZ * 1e3
            t_end = proto_max_ms.get(proto, 0.0)
            if t_end > 0.0 and (x_ms.size == 0 or x_ms[-1] < t_end):
                x_ms = np.append(x_ms, t_end)
                bw_values = np.append(bw_MBps.to_numpy(), 0.0)
            else:
                bw_values = bw_MBps.to_numpy()
            ax.plot(
                x_ms,
                bw_values,
                color=color,
                linestyle=linestyle,
                linewidth=2,
                label=label,
            )

    # Save figures
    for proto, (fig, ax) in figures.items():
        t_end = proto_max_ms.get(proto, 0.0)
        if t_end > 0.0:
            ax.set_xlim(0.0, t_end)
            ax.margins(x=0)
        ax.legend(ncol=2)
        fig.tight_layout()
        out_path = _graph_out(f"{proto}_windowed_bandwidth_{window}cyc.png")
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 2: latency box plot + raw points
# ------------------------------------------------------------


def plot_latency_boxplots(dir):
    latency_by_proto = collect_latency_by_proto(dir)

    for proto, lat_dict in latency_by_proto.items():
        fig, ax = plt.subplots(figsize=(12, 6))

        keys = sorted(lat_dict.keys())
        data = [lat_dict[k] for k in keys]

        bp = ax.boxplot(
            data,
            labels=keys,
            patch_artist=True,
            showfliers=False,  # fliers would double-count with scatter
        )

        colors = plt.cm.tab10.colors

        for i, (patch, key) in enumerate(zip(bp["boxes"], keys)):
            color = colors[i % len(colors)]
            patch.set_facecolor(color)
            patch.set_alpha(0.5)

            # --- overlay raw latency points with jitter ---
            y = lat_dict[key]
            x = np.random.normal(
                loc=i + 1,  # boxplot positions are 1-based
                scale=0.04,  # jitter amount
                size=len(y),
            )

            ax.scatter(x, y, s=10, color=color, alpha=0.6, edgecolors="none")

        ax.set_title(f"{proto} Latency Boxplot")
        ax.set_ylabel("Latency (cycles)")
        ax.set_xticklabels(keys, rotation=45, ha="right")
        ax.grid(axis="y", alpha=0.3)

        fig.tight_layout()
        out = _graph_out(f"{proto}_latency_boxplot.png")
        fig.savefig(out, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out}")


# ------------------------------------------------------------
# GRAPH 3: latency histogram + percentiles (per protocol)
# ------------------------------------------------------------


def plot_latency_histograms(dir):
    latency_by_proto = collect_latency_by_proto(dir)

    for proto, lat_dict in latency_by_proto.items():
        for key, lat in lat_dict.items():
            if lat.size == 0:
                print(
                    f"\033[93mnoc_graphs.py: plot_latency_histograms skipping {proto} {key}: empty latency array\033[0m"
                )
                continue

            fig, ax = plt.subplots()

            lat_min, lat_max = lat.min(), lat.max()
            lat_range = max(lat_max - lat_min, 1)
            bin_width = max(1, int(lat_range * 0.07))

            bins = np.arange(lat_min, lat_max + bin_width, bin_width)

            ax.hist(lat, bins=bins, alpha=0.6, edgecolor="black")

            for p, c in zip([50, 95, 99], ["red", "orange", "purple"]):
                ax.axvline(
                    np.percentile(lat, p),
                    color=c,
                    linestyle="--",
                    label=f"P{p}",
                )

            ax.set_title(f"{proto} {key} Latency Histogram")
            ax.set_xlabel("Latency (cycles)")
            ax.set_ylabel("Frequency")
            ax.legend(loc="upper right")

            fig.tight_layout()
            out = _graph_out(f"{proto}_{key}_latency_hist.png")
            fig.savefig(out, dpi=200)
            plt.close(fig)
            print(f"Saved plot to {out}")


# ------------------------------------------------------------
# GRAPH 4: latency ECDF (per protocol)
# ------------------------------------------------------------


def plot_latency_ecdf(dir):
    latency_by_proto = collect_latency_by_proto(dir)

    for proto, lat_dict in latency_by_proto.items():
        fig, ax = plt.subplots(figsize=(10, 6))

        base_colors = {}
        colors = plt.cm.tab10.colors
        ci = 0

        for key in sorted(lat_dict):
            lat = lat_dict[key]
            base, subtype = split_link_key(key)

            if base not in base_colors:
                base_colors[base] = colors[ci % len(colors)]
                ci += 1

            linestyle = ":" if subtype == "write" else "-"
            label = key

            lat = np.sort(lat)
            ecdf = np.arange(1, len(lat) + 1) / len(lat)

            ax.plot(
                lat,
                ecdf,
                color=base_colors[base],
                linestyle=linestyle,
                linewidth=2,
                label=label,
            )

        ax.set_title(f"{proto} Latency ECDF")
        ax.set_xlabel("Latency (cycles)")
        ax.set_ylabel("ECDF")
        ax.set_ylim(0, 1.01)
        ax.grid(True, alpha=0.3)
        ax.legend(ncol=2)

        fig.tight_layout()
        out = _graph_out(f"{proto}_latency_ecdf.png")
        fig.savefig(out, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out}")


# ------------------------------------------------------------
# GRAPH 5: latency percentile bars (per protocol)
# ------------------------------------------------------------


def plot_latency_percentiles(dir):
    latency_by_proto = collect_latency_by_proto(dir)
    percentiles = [50, 90, 99.9]
    labels = ["P50", "P90", "P99.9"]

    for proto, lat_dict in latency_by_proto.items():
        keys = sorted(lat_dict)
        x = np.arange(len(percentiles))
        width = 0.8 / max(len(keys), 1)

        fig, ax = plt.subplots(figsize=(10, 6))

        base_colors = {}
        colors = plt.cm.tab10.colors
        ci = 0

        for i, key in enumerate(keys):
            lat = lat_dict[key]
            base, subtype = split_link_key(key)

            if base not in base_colors:
                base_colors[base] = colors[ci % len(colors)]
                ci += 1

            hatch = "xx" if subtype == "write" else None
            pct = np.percentile(lat, percentiles)

            ax.bar(
                x + i * width,
                pct,
                width,
                color=base_colors[base],
                hatch=hatch,
                edgecolor="black",
                label=key,
            )

        ax.set_xticks(x + width * (len(keys) - 1) / 2)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Latency (cycles)")
        ax.set_title(f"{proto} Latency Percentiles")
        ax.legend(ncol=2)
        ax.grid(axis="y", alpha=0.3)

        fig.tight_layout()
        out = _graph_out(f"{proto}_latency_percentiles.png")
        fig.savefig(out, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out}")


# ------------------------------------------------------------
# GRAPH 6: ready/valid percentages
# ------------------------------------------------------------


def plot_ready_valid_pct(dir):
    path = os.path.join(dir, "ready_valid.csv")
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print(
            f"\033[93mnoc_graphs.py: plot_ready_valid_pct empty CSV: {path}\033[0m"
        )
        return
    if df.empty:
        print(f"\033[93mnoc_graphs.py: plot_ready_valid_pct empty DataFrame: {path}\033[0m")
        return

    if 'ready' in df.columns and 'valid' in df.columns:
        n0 = len(df)
        df = df.dropna(subset=['ready', 'valid'])
        if len(df) < n0:
            print(
                f"\033[93mnoc_graphs.py: plot_ready_valid_pct dropped {n0 - len(df)} "
                f"row(s) with NaN ready/valid\033[0m"
            )
    if df.empty:
        print(f"\033[93mnoc_graphs.py: plot_ready_valid_pct empty after dropna: {path}\033[0m")
        return

    # Split by protocol
    if "protocol" not in df.columns or "channel_name" not in df.columns:
        # Fallback: previous behavior on entire file
        nodes = sorted(df["node_id"].unique().tolist())
        if len(nodes) == 0:
            print(
                f"\033[93mnoc_graphs.py: plot_ready_valid_pct no nodes found in fallback mode\033[0m"
            )
            return
        ready_only_pct = []
        valid_only_pct = []
        both_pct = []
        neither_pct = []
        for nid in nodes:
            g = df[df["node_id"] == nid]
            total = max(len(g), 1)
            ro = ((g["ready"] == 1) & (g["valid"] == 0)).sum()
            vo = ((g["valid"] == 1) & (g["ready"] == 0)).sum()
            bo = ((g["ready"] == 1) & (g["valid"] == 1)).sum()
            ne = ((g["ready"] == 0) & (g["valid"] == 0)).sum()
            ready_only_pct.append(100.0 * ro / total)
            valid_only_pct.append(100.0 * vo / total)
            both_pct.append(100.0 * bo / total)
            neither_pct.append(100.0 * ne / total)
        x = np.arange(len(nodes))
        width = 0.6
        fig, ax = plt.subplots(figsize=(12, 6))
        bottom1 = np.zeros(len(nodes))
        ax.bar(
            x,
            ready_only_pct,
            width,
            label=STATE_LABELS[(1, 0)],
            color=STATE_COLORS[(1, 0)],
        )
        bottom2 = bottom1 + np.array(ready_only_pct)
        ax.bar(
            x,
            valid_only_pct,
            width,
            bottom=bottom2,
            label=STATE_LABELS[(0, 1)],
            color=STATE_COLORS[(0, 1)],
        )
        bottom3 = bottom2 + np.array(valid_only_pct)
        ax.bar(
            x,
            both_pct,
            width,
            bottom=bottom3,
            label=STATE_LABELS[(1, 1)],
            color=STATE_COLORS[(1, 1)],
        )
        bottom4 = bottom3 + np.array(both_pct)
        ax.bar(
            x,
            neither_pct,
            width,
            bottom=bottom4,
            label=STATE_LABELS[(0, 0)],
            color=STATE_COLORS[(0, 0)],
        )
        annotate_stack(ax, x, ready_only_pct, bottom1)
        annotate_stack(ax, x, valid_only_pct, bottom2)
        annotate_stack(ax, x, both_pct, bottom3)
        annotate_stack(ax, x, neither_pct, bottom4)
        ax.set_xticks(x)
        ax.set_xticklabels([str(n) for n in nodes])
        ax.set_ylabel('Percentage of cycles')
        ax.set_xlabel('NoC Interface ID')
        ax.set_ylim(0, 100)
        ax.set_title('Ready/Valid State Percentages per NoC Interface')
        ax.legend(ncol=2)
        fig.tight_layout()
        out_path = _graph_out("ready_valid_percentages.png")
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")
        return

    # AXIS: keep single stacked bar per node
    df_axis = df[df["protocol"] == "AXIS"]
    if not df_axis.empty:
        nodes = sorted(df_axis["node_id"].unique().tolist())
        if len(nodes) > 0:
            ready_only_pct = []
            valid_only_pct = []
            both_pct = []
            neither_pct = []
            for nid in nodes:
                g = df_axis[df_axis["node_id"] == nid]
                total = max(len(g), 1)
                ro = ((g["ready"] == 1) & (g["valid"] == 0)).sum()
                vo = ((g["valid"] == 1) & (g["ready"] == 0)).sum()
                bo = ((g["ready"] == 1) & (g["valid"] == 1)).sum()
                ne = ((g["ready"] == 0) & (g["valid"] == 0)).sum()
                ready_only_pct.append(100.0 * ro / total)
                valid_only_pct.append(100.0 * vo / total)
                both_pct.append(100.0 * bo / total)
                neither_pct.append(100.0 * ne / total)
            x = np.arange(len(nodes))
            width = 0.6
            fig, ax = plt.subplots(figsize=(12, 6))
            b1 = ax.bar(
                x,
                ready_only_pct,
                width,
                label=STATE_LABELS[(1, 0)],
                color=STATE_COLORS[(1, 0)],
            )
            bottom2 = np.array(ready_only_pct)
            b2 = ax.bar(
                x,
                valid_only_pct,
                width,
                bottom=bottom2,
                label=STATE_LABELS[(0, 1)],
                color=STATE_COLORS[(0, 1)],
            )
            bottom3 = bottom2 + np.array(valid_only_pct)
            b3 = ax.bar(
                x,
                both_pct,
                width,
                bottom=bottom3,
                label=STATE_LABELS[(1, 1)],
                color=STATE_COLORS[(1, 1)],
            )
            bottom4 = bottom3 + np.array(both_pct)
            b4 = ax.bar(
                x,
                neither_pct,
                width,
                bottom=bottom4,
                label=STATE_LABELS[(0, 0)],
                color=STATE_COLORS[(0, 0)],
            )
            annotate_stack(ax, x, ready_only_pct, np.zeros(len(nodes)))
            annotate_stack(ax, x, valid_only_pct, bottom2)
            annotate_stack(ax, x, both_pct, bottom3)
            annotate_stack(ax, x, neither_pct, bottom4)
            ax.set_xticks(x)
            ax.set_xticklabels([str(n) for n in nodes])
            ax.set_ylabel('Percentage of cycles')
            ax.set_xlabel('NoC Interface ID')
            ax.set_ylim(0, 100)
            ax.set_title('AXIS Ready/Valid State Percentages per NoC Interface')
            ax.legend(ncol=2)
            fig.tight_layout()
            out_path = _graph_out("AXIS_ready_valid_percentages.png")
            fig.savefig(out_path, dpi=200)
            plt.close(fig)
            print(f"Saved plot to {out_path}")

    # AXIMM: grouped bars per node by channel_name
    df_aximm = df[df["protocol"] == "AXIMM"]
    if not df_aximm.empty:
        nodes = sorted(df_aximm["node_id"].unique().tolist())
        channels = sorted(df_aximm["channel_name"].dropna().unique().tolist())

        if nodes and channels:
            x = np.arange(len(nodes))
            total_width = 0.8
            w = total_width / len(channels)

            fig, ax = plt.subplots(figsize=(14, 6))

            for ci, ch in enumerate(channels):
                ro_list, vo_list, bo_list, ne_list = [], [], [], []

                for nid in nodes:
                    g = df_aximm[
                        (df_aximm["node_id"] == nid)
                        & (df_aximm["channel_name"] == ch)
                    ]
                    total = max(len(g), 1)
                    ro = ((g["ready"] == 1) & (g["valid"] == 0)).sum()
                    vo = ((g["valid"] == 1) & (g["ready"] == 0)).sum()
                    bo = ((g["ready"] == 1) & (g["valid"] == 1)).sum()
                    ne = ((g["ready"] == 0) & (g["valid"] == 0)).sum()

                    ro_list.append(100.0 * ro / total)
                    vo_list.append(100.0 * vo / total)
                    bo_list.append(100.0 * bo / total)
                    ne_list.append(100.0 * ne / total)

                x_pos = x + ci * w - (total_width - w) / 2

                b_ro = ax.bar(
                    x_pos,
                    ro_list,
                    w,
                    color=STATE_COLORS[(1, 0)],
                    edgecolor="black",
                    linewidth=0.4,
                )
                b_vo = ax.bar(
                    x_pos,
                    vo_list,
                    w,
                    bottom=ro_list,
                    color=STATE_COLORS[(0, 1)],
                    edgecolor="black",
                    linewidth=0.4,
                )
                bottom2 = np.array(ro_list) + np.array(vo_list)
                b_bo = ax.bar(
                    x_pos,
                    bo_list,
                    w,
                    bottom=bottom2,
                    color=STATE_COLORS[(1, 1)],
                    edgecolor="black",
                    linewidth=0.4,
                )
                bottom3 = bottom2 + np.array(bo_list)
                b_ne = ax.bar(
                    x_pos,
                    ne_list,
                    w,
                    bottom=bottom3,
                    color=STATE_COLORS[(0, 0)],
                    edgecolor="black",
                    linewidth=0.4,
                )

                # ---- percentage annotations (only if tall enough) ----
                def annotate(vals, bottoms):
                    for xi, v, b in zip(x_pos, vals, bottoms):
                        if v >= 5.0:  # threshold %
                            ax.text(
                                xi,
                                b + v / 2,
                                f"{v:.1f}%",
                                ha="center",
                                va="center",
                                fontsize=8,
                                color="black",
                            )

                annotate(ro_list, np.zeros(len(nodes)))
                annotate(vo_list, np.array(ro_list))
                annotate(bo_list, bottom2)
                annotate(ne_list, bottom3)

                # ---- channel label at bottom of each bar ----
                for xi in x_pos:
                    ax.text(
                        xi,
                        -4,
                        ch,
                        ha="center",
                        va="top",
                        fontsize=8,
                        rotation=90,
                    )

            # ---- node super-labels ----
            for xi, nid in zip(x, nodes):
                ax.text(
                    xi,
                    -10,
                    f"NoC Interface {int(nid)}",
                    ha='center',
                    va='top',
                    fontsize=10,
                    fontweight="bold",
                )

            ax.set_xticks([])
            ax.set_ylabel("Percentage of cycles")
            ax.set_ylim(-14, 100)
            ax.set_title('AXIMM Ready/Valid State Percentages per NoC Interface by Channel')

            # legend (state-based only)
            handles = [
                plt.Rectangle((0, 0), 1, 1, color=STATE_COLORS[(1, 0)]),
                plt.Rectangle((0, 0), 1, 1, color=STATE_COLORS[(0, 1)]),
                plt.Rectangle((0, 0), 1, 1, color=STATE_COLORS[(1, 1)]),
                plt.Rectangle((0, 0), 1, 1, color=STATE_COLORS[(0, 0)]),
            ]
            labels = [
                STATE_LABELS[(1, 0)],
                STATE_LABELS[(0, 1)],
                STATE_LABELS[(1, 1)],
                STATE_LABELS[(0, 0)],
            ]
            ax.legend(handles, labels, ncol=2)

            fig.tight_layout()
            out_path = _graph_out("AXIMM_ready_valid_percentages_by_channel.png")
            fig.savefig(out_path, dpi=200)
            plt.close(fig)
            print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 7: ready/valid timeline
# ------------------------------------------------------------


def plot_ready_valid_timeline(dir):
    path = os.path.join(dir, "ready_valid.csv")
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print(
            f"\033[93mnoc_graphs.py: plot_ready_valid_timeline empty CSV: {path}\033[0m"
        )
        return

    if df.empty:
        print(f"\033[93mnoc_graphs.py: plot_ready_valid_timeline empty DataFrame: {path}\033[0m")
        return

    if 'ready' in df.columns and 'valid' in df.columns:
        n0 = len(df)
        df = df.dropna(subset=['ready', 'valid'])
        if len(df) < n0:
            print(
                f"\033[93mnoc_graphs.py: plot_ready_valid_timeline dropped {n0 - len(df)} "
                f"row(s) with NaN ready/valid\033[0m"
            )
    if df.empty:
        print(f"\033[93mnoc_graphs.py: plot_ready_valid_timeline empty after dropna: {path}\033[0m")
        return

    # convert ms → cycles (exactly your formula)
    df["cycle"] = (df["ms"] * 1e-3 * CLK_HZ).round().astype(int)

    # AXIS: original single row per node
    df_axis = (
        df[df["protocol"] == "AXIS"]
        if "protocol" in df.columns
        else df.iloc[0:0]
    )
    if not df_axis.empty:
        nodes = sorted(df_axis["node_id"].unique().tolist())
        fig, ax = plt.subplots(figsize=(14, 0.6 * len(nodes) + 2))
        bar_height = 0.6
        for y, nid in enumerate(nodes):
            g = df_axis[df_axis["node_id"] == nid].sort_values("cycle")
            # normalize to per-node active time: start each at zero
            first_c = int(g["cycle"].iloc[0]) if not g.empty else 0
            cycles = (g["cycle"] - first_c).to_numpy()
            ready = g["ready"].to_numpy()
            valid = g["valid"].to_numpy()
            if len(cycles) == 0:
                continue
            start_c = cycles[0]
            curr_state = (ready[0], valid[0])
            for i in range(1, len(cycles)):
                state = (ready[i], valid[i])
                if state != curr_state:
                    ax.barh(
                        y,
                        cycles[i] - start_c,
                        left=start_c,
                        height=bar_height,
                        color=STATE_COLORS[curr_state],
                        edgecolor="none",
                    )
                    start_c = cycles[i]
                    curr_state = state
            ax.barh(
                y,
                cycles[-1] - start_c + 1,
                left=start_c,
                height=bar_height,
                color=STATE_COLORS[curr_state],
                edgecolor="none",
            )
        ax.set_yticks(range(len(nodes)))
        ax.set_yticklabels([str(n) for n in nodes])
        ax.set_xlabel('Time (cycles)')
        ax.set_ylabel('NoC Interface ID')
        ax.set_title('AXIS Ready / Valid Activity per NoC Interface Over Time')
        handles = [plt.Line2D([0], [0], color=STATE_COLORS[s], lw=8) for s in STATE_COLORS]
        ax.legend(handles, [STATE_LABELS[s] for s in STATE_COLORS], ncol=2, loc='upper right')
        ax.grid(axis='x', alpha=0.3)
        fig.tight_layout()
        out_path = _graph_out("AXIS_ready_valid_timeline.png")
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")

    # AXIMM: grouped channels per node with tight spacing
    df_aximm = (
        df[df["protocol"] == "AXIMM"]
        if "protocol" in df.columns
        else df.iloc[0:0]
    )
    if not df_aximm.empty:
        nodes = sorted(df_aximm["node_id"].unique().tolist())
        channels = sorted(df_aximm["channel_name"].dropna().unique().tolist())

        if nodes and channels:
            ch_gap = 0.8  # spacing between channels
            node_gap = 1.5  # extra gap between nodes
            bar_height = 0.6

            # compute y positions
            y_positions = {}
            y = 0.0
            node_centers = {}

            for nid in nodes:
                start_y = y
                for ch in channels:
                    y_positions[(nid, ch)] = y
                    y += ch_gap
                node_centers[nid] = (start_y + y - ch_gap) / 2
                y += node_gap

            fig, ax = plt.subplots(figsize=(14, 0.5 * y + 2))

            for (nid, ch), y_pos in y_positions.items():
                g = df_aximm[
                    (df_aximm["node_id"] == nid)
                    & (df_aximm["channel_name"] == ch)
                ].sort_values("cycle")

                if g.empty:
                    continue

                # normalize per (node, channel) active time
                first_c = int(g["cycle"].iloc[0]) if not g.empty else 0
                cycles = (g["cycle"] - first_c).to_numpy()
                ready = g["ready"].to_numpy()
                valid = g["valid"].to_numpy()

                start_c = cycles[0]
                curr_state = (ready[0], valid[0])

                for i in range(1, len(cycles)):
                    state = (ready[i], valid[i])
                    if state != curr_state:
                        ax.barh(
                            y_pos,
                            cycles[i] - start_c,
                            left=start_c,
                            height=bar_height,
                            color=STATE_COLORS[curr_state],
                            edgecolor="none",
                        )
                        start_c = cycles[i]
                        curr_state = state

                ax.barh(
                    y_pos,
                    cycles[-1] - start_c + 1,
                    left=start_c,
                    height=bar_height,
                    color=STATE_COLORS[curr_state],
                    edgecolor="none",
                )

                # channel label centered on bar
                ax.text(
                    cycles.mean(),
                    y_pos,
                    ch,
                    va="center",
                    ha="center",
                    fontsize=9,
                    color="black",
                    alpha=0.8,
                )

            # y-axis: node labels only
            ax.set_yticks(list(node_centers.values()))
            ax.set_yticklabels([str(n) for n in nodes])
            ax.set_ylabel("Node ID")
            ax.set_xlabel("Time (cycles)")
            ax.set_title("AXIMM Ready / Valid Activity NoC Interface (Channels Grouped)")

            handles = [
                plt.Line2D([0], [0], color=STATE_COLORS[s], lw=8)
                for s in STATE_COLORS
            ]
            ax.legend(
                handles,
                [STATE_LABELS[s] for s in STATE_COLORS],
                ncol=2,
                loc="upper right",
            )

            ax.grid(axis="x", alpha=0.3)
            fig.tight_layout()

            out_path = _graph_out("AXIMM_ready_valid_timeline_grouped.png")
            fig.savefig(out_path, dpi=200)
            plt.close(fig)
            print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 8: bytes transferred per link
# ------------------------------------------------------------


def plot_bytes_transferred_per_link(dir):
    """
    Plot cumulative bytes transferred per link over time (per protocol).
    Synthetic refresh rows use link_id < 0 and num_bytes == 0. They do not add
    bytes, but they extend the x-axis so the cumulative curve spans the full
    experiment even after traffic stops.
    Uses same linestyle convention:
      - AXIS: sender = solid, receiver = dotted
      - AXIMM: read = solid, write = dotted
    """
    p = Path(dir)

    def is_monitor_csv(file_path):
        return file_path.is_file() and file_path.name.startswith(("nmu_", "nsu_"))

    # Pass 1: max cycle per protocol for padding. Include refresh rows here;
    # they define the experiment end time even when no real link transfers.
    global_max_cycle = {}
    proto_max_ms = {}
    for file_path in p.iterdir():
        if not is_monitor_csv(file_path):
            continue
        parts = file_path.stem.split('_')
        if len(parts) < 4:
            continue
        proto = parts[2]  # AXIS or AXIMM
        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: plot_bytes_transferred_per_link empty CSV skipped: {file_path}\033[0m"
            )
            continue
        if df.empty or "ms" not in df.columns:
            if df.empty:
                print(
                    f"\033[93mnoc_graphs.py: plot_bytes_transferred_per_link empty DataFrame skipped: {file_path}\033[0m"
                )
            else:
                print(
                    f"\033[93mnoc_graphs.py: plot_bytes_transferred_per_link missing 'ms' column: {file_path}\033[0m"
                )
            continue
        df = df.sort_values('ms')
        df['cycle'] = (df['ms'] * 1e-3 * CLK_HZ).round().astype(int)
        if not df['cycle'].empty:
            max_cycle = int(df['cycle'].max())
            global_max_cycle[proto] = max(global_max_cycle.get(proto, 0), max_cycle)
            proto_max_ms[proto] = max(
                proto_max_ms.get(proto, 0.0),
                float(df['ms'].max()),
                max_cycle / CLK_HZ * 1e3,
            )

    full_cycle_index = {
        proto: pd.RangeIndex(0, max_cycle + 1)
        for proto, max_cycle in global_max_cycle.items()
    }

    figures = {}  # proto -> (fig, ax)
    link_colors = {}  # link_id -> color
    _colors = list(plt.cm.tab10.colors)
    _ci = 0

    def get_ax(proto):
        if proto not in figures:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.set_title(f"{proto} Cumulative Bytes Transferred per Link")
            ax.set_xlabel("Time (µs)")
            ax.set_ylabel("Bytes (MB)")
            ax.grid(True, alpha=0.3)
            figures[proto] = (fig, ax)
        return figures[proto][1]

    # Pass 2: build cumulative curves and plot
    for file_path in p.iterdir():
        if not is_monitor_csv(file_path):
            continue

        parts = file_path.stem.split('_')
        if len(parts) < 4:
            continue
        proto = parts[2]          # AXIS or AXIMM
        subtype = parts[3]        # sender/receiver or read/write

        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: plot_bytes_transferred_per_link empty CSV skipped: {file_path}\033[0m"
            )
            continue
        required_columns = ['ms', 'link_id', 'num_bytes']
        if df.empty or any(c not in df.columns for c in required_columns):
            reason = "empty DataFrame" if df.empty else "missing columns: " + ", ".join(c for c in required_columns if c not in df.columns)
            print(f"\033[93mnoc_graphs.py: plot_bytes_transferred_per_link skipping {file_path}: {reason}\033[0m")
            continue

        df = df.sort_values('ms')
        df['cycle'] = (df['ms'] * 1e-3 * CLK_HZ).round().astype(int)
        idle_df = df.loc[df['link_id'] < 0, ['cycle', 'num_bytes']]
        traffic_df = df.loc[df['link_id'] >= 0]
        if traffic_df.empty:
            continue

        cycle_index = full_cycle_index.get(proto)
        if cycle_index is None or cycle_index.empty:
            continue

        for link_id, link_df in traffic_df.groupby('link_id'):
            # Fan out refresh rows onto every real link. They carry zero bytes,
            # so the cumulative sum stays flat while the x-axis advances.
            merged = pd.concat(
                [link_df[['cycle', 'num_bytes']], idle_df],
                ignore_index=True,
            )
            per_cycle = merged.groupby('cycle')['num_bytes'].sum()
            bytes_per_cycle = per_cycle.reindex(cycle_index, fill_value=0)

            # cumulative bytes and MB conversion
            cum_bytes = bytes_per_cycle.cumsum()
            cum_MB = cum_bytes / 1e6

            ax = get_ax(proto)

            # color per physical link_id
            if link_id not in link_colors:
                link_colors[link_id] = _colors[_ci % len(_colors)]
                _ci += 1
            color = link_colors[link_id]

            # linestyle convention
            if proto == "AXIS":
                linestyle = "-" if subtype == "sender" else ":"
                label = f"Link {int(link_id)} {subtype}"
            elif proto == "AXIMM":
                linestyle = "-" if subtype == "read" else ":"
                label = f"Link {int(link_id)} {subtype}"
            else:
                continue

            ax.plot(
                cycle_index.to_numpy() / 1e3,  # cycles (1 GHz) → µs
                cum_MB.to_numpy(),
                color=color,
                linestyle=linestyle,
                linewidth=2,
                label=label,
            )

    # Save figures
    for proto, (fig, ax) in figures.items():
        t_end = proto_max_ms.get(proto, 0.0)
        if t_end > 0.0:
            ax.set_xlim(0.0, t_end * 1e3)
            ax.margins(x=0)
        ax.legend(ncol=2)
        fig.tight_layout()
        out_path = _graph_out(f"{proto}_bytes_sent.png")
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 9: axi stream write transactions over time
# ------------------------------------------------------------


def plot_axis_tlast_counts_over_time(dir):
    """
    For AXI-Stream only:
    - For each link, plot cumulative packet counts over time for sender and receiver.
    - A packet increments the count whenever end == 1 in the CSV.
    - X-axis: time (µs since first event on that link)
    - Y-axis: cumulative packets
    """
    p = Path(dir)

    # Collect only AXIS files
    axis_files = []
    for file_path in p.iterdir():
        if not (file_path.is_file() and file_path.name.startswith("nmu_")):
            continue
        parts = file_path.stem.split("_")
        if len(parts) < 4:
            print(
                f"\033[93mnoc_graphs.py: plot_axis_tlast_counts_over_time malformed filename: {file_path}\033[0m"
            )
            continue
        proto = parts[2]
        if proto != "AXIS":
            continue
        axis_files.append(file_path)

    if not axis_files:
        print(
            "\033[93mnoc_graphs.py: plot_axis_tlast_counts_over_time found no AXIS files\033[0m"
        )
        return

    # Prepare figure
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_title("AXIS TLAST Packet Counts Over Time (per Link)")
    ax.set_xlabel("Time (µs)")
    ax.set_ylabel("Packets (cumulative)")
    ax.grid(True, alpha=0.3)

    link_colors = {}
    colors = list(plt.cm.tab10.colors)
    ci = 0

    # Process each AXIS CSV
    for file_path in axis_files:
        parts = file_path.stem.split("_")
        subtype = parts[3]  # 'sender' or 'receiver'

        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: plot_axis_tlast_counts_over_time empty CSV skipped: {file_path}\033[0m"
            )
            continue
        if df.empty:
            print(
                f"\033[93mnoc_graphs.py: plot_axis_tlast_counts_over_time empty DataFrame skipped: {file_path}\033[0m"
            )
            continue
        if "ms" not in df.columns:
            print(
                f"\033[93mnoc_graphs.py: plot_axis_tlast_counts_over_time missing 'ms' column: {file_path}\033[0m"
            )
            continue
        if "end" not in df.columns:
            print(
                f"\033[93mnoc_graphs.py: plot_axis_tlast_counts_over_time missing 'end' column (TLAST) for {file_path}\033[0m"
            )
            continue
        if "link_id" not in df.columns:
            print(
                f"\033[93mnoc_graphs.py: plot_axis_tlast_counts_over_time missing 'link_id' column: {file_path}\033[0m"
            )
            continue

        # Filter only TLAST rows
        df = df[df["end"] == 1].copy()
        if df.empty:
            # No packets for this subtype/file
            continue
        df = df.sort_values("ms")

        for link_id, g in df.groupby("link_id"):
            g = g.sort_values("ms")
            if g.empty:
                continue
            # Normalize time to start at zero for this link
            t0 = g["ms"].iloc[0]
            x_us = (g["ms"] - t0) * 1000.0
            # Cumulative count: 1,2,3,...
            y_cnt = np.arange(1, len(g) + 1, dtype=int)

            # Assign consistent color per physical link
            if link_id not in link_colors:
                link_colors[link_id] = colors[ci % len(colors)]
                ci += 1
            color = link_colors[link_id]

            # linestyle by subtype: sender solid, receiver dotted
            linestyle = "-" if subtype == "sender" else ":"
            label = f"Link {int(link_id)} {subtype}"

            # Step plot to show increments at TLAST events
            ax.step(
                x_us.to_numpy(),
                y_cnt,
                where="post",
                color=color,
                linestyle=linestyle,
                linewidth=2,
                label=label,
            )

    # If nothing plotted, bail
    if not ax.lines:
        print(
            "\033[93mnoc_graphs.py: plot_axis_tlast_counts_over_time no TLAST events to plot\033[0m"
        )
        plt.close(fig)
        return

    # Build legend: combine identical labels once
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    ax.legend(unique.values(), unique.keys(), ncol=2)

    fig.tight_layout()
    out_path = _graph_out("AXIS_tlast_counts_over_time.png")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 10: AXIS TLAST sender - receiver difference over time
# ------------------------------------------------------------


def plot_axis_tlast_diff_over_time(dir):
    """
    For AXI-Stream only:
    Per link, plot the cumulative difference over time:
        diff(t) = (#sender TLAST up to t) - (#receiver TLAST up to t)
    X-axis: time (µs since first TLAST on that link)
    Y-axis: cumulative difference
    """
    p = Path(dir)

    # Gather TLAST timestamps (ms) per link for sender/receiver
    axis_events = {}  # link_id -> {'sender': [ms,...], 'receiver': [ms,...]}

    for file_path in p.iterdir():
        if not (file_path.is_file() and file_path.name.startswith("nmu_")):
            continue
        parts = file_path.stem.split("_")
        if len(parts) < 4:
            continue
        proto = parts[2]
        subtype = parts[3]  # 'sender' or 'receiver'
        if proto != "AXIS":
            continue
        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            print(
                f"\033[93mnoc_graphs.py: plot_axis_tlast_diff_over_time empty CSV skipped: {file_path}\033[0m"
            )
            continue
        if df.empty:
            continue
        if (
            "ms" not in df.columns
            or "end" not in df.columns
            or "link_id" not in df.columns
        ):
            print(
                f"\033[93mnoc_graphs.py: plot_axis_tlast_diff_over_time missing required columns in {file_path}\033[0m"
            )
            continue
        df = df[df["end"] == 1].copy()
        if df.empty:
            continue
        for link_id, g in df.groupby("link_id"):
            times = g["ms"].sort_values().to_list()
            entry = axis_events.setdefault(
                int(link_id), {"sender": [], "receiver": []}
            )
            if subtype in ("sender", "receiver"):
                entry[subtype].extend(times)

    if not axis_events:
        print(
            "\033[93mnoc_graphs.py: plot_axis_tlast_diff_over_time found no AXIS TLAST events\033[0m"
        )
        return

    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_title("AXIS TLAST Sender-Receiver Difference Over Time (per Link)")
    ax.set_xlabel("Time (µs)")
    ax.set_ylabel("Packets (sender - receiver)")
    ax.grid(True, alpha=0.3)

    link_colors = {}
    colors = list(plt.cm.tab10.colors)
    ci = 0

    any_plotted = False
    for link_id, ev in sorted(axis_events.items()):
        s_times = sorted(ev.get("sender", []))
        r_times = sorted(ev.get("receiver", []))
        if not s_times and not r_times:
            continue
        t0 = None
        if s_times and r_times:
            t0 = min(s_times[0], r_times[0])
        elif s_times:
            t0 = s_times[0]
        else:
            t0 = r_times[0]

        # Merge walk to compute difference steps
        i = j = 0
        s_cnt = r_cnt = 0
        x_us = []
        y_diff = []
        while i < len(s_times) or j < len(r_times):
            t_next = None
            ts = s_times[i] if i < len(s_times) else None
            tr = r_times[j] if j < len(r_times) else None
            if ts is not None and tr is not None:
                t_next = ts if ts <= tr else tr
            else:
                t_next = ts if tr is None else tr
            # consume all sender events at t_next
            while i < len(s_times) and s_times[i] == t_next:
                s_cnt += 1
                i += 1
            # consume all receiver events at t_next
            while j < len(r_times) and r_times[j] == t_next:
                r_cnt += 1
                j += 1
            x_us.append((t_next - t0) * 1000.0)
            y_diff.append(s_cnt - r_cnt)

        if link_id not in link_colors:
            link_colors[link_id] = colors[ci % len(colors)]
            ci += 1
        color = link_colors[link_id]
        label = f"Link {int(link_id)} diff"
        ax.step(
            np.array(x_us),
            np.array(y_diff),
            where="post",
            color=color,
            linewidth=2,
            label=label,
        )
        any_plotted = True

    if not any_plotted:
        print(
            "\033[93mnoc_graphs.py: plot_axis_tlast_diff_over_time nothing to plot\033[0m"
        )
        plt.close(fig)
        return

    ax.legend(ncol=2)
    fig.tight_layout()
    out_path = _graph_out("AXIS_tlast_diff_over_time.png")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 11: Heatmap of Aggregate NPS activity
# ------------------------------------------------------------


def plot_nps_heatmap(dir):
    # Coordinates in this plot are pixel coordinates:
    # x += 1 moves 1 pixel right, y += 1 moves 1 pixel down.
    occ_csv_path = os.path.join(dir, "nps_occ_all.csv")
    if not os.path.exists(occ_csv_path):
        print(
            f"\033[93mnoc_graphs.py: plot_nps_heatmap missing {occ_csv_path}\033[0m"
        )
        return

    map_candidates = [
        os.path.join("src", "noc", "testing", "assets", "nps_pixel_map.json"),
        os.path.join(dir, "nps_pixel_map.json"),
    ]
    map_path = next((p for p in map_candidates if os.path.exists(p)), None)
    if not map_path:
        print(
            "\033[93mnoc_graphs.py: plot_nps_heatmap missing nps_pixel_map.json "
            "(looked in src/noc/testing/assets/ and dir)\033[0m"
        )
        return

    with open(map_path) as f:
        nps_map = json.load(f)

    # Output size must be exactly 1422x739 pixels.
    out_w_px, out_h_px = 1422, 739

    # RADIUS (in pixels) for the kernel footprint
    h = 9
    factor = 1.001

    # Build an intensity image where repeated points add more weight.
    # This directly treats each occurrence as +1 frequency at that pixel.
    intensity = np.zeros((out_h_px, out_w_px), dtype=float)

    def kde_quartic(d, h):
        dn = d / h
        return (15 / 16) * (1 - dn**2) ** 2

    # Precompute kernel weights for a (2h+1)x(2h+1) window.
    xs = np.arange(-h, h + 1, dtype=float)
    ys = np.arange(-h, h + 1, dtype=float)
    dx, dy = np.meshgrid(xs, ys)
    dist = np.sqrt(dx**2 + dy**2)
    kernel = np.zeros_like(dist, dtype=float)
    inside = dist <= h
    kernel[inside] = kde_quartic(dist[inside], h)

    # Read occupancy CSV and add weighted "points" per NPS occurrence.
    try:
        df = pd.read_csv(occ_csv_path)
    except pd.errors.EmptyDataError:
        print(
            f"\033[93mnoc_graphs.py: plot_nps_heatmap empty CSV: {occ_csv_path}\033[0m"
        )
        return

    required_cols = {"nps_name", "occupancy_sum"}
    if not required_cols.issubset(set(df.columns)):
        print(
            f"\033[93mnoc_graphs.py: plot_nps_heatmap missing columns in {occ_csv_path}: "
            f"need {sorted(required_cols)}\033[0m"
        )
        return

    csv_nps_names = sorted(
        {
            str(name)
            for name in df["nps_name"].dropna().unique()
            if str(name).strip()
        }
    )
    missing_nps_names = [name for name in csv_nps_names if name not in nps_map]
    if missing_nps_names:
        raise ValueError(
            "noc_graphs.py: plot_nps_heatmap missing coordinates in nps_pixel_map.json "
            f"for NPS entries used in this run: {missing_nps_names}"
        )

    # Track per-pixel total weight for normalization.
    pixel_weight = {}

    for row in df.itertuples(index=False):
        nps_name = getattr(row, "nps_name")
        try:
            occ = int(getattr(row, "occupancy_sum"))
        except Exception:
            continue
        if occ <= 0:
            continue

        entry = nps_map.get(nps_name)
        if not entry:
            continue
        xi = int(entry.get("x"))
        yi = int(entry.get("y"))
        if xi < 0 or xi >= out_w_px or yi < 0 or yi >= out_h_px:
            continue

        pixel_weight[(xi, yi)] = pixel_weight.get((xi, yi), 0) + occ

        x0 = max(0, xi - h)
        x1 = min(out_w_px, xi + h + 1)
        y0 = max(0, yi - h)
        y1 = min(out_h_px, yi + h + 1)

        kx0 = x0 - (xi - h)
        kx1 = kx0 + (x1 - x0)
        ky0 = y0 - (yi - h)
        ky1 = ky0 + (y1 - y0)

        intensity[y0:y1, x0:x1] += occ * kernel[ky0:ky1, kx0:kx1]
    dpi = 100
    fig_w_in, fig_h_in = out_w_px / dpi, out_h_px / dpi
    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in), dpi=dpi)

    # Use the canonical NoC layout image when available; callers may override
    # it by placing a NoC.png beside their trace output.
    bg_candidates = [
        os.path.join("src", "noc", "testing", "assets", "NoC.png"),
        os.path.join(dir, "NoC.png"),
    ]
    bg_path = next((p for p in bg_candidates if os.path.exists(p)), None)
    if bg_path:
        bg = plt.imread(bg_path)
        # Background is drawn in pixel coordinates with (0,0) at top-left.
        ax.imshow(
            bg,
            extent=[0, out_w_px, out_h_px, 0],
            origin="upper",
            aspect="equal",
            interpolation="nearest",
            zorder=0,
        )

    # Make the least populated regions clear by masking zeros.
    masked = np.ma.masked_less_equal(intensity, 0.0)
    cmap = plt.cm.viridis.copy()
    cmap.set_bad(alpha=0.0)  # masked cells are transparent (clear)

    # Normalize using a stable scale so "more hits at same pixel" changes color.
    # If we normalized to the global max, a single unique point would always
    # saturate regardless of frequency.
    kernel_peak = float(np.max(kernel)) if kernel.size else 1.0
    if pixel_weight:
        typical_hits = float(np.median(list(pixel_weight.values())))
    else:
        typical_hits = 1.0
    vmax = max(1e-12, kernel_peak * typical_hits * factor)
    norm = mcolors.Normalize(vmin=0.0, vmax=vmax)

    # Draw heatmap in the same pixel coordinate system.
    ax.imshow(
        masked,
        cmap=cmap,
        norm=norm,
        extent=[0, out_w_px, out_h_px, 0],
        origin="upper",
        aspect="equal",
        interpolation="nearest",
        alpha=0.5,
        zorder=1,
    )

    # Optional: show point locations (kept from original demo)
    # ax.plot(x, y, "ro", markersize=3, zorder=2)

    # Force exact pixel output with no padding/margins; image is the plot.
    ax.set_xlim(0, out_w_px)
    ax.set_ylim(out_h_px, 0)
    ax.set_axis_off()
    ax.set_position([0, 0, 1, 1])

    out_path = _graph_out("nps_heatmap.png")
    fig.savefig(out_path, dpi=dpi, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 12: Heatmap of average NPS buffer occupancy
# ------------------------------------------------------------


def plot_nps_avg_buffer_occupancy_heatmap(dir):
    """
    Heatmap rules:
      - Use src/noc/testing/assets/nps_pixel_map.json to map nps_name -> (x,y) pixels.
      - Per NPS: average occupancy_sum over all logged rows, then divide by
        max_buffer_size to get mean buffer fullness in [0, 1]. Stamp each NPS
        once at its pixel (small kernel) with weight = that fullness.
    """
    occ_csv_path = os.path.join(dir, "nps_occ_all.csv")
    if not os.path.exists(occ_csv_path):
        print(
            f"\033[93mnoc_graphs.py: plot_nps_avg_buffer_occupancy_heatmap missing {occ_csv_path}\033[0m"
        )
        return

    map_candidates = [
        os.path.join("src", "noc", "testing", "assets", "nps_pixel_map.json"),
        os.path.join(dir, "nps_pixel_map.json"),
    ]
    map_path = next((p for p in map_candidates if os.path.exists(p)), None)
    if not map_path:
        print(
            "\033[93mnoc_graphs.py: plot_nps_avg_buffer_occupancy_heatmap missing nps_pixel_map.json "
            "(looked in src/noc/testing/assets/ and dir)\033[0m"
        )
        return

    with open(map_path) as f:
        nps_map = json.load(f)

    # Output size must be exactly 1422x739 pixels.
    out_w_px, out_h_px = 1422, 739

    # Kernel radius in pixels (small blur around the NPS location)
    h = 9
    alpha = 0.5
    occupancy_visual_factor = 50.0

    intensity = np.zeros((out_h_px, out_w_px), dtype=float)

    def kde_quartic(d, h):
        dn = d / h
        return (15 / 16) * (1 - dn**2) ** 2

    xs = np.arange(-h, h + 1, dtype=float)
    ys = np.arange(-h, h + 1, dtype=float)
    dx, dy = np.meshgrid(xs, ys)
    dist = np.sqrt(dx**2 + dy**2)
    kernel = np.zeros_like(dist, dtype=float)
    inside = dist <= h
    kernel[inside] = kde_quartic(dist[inside], h)
    kernel_peak = float(np.max(kernel)) if kernel.size else 1.0
    if kernel_peak > 0:
        kernel = kernel / kernel_peak

    try:
        df = pd.read_csv(occ_csv_path)
    except pd.errors.EmptyDataError:
        print(
            f"\033[93mnoc_graphs.py: plot_nps_avg_buffer_occupancy_heatmap empty CSV: {occ_csv_path}\033[0m"
        )
        return

    required_cols = {"nps_name", "nps_type", "occupancy_sum", "max_buffer_size"}
    if not required_cols.issubset(set(df.columns)):
        print(
            f"\033[93mnoc_graphs.py: plot_nps_avg_buffer_occupancy_heatmap missing columns in {occ_csv_path}: "
            f"need {sorted(required_cols)}\033[0m"
        )
        return

    csv_nps_names = sorted(
        {
            str(name)
            for name in df["nps_name"].dropna().unique()
            if str(name).strip()
        }
    )
    missing_nps_names = [name for name in csv_nps_names if name not in nps_map]
    if missing_nps_names:
        raise ValueError(
            "noc_graphs.py: plot_nps_avg_buffer_occupancy_heatmap missing coordinates "
            f"in nps_pixel_map.json for NPS entries used in this run: {missing_nps_names}"
        )

    # Track per-pixel total weight for normalization.
    pixel_weight = {}

    def _mean_fullness(group):
        caps = pd.to_numeric(group["max_buffer_size"], errors="coerce").dropna()
        if caps.empty:
            return None
        cap = float(caps.iloc[-1])
        occ_mean = float(group["occupancy_sum"].mean())
        return min(max(occ_mean / cap, 0.0), 1.0)

    for nps_name, g in df.groupby("nps_name", sort=False):
        fullness = _mean_fullness(g)
        if fullness is None or fullness <= 0:
            continue

        entry = nps_map.get(nps_name)
        if not entry:
            continue
        xi = int(entry.get("x"))
        yi = int(entry.get("y"))
        if xi < 0 or xi >= out_w_px or yi < 0 or yi >= out_h_px:
            continue

        weight = fullness
        pixel_weight[(xi, yi)] = pixel_weight.get((xi, yi), 0) + weight

        x0 = max(0, xi - h)
        x1 = min(out_w_px, xi + h + 1)
        y0 = max(0, yi - h)
        y1 = min(out_h_px, yi + h + 1)

        kx0 = x0 - (xi - h)
        kx1 = kx0 + (x1 - x0)
        ky0 = y0 - (yi - h)
        ky1 = ky0 + (y1 - y0)

        intensity[y0:y1, x0:x1] += weight * kernel[ky0:ky1, kx0:kx1]

    dpi = 100
    fig_w_in, fig_h_in = out_w_px / dpi, out_h_px / dpi
    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in), dpi=dpi)

    # Background image
    bg_candidates = [
        os.path.join("src", "noc", "testing", "assets", "NoC.png"),
        os.path.join(dir, "NoC.png"),
    ]
    bg_path = next((p for p in bg_candidates if os.path.exists(p)), None)
    if bg_path:
        bg = plt.imread(bg_path)
        ax.imshow(
            bg,
            extent=[0, out_w_px, out_h_px, 0],
            origin="upper",
            aspect="equal",
            interpolation="nearest",
            zorder=0,
        )

    display_intensity = np.clip(intensity * occupancy_visual_factor, 0.0, 1.0)
    masked = np.ma.masked_less_equal(display_intensity, 0.0)
    cmap = plt.cm.viridis.copy()
    cmap.set_bad(alpha=0.0)

    norm = mcolors.Normalize(vmin=0.0, vmax=1.0)

    heatmap = ax.imshow(
        masked,
        cmap=cmap,
        norm=norm,
        extent=[0, out_w_px, out_h_px, 0],
        origin="upper",
        aspect="equal",
        interpolation="nearest",
        alpha=alpha,
        zorder=1,
    )

    ax.set_xlim(0, out_w_px)
    ax.set_ylim(out_h_px, 0)
    ax.set_axis_off()
    ax.set_position([0, 0, 1, 1])
    cax = fig.add_axes([0.945, 0.16, 0.018, 0.55])
    colorbar_mappable = plt.cm.ScalarMappable(norm=norm, cmap=plt.cm.viridis)
    colorbar = fig.colorbar(colorbar_mappable, cax=cax)
    colorbar.ax.tick_params(colors='white')

    out_path = _graph_out("nps_avg_buffer_occupancy_heatmap.png")
    fig.savefig(out_path, dpi=dpi, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    print(f"Saved plot to {out_path}")




# ------------------------------------------------------------
# GRAPH 13: Heatmap of NPS data movement
# ------------------------------------------------------------

def plot_nps_data_movement(dir):
    """
    Heatmap rules:
      - Use nps_flit_trace.csv event rows to measure flit movement.
      - Count dequeue events so the weight means flits that traversed an NPS
        input FIFO.
      - Normalize each NPS by simulation_ticks / 1000 / 2, where
        simulation_ticks is the tick from the final trace row.
      - Group by nocname and stamp each NPS once at its pixel with weight equal
        to the normalized dequeue rate.
    """
    trace_candidates = [
        os.path.join(dir, "nps_flit_trace.csv"),
        runtime_trace_artifact_path("nps_flit_trace.csv"),
        os.path.join(os.fspath(NOC_CSV_OUTPUT_DIR), "nps_flit_trace.csv"),
    ]
    trace_csv_path = next((p for p in trace_candidates if os.path.exists(p)), None)
    if not trace_csv_path:
        print(
            "\033[93mnoc_graphs.py: plot_nps_data_movement missing "
            "nps_flit_trace.csv (looked in csv dir and src/noc/out/csv)\033[0m"
        )
        return

    map_candidates = [
        os.path.join("src", "noc", "testing", "assets", "nps_pixel_map.json"),
        os.path.join(dir, "nps_pixel_map.json"),
    ]
    map_path = next((p for p in map_candidates if os.path.exists(p)), None)
    if not map_path:
        print(
            "\033[93mnoc_graphs.py: plot_nps_data_movement missing "
            "nps_pixel_map.json (looked in src/noc/testing/assets/ and dir)\033[0m"
        )
        return

    with open(map_path, "r") as f:
        nps_map = json.load(f)

    out_w_px, out_h_px = 1422, 739
    h = 9
    alpha = 0.5
    movement_visual_factor = 50.0
    intensity = np.zeros((out_h_px, out_w_px), dtype=float)

    def kde_quartic(d, h):
        dn = d / h
        return (15 / 16) * (1 - dn**2) ** 2

    xs = np.arange(-h, h + 1, dtype=float)
    ys = np.arange(-h, h + 1, dtype=float)
    dx, dy = np.meshgrid(xs, ys)
    dist = np.sqrt(dx**2 + dy**2)
    kernel = np.zeros_like(dist, dtype=float)
    inside = dist <= h
    kernel[inside] = kde_quartic(dist[inside], h)
    kernel_peak = float(np.max(kernel)) if kernel.size else 1.0
    if kernel_peak > 0:
        kernel = kernel / kernel_peak

    try:
        df = pd.read_csv(trace_csv_path)
    except pd.errors.EmptyDataError:
        print(f"\033[93mnoc_graphs.py: plot_nps_data_movement empty CSV: {trace_csv_path}\033[0m")
        return

    required_cols = {"nocname", "event", "tick"}
    if not required_cols.issubset(set(df.columns)):
        print(
            f"\033[93mnoc_graphs.py: plot_nps_data_movement missing columns in {trace_csv_path}: "
            f"need {sorted(required_cols)}\033[0m"
        )
        return

    if df.empty:
        print(f"\033[93mnoc_graphs.py: plot_nps_data_movement no rows in {trace_csv_path}\033[0m")
        return
    simulation_tick = pd.to_numeric(pd.Series([df["tick"].iloc[-1]]), errors="coerce").iloc[0]
    if pd.isna(simulation_tick):
        print(
            f"\033[93mnoc_graphs.py: plot_nps_data_movement invalid last-row tick "
            f"in {trace_csv_path}\033[0m"
        )
        return
    simulation_ticks = float(simulation_tick)
    denominator = simulation_ticks / 1000.0 / 2.0
    if denominator <= 0:
        print(
            f"\033[93mnoc_graphs.py: plot_nps_data_movement invalid simulation tick "
            f"{simulation_ticks} in {trace_csv_path}\033[0m"
        )
        return

    df["event"] = df["event"].astype(str).str.lower()
    movement_df = df[df["event"] == "dequeue"]
    if movement_df.empty:
        print(f"\033[93mnoc_graphs.py: plot_nps_data_movement no dequeue rows in {trace_csv_path}\033[0m")
        return

    movement_by_nps = movement_df.groupby("nocname", sort=False).size() / denominator
    pixel_weight = {}

    for nps_name, dequeue_rate in movement_by_nps.items():
        entry = nps_map.get(nps_name)
        if not entry:
            continue
        xi = int(entry.get("x"))
        yi = int(entry.get("y"))
        if xi < 0 or xi >= out_w_px or yi < 0 or yi >= out_h_px:
            continue

        weight = min(max(float(dequeue_rate), 0.0), 1.0)
        if weight <= 0:
            continue

        pixel_weight[(xi, yi)] = pixel_weight.get((xi, yi), 0) + weight

        x0 = max(0, xi - h)
        x1 = min(out_w_px, xi + h + 1)
        y0 = max(0, yi - h)
        y1 = min(out_h_px, yi + h + 1)

        kx0 = x0 - (xi - h)
        kx1 = kx0 + (x1 - x0)
        ky0 = y0 - (yi - h)
        ky1 = ky0 + (y1 - y0)

        intensity[y0:y1, x0:x1] += weight * kernel[ky0:ky1, kx0:kx1]

    if not pixel_weight:
        print(
            f"\033[93mnoc_graphs.py: plot_nps_data_movement no trace NPS names "
            f"matched nps_pixel_map.json from {trace_csv_path}\033[0m"
        )
        return

    dpi = 100
    fig_w_in, fig_h_in = out_w_px / dpi, out_h_px / dpi
    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in), dpi=dpi)

    bg_candidates = [
        os.path.join("src", "noc", "testing", "assets", "NoC.png"),
        os.path.join(dir, "NoC.png"),
    ]
    bg_path = next((p for p in bg_candidates if os.path.exists(p)), None)
    if bg_path:
        bg = plt.imread(bg_path)
        ax.imshow(
            bg,
            extent=[0, out_w_px, out_h_px, 0],
            origin="upper",
            aspect="equal",
            interpolation="nearest",
            zorder=0,
        )

    display_intensity = np.clip(intensity * movement_visual_factor, 0.0, 1.0)
    masked = np.ma.masked_less_equal(display_intensity, 0.0)
    cmap = plt.cm.viridis.copy()
    cmap.set_bad(alpha=0.0)

    norm = mcolors.Normalize(vmin=0.0, vmax=1.0)

    heatmap = ax.imshow(
        masked,
        cmap=cmap,
        norm=norm,
        extent=[0, out_w_px, out_h_px, 0],
        origin="upper",
        aspect="equal",
        interpolation="nearest",
        alpha=alpha,
        zorder=1,
    )

    ax.set_xlim(0, out_w_px)
    ax.set_ylim(out_h_px, 0)
    ax.set_axis_off()
    ax.set_position([0, 0, 1, 1])
    cax = fig.add_axes([0.945, 0.16, 0.018, 0.55])
    colorbar_mappable = plt.cm.ScalarMappable(norm=norm, cmap=plt.cm.viridis)
    colorbar = fig.colorbar(colorbar_mappable, cax=cax)
    colorbar.ax.tick_params(colors='white')

    out_path = _graph_out("nps_data_movement_heatmap.png")
    fig.savefig(out_path, dpi=dpi, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 14: AXIMM outstanding writes over time (record_mode_interfaces)
# ------------------------------------------------------------


def _read_link_id_mapping(dir):
    path = os.path.join(dir, "link_id_mapping.csv")
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return {}
    if df.empty or "link_id" not in df.columns or "nmu_id" not in df.columns:
        return {}
    return {
        int(row.link_id): int(row.nmu_id)
        for row in df.itertuples(index=False)
        if pd.notna(row.link_id) and pd.notna(row.nmu_id)
    }


def plot_aximm_outstanding_writes_over_time(dir):
    """
    Plot outstanding AXIMM write count over time per NMU/link using
    nmu_*_AXIMM_write.csv (outstanding_writes column from TrafficMonitor).
    """
    p = Path(dir)
    link_to_nmu = _read_link_id_mapping(dir)
    series = []

    for file_path in sorted(p.glob("nmu_*_AXIMM_write.csv")):
        try:
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            continue
        if df.empty or "ms" not in df.columns:
            continue
        if "outstanding_writes" not in df.columns:
            print(
                f"\033[93mnoc_graphs.py: plot_aximm_outstanding_writes_over_time "
                f"missing outstanding_writes in {file_path}; re-run with updated monitor\033[0m"
            )
            continue
        df = df.sort_values("ms")
        parts = file_path.stem.split("_")
        nmu_id = int(parts[1]) if len(parts) > 1 else -1
        for link_id, g in df.groupby("link_id"):
            if int(link_id) < 0:
                continue
            label_nmu = link_to_nmu.get(int(link_id), nmu_id)
            series.append(
                (
                    f"NMU {label_nmu} link {int(link_id)}",
                    g["ms"].to_numpy(),
                    g["outstanding_writes"].to_numpy(),
                )
            )

    if not series:
        print(
            "\033[93mnoc_graphs.py: plot_aximm_outstanding_writes_over_time "
            "found no plottable write CSV rows\033[0m"
        )
        return

    colors = list(plt.cm.tab10.colors)
    group_size = 10
    for group_idx, start in enumerate(range(0, len(series), group_size), start=1):
        group = series[start : start + group_size]
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.set_title(
            "AXIMM Outstanding Writes Over Time "
            f"(group {group_idx}, traces {start + 1}-{start + len(group)})"
        )
        ax.set_xlabel("Simulation time (ms)")
        ax.set_ylabel("Outstanding writes")
        ax.grid(True, alpha=0.3)
        for i, (label, x, y) in enumerate(group):
            ax.plot(
                x,
                y,
                color=colors[i % len(colors)],
                linewidth=1.5,
                label=label,
            )
        ax.legend(ncol=2, fontsize=8)
        fig.tight_layout()
        out_path = _graph_out(
            f"AXIMM_outstanding_writes_over_time_group_{group_idx:02d}.png"
        )
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")


# ------------------------------------------------------------
# GRAPH 15–18: HBM stats from hbm_stats.csv (record_hbm)
# ------------------------------------------------------------

HBM_STATS_FILENAME = "hbm_stats.csv"


def _load_hbm_stats_df(dir):
    candidates = [
        os.path.join(dir, HBM_STATS_FILENAME),
        runtime_trace_artifact_path(HBM_STATS_FILENAME),
        os.path.join(os.fspath(NOC_CSV_OUTPUT_DIR), HBM_STATS_FILENAME),
    ]
    stats_path = next((p for p in candidates if os.path.exists(p)), None)
    if not stats_path:
        print(
            f"\033[93mnoc_graphs.py: missing {HBM_STATS_FILENAME} "
            f"(enable record_hbm in .opts.json)\033[0m"
        )
        return None
    try:
        df = pd.read_csv(stats_path)
    except pd.errors.EmptyDataError:
        print(f"\033[93mnoc_graphs.py: empty {stats_path}\033[0m")
        return None
    required = {
        "ms",
        "controller_id",
        "port_id",
        "pseudo_channel_id",
        "queue_depth",
        "read_bytes",
        "write_bytes",
    }
    if df.empty or not required.issubset(df.columns):
        print(
            f"\033[93mnoc_graphs.py: {stats_path} missing columns; "
            f"need {sorted(required)}\033[0m"
        )
        return None

    # Older hbm_stats.csv files were appended across runs. Keep only the latest
    # monotonic segment so samples from multiple runs are not summed together.
    reset_points = df.index[df["ms"].diff() < 0].tolist()
    if reset_points:
        df = df.loc[reset_points[-1] :].copy()
        print(
            f"\033[93mnoc_graphs.py: using latest appended HBM stats segment "
            f"from {stats_path}\033[0m"
        )

    df = df.sort_values("ms").copy()
    df["pc_key"] = (
        df["controller_id"].astype(int).astype(str)
        + "_pc"
        + df["pseudo_channel_id"].astype(int).astype(str)
    )
    df["port_key"] = (
        df["controller_id"].astype(int).astype(str)
        + "_p"
        + df["port_id"].astype(int).astype(str)
        + "_pc"
        + df["pseudo_channel_id"].astype(int).astype(str)
    )
    return df


def _hbm_windowed_bw_mb_s(time_ms, bytes_per_sample, window_cycles):
    if len(time_ms) == 0:
        return time_ms, np.array([])
    if window_cycles is None or window_cycles <= 0:
        raise ValueError("window_cycles must be a positive integer")

    df = pd.DataFrame(
        {
            "cycle": (
                pd.Series(time_ms, dtype=float) * 1e-3 * CLK_HZ
            ).round().astype(int),
            "num_bytes": pd.Series(bytes_per_sample, dtype=float),
        }
    ).sort_values("cycle")
    if df.empty:
        return np.array([]), np.array([])

    max_cycle = int(df["cycle"].max())
    cycle_index = pd.RangeIndex(0, max_cycle + 1)
    bytes_per_cycle = (
        df.groupby("cycle")["num_bytes"]
        .sum()
        .reindex(cycle_index, fill_value=0)
    )
    window_bytes = bytes_per_cycle.rolling(
        window=int(window_cycles), min_periods=1
    ).sum()
    window_seconds = int(window_cycles) / CLK_HZ
    bw_MBps = (window_bytes / window_seconds) / 1e6
    x_ms = cycle_index.to_numpy(dtype=np.float64) / CLK_HZ * 1e3
    return x_ms, bw_MBps.to_numpy()


def plot_hbm_bandwidth_by_pseudo_channel(dir, window_cycles=100):
    df = _load_hbm_stats_df(dir)
    if df is None:
        return
    colors = list(plt.cm.tab10.colors)
    for controller_id, ctrl_df in df.groupby("controller_id"):
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.set_title(
            f"HBM Controller {int(controller_id)} Write Bandwidth by "
            f"Pseudo-Channel (window={window_cycles} cycles)"
        )
        ax.set_xlabel("Simulation time (ms)")
        ax.set_ylabel("Bandwidth (MB/s)")
        ax.grid(True, alpha=0.3)

        for ci, (pc_id, g) in enumerate(ctrl_df.groupby("pseudo_channel_id")):
            agg = g.groupby("ms", as_index=False)["write_bytes"].sum()
            x, y = _hbm_windowed_bw_mb_s(
                agg["ms"].to_numpy(), agg["write_bytes"].to_numpy(), window_cycles
            )
            ax.plot(
                x,
                y,
                color=colors[ci % len(colors)],
                linewidth=1.8,
                label=f"PC {int(pc_id)} write",
            )

        ax.legend(ncol=2, fontsize=8)
        fig.tight_layout()
        out_path = _graph_out(
            f"HBM_controller_{int(controller_id):02d}_write_bw_by_pseudo_channel_"
            f"{window_cycles}cyc.png"
        )
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")


def plot_hbm_bandwidth_by_port(dir, window_cycles=100):
    df = _load_hbm_stats_df(dir)
    if df is None:
        return
    colors = list(plt.cm.tab10.colors)
    linestyles = ["-", "--", ":", "-."]
    for controller_id, ctrl_df in df.groupby("controller_id"):
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.set_title(
            f"HBM Controller {int(controller_id)} Write Bandwidth per Port "
            f"(window={window_cycles} cycles)"
        )
        ax.set_xlabel("Simulation time (ms)")
        ax.set_ylabel("Bandwidth (MB/s)")
        ax.grid(True, alpha=0.3)

        for ci, ((pc_id, port_id), g) in enumerate(
            ctrl_df.groupby(["pseudo_channel_id", "port_id"])
        ):
            x, y = _hbm_windowed_bw_mb_s(
                g["ms"].to_numpy(), g["write_bytes"].to_numpy(), window_cycles
            )
            ax.plot(
                x,
                y,
                color=colors[int(pc_id) % len(colors)],
                linestyle=linestyles[int(port_id) % len(linestyles)],
                linewidth=1.5,
                label=f"PC {int(pc_id)} port {int(port_id)}",
            )

        ax.legend(ncol=2, fontsize=8)
        fig.tight_layout()
        out_path = _graph_out(
            f"HBM_controller_{int(controller_id):02d}_write_bw_by_port_"
            f"{window_cycles}cyc.png"
        )
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")


def plot_hbm_queue_occupancy_over_time(dir):
    df = _load_hbm_stats_df(dir)
    if df is None:
        return

    colors = list(plt.cm.tab10.colors)
    linestyles = ["-", "--", ":", "-."]
    for controller_id, ctrl_df in df.groupby("controller_id"):
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.set_title(f"HBM Controller {int(controller_id)} Queue Occupancy")
        ax.set_xlabel("Simulation time (ms)")
        ax.set_ylabel("Queue depth (cmds + buffered writes)")
        ax.grid(True, alpha=0.3)

        for (pc_id, port_id), g in ctrl_df.groupby(
            ["pseudo_channel_id", "port_id"]
        ):
            ax.plot(
                g["ms"].to_numpy(),
                g["queue_depth"].to_numpy(),
                color=colors[int(pc_id) % len(colors)],
                linestyle=linestyles[int(port_id) % len(linestyles)],
                linewidth=1.5,
                alpha=0.9,
                label=f"PC {int(pc_id)} port {int(port_id)}",
            )

        ax.legend(ncol=2, fontsize=8)
        fig.tight_layout()
        out_path = _graph_out(
            f"HBM_controller_{int(controller_id):02d}_queue_occupancy_over_time.png"
        )
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        print(f"Saved plot to {out_path}")


def plot_hbm_stats(dir, window_cycles=100):
    """Generate all HBM stats plots from hbm_stats.csv."""
    plot_hbm_bandwidth_by_pseudo_channel(dir, window_cycles=window_cycles)
    plot_hbm_bandwidth_by_port(dir, window_cycles=window_cycles)
    plot_hbm_queue_occupancy_over_time(dir)
