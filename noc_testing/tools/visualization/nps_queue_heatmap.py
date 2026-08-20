#!/usr/bin/env python3
"""
Scrubbable floorplan overlay for NPS queue trace CSV.

The modern gem5 default output path is
``src/noc/out/csv/nps_queue_trace.csv``.

For each slider position, take the last row at or before that time for each
(nocname, queue_kind, inport, vc), then aggregate depth per nocname (sum or max).

Activity is drawn as a **smooth heatmap** (Gaussian splats blended together), not
separate disks. Positions JSON: ``{"NOC_...": {"x": px, "y": px}}`` in the same
matplotlib data coordinates as the floorplan ``imshow`` (hover to read x,y).

Color scale: green (low) to red (high). Use ``--auto-scrub`` to loop time.

**Time shaping:** with ``--time-metric cumulative`` (default), each NPS uses the
sum of all logged depths up to the current time (build-up / accumulation), so
scrubbing forward slowly ramps heat instead of snapping to the latest sample.
``--z-ema`` optionally smooths the *displayed* heatmap between frames (nice for
auto-scrub); scrubbing backward resets that smoother.

**Sparse CSV:** gem5 only logs rows when depth > 0. By default we **densify** on
the inferred tick grid and fill missing samples with **depth 0**, so
instantaneous views go idle after the last event and the heat can fade. Use
``--no-dense-fill`` to keep the raw CSV.

**Time axis:** with default densify, the grid starts at ``--time-origin`` (0 by
default), so simulation time **before the first CSV row** is explicit idle
(depth 0) and the scrubber matches real ``tick`` / ``cycle`` values (``valfmt``
integer, no “offset” confusion).

**Look:** the overlay is **RGBA** — Gaussian tails below ``--heat-tail`` of the
peak are dropped so the floorplan is not washed in green. With
``--activity-smooth`` (default), the **painted** time ``display_raw`` eases
toward the slider on a **wall-clock timer** (see ``--activity-catchup-seconds-per-gdt``),
so crossing 20000→21000 produces many visible frames instead of one invisible
burst of micro-updates inside a single redraw. Use ``--no-activity-catchup`` to
snap the overlay to the slider immediately.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import Colormap, LinearSegmentedColormap
from matplotlib.widgets import Slider

# Low depth = green, high = red (smooth gradient)
GREEN_TO_RED = LinearSegmentedColormap.from_list(
    "green_to_red",
    ["#00994d", "#66cc66", "#cce34d", "#ffcc00", "#ff6633", "#cc0000"],
    N=256,
)


def load_positions(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("positions JSON must be {nocname: {x,y}, ...}")
    return data


def pick_entry(nocname: str, positions: dict) -> tuple[str, dict] | None:
    if nocname in positions:
        return nocname, positions[nocname]
    best_key = None
    best_len = -1
    for key in positions:
        if str(key).startswith("_"):
            continue
        if key in nocname or nocname in key:
            if len(key) > best_len:
                best_len = len(key)
                best_key = key
    if best_key is None:
        return None
    return best_key, positions[best_key]


def marker_xy(
    nocname: str, positions: dict, img_w: int, img_h: int, normalized: bool
) -> tuple[float, float] | None:
    picked = pick_entry(nocname, positions)
    if picked is None:
        return None
    _k, entry = picked
    if "x" not in entry or "y" not in entry:
        raise ValueError(f"Entry for {nocname} must include x and y: {entry}")
    x = float(entry["x"])
    y = float(entry["y"])
    if normalized:
        return x * img_w, y * img_h
    return x, y


def snapshot_at(df: pd.DataFrame, t: int, tcol: str, agg: str) -> dict[str, float]:
    sub = df[df[tcol] <= t]
    if sub.empty:
        return {}
    last_per = (
        sub.sort_values(tcol)
        .groupby(["nocname", "queue_kind", "inport", "vc"], as_index=False)
        .last()
    )
    if agg == "sum":
        return last_per.groupby("nocname")["depth"].sum().to_dict()
    if agg == "max":
        return last_per.groupby("nocname")["depth"].max().to_dict()
    raise ValueError(f"Unknown agg {agg!r} (use sum or max)")


def cumulative_by_nocname(df: pd.DataFrame, t: int, tcol: str) -> dict[str, float]:
    """Sum of all logged depths up to time t, per nocname (accumulation in sim time)."""
    sub = df[df[tcol] <= t]
    if sub.empty:
        return {}
    return sub.groupby("nocname")["depth"].sum().to_dict()


def infer_sample_step(df: pd.DataFrame, tcol: str) -> int:
    """Smallest positive gap between consecutive sample times (sim tick/cycle grid)."""
    ut = np.sort(df[tcol].unique().astype(np.int64))
    if len(ut) < 2:
        return 1
    d = np.diff(ut)
    d = d[d > 0]
    if len(d) == 0:
        return 1
    return int(max(1, int(d.min())))


def densify_sparse_trace(
    df: pd.DataFrame, tcol: str, *, time_origin: int = 0
) -> pd.DataFrame:
    """
    For each (nocname, queue_kind, inport, vc), reindex onto the global regular
    time grid and fill missing depths with 0 so ``last`` at time t reflects idle
    periods after activity ends.

    The grid starts at ``grid_lo = min(align_down(time_origin), t_min)`` so
    simulation time before the first log (e.g. tick 0 … 20000 when the first row
    is 21000) is present as zeros, not “missing history”.
    """
    gcols = ["nocname", "queue_kind", "inport", "vc"]
    gdt = infer_sample_step(df, tcol)
    t_min_orig = int(df[tcol].min())
    t_max = int(df[tcol].max())
    origin = max(0, int(time_origin))
    grid_lo = min((origin // gdt) * gdt, t_min_orig)
    full_ticks = np.arange(grid_lo, t_max + 1, gdt, dtype=np.int64)

    ratio = df["cycle"].astype(float) / df[tcol].astype(float)
    ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
    cpt = float(ratio.median()) if len(ratio) else 0.0

    static_cols = ["router_id", "nocname", "nps_type", "queue_kind", "inport", "vc"]
    parts: list[pd.DataFrame] = []
    for _key, grp in df.groupby(gcols, sort=False):
        g = grp.sort_values(tcol).groupby(tcol, as_index=False).last()
        g = g.set_index(tcol)
        rei = g.reindex(full_ticks)
        rei["depth"] = rei["depth"].fillna(0.0)
        for c in static_cols:
            if c in rei.columns:
                rei[c] = rei[c].bfill().ffill()
        rei[tcol] = rei.index.astype(np.int64)
        rei["cycle"] = np.round(rei[tcol].to_numpy(dtype=float) * cpt).astype(np.int64)
        parts.append(rei.reset_index(drop=True))

    out = pd.concat(parts, ignore_index=True)
    return out.sort_values([tcol] + gcols, kind="mergesort").reset_index(drop=True)


def splat_gaussian_heatmap(
    xs: list[float],
    ys: list[float],
    vals: list[float],
    gw: int,
    gh: int,
    img_w: int,
    img_h: int,
    sigma_px: float,
) -> np.ndarray:
    """Sum of depth-weighted 2D Gaussians on a gw x gh grid (pixel-ish coords)."""
    Z = np.zeros((gh, gw), dtype=np.float64)
    if not xs:
        return Z
    px = (np.arange(gw, dtype=np.float64) + 0.5) / gw * img_w
    py = (np.arange(gh, dtype=np.float64) + 0.5) / gh * img_h
    PX, PY = np.meshgrid(px, py)
    inv2s2 = 1.0 / (2.0 * sigma_px * sigma_px)
    for xi, yi, v in zip(xs, ys, vals):
        if v <= 0:
            continue
        dist2 = (PX - xi) ** 2 + (PY - yi) ** 2
        Z += float(v) * np.exp(-dist2 * inv2s2)
    return Z


def z_to_rgba(
    Z: np.ndarray,
    cmap: Colormap,
    *,
    tail_rel: float,
    alpha_max: float,
    alpha_gamma: float = 0.55,
) -> np.ndarray:
    """
    Map scalar splat grid to RGBA. Values below ``tail_rel * Z.max()`` are fully
    transparent so only localized activity is visible, not a green haze.
    """
    gh, gw = Z.shape
    out = np.zeros((gh, gw, 4), dtype=np.float64)
    zmax = float(Z.max())
    if zmax <= 1e-15:
        return out
    thr = max(0.0, float(tail_rel)) * zmax
    w = np.zeros_like(Z, dtype=np.float64)
    m = Z > thr
    if not np.any(m):
        return out
    w[m] = ((Z[m] - thr) / (zmax - thr + 1e-12)).clip(0.0, 1.0)
    rgb = cmap(np.clip(w, 0.0, 1.0))
    vis = (w ** float(alpha_gamma)) * float(alpha_max)
    out[:, :, 0] = rgb[:, :, 0]
    out[:, :, 1] = rgb[:, :, 1]
    out[:, :, 2] = rgb[:, :, 2]
    out[:, :, 3] = vis * (m.astype(np.float64))
    return np.clip(out, 0.0, 1.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "csv",
        type=Path,
        help="Queue trace CSV, typically src/noc/out/csv/nps_queue_trace.csv",
    )
    ap.add_argument("image", type=Path, help="Floorplan image (png/jpg)")
    ap.add_argument("positions", type=Path, help="JSON map nocname -> {x,y}")
    ap.add_argument(
        "--agg",
        choices=("sum", "max"),
        default="sum",
        help="Aggregate depth across queues per nocname at current time",
    )
    ap.add_argument(
        "--time-column",
        choices=("tick", "cycle"),
        default="tick",
        help="Scrub along simulation tick or network cycle",
    )
    ap.add_argument(
        "--normalized",
        action="store_true",
        help="Interpret JSON x,y as 0-1 fractions of image width/height (legacy).",
    )
    ap.add_argument(
        "--heat-grid",
        type=int,
        default=256,
        help="Heatmap raster width in cells (height scales with image aspect).",
    )
    ap.add_argument(
        "--heat-sigma",
        type=float,
        default=None,
        help="Gaussian std-dev in floorplan pixels (smaller = tighter blobs). "
        "Default ~1/48 of min(image w,h).",
    )
    ap.add_argument(
        "--heat-alpha",
        type=float,
        default=0.55,
        help="Peak opacity of the overlay (alpha scales with normalized splat height).",
    )
    ap.add_argument(
        "--heat-tail",
        type=float,
        default=0.02,
        help="Drop splat values below this fraction of the frame peak (kills green "
        "wash from Gaussian tails; higher = tighter blobs).",
    )
    ap.add_argument(
        "--heat-alpha-gamma",
        type=float,
        default=0.55,
        help="Exponent on visibility vs intensity (<1 boosts mid-levels slightly).",
    )
    ap.add_argument(
        "--no-activity-smooth",
        action="store_true",
        help="Snap splat strengths to the metric at the scrub time (no catch-up animation).",
    )
    ap.add_argument(
        "--no-activity-catchup",
        action="store_true",
        help="With --activity-smooth (default), snap painted time to the slider on "
        "every redraw instead of easing it in over wall-clock time.",
    )
    ap.add_argument(
        "--activity-catchup-seconds-per-gdt",
        type=float,
        default=0.65,
        help="Wall-clock seconds to traverse one sample interval (e.g. 1000 ticks) "
        "when the slider jumps ahead of the painted time; larger = slower visible ramp.",
    )
    ap.add_argument(
        "--activity-anim-fps",
        type=float,
        default=32.0,
        help="Timer callback rate for catch-up animation (frames per second).",
    )
    ap.add_argument(
        "--time-metric",
        choices=("instant", "cumulative"),
        default="cumulative",
        help="instant: last sample at t (respects --agg). cumulative: sum of all "
        "logged depths ≤ t per nocname (ignores --agg; ramps as you scrub forward).",
    )
    ap.add_argument(
        "--z-ema",
        type=float,
        default=1.0,
        help="Blend splat grid before coloring: Z=(1-a)*Z + a*Z_new. 1 disables. "
        "Try 0.1–0.3 with --no-activity-smooth for spatial smear only.",
    )
    ap.add_argument(
        "--auto-scrub",
        action="store_true",
        help="Automatically advance time (loops); still draggable when paused.",
    )
    ap.add_argument(
        "--auto-scrub-seconds",
        type=float,
        default=12.0,
        help="Wall-clock seconds for one full sweep from min to max time.",
    )
    ap.add_argument(
        "--auto-scrub-fps",
        type=float,
        default=20.0,
        help="Timer updates per second during auto-scrub.",
    )
    ap.add_argument(
        "--no-dense-fill",
        action="store_true",
        help="Keep sparse CSV only (no synthetic zero-depth rows); heat may not "
        "fade after the last positive sample.",
    )
    ap.add_argument(
        "--time-origin",
        type=int,
        default=0,
        help="When densifying, align the time grid from this value downward to the "
        "sample step (default 0). Idle samples are inserted from here up to the "
        "first logged tick so the heatmap at tick 0 is idle before real traffic.",
    )
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    required = {
        "tick",
        "cycle",
        "router_id",
        "nocname",
        "nps_type",
        "queue_kind",
        "inport",
        "vc",
        "depth",
    }
    missing = required - set(df.columns)
    if missing:
        print(f"CSV missing columns: {missing}", file=sys.stderr)
        return 1

    if not args.no_dense_fill:
        df = densify_sparse_trace(
            df, args.time_column, time_origin=args.time_origin
        )

    positions = load_positions(args.positions)
    img = plt.imread(str(args.image))
    img_h, img_w = img.shape[0], img.shape[1]

    gw = max(32, int(args.heat_grid))
    gh = max(32, int(round(gw * img_h / img_w)))

    sigma = args.heat_sigma
    if sigma is None:
        sigma = max(4.0, min(img_w, img_h) / 48.0)

    tcol = args.time_column
    t_min = int(df[tcol].min())
    t_max = int(df[tcol].max())
    gdt = infer_sample_step(df, tcol)
    t_span = t_max - t_min

    cum_at_end = cumulative_by_nocname(df, t_max, tcol)
    cum_scale = max(cum_at_end.values()) if cum_at_end else 1.0
    cum_scale = max(cum_scale, 1e-9)
    inst_at_end = snapshot_at(df, t_max, tcol, args.agg)
    inst_scale = max(inst_at_end.values()) if inst_at_end else 1.0
    inst_scale = max(inst_scale, 1e-9)

    known_nocs = sorted({str(x) for x in df["nocname"].unique()})
    mapped_nocs = [
        noc
        for noc in known_nocs
        if marker_xy(noc, positions, img_w, img_h, args.normalized) is not None
    ]
    unmapped_nocs = [noc for noc in known_nocs if noc not in mapped_nocs]
    if unmapped_nocs:
        pos_keys = sorted(
            str(k) for k in positions.keys() if not str(k).startswith("_")
        )
        raise ValueError(
            "Positions JSON is missing coordinates for trace NOCs used in this run: "
            f"{unmapped_nocs}. Available mapped keys: {pos_keys}"
        )

    fig, ax = plt.subplots(figsize=(10, 8))
    plt.subplots_adjust(bottom=0.18)
    im_bg = ax.imshow(img)
    ax.set_axis_off()
    extent = im_bg.get_extent()
    origin = im_bg.origin

    im_hi = ax.imshow(
        np.zeros((gh, gw, 4)),
        extent=extent,
        origin=origin,
        alpha=1.0,
        zorder=im_bg.get_zorder() + 1,
        interpolation="bicubic",
    )

    smooth_state: dict[str, object] = {
        "Z": None,
        "t_prev": None,
        "slider_raw": float(t_max),
        "display_raw": float(t_max),
        "_catchup_armed": False,
    }

    def snap_time(val: float) -> int:
        step = float(gdt)
        t_abs = int(round(float(val) / step)) * int(gdt)
        return int(min(t_max, max(t_min, t_abs)))

    def metrics_raw(t_abs: int) -> dict[str, float]:
        if args.time_metric == "cumulative":
            return cumulative_by_nocname(df, t_abs, tcol)
        return snapshot_at(df, t_abs, tcol, args.agg)

    def metrics_normalized(t_abs: int) -> dict[str, float]:
        r = metrics_raw(t_abs)
        if args.time_metric == "cumulative":
            return {k: float(v) / cum_scale for k, v in r.items()}
        return {k: float(v) / inst_scale for k, v in r.items()}

    def metrics_normalized_interp(tq: float) -> dict[str, float]:
        """Linear blend of normalized metrics between adjacent sample-grid times."""
        tq = max(float(t_min), min(float(t_max), float(tq)))
        g = float(gdt)
        t_lo = int(t_min + math.floor((tq - float(t_min)) / g) * g)
        t_hi = int(min(t_max, t_lo + int(gdt)))
        if t_hi <= t_lo:
            return {noc: float(metrics_normalized(t_lo).get(noc, 0.0)) for noc in known_nocs}
        lo = metrics_normalized(t_lo)
        hi = metrics_normalized(t_hi)
        frac = (tq - float(t_lo)) / float(t_hi - t_lo)
        return {
            noc: (1.0 - frac) * float(lo.get(noc, 0.0)) + frac * float(hi.get(noc, 0.0))
            for noc in known_nocs
        }

    activity_smooth = not args.no_activity_smooth
    use_catchup = activity_smooth and not args.no_activity_catchup
    catchup_interval_ms = max(8, int(1000.0 / max(1.0, float(args.activity_anim_fps))))
    sec_per_gdt = max(1e-4, float(args.activity_catchup_seconds_per_gdt))

    def paint_heatmap_from_display_time(display_r: float) -> None:
        t_snap = snap_time(display_r)
        if not activity_smooth:
            ema_noc = metrics_normalized(t_snap)
        else:
            ema_noc = metrics_normalized_interp(display_r)

        xs, ys, vals = [], [], []
        for noc in known_nocs:
            d = float(ema_noc.get(noc, 0.0))
            if d <= 0.0:
                continue
            xy = marker_xy(noc, positions, img_w, img_h, args.normalized)
            if xy is None:
                continue
            xp, yp = xy
            xs.append(xp)
            ys.append(yp)
            vals.append(d)

        Z_tgt = splat_gaussian_heatmap(xs, ys, vals, gw, gh, img_w, img_h, sigma)

        t_prev = smooth_state["t_prev"]
        if t_prev is not None and t_snap < int(t_prev):
            smooth_state["Z"] = None
        smooth_state["t_prev"] = t_snap

        a = max(0.0, min(1.0, float(args.z_ema)))
        if a <= 0.0 or smooth_state["Z"] is None:
            Z = Z_tgt
            smooth_state["Z"] = Z_tgt.copy()
        else:
            Z_prev = smooth_state["Z"]
            assert Z_prev is not None
            smooth_state["Z"] = (1.0 - a) * Z_prev + a * Z_tgt
            Z = smooth_state["Z"]

        rgba = z_to_rgba(
            Z,
            GREEN_TO_RED,
            tail_rel=float(args.heat_tail),
            alpha_max=float(args.heat_alpha),
            alpha_gamma=float(args.heat_alpha_gamma),
        )
        im_hi.set_data(rgba)

    catchup_timer = fig.canvas.new_timer(interval=catchup_interval_ms)

    def catchup_step() -> None:
        if not use_catchup:
            return
        sl = float(smooth_state["slider_raw"])
        dr = float(smooth_state["display_raw"])
        diff = sl - dr
        if abs(diff) <= 1e-3:
            catchup_timer.stop()
            smooth_state["_catchup_armed"] = False
            return
        dt = catchup_interval_ms / 1000.0
        step_mag = (float(gdt) / sec_per_gdt) * dt
        step = math.copysign(min(abs(diff), step_mag), diff)
        nxt = dr + step
        if abs(sl - nxt) < 1.0:
            smooth_state["display_raw"] = sl
        else:
            smooth_state["display_raw"] = nxt
        paint_heatmap_from_display_time(float(smooth_state["display_raw"]))
        fig.canvas.draw_idle()
        if abs(float(smooth_state["slider_raw"]) - float(smooth_state["display_raw"])) <= 1e-3:
            catchup_timer.stop()
            smooth_state["_catchup_armed"] = False

    catchup_timer.add_callback(catchup_step)

    def redraw(val: float) -> None:
        raw = max(float(t_min), min(float(t_max), float(val)))
        smooth_state["slider_raw"] = raw

        if not activity_smooth:
            smooth_state["display_raw"] = raw
            paint_heatmap_from_display_time(raw)
            fig.canvas.draw_idle()
            return

        if raw + 1e-6 < float(smooth_state["display_raw"]):
            smooth_state["display_raw"] = raw
            smooth_state["Z"] = None
            if use_catchup:
                catchup_timer.stop()
                smooth_state["_catchup_armed"] = False
        elif args.no_activity_catchup:
            smooth_state["display_raw"] = raw

        paint_heatmap_from_display_time(float(smooth_state["display_raw"]))
        fig.canvas.draw_idle()

        if use_catchup and abs(
            float(smooth_state["slider_raw"]) - float(smooth_state["display_raw"])
        ) > 1e-3:
            if not bool(smooth_state.get("_catchup_armed")):
                smooth_state["_catchup_armed"] = True
                catchup_timer.start()

    slider_ax = fig.add_axes((0.12, 0.05, 0.76, 0.03))
    slider = Slider(
        slider_ax,
        tcol,
        float(t_min),
        float(t_max),
        valinit=float(t_max),
        valstep=float(gdt),
        valfmt="%d",
    )
    slider.on_changed(redraw)
    redraw(float(t_max))

    if args.auto_scrub and t_max > t_min:
        fps = max(0.5, float(args.auto_scrub_fps))
        sec = max(0.1, float(args.auto_scrub_seconds))
        span = float(t_span)
        advance = span / (fps * sec)
        scrub_state: dict[str, float] = {"t": float(t_min)}

        def on_timer():
            scrub_state["t"] += advance
            if scrub_state["t"] >= float(t_max):
                scrub_state["t"] = float(t_min)
            tv = float(scrub_state["t"])
            slider.eventson = False
            try:
                slider.set_val(tv)
            finally:
                slider.eventson = True
            redraw(tv)

        interval_ms = max(1, int(1000.0 / fps))
        timer = fig.canvas.new_timer(interval=interval_ms)
        timer.add_callback(on_timer)
        timer.start()

    plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
