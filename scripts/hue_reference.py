#!/usr/bin/env python3
"""Rebuild the coordinate and selective-hue swatches using the grading engine."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import photo_grade as grade


def build_reference(output: Path) -> None:
    canvas = Image.new("RGB", (1100, 690), "#f4f4f4")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 15), "Hue coordinates / sRGB preview", fill="black")
    angles = np.arange(360, dtype=np.float32)
    hsv = grade.hsv_to_rgb(angles, np.full_like(angles, 0.75), np.full_like(angles, 0.8))
    lch = np.stack((np.full_like(angles, 0.7), np.full_like(angles, 0.1), angles), axis=-1)
    oklch = grade.oklab_to_srgb(grade.oklch_to_oklab(lch))
    for y, label, rgb in [(70, "HSV: S=.75 V=.8", hsv), (170, "OKLCh: L=.7 C=.1", oklch)]:
        draw.text((20, y - 25), label, fill="black")
        strip = np.repeat(np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8)[None], 45, axis=0)
        canvas.paste(Image.fromarray(strip).resize((900, 45)), (180, y))
        for angle in range(0, 361, 60):
            draw.text((180 + int(angle * 2.5) - 10, y + 50), str(angle), fill="black")
    draw.text((20, 275), "HSL: each column activates only its own HSV range; S=.6 V=.7 source", fill="black")
    centers = np.array(list(grade.HUE_CENTERS.values()), dtype=np.float32)
    source = grade.hsv_to_rgb(centers, np.full_like(centers, .6), np.full_like(centers, .7))[None]
    for i, name in enumerate(grade.HUE_CENTERS):
        draw.text((185 + i * 110, 305), name, fill="black")
    rows = [("Source", None, 0), ("HSV shift -30", "legacy", -30),
            ("OKLCh shift -30", "perceptual", -30),
            ("HSV shift +30", "legacy", 30), ("OKLCh shift +30", "perceptual", 30)]
    for row, (label, mode, shift) in enumerate(rows):
        y = 335 + row * 65
        draw.text((20, y + 15), label, fill="black")
        for i, name in enumerate(grade.HUE_CENTERS):
            controls = {name: (shift, 0, 0)}
            rgb = source[:, i:i + 1]
            if mode == "legacy":
                rgb = grade.apply_selective_color(rgb, controls)
            elif mode == "perceptual":
                rgb = grade.apply_perceptual_selective_color(rgb, controls)
                rgb = grade.oklch_compress(rgb)
            color = tuple(np.rint(np.clip(rgb[0, 0], 0, 1) * 255).astype(int))
            draw.rectangle((180 + i * 110, y, 280 + i * 110, y + 45), fill=color)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, icc_profile=grade.srgb_profile_bytes())


if __name__ == "__main__":
    build_reference(Path(__file__).resolve().parents[1] / "references" / "hue-coordinates.png")
