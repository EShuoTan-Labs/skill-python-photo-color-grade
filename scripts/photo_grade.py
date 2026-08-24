#!/usr/bin/env python3
"""Deterministic, non-generative JPEG/PNG analysis and color grading."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageFilter, PngImagePlugin


SUPPORTED = {".jpg", ".jpeg", ".png"}
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
HUE_CENTERS = {
    "red": 0.0,
    "orange": 30.0,
    "yellow": 60.0,
    "green": 120.0,
    "aqua": 180.0,
    "blue": 240.0,
    "purple": 275.0,
    "magenta": 315.0,
}
VISUAL_INTENT_FIELDS = {
    "brightness_key",
    "contrast_structure",
    "light_geometry",
    "palette",
    "subject_separation",
    "texture",
}
BASIC_FIELDS = {
    "temperature",
    "tint",
    "exposure",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "contrast",
    "vibrance",
    "saturation",
}
LOCAL_ADJUSTMENT_FIELDS = BASIC_FIELDS | {"curve"}
SKILL_ROOT = Path(__file__).resolve().parent.parent


def check_for_update() -> str | None:
    """Return the updater message only when a newer skill version exists."""
    try:
        result = subprocess.run(
            [sys.executable, "update.py"],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout)
        if payload.get("NEED_UPDATE") is not True:
            return None
        message = payload.get("MESSAGE")
        return message.strip() if isinstance(message, str) and message.strip() else None
    except Exception:
        return None


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise ValueError(f"{label} is missing required keys: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{label} has unsupported keys: {sorted(unknown)}")


def require_number(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite number.")
    number = float(value)
    if number < low or number > high:
        raise ValueError(f"{label} must be between {low} and {high}.")
    return number


def validate_curve_value(value: Any, label: str) -> str | None:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array of [x, y] points.")
    if not value:
        return None
    if len(value) < 2:
        raise ValueError(f"{label} requires at least two points or an empty array.")
    points: list[tuple[float, float]] = []
    for index, point in enumerate(value):
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"{label}[{index}] must be [x, y].")
        x = require_number(point[0], f"{label}[{index}][0]", 0.0, 1.0)
        y = require_number(point[1], f"{label}[{index}][1]", 0.0, 1.0)
        points.append((x, y))
    if points[0][0] != 0.0 or points[-1][0] != 1.0:
        raise ValueError(f"{label} must begin at x=0 and end at x=1.")
    if any(current[0] <= previous[0] for previous, current in zip(points, points[1:])):
        raise ValueError(f"{label} x coordinates must be strictly increasing.")
    return ",".join(f"{x:g}:{y:g}" for x, y in points)


def validate_coordinate_pair(value: Any, label: str, low: float = 0.0, high: float = 1.0) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must contain two coordinates.")
    return [
        require_number(value[0], f"{label}[0]", low, high),
        require_number(value[1], f"{label}[1]", low, high),
    ]


def validate_local_adjustments(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array.")
    validated: list[dict[str, Any]] = []
    for index, item_value in enumerate(value):
        item_label = f"{label}[{index}]"
        item = require_object(item_value, item_label)
        require_exact_keys(item, {"mask", "adjustments"}, item_label)
        mask = require_object(item["mask"], f"{item_label}.mask")
        mask_type = mask.get("type")
        common = {"type", "opacity", "invert"}
        if mask_type == "luminance":
            require_exact_keys(mask, common | {"min", "max", "feather"}, f"{item_label}.mask")
            minimum = require_number(mask["min"], f"{item_label}.mask.min", 0.0, 1.0)
            maximum = require_number(mask["max"], f"{item_label}.mask.max", 0.0, 1.0)
            if maximum <= minimum:
                raise ValueError(f"{item_label}.mask.max must be greater than min.")
            require_number(mask["feather"], f"{item_label}.mask.feather", 0.0001, 1.0)
        elif mask_type == "color":
            require_exact_keys(mask, common | {"hue", "width", "min_saturation"}, f"{item_label}.mask")
            require_number(mask["hue"], f"{item_label}.mask.hue", 0.0, 360.0)
            require_number(mask["width"], f"{item_label}.mask.width", 1.0, 180.0)
            require_number(mask["min_saturation"], f"{item_label}.mask.min_saturation", 0.0, 1.0)
        elif mask_type == "linear":
            require_exact_keys(mask, common | {"start", "end"}, f"{item_label}.mask")
            start = validate_coordinate_pair(mask["start"], f"{item_label}.mask.start")
            end = validate_coordinate_pair(mask["end"], f"{item_label}.mask.end")
            if start == end:
                raise ValueError(f"{item_label}.mask start and end must differ.")
        elif mask_type == "radial":
            require_exact_keys(mask, common | {"center", "radius", "feather"}, f"{item_label}.mask")
            validate_coordinate_pair(mask["center"], f"{item_label}.mask.center")
            validate_coordinate_pair(mask["radius"], f"{item_label}.mask.radius", 0.0001, 1.0)
            require_number(mask["feather"], f"{item_label}.mask.feather", 0.0, 0.99)
        else:
            raise ValueError(f"{item_label}.mask.type must be luminance, color, linear, or radial.")
        require_number(mask["opacity"], f"{item_label}.mask.opacity", 0.0, 1.0)
        if not isinstance(mask["invert"], bool):
            raise ValueError(f"{item_label}.mask.invert must be true or false.")

        adjustments = require_object(item["adjustments"], f"{item_label}.adjustments")
        if not adjustments:
            raise ValueError(f"{item_label}.adjustments must not be empty.")
        unknown = set(adjustments) - LOCAL_ADJUSTMENT_FIELDS
        if unknown:
            raise ValueError(f"{item_label}.adjustments has unsupported keys: {sorted(unknown)}")
        normalized_adjustments = dict(adjustments)
        for name, raw_value in adjustments.items():
            if name == "curve":
                normalized_adjustments[name] = validate_curve_value(raw_value, f"{item_label}.adjustments.curve")
            elif name == "exposure":
                require_number(raw_value, f"{item_label}.adjustments.{name}", -4.0, 4.0)
            else:
                require_number(raw_value, f"{item_label}.adjustments.{name}", -1.0, 1.0)
        validated.append({"mask": mask, "adjustments": normalized_adjustments})
    return validated


def load_recipe(path: Path) -> tuple[argparse.Namespace, dict[str, Any]]:
    with path.resolve().open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    recipe = require_object(payload, "recipe")
    require_exact_keys(
        recipe,
        {"schema_version", "style", "visual_intent", "success_criteria", "parameters"},
        "recipe",
    )
    if isinstance(recipe["schema_version"], bool) or recipe["schema_version"] != 1:
        raise ValueError("recipe.schema_version must be 1.")

    style = require_object(recipe["style"], "recipe.style")
    require_exact_keys(style, {"id", "name", "intensity"}, "recipe.style")
    if not isinstance(style["id"], str) or not re.fullmatch(r"[A-Z]", style["id"]):
        raise ValueError("recipe.style.id must be one uppercase letter.")
    if not isinstance(style["name"], str) or not style["name"].strip():
        raise ValueError("recipe.style.name must be a non-empty string.")
    if isinstance(style["intensity"], bool) or style["intensity"] not in {1, 2, 3}:
        raise ValueError("recipe.style.intensity must be 1, 2, or 3.")

    intent = require_object(recipe["visual_intent"], "recipe.visual_intent")
    require_exact_keys(intent, VISUAL_INTENT_FIELDS, "recipe.visual_intent")
    for name, value in intent.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"recipe.visual_intent.{name} must be a non-empty string.")

    criteria = recipe["success_criteria"]
    if not isinstance(criteria, list) or not 3 <= len(criteria) <= 5:
        raise ValueError("recipe.success_criteria must contain three to five items.")
    if any(not isinstance(item, str) or not item.strip() for item in criteria):
        raise ValueError("Every recipe.success_criteria item must be a non-empty string.")

    parameters = require_object(recipe["parameters"], "recipe.parameters")
    require_exact_keys(
        parameters,
        {"basic", "curve", "hsl", "color_grading", "local_corrections", "local_adjustments", "detail", "output"},
        "recipe.parameters",
    )
    basic = require_object(parameters["basic"], "recipe.parameters.basic")
    require_exact_keys(basic, BASIC_FIELDS, "recipe.parameters.basic")
    normalized: dict[str, Any] = {}
    for name, value in basic.items():
        low, high = (-4.0, 4.0) if name == "exposure" else (-1.0, 1.0)
        normalized[name] = require_number(value, f"recipe.parameters.basic.{name}", low, high)
    normalized["curve"] = validate_curve_value(parameters["curve"], "recipe.parameters.curve")

    hsl = require_object(parameters["hsl"], "recipe.parameters.hsl")
    require_exact_keys(hsl, set(HUE_CENTERS), "recipe.parameters.hsl")
    for color in HUE_CENTERS:
        color_values = require_object(hsl[color], f"recipe.parameters.hsl.{color}")
        require_exact_keys(color_values, {"hue", "saturation", "luminance"}, f"recipe.parameters.hsl.{color}")
        normalized[f"{color}_hue"] = require_number(color_values["hue"], f"recipe.parameters.hsl.{color}.hue", -90.0, 90.0)
        normalized[f"{color}_sat"] = require_number(color_values["saturation"], f"recipe.parameters.hsl.{color}.saturation", -1.0, 1.5)
        normalized[f"{color}_lum"] = require_number(color_values["luminance"], f"recipe.parameters.hsl.{color}.luminance", -1.0, 1.0)

    grading = require_object(parameters["color_grading"], "recipe.parameters.color_grading")
    require_exact_keys(grading, {"shadows", "midtones", "highlights", "balance", "blending"}, "recipe.parameters.color_grading")
    for zone in ("shadows", "midtones", "highlights"):
        zone_values = require_object(grading[zone], f"recipe.parameters.color_grading.{zone}")
        require_exact_keys(zone_values, {"hue", "saturation"}, f"recipe.parameters.color_grading.{zone}")
        normalized[f"grade_{zone}_hue"] = require_number(zone_values["hue"], f"recipe.parameters.color_grading.{zone}.hue", 0.0, 360.0)
        normalized[f"grade_{zone}_sat"] = require_number(zone_values["saturation"], f"recipe.parameters.color_grading.{zone}.saturation", 0.0, 1.0)
    normalized["grading_balance"] = require_number(grading["balance"], "recipe.parameters.color_grading.balance", -1.0, 1.0)
    normalized["grading_blending"] = require_number(grading["blending"], "recipe.parameters.color_grading.blending", 0.0, 1.0)
    normalized["local_corrections"] = validate_local_adjustments(parameters["local_corrections"], "recipe.parameters.local_corrections")
    normalized["local_adjustments"] = validate_local_adjustments(parameters["local_adjustments"], "recipe.parameters.local_adjustments")

    detail = require_object(parameters["detail"], "recipe.parameters.detail")
    require_exact_keys(detail, {"denoise", "sharpen", "sharpen_radius"}, "recipe.parameters.detail")
    normalized["denoise"] = require_number(detail["denoise"], "recipe.parameters.detail.denoise", 0.0, 1.0)
    normalized["sharpen"] = require_number(detail["sharpen"], "recipe.parameters.detail.sharpen", 0.0, 2.0)
    normalized["sharpen_radius"] = require_number(detail["sharpen_radius"], "recipe.parameters.detail.sharpen_radius", 0.1, 5.0)

    output = require_object(parameters["output"], "recipe.parameters.output")
    require_exact_keys(output, {"jpeg_quality", "png_compress"}, "recipe.parameters.output")
    jpeg_quality = require_number(output["jpeg_quality"], "recipe.parameters.output.jpeg_quality", 1, 100)
    png_compress = require_number(output["png_compress"], "recipe.parameters.output.png_compress", 0, 9)
    if not jpeg_quality.is_integer() or not png_compress.is_integer():
        raise ValueError("Output quality and compression values must be integers.")
    normalized["jpeg_quality"] = int(jpeg_quality)
    normalized["png_compress"] = int(png_compress)
    return argparse.Namespace(**normalized), recipe


def require_supported(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Only JPEG and PNG are supported by this skill.")


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    rgb = np.maximum(rgb, 0.0)
    return np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def rgb_hsv_components(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mx = np.max(rgb, axis=2)
    mn = np.min(rgb, axis=2)
    chroma = mx - mn
    sat = np.divide(chroma, np.maximum(mx, 1e-6))
    hue = np.zeros_like(mx)
    valid = chroma > 1e-6
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mr = valid & (mx == r)
    mg = valid & (mx == g)
    mb = valid & (mx == b)
    hue[mr] = (60.0 * ((g[mr] - b[mr]) / chroma[mr])) % 360.0
    hue[mg] = 60.0 * ((b[mg] - r[mg]) / chroma[mg] + 2.0)
    hue[mb] = 60.0 * ((r[mb] - g[mb]) / chroma[mb] + 4.0)
    return hue, sat, mx


def hsv_to_rgb(hue: np.ndarray, saturation: np.ndarray, value: np.ndarray) -> np.ndarray:
    h = (hue % 360.0) / 60.0
    sector = np.floor(h).astype(np.int16) % 6
    fraction = h - np.floor(h)
    p = value * (1.0 - saturation)
    q = value * (1.0 - saturation * fraction)
    t = value * (1.0 - saturation * (1.0 - fraction))
    choices = (
        (value, t, p),
        (q, value, p),
        (p, value, t),
        (p, q, value),
        (t, p, value),
        (value, p, q),
    )
    result = np.empty((*hue.shape, 3), dtype=np.float32)
    for index, channels in enumerate(choices):
        mask = sector == index
        for channel, values in enumerate(channels):
            result[..., channel][mask] = values[mask]
    return result


def circular_hue_weight(hue: np.ndarray, center: float, width: float = 32.0) -> np.ndarray:
    distance = np.abs((hue - center + 180.0) % 360.0 - 180.0)
    return np.exp(-0.5 * (distance / width) ** 2)


def load_image(path: Path) -> tuple[np.ndarray, np.ndarray | None, dict[str, Any]]:
    require_supported(path)
    with Image.open(path) as source:
        source.load()
        metadata: dict[str, Any] = {
            "format": source.format,
            "exif": source.info.get("exif"),
            "icc_profile": source.info.get("icc_profile"),
            "dpi": source.info.get("dpi"),
            "png_text": {k: v for k, v in source.info.items() if isinstance(v, str)},
        }
        has_alpha = source.mode in {"RGBA", "LA"} or (
            source.mode == "P" and "transparency" in source.info
        )
        image = source.convert("RGBA") if has_alpha else source.convert("RGB")

        if metadata["icc_profile"]:
            try:
                in_profile = ImageCms.ImageCmsProfile(metadata["icc_profile"])
                out_profile = ImageCms.createProfile("sRGB")
                output_mode = "RGBA" if has_alpha else "RGB"
                image = ImageCms.profileToProfile(image, in_profile, out_profile, outputMode=output_mode)
                metadata["icc_profile"] = ImageCms.ImageCmsProfile(out_profile).tobytes()
            except Exception:
                # Keep the original profile if Pillow cannot safely transform it.
                pass

        pixels = np.asarray(image, dtype=np.float32) / 255.0
        alpha = pixels[..., 3:4].copy() if has_alpha else None
        rgb = pixels[..., :3].copy()
        metadata["size"] = [int(image.width), int(image.height)]
        metadata["has_alpha"] = has_alpha
        return rgb, alpha, metadata


def image_metrics(rgb: np.ndarray, alpha: np.ndarray | None = None) -> dict[str, Any]:
    visible = np.ones(rgb.shape[:2], dtype=bool) if alpha is None else alpha[..., 0] > 0.01
    values = rgb[visible]
    if values.size == 0:
        raise ValueError("Image has no visible pixels.")
    luma = values @ LUMA
    mx = np.max(values, axis=1)
    mn = np.min(values, axis=1)
    saturation = (mx - mn) / np.maximum(mx, 1e-6)
    q = np.percentile(luma, [1, 5, 25, 50, 75, 95, 99])
    channel_mean = np.mean(values, axis=0)
    neutral = (saturation < 0.12) & (luma > 0.2) & (luma < 0.95)
    neutral_mean = np.mean(values[neutral], axis=0) if np.any(neutral) else np.array([np.nan] * 3)
    height, width = rgb.shape[:2]
    luma_map = rgb @ LUMA
    visible_map = np.ones((height, width), dtype=bool) if alpha is None else alpha[..., 0] > 0.01
    labels = [
        ["top-left", "top", "top-right"],
        ["left", "center", "right"],
        ["bottom-left", "bottom", "bottom-right"],
    ]
    spatial_grid: list[list[float | None]] = []
    cells: list[tuple[float, int, int]] = []
    for row in range(3):
        row_values: list[float | None] = []
        y0, y1 = round(row * height / 3), round((row + 1) * height / 3)
        for column in range(3):
            x0, x1 = round(column * width / 3), round((column + 1) * width / 3)
            cell_visible = visible_map[y0:y1, x0:x1]
            cell_luma = luma_map[y0:y1, x0:x1][cell_visible]
            if cell_luma.size:
                mean = round(float(np.mean(cell_luma)), 5)
                cells.append((mean, row, column))
                row_values.append(mean)
            else:
                row_values.append(None)
        spatial_grid.append(row_values)
    brightest = max(cells)
    darkest = min(cells)
    return {
        "luma_mean": round(float(np.mean(luma)), 5),
        "luma_percentiles": {str(k): round(float(v), 5) for k, v in zip([1, 5, 25, 50, 75, 95, 99], q)},
        "shadow_clip_ratio": round(float(np.mean(luma <= 0.01)), 6),
        "highlight_clip_ratio": round(float(np.mean(luma >= 0.99)), 6),
        "any_channel_low_clip_ratio": round(float(np.mean(np.min(values, axis=1) <= 0.002)), 6),
        "any_channel_high_clip_ratio": round(float(np.mean(np.max(values, axis=1) >= 0.998)), 6),
        "dynamic_range_p95_p05": round(float(q[5] - q[1]), 5),
        "saturation_mean": round(float(np.mean(saturation)), 5),
        "saturation_p95": round(float(np.percentile(saturation, 95)), 5),
        "channel_mean_rgb": [round(float(v), 5) for v in channel_mean],
        "neutral_candidate_ratio": round(float(np.mean(neutral)), 5),
        "neutral_candidate_mean_rgb": [None if np.isnan(v) else round(float(v), 5) for v in neutral_mean],
        "spatial_luma_grid_3x3": spatial_grid,
        "brightest_cell": {
            "label": labels[brightest[1]][brightest[2]],
            "row": brightest[1],
            "column": brightest[2],
            "luma_mean": brightest[0],
        },
        "darkest_cell": {
            "label": labels[darkest[1]][darkest[2]],
            "row": darkest[1],
            "column": darkest[2],
            "luma_mean": darkest[0],
        },
    }


def analyze(path: Path) -> dict[str, Any]:
    rgb, alpha, meta = load_image(path)
    return {
        "file": str(path),
        "format": meta["format"],
        "width": meta["size"][0],
        "height": meta["size"][1],
        "has_alpha": meta["has_alpha"],
        "metrics": image_metrics(rgb, alpha),
    }


def apply_white_balance(linear: np.ndarray, temperature: float, tint: float) -> np.ndarray:
    # Multiplicative adaptation in linear light; unlike channel offsets it preserves gradation.
    temp = float(np.clip(temperature, -1.0, 1.0))
    tint = float(np.clip(tint, -1.0, 1.0))
    gains = np.array(
        [2.0 ** (0.45 * temp + 0.12 * tint), 2.0 ** (-0.24 * tint), 2.0 ** (-0.45 * temp + 0.12 * tint)],
        dtype=np.float32,
    )
    balanced = linear * gains
    before_y = np.mean(linear @ LUMA)
    after_y = np.mean(balanced @ LUMA)
    if after_y > 1e-7:
        balanced *= before_y / after_y
    return balanced


def scale_to_luma(rgb: np.ndarray, target: np.ndarray) -> np.ndarray:
    current = rgb @ LUMA
    ratio = np.divide(target, np.maximum(current, 1e-5))
    ratio = np.clip(ratio, 0.05, 20.0)
    return rgb * ratio[..., None]


def apply_tone(
    rgb: np.ndarray,
    contrast: float,
    highlights: float,
    shadows: float,
    whites: float,
    blacks: float,
) -> np.ndarray:
    luma = np.clip(rgb @ LUMA, 0.0, 1.0)
    shadow_mask = (1.0 - smoothstep(0.06, 0.62, luma)) ** 1.15
    highlight_mask = smoothstep(0.38, 0.96, luma) ** 1.15
    black_mask = (1.0 - smoothstep(0.0, 0.28, luma)) ** 1.4
    white_mask = smoothstep(0.72, 1.0, luma) ** 1.4
    stops = 0.8 * shadows * shadow_mask + 0.8 * highlights * highlight_mask
    stops += 0.42 * blacks * black_mask + 0.42 * whites * white_mask
    target = np.clip(luma * np.exp2(stops), 0.0, 1.0)

    c = float(np.clip(contrast, -1.0, 1.0))
    if c >= 0:
        strength = 1.0 + 2.2 * c
        curved = 0.5 + np.tanh((target - 0.5) * strength) / (2.0 * math.tanh(0.5 * strength))
        target = (1.0 - c) * target + c * curved
    else:
        target = (1.0 + c) * target + (-c) * (0.5 + 0.55 * (target - 0.5))
    return scale_to_luma(rgb, np.clip(target, 0.0, 1.0))


def apply_color(rgb: np.ndarray, vibrance: float, saturation: float) -> np.ndarray:
    luma = (rgb @ LUMA)[..., None]
    hue, sat, _ = rgb_hsv_components(np.clip(rgb, 0.0, 1.0))
    skin = circular_hue_weight(hue, 28.0, 22.0) * smoothstep(0.08, 0.35, sat) * (1.0 - smoothstep(0.72, 1.0, sat))
    vib = float(np.clip(vibrance, -1.0, 1.0))
    if vib >= 0:
        factor = 1.0 + vib * (1.0 - sat) * (1.0 - 0.65 * skin)
    else:
        factor = 1.0 + vib * (0.45 + 0.55 * sat)
    result = luma + (rgb - luma) * factor[..., None]
    saturation_factor = 1.0 + float(np.clip(saturation, -1.0, 1.0))
    return luma + (result - luma) * saturation_factor


def parse_curve(specification: str | None) -> tuple[np.ndarray, np.ndarray] | None:
    if not specification:
        return None
    points: list[tuple[float, float]] = []
    for pair in specification.split(","):
        try:
            x_text, y_text = pair.split(":", 1)
            points.append((float(x_text), float(y_text)))
        except ValueError as exc:
            raise ValueError("Curve must use x:y pairs separated by commas.") from exc
    if len(points) < 2:
        raise ValueError("Curve requires at least two points.")
    x = np.array([point[0] for point in points], dtype=np.float32)
    y = np.array([point[1] for point in points], dtype=np.float32)
    if np.any(x < 0.0) or np.any(x > 1.0) or np.any(y < 0.0) or np.any(y > 1.0):
        raise ValueError("Curve coordinates must be between 0 and 1.")
    if np.any(np.diff(x) <= 0.0):
        raise ValueError("Curve x coordinates must be strictly increasing.")
    if x[0] != 0.0 or x[-1] != 1.0:
        raise ValueError("Curve must start at x=0 and end at x=1.")
    return x, y


def apply_curve(rgb: np.ndarray, specification: str | None) -> np.ndarray:
    points = parse_curve(specification)
    if points is None:
        return rgb
    x, y = points
    luma = np.clip(rgb @ LUMA, 0.0, 1.0)
    target = np.interp(luma, x, y).astype(np.float32)
    return scale_to_luma(rgb, target)


def apply_selective_color(
    rgb: np.ndarray,
    adjustments: dict[str, tuple[float, float, float]],
) -> np.ndarray:
    base = np.clip(rgb, 0.0, 1.0)
    hue, sat, value = rgb_hsv_components(base)
    presence = smoothstep(0.025, 0.2, sat)
    hue_shift = np.zeros_like(hue)
    saturation_delta = np.zeros_like(sat)
    luminance_stops = np.zeros_like(sat)
    for name, (hue_adjust, sat_adjust, lum_adjust) in adjustments.items():
        if abs(hue_adjust) < 1e-9 and abs(sat_adjust) < 1e-9 and abs(lum_adjust) < 1e-9:
            continue
        weight = circular_hue_weight(hue, HUE_CENTERS[name]) * presence
        hue_shift += float(np.clip(hue_adjust, -90.0, 90.0)) * weight
        saturation_delta += float(np.clip(sat_adjust, -1.0, 1.0)) * weight
        luminance_stops += 0.45 * float(np.clip(lum_adjust, -1.0, 1.0)) * weight
    shifted = hsv_to_rgb(
        hue + np.clip(hue_shift, -90.0, 90.0),
        np.clip(sat * (1.0 + np.clip(saturation_delta, -1.0, 1.5)), 0.0, 1.0),
        value,
    )
    target = np.clip((shifted @ LUMA) * np.exp2(luminance_stops), 0.0, 1.0)
    return scale_to_luma(shifted, target)


def hue_chroma(hue: float) -> np.ndarray:
    h = np.array([[hue]], dtype=np.float32)
    color = hsv_to_rgb(h, np.ones_like(h), np.ones_like(h))[0, 0]
    return color - float(color @ LUMA)


def apply_color_grading(
    rgb: np.ndarray,
    shadows_hue: float,
    shadows_sat: float,
    midtones_hue: float,
    midtones_sat: float,
    highlights_hue: float,
    highlights_sat: float,
    balance: float,
    blending: float,
) -> np.ndarray:
    if max(abs(shadows_sat), abs(midtones_sat), abs(highlights_sat)) < 1e-9:
        return rgb
    luma = np.clip(rgb @ LUMA, 0.0, 1.0)
    balance = float(np.clip(balance, -1.0, 1.0))
    blending = float(np.clip(blending, 0.0, 1.0))
    pivot = 0.5 - 0.16 * balance
    width = 0.16 + 0.18 * blending
    shadow_weight = 1.0 - smoothstep(pivot - width, pivot + width, luma)
    highlight_weight = smoothstep(pivot - width, pivot + width, luma)
    midtone_width = 0.16 + 0.18 * blending
    midtone_weight = np.exp(-0.5 * ((luma - pivot) / midtone_width) ** 2)
    result = rgb.copy()
    zones = (
        (shadows_hue, shadows_sat, shadow_weight),
        (midtones_hue, midtones_sat, midtone_weight),
        (highlights_hue, highlights_sat, highlight_weight),
    )
    for hue_value, saturation_value, weight in zones:
        strength = 0.35 * float(np.clip(saturation_value, 0.0, 1.0))
        if strength > 0.0:
            result += hue_chroma(hue_value)[None, None, :] * (strength * weight)[..., None]
    return scale_to_luma(result, luma)


def apply_tonal_adjustments(rgb: np.ndarray, parameters: Any) -> np.ndarray:
    linear = srgb_to_linear(np.clip(rgb, 0.0, 1.0))
    linear = apply_white_balance(linear, parameters.temperature, parameters.tint)
    linear *= 2.0 ** float(np.clip(parameters.exposure, -4.0, 4.0))
    result = linear_to_srgb(linear)
    result = apply_tone(
        result,
        parameters.contrast,
        parameters.highlights,
        parameters.shadows,
        parameters.whites,
        parameters.blacks,
    )
    return apply_curve(result, getattr(parameters, "curve", None))


def apply_adjustment_bundle(rgb: np.ndarray, parameters: Any) -> np.ndarray:
    result = apply_tonal_adjustments(rgb, parameters)
    return apply_color(result, parameters.vibrance, parameters.saturation)


def local_parameters(adjustments: dict[str, Any]) -> SimpleNamespace:
    allowed = {
        "exposure",
        "temperature",
        "tint",
        "contrast",
        "highlights",
        "shadows",
        "whites",
        "blacks",
        "saturation",
        "vibrance",
        "curve",
    }
    unknown = set(adjustments) - allowed
    if unknown:
        raise ValueError(f"Unsupported local adjustment keys: {sorted(unknown)}")
    values = {name: 0.0 for name in allowed if name != "curve"}
    values["curve"] = None
    values.update(adjustments)
    return SimpleNamespace(**values)


def build_local_mask(rgb: np.ndarray, specification: dict[str, Any]) -> np.ndarray:
    height, width = rgb.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    x = xx.astype(np.float32) / max(width - 1, 1)
    y = yy.astype(np.float32) / max(height - 1, 1)
    mask_type = specification.get("type")
    if mask_type == "luminance":
        luma = np.clip(rgb @ LUMA, 0.0, 1.0)
        low = float(specification.get("min", 0.0))
        high = float(specification.get("max", 1.0))
        feather = max(float(specification.get("feather", 0.08)), 1e-4)
        mask = smoothstep(low - feather, low + feather, luma)
        mask *= 1.0 - smoothstep(high - feather, high + feather, luma)
    elif mask_type == "color":
        hue, sat, _ = rgb_hsv_components(np.clip(rgb, 0.0, 1.0))
        center = float(specification.get("hue", 0.0))
        width_degrees = max(float(specification.get("width", 30.0)), 1.0)
        minimum_sat = float(specification.get("min_saturation", 0.05))
        mask = circular_hue_weight(hue, center, width_degrees)
        mask *= smoothstep(minimum_sat, min(minimum_sat + 0.2, 1.0), sat)
    elif mask_type == "linear":
        start = specification.get("start", [0.0, 0.0])
        end = specification.get("end", [1.0, 1.0])
        sx, sy = float(start[0]), float(start[1])
        ex, ey = float(end[0]), float(end[1])
        dx, dy = ex - sx, ey - sy
        length_squared = dx * dx + dy * dy
        if length_squared < 1e-8:
            raise ValueError("Linear mask start and end must differ.")
        projection = ((x - sx) * dx + (y - sy) * dy) / length_squared
        mask = smoothstep(0.0, 1.0, projection)
    elif mask_type == "radial":
        center = specification.get("center", [0.5, 0.5])
        radius = specification.get("radius", [0.35, 0.35])
        cx, cy = float(center[0]), float(center[1])
        rx, ry = max(float(radius[0]), 1e-4), max(float(radius[1]), 1e-4)
        distance = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
        feather = float(np.clip(specification.get("feather", 0.35), 0.0, 0.99))
        mask = 1.0 - smoothstep(1.0 - feather, 1.0, distance)
    else:
        raise ValueError("Local mask type must be luminance, color, linear, or radial.")
    if specification.get("invert", False):
        mask = 1.0 - mask
    opacity = float(np.clip(specification.get("opacity", 1.0), 0.0, 1.0))
    return np.clip(mask * opacity, 0.0, 1.0)


def apply_local_adjustments(rgb: np.ndarray, payload: Any) -> np.ndarray:
    if not payload:
        return rgb
    masks = payload.get("masks") if isinstance(payload, dict) else payload
    if not isinstance(masks, list):
        raise ValueError("Local adjustments must be a list or contain a masks list.")
    result = rgb
    for item in masks:
        if not isinstance(item, dict) or not isinstance(item.get("mask"), dict):
            raise ValueError("Each local adjustment requires mask and adjustments objects.")
        adjustments = item.get("adjustments", {})
        if not isinstance(adjustments, dict):
            raise ValueError("Local adjustments must be an object.")
        mask = build_local_mask(result, item["mask"])
        variant = apply_adjustment_bundle(result, local_parameters(adjustments))
        result = result * (1.0 - mask[..., None]) + variant * mask[..., None]
    return result


def pil_filter_array(rgb: np.ndarray, image_filter: ImageFilter.Filter) -> np.ndarray:
    image = Image.fromarray(np.rint(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8), "RGB")
    return np.asarray(image.filter(image_filter), dtype=np.float32) / 255.0


def apply_denoise(rgb: np.ndarray, denoise: float) -> np.ndarray:
    result = np.clip(rgb, 0.0, 1.0)
    denoise = float(np.clip(denoise, 0.0, 1.0))
    if denoise > 0.0:
        median = pil_filter_array(result, ImageFilter.MedianFilter(size=3))
        result = result * (1.0 - denoise) + median * denoise
    return np.clip(result, 0.0, 1.0)


def apply_sharpen(rgb: np.ndarray, sharpen: float, radius: float) -> np.ndarray:
    result = np.clip(rgb, 0.0, 1.0)
    sharpen = float(np.clip(sharpen, 0.0, 2.0))
    if sharpen > 0.0:
        blurred = pil_filter_array(result, ImageFilter.GaussianBlur(radius=float(np.clip(radius, 0.1, 5.0))))
        result = result + sharpen * (result - blurred)
    return np.clip(result, 0.0, 1.0)


def grade_pixels(rgb: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    result = apply_denoise(rgb, args.denoise)
    result = apply_tonal_adjustments(result, args)
    result = apply_local_adjustments(result, args.local_corrections)
    result = apply_color(result, args.vibrance, args.saturation)
    adjustments = {
        name: (
            getattr(args, f"{name}_hue"),
            getattr(args, f"{name}_sat"),
            getattr(args, f"{name}_lum"),
        )
        for name in HUE_CENTERS
    }
    result = apply_selective_color(result, adjustments)
    result = apply_color_grading(
        result,
        args.grade_shadows_hue,
        args.grade_shadows_sat,
        args.grade_midtones_hue,
        args.grade_midtones_sat,
        args.grade_highlights_hue,
        args.grade_highlights_sat,
        args.grading_balance,
        args.grading_blending,
    )
    result = apply_local_adjustments(result, args.local_adjustments)
    result = apply_sharpen(result, args.sharpen, args.sharpen_radius)
    return np.clip(result, 0.0, 1.0)


def save_image(
    path: Path,
    rgb: np.ndarray,
    alpha: np.ndarray | None,
    meta: dict[str, Any],
    jpeg_quality: int = 95,
    png_compress: int = 6,
) -> None:
    require_supported(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb8 = np.rint(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)
    if alpha is not None and path.suffix.lower() == ".png":
        alpha8 = np.rint(np.clip(alpha, 0.0, 1.0) * 255.0).astype(np.uint8)
        image = Image.fromarray(np.concatenate([rgb8, alpha8], axis=2), "RGBA")
    else:
        image = Image.fromarray(rgb8, "RGB")

    common: dict[str, Any] = {}
    if meta.get("icc_profile"):
        common["icc_profile"] = meta["icc_profile"]
    if meta.get("exif"):
        common["exif"] = meta["exif"]
    if meta.get("dpi"):
        common["dpi"] = meta["dpi"]

    if path.suffix.lower() in {".jpg", ".jpeg"}:
        if alpha is not None:
            raise ValueError("Cannot preserve alpha in JPEG; use a PNG output path.")
        image.save(
            path,
            format="JPEG",
            quality=int(np.clip(jpeg_quality, 1, 100)),
            subsampling=0,
            optimize=True,
            **common,
        )
    else:
        pnginfo = PngImagePlugin.PngInfo()
        for key, value in meta.get("png_text", {}).items():
            pnginfo.add_text(key, value)
        image.save(
            path,
            format="PNG",
            compress_level=int(np.clip(png_compress, 0, 9)),
            pnginfo=pnginfo,
            **common,
        )


def run_grade(args: argparse.Namespace, settings: argparse.Namespace, recipe: dict[str, Any]) -> dict[str, Any]:
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    require_supported(source)
    require_supported(output)
    if source == output:
        raise ValueError("Refusing to overwrite the original image.")
    rgb, alpha, meta = load_image(source)
    before = image_metrics(rgb, alpha)
    graded = grade_pixels(rgb, settings)
    save_image(output, graded, alpha, meta, settings.jpeg_quality, settings.png_compress)
    check_rgb, check_alpha, check_meta = load_image(output)
    if meta["size"] != check_meta["size"]:
        output.unlink(missing_ok=True)
        raise RuntimeError("Output dimensions changed; output was removed.")
    if bool(alpha is not None) != bool(check_alpha is not None):
        output.unlink(missing_ok=True)
        raise RuntimeError("Output alpha presence changed; output was removed.")
    if alpha is not None and not np.array_equal(
        np.rint(alpha * 255.0).astype(np.uint8),
        np.rint(check_alpha * 255.0).astype(np.uint8),
    ):
        output.unlink(missing_ok=True)
        raise RuntimeError("Output alpha values changed; output was removed.")
    result = {
        "input": str(source),
        "output": str(output),
        "width": meta["size"][0],
        "height": meta["size"][1],
        "style": recipe["style"],
        "recipe_validated": True,
        "before": before,
        "after": image_metrics(check_rgb, check_alpha),
    }
    if args.show_parameters:
        result["parameters"] = recipe["parameters"]
    return result


def compare_images(original: Path, graded: Path) -> dict[str, Any]:
    first = analyze(original)
    second = analyze(graded)
    same_geometry = (first["width"], first["height"]) == (second["width"], second["height"])
    same_alpha = first["has_alpha"] == second["has_alpha"]
    _, first_alpha, _ = load_image(original)
    _, second_alpha, _ = load_image(graded)
    same_alpha_values = same_alpha and (
        first_alpha is None
        or np.array_equal(
            np.rint(first_alpha * 255.0).astype(np.uint8),
            np.rint(second_alpha * 255.0).astype(np.uint8),
        )
    )
    return {
        "original": first,
        "graded": second,
        "checks": {
            "same_geometry": same_geometry,
            "same_alpha_presence": same_alpha,
            "same_alpha_values": same_alpha_values,
            "passed": same_geometry and same_alpha_values,
        },
    }


def add_grade_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument(
        "--recipe",
        required=True,
        help="Required structured JSON recipe decided before rendering",
    )
    parser.add_argument(
        "--show-parameters",
        action="store_true",
        help="Include final recipe parameters in the report only when explicitly requested",
    )
    parser.add_argument("--pretty", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    analyze_parser = sub.add_parser("analyze", help="Print deterministic image metrics")
    analyze_parser.add_argument("input")
    analyze_parser.add_argument("--pretty", action="store_true")
    grade_parser = sub.add_parser("grade", help="Apply one non-generative color grade")
    add_grade_arguments(grade_parser)
    compare_parser = sub.add_parser("compare", help="Compare source and output metrics/geometry")
    compare_parser.add_argument("original")
    compare_parser.add_argument("graded")
    compare_parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    update_future: Future[str | None] | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="skill-update") as executor:
        if args.command == "grade":
            update_future = executor.submit(check_for_update)
        try:
            if args.command == "analyze":
                report = analyze(Path(args.input).resolve())
            elif args.command == "grade":
                settings, recipe = load_recipe(Path(args.recipe))
                report = run_grade(args, settings, recipe)
            else:
                report = compare_images(Path(args.original).resolve(), Path(args.graded).resolve())
            if update_future is not None:
                update_message = update_future.result()
                if update_message is not None:
                    report["MESSAGE"] = update_message
            print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
            return 0
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
