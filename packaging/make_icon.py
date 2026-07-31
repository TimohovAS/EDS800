"""Draw the application icon.

The editor has no artwork of its own, so the icon is generated from the brand
palette in :mod:`enc_editor.ui.theme`: a deep navy tile carrying the sine wave
a frequency converter produces, with the DC bus rail underneath.

Run it only when the icon is missing or the palette changed::

    python packaging/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ICON_PATH = Path(__file__).resolve().parent / "enc_editor.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BRAND = "#12314F"
ACCENT = "#3B82F6"
WAVE = "#FFFFFF"
RAIL = "#9FB6CE"

# Everything is drawn at this size and downsampled, so the curves stay smooth.
CANVAS = 1024


def _sine(draw: ImageDraw.ImageDraw) -> None:
    """One full period across the tile, as a band of constant thickness.

    ``ImageDraw.line`` has no antialiasing and its round joints fringe a curve
    this thick, so the stroke is built as a polygon between two offset copies
    of the curve instead; the downsample to icon sizes smooths the edges.
    """
    left, right = 0.16 * CANVAS, 0.84 * CANVAS
    middle = 0.44 * CANVAS
    amplitude = 0.20 * CANVAS
    half = 0.037 * CANVAS
    steps = 480

    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    for step in range(steps + 1):
        phase = 2 * math.pi * step / steps
        x = left + (right - left) * step / steps
        y = middle - amplitude * math.sin(phase)
        # Normal of the curve, so the band keeps its width through the bends.
        slope = -amplitude * math.cos(phase) * (2 * math.pi / (right - left))
        length = math.hypot(1.0, slope)
        nx, ny = -slope / length, 1.0 / length
        upper.append((x + nx * half, y + ny * half))
        lower.append((x - nx * half, y - ny * half))

    draw.polygon(upper + lower[::-1], fill=WAVE)
    # Round the two open ends.
    for end in (0, -1):
        x, y = (upper[end][0] + lower[end][0]) / 2, (upper[end][1] + lower[end][1]) / 2
        draw.ellipse((x - half, y - half, x + half, y + half), fill=WAVE)


def _rails(draw: ImageDraw.ImageDraw) -> None:
    """The DC bus: one bright rail, one muted."""
    height = int(0.05 * CANVAS)
    for offset, colour, inset in ((0.72, ACCENT, 0.16), (0.84, RAIL, 0.28)):
        top = offset * CANVAS
        draw.rounded_rectangle(
            (inset * CANVAS, top, (1 - inset) * CANVAS, top + height),
            radius=height / 2,
            fill=colour,
        )


def build() -> Path:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, CANVAS - 1, CANVAS - 1), radius=int(0.22 * CANVAS), fill=BRAND
    )
    _sine(draw)
    _rails(draw)

    # Resize explicitly so every frame gets the same high-quality filter.
    frames = [image.resize((size, size), Image.LANCZOS) for size in SIZES]
    frames[-1].save(ICON_PATH, sizes=[frame.size for frame in frames])
    return ICON_PATH


if __name__ == "__main__":
    print(f"wrote {build()}")
