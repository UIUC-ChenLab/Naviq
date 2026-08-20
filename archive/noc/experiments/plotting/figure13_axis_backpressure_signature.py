#!/usr/bin/env python3
"""Generate Figure 13: AXI4-Stream backpressure bottleneck signature.

This script intentionally has no third-party dependencies.  It writes a
small-multiple SVG and a simple vector PDF using only the Python standard
library so the figure remains reproducible on minimal research/build machines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


OUT_DIR = Path(__file__).resolve().parents[1] / "plots" / "figure13_axis_backpressure_signature"
SVG_PATH = OUT_DIR / "figure13_axis_backpressure_signature.svg"
PDF_PATH = OUT_DIR / "figure13_axis_backpressure_signature.pdf"


@dataclass(frozen=True)
class Case:
    name: str
    pattern: str
    throughput_gbps: float
    axis_window_us: float
    dma_read_p99_cycles: float
    dma_read_avg_cycles: float
    valid_only_pct: float

    @property
    def label(self) -> str:
        return f"{self.name}\\n{self.pattern.replace('/', ':')}"


CASES = [
    Case("None", "1/1", 2.706, 59.723, 199, 117.64, 0.019),
    Case("Moderate", "64/1", 2.566, 62.985, 199, 117.64, 1.669),
    Case("Strong", "128/1", 1.376, 117.423, 198, 117.64, 3.312),
]

PANELS = [
    ("A", "Packet throughput (Gb/s)", "throughput_gbps", "{:.3f}", 3.0),
    ("B", "AXI4-Stream window (us)", "axis_window_us", "{:.1f}", 125.0),
    ("C", "DMA read P99 latency (cycles)", "dma_read_p99_cycles", "{:.0f}", 220.0),
]

BAR_COLOR = "#4C78A8"
BAR_EDGE = "#243B53"
GRID_COLOR = "#D8DEE9"
TEXT_COLOR = "#111827"
AXIS_COLOR = "#374151"
VALID_COLOR = "#6B7280"


def esc_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def esc_pdf(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def nice_ticks(max_y: float) -> list[float]:
    if max_y <= 3.0:
        return [0.0, 1.0, 2.0, 3.0]
    if max_y <= 125.0:
        return [0.0, 40.0, 80.0, 120.0]
    return [0.0, 50.0, 100.0, 150.0, 200.0]


def panel_values(metric: str) -> list[float]:
    return [float(getattr(case, metric)) for case in CASES]


def svg_text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 10,
    anchor: str = "middle",
    weight: str = "normal",
    color: str = TEXT_COLOR,
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" '
        f'font-family="Arial, Helvetica, sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{color}">{esc_xml(text)}</text>'
    )


def write_svg() -> None:
    width = 980
    height = 310
    margin_left = 70
    margin_right = 22
    panel_gap = 38
    top = 34
    bottom = 82
    plot_h = height - top - bottom
    panel_w = (width - margin_left - margin_right - 2 * panel_gap) / 3.0

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]

    for p_idx, (letter, ylabel, metric, fmt, max_y) in enumerate(PANELS):
        left = margin_left + p_idx * (panel_w + panel_gap)
        bottom_y = top + plot_h
        ticks = nice_ticks(max_y)
        values = panel_values(metric)

        out.append(svg_text(left - 38, top - 14, letter, size=12, anchor="start", weight="bold"))
        out.append(svg_text(left + panel_w / 2.0, top - 14, ylabel, size=10))

        for tick in ticks:
            y = bottom_y - (tick / max_y) * plot_h
            out.append(
                f'<line x1="{left:.2f}" y1="{y:.2f}" x2="{left + panel_w:.2f}" '
                f'y2="{y:.2f}" stroke="{GRID_COLOR}" stroke-width="0.8"/>'
            )
            tick_label = f"{tick:.0f}" if tick >= 10 else f"{tick:g}"
            out.append(svg_text(left - 8, y + 4, tick_label, size=8, anchor="end", color=AXIS_COLOR))

        out.append(
            f'<line x1="{left:.2f}" y1="{top:.2f}" x2="{left:.2f}" '
            f'y2="{bottom_y:.2f}" stroke="{AXIS_COLOR}" stroke-width="1"/>'
        )
        out.append(
            f'<line x1="{left:.2f}" y1="{bottom_y:.2f}" x2="{left + panel_w:.2f}" '
            f'y2="{bottom_y:.2f}" stroke="{AXIS_COLOR}" stroke-width="1"/>'
        )

        bar_w = panel_w * 0.18
        for i, case in enumerate(CASES):
            x_center = left + panel_w * (0.2 + i * 0.3)
            value = values[i]
            bar_h = (value / max_y) * plot_h
            x = x_center - bar_w / 2.0
            y = bottom_y - bar_h
            out.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{bar_h:.2f}" '
                f'fill="{BAR_COLOR}" stroke="{BAR_EDGE}" stroke-width="0.9"/>'
            )
            out.append(svg_text(x_center, y - 5, fmt.format(value), size=8, color=TEXT_COLOR))
            out.append(svg_text(x_center, bottom_y + 17, case.name, size=8))
            out.append(svg_text(x_center, bottom_y + 31, case.pattern.replace("/", ":"), size=8))
            if p_idx == 0:
                out.append(
                    svg_text(
                        x_center,
                        bottom_y + 48,
                        f"v-only {case.valid_only_pct:.3f}%",
                        size=7,
                        color=VALID_COLOR,
                    )
                )

        out.append(
            svg_text(
                left + panel_w / 2.0,
                height - 10,
                "Backpressure case / period:allow pattern",
                size=8,
                color=AXIS_COLOR,
            )
        )

    out.append("</svg>")
    SVG_PATH.write_text("\n".join(out) + "\n")


class PdfCanvas:
    def __init__(self, path: Path, width: float, height: float) -> None:
        self.path = path
        self.width = width
        self.height = height
        self.commands: list[str] = []

    def _rgb(self, color: str) -> tuple[float, float, float]:
        color = color.lstrip("#")
        return tuple(int(color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def _y(self, y_top: float) -> float:
        return self.height - y_top

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str, width: float = 1.0) -> None:
        r, g, b = self._rgb(color)
        self.commands.append(
            f"{r:.4f} {g:.4f} {b:.4f} RG {width:.2f} w "
            f"{x1:.2f} {self._y(y1):.2f} m {x2:.2f} {self._y(y2):.2f} l S"
        )

    def rect(self, x: float, y: float, w: float, h: float, fill: str, stroke: str, stroke_w: float = 0.7) -> None:
        fr, fg, fb = self._rgb(fill)
        sr, sg, sb = self._rgb(stroke)
        y_pdf = self._y(y + h)
        self.commands.append(
            f"{fr:.4f} {fg:.4f} {fb:.4f} rg {sr:.4f} {sg:.4f} {sb:.4f} RG "
            f"{stroke_w:.2f} w {x:.2f} {y_pdf:.2f} {w:.2f} {h:.2f} re B"
        )

    def text(
        self,
        x: float,
        y: float,
        text: str,
        *,
        size: float = 8.0,
        align: str = "center",
        bold: bool = False,
        color: str = TEXT_COLOR,
    ) -> None:
        r, g, b = self._rgb(color)
        font = "/F2" if bold else "/F1"
        approx_w = len(text) * size * 0.5
        if align == "center":
            x -= approx_w / 2.0
        elif align == "right":
            x -= approx_w
        self.commands.append(
            f"BT {r:.4f} {g:.4f} {b:.4f} rg {font} {size:.2f} Tf "
            f"{x:.2f} {self._y(y):.2f} Td ({esc_pdf(text)}) Tj ET"
        )

    def save(self) -> None:
        stream = "\n".join(self.commands).encode("latin-1")
        objects: list[bytes] = []
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.width:.2f} {self.height:.2f}] "
                f"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>"
            ).encode("latin-1")
        )
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")

        content = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for idx, obj in enumerate(objects, start=1):
            offsets.append(len(content))
            content.extend(f"{idx} 0 obj\n".encode("ascii"))
            content.extend(obj)
            content.extend(b"\nendobj\n")
        xref = len(content)
        content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        content.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        content.extend(
            (
                f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n"
            ).encode("ascii")
        )
        self.path.write_bytes(bytes(content))


def write_pdf() -> None:
    width = 7.1 * 72.0
    height = 2.35 * 72.0
    c = PdfCanvas(PDF_PATH, width, height)
    margin_left = 39.0
    margin_right = 10.0
    panel_gap = 20.0
    top = 21.0
    bottom = 45.0
    plot_h = height - top - bottom
    panel_w = (width - margin_left - margin_right - 2 * panel_gap) / 3.0

    for p_idx, (letter, ylabel, metric, fmt, max_y) in enumerate(PANELS):
        left = margin_left + p_idx * (panel_w + panel_gap)
        bottom_y = top + plot_h
        values = panel_values(metric)
        c.text(left - 27, top - 7, letter, size=8.5, align="left", bold=True)
        c.text(left + panel_w / 2.0, top - 7, ylabel, size=7.3)

        for tick in nice_ticks(max_y):
            y = bottom_y - (tick / max_y) * plot_h
            c.line(left, y, left + panel_w, y, GRID_COLOR, 0.45)
            tick_label = f"{tick:.0f}" if tick >= 10 else f"{tick:g}"
            c.text(left - 5, y + 2, tick_label, size=6.0, align="right", color=AXIS_COLOR)
        c.line(left, top, left, bottom_y, AXIS_COLOR, 0.7)
        c.line(left, bottom_y, left + panel_w, bottom_y, AXIS_COLOR, 0.7)

        bar_w = panel_w * 0.18
        for i, case in enumerate(CASES):
            x_center = left + panel_w * (0.2 + i * 0.3)
            value = values[i]
            bar_h = (value / max_y) * plot_h
            x = x_center - bar_w / 2.0
            y = bottom_y - bar_h
            c.rect(x, y, bar_w, bar_h, BAR_COLOR, BAR_EDGE, 0.45)
            c.text(x_center, y - 4, fmt.format(value), size=5.9)
            c.text(x_center, bottom_y + 11, case.name, size=5.8)
            c.text(x_center, bottom_y + 21, case.pattern.replace("/", ":"), size=5.8)
            if p_idx == 0:
                c.text(x_center, bottom_y + 32, f"{case.valid_only_pct:.3f}%", size=5.2, color=VALID_COLOR)
        c.text(left + panel_w / 2.0, height - 5, "Case / period:allow", size=5.8, color=AXIS_COLOR)

    c.save()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_svg()
    write_pdf()
    print(f"Wrote {SVG_PATH}")
    print(f"Wrote {PDF_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
