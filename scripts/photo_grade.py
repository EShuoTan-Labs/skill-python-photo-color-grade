#!/usr/bin/env python3
"""Deterministic, non-generative JPEG/PNG analysis and color grading."""

from __future__ import annotations

import argparse
import importlib.metadata
import io
import json
import math
import platform
import re
import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageFilter, PngImagePlugin

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from png16 import chunk_types, inspect_ihdr, read_png16, write_png16


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
BASIC_FIELD_ORDER = (
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
)
BASIC_FIELDS = set(BASIC_FIELD_ORDER)
CHANNEL_NAMES = ("red", "green", "blue")
PRESENCE_FIELDS = {"dehaze", "clarity", "texture"}
COLOR_RENDERING_MODES = {"legacy", "perceptual"}
GAMUT_MAPPING_MODES = {"clip", "oklch_compress"}
PNG_DITHER_MODES = {"none", "tpdf"}
LOCAL_PRESENCE_FIELDS = {"clarity", "texture"}
LOCAL_ADJUSTMENT_FIELDS = BASIC_FIELDS | {"curve", "channel_curves"} | LOCAL_PRESENCE_FIELDS
COMPOSITE_MASK_OPERATIONS = {"and", "or", "subtract"}
MAX_MASK_DEPTH = 6
MAX_MASK_LEAVES = 32
SKILL_ROOT = Path(__file__).resolve().parent.parent
SRGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
XYZ_TO_SRGB = np.linalg.inv(SRGB_TO_XYZ)
LINEAR_SRGB_TO_LMS = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float64,
)
XYZ_TO_LMS = LINEAR_SRGB_TO_LMS @ XYZ_TO_SRGB
LMS_CUBERT_TO_OKLAB = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float64,
)
OKLAB_TO_LMS_CUBERT = np.linalg.inv(LMS_CUBERT_TO_OKLAB)
LMS_TO_XYZ = np.linalg.inv(XYZ_TO_LMS)


def check_for_update() -> str | None:
    """Return the updater message only when a newer skill version exists."""
    try:
        result = subprocess.run(
            [sys.executable, "update.py"],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            timeout=12,
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


def reject_unknown_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
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


def validate_channel_curves(
    value: Any,
    label: str,
) -> tuple[dict[str, str | None], dict[str, list[Any]]]:
    curves = require_object(value, label)
    reject_unknown_keys(curves, set(CHANNEL_NAMES), label)
    normalized: dict[str, str | None] = {}
    expanded: dict[str, list[Any]] = {}
    for channel in CHANNEL_NAMES:
        curve = curves.get(channel, [])
        normalized[channel] = validate_curve_value(curve, f"{label}.{channel}")
        expanded[channel] = curve
    return normalized, expanded


def validate_coordinate_pair(value: Any, label: str, low: float = 0.0, high: float = 1.0) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must contain two coordinates.")
    return [
        require_number(value[0], f"{label}[0]", low, high),
        require_number(value[1], f"{label}[1]", low, high),
    ]


def validate_mask_specification(value: Any, label: str, depth: int = 1) -> int:
    """Validate one mask tree and return its leaf count."""
    if depth > MAX_MASK_DEPTH:
        raise ValueError(f"{label} exceeds the maximum mask depth of {MAX_MASK_DEPTH}.")
    mask = require_object(value, label)
    mask_type = mask.get("type")
    common = {"type", "opacity", "invert"}
    if mask_type == "luminance":
        require_exact_keys(mask, common | {"min", "max", "feather"}, label)
        minimum = require_number(mask["min"], f"{label}.min", 0.0, 1.0)
        maximum = require_number(mask["max"], f"{label}.max", 0.0, 1.0)
        if maximum <= minimum:
            raise ValueError(f"{label}.max must be greater than min.")
        require_number(mask["feather"], f"{label}.feather", 0.0001, 1.0)
        leaf_count = 1
    elif mask_type == "color":
        require_exact_keys(mask, common | {"hue", "width", "min_saturation"}, label)
        require_number(mask["hue"], f"{label}.hue", 0.0, 360.0)
        require_number(mask["width"], f"{label}.width", 1.0, 180.0)
        require_number(mask["min_saturation"], f"{label}.min_saturation", 0.0, 1.0)
        leaf_count = 1
    elif mask_type == "linear":
        require_exact_keys(mask, common | {"start", "end"}, label)
        start = validate_coordinate_pair(mask["start"], f"{label}.start")
        end = validate_coordinate_pair(mask["end"], f"{label}.end")
        if start == end:
            raise ValueError(f"{label} start and end must differ.")
        leaf_count = 1
    elif mask_type == "radial":
        require_exact_keys(mask, common | {"center", "radius", "feather"}, label)
        validate_coordinate_pair(mask["center"], f"{label}.center")
        validate_coordinate_pair(mask["radius"], f"{label}.radius", 0.0001, 1.0)
        require_number(mask["feather"], f"{label}.feather", 0.0, 0.99)
        leaf_count = 1
    elif mask_type == "composite":
        require_exact_keys(mask, common | {"operation", "inputs"}, label)
        operation = mask["operation"]
        if not isinstance(operation, str) or operation not in COMPOSITE_MASK_OPERATIONS:
            raise ValueError(f"{label}.operation must be one of: and, or, subtract.")
        inputs = mask["inputs"]
        if not isinstance(inputs, list):
            raise ValueError(f"{label}.inputs must be an array.")
        expected = 2 if operation == "subtract" else None
        if expected is not None and len(inputs) != expected:
            raise ValueError(f"{label}.inputs must contain exactly two masks for subtract.")
        if operation in {"and", "or"} and not 2 <= len(inputs) <= 8:
            raise ValueError(f"{label}.inputs must contain between 2 and 8 masks for {operation}.")
        leaf_count = 0
        for index, child in enumerate(inputs):
            leaf_count += validate_mask_specification(child, f"{label}.inputs[{index}]", depth + 1)
            if leaf_count > MAX_MASK_LEAVES:
                raise ValueError(f"{label} exceeds the maximum of {MAX_MASK_LEAVES} leaf masks.")
    else:
        raise ValueError(f"{label}.type must be luminance, color, linear, radial, or composite.")

    require_number(mask["opacity"], f"{label}.opacity", 0.0, 1.0)
    if not isinstance(mask["invert"], bool):
        raise ValueError(f"{label}.invert must be true or false.")
    return leaf_count


def validate_local_adjustments(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array.")
    validated: list[dict[str, Any]] = []
    for index, item_value in enumerate(value):
        item_label = f"{label}[{index}]"
        item = require_object(item_value, item_label)
        require_exact_keys(item, {"mask", "adjustments"}, item_label)
        mask = require_object(item["mask"], f"{item_label}.mask")
        validate_mask_specification(mask, f"{item_label}.mask")

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
            elif name == "channel_curves":
                normalized_adjustments[name], _ = validate_channel_curves(
                    raw_value,
                    f"{item_label}.adjustments.channel_curves",
                )
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

    parameter_fields = {
        "basic",
        "curve",
        "channel_curves",
        "presence",
        "color_management",
        "hsl",
        "color_grading",
        "local_corrections",
        "local_adjustments",
        "detail",
        "output",
    }
    parameters = require_object(recipe["parameters"], "recipe.parameters")
    reject_unknown_keys(parameters, parameter_fields, "recipe.parameters")
    basic = require_object(parameters.get("basic", {}), "recipe.parameters.basic")
    reject_unknown_keys(basic, BASIC_FIELDS, "recipe.parameters.basic")
    normalized: dict[str, Any] = {}
    expanded_basic: dict[str, float] = {}
    for name in BASIC_FIELD_ORDER:
        value = basic.get(name, 0.0)
        low, high = (-4.0, 4.0) if name == "exposure" else (-1.0, 1.0)
        validated = require_number(value, f"recipe.parameters.basic.{name}", low, high)
        normalized[name] = validated
        expanded_basic[name] = validated
    curve = parameters.get("curve", [])
    normalized["curve"] = validate_curve_value(curve, "recipe.parameters.curve")
    channel_curves, expanded_channel_curves = validate_channel_curves(
        parameters.get("channel_curves", {}),
        "recipe.parameters.channel_curves",
    )
    normalized["channel_curves"] = channel_curves

    color_management = require_object(
        parameters.get("color_management", {}),
        "recipe.parameters.color_management",
    )
    reject_unknown_keys(
        color_management,
        {"rendering", "gamut_mapping"},
        "recipe.parameters.color_management",
    )
    rendering = color_management.get("rendering", "legacy")
    if not isinstance(rendering, str) or rendering not in COLOR_RENDERING_MODES:
        raise ValueError("recipe.parameters.color_management.rendering must be legacy or perceptual.")
    gamut_mapping = color_management.get("gamut_mapping", "clip")
    if not isinstance(gamut_mapping, str) or gamut_mapping not in GAMUT_MAPPING_MODES:
        raise ValueError(
            "recipe.parameters.color_management.gamut_mapping must be clip or oklch_compress."
        )
    normalized["rendering"] = rendering
    normalized["gamut_mapping"] = gamut_mapping

    presence = require_object(parameters.get("presence", {}), "recipe.parameters.presence")
    reject_unknown_keys(presence, PRESENCE_FIELDS, "recipe.parameters.presence")
    expanded_presence: dict[str, float] = {}
    for name in ("dehaze", "clarity", "texture"):
        value = require_number(
            presence.get(name, 0.0),
            f"recipe.parameters.presence.{name}",
            -1.0,
            1.0,
        )
        normalized[name] = value
        expanded_presence[name] = value

    hsl = require_object(parameters.get("hsl", {}), "recipe.parameters.hsl")
    reject_unknown_keys(hsl, set(HUE_CENTERS), "recipe.parameters.hsl")
    expanded_hsl: dict[str, dict[str, float]] = {}
    for color in HUE_CENTERS:
        color_values = require_object(hsl.get(color, {}), f"recipe.parameters.hsl.{color}")
        color_fields = {"hue", "saturation", "luminance"}
        reject_unknown_keys(color_values, color_fields, f"recipe.parameters.hsl.{color}")
        hue = require_number(color_values.get("hue", 0.0), f"recipe.parameters.hsl.{color}.hue", -90.0, 90.0)
        saturation = require_number(
            color_values.get("saturation", 0.0),
            f"recipe.parameters.hsl.{color}.saturation",
            -1.0,
            1.5,
        )
        luminance = require_number(
            color_values.get("luminance", 0.0),
            f"recipe.parameters.hsl.{color}.luminance",
            -1.0,
            1.0,
        )
        normalized[f"{color}_hue"] = hue
        normalized[f"{color}_sat"] = saturation
        normalized[f"{color}_lum"] = luminance
        expanded_hsl[color] = {"hue": hue, "saturation": saturation, "luminance": luminance}

    grading_fields = {"shadows", "midtones", "highlights", "balance", "blending"}
    grading = require_object(parameters.get("color_grading", {}), "recipe.parameters.color_grading")
    reject_unknown_keys(grading, grading_fields, "recipe.parameters.color_grading")
    expanded_grading: dict[str, Any] = {}
    for zone in ("shadows", "midtones", "highlights"):
        zone_values = require_object(grading.get(zone, {}), f"recipe.parameters.color_grading.{zone}")
        reject_unknown_keys(zone_values, {"hue", "saturation"}, f"recipe.parameters.color_grading.{zone}")
        hue = require_number(zone_values.get("hue", 0.0), f"recipe.parameters.color_grading.{zone}.hue", 0.0, 360.0)
        saturation = require_number(
            zone_values.get("saturation", 0.0),
            f"recipe.parameters.color_grading.{zone}.saturation",
            0.0,
            1.0,
        )
        normalized[f"grade_{zone}_hue"] = hue
        normalized[f"grade_{zone}_sat"] = saturation
        expanded_grading[zone] = {"hue": hue, "saturation": saturation}
    balance = require_number(grading.get("balance", 0.0), "recipe.parameters.color_grading.balance", -1.0, 1.0)
    blending = require_number(grading.get("blending", 0.5), "recipe.parameters.color_grading.blending", 0.0, 1.0)
    normalized["grading_balance"] = balance
    normalized["grading_blending"] = blending
    expanded_grading["balance"] = balance
    expanded_grading["blending"] = blending
    local_corrections = parameters.get("local_corrections", [])
    local_adjustments = parameters.get("local_adjustments", [])
    normalized["local_corrections"] = validate_local_adjustments(local_corrections, "recipe.parameters.local_corrections")
    normalized["local_adjustments"] = validate_local_adjustments(local_adjustments, "recipe.parameters.local_adjustments")

    detail = require_object(parameters.get("detail", {}), "recipe.parameters.detail")
    reject_unknown_keys(detail, {"denoise", "sharpen", "sharpen_radius"}, "recipe.parameters.detail")
    denoise = require_number(detail.get("denoise", 0.0), "recipe.parameters.detail.denoise", 0.0, 1.0)
    sharpen = require_number(detail.get("sharpen", 0.0), "recipe.parameters.detail.sharpen", 0.0, 2.0)
    sharpen_radius = require_number(
        detail.get("sharpen_radius", 1.0),
        "recipe.parameters.detail.sharpen_radius",
        0.1,
        5.0,
    )
    normalized["denoise"] = denoise
    normalized["sharpen"] = sharpen
    normalized["sharpen_radius"] = sharpen_radius

    output = require_object(parameters.get("output", {}), "recipe.parameters.output")
    reject_unknown_keys(
        output,
        {"jpeg_quality", "png_compress", "png_bit_depth", "png_dither"},
        "recipe.parameters.output",
    )
    jpeg_quality = require_number(output.get("jpeg_quality", 95), "recipe.parameters.output.jpeg_quality", 1, 100)
    png_compress = require_number(output.get("png_compress", 6), "recipe.parameters.output.png_compress", 0, 9)
    png_bit_depth = require_number(output.get("png_bit_depth", 8), "recipe.parameters.output.png_bit_depth", 8, 16)
    if not jpeg_quality.is_integer() or not png_compress.is_integer() or not png_bit_depth.is_integer():
        raise ValueError("Output quality, compression, and PNG bit-depth values must be integers.")
    if int(png_bit_depth) not in {8, 16}:
        raise ValueError("recipe.parameters.output.png_bit_depth must be 8 or 16.")
    png_dither = output.get("png_dither", "none")
    if not isinstance(png_dither, str) or png_dither not in PNG_DITHER_MODES:
        raise ValueError("recipe.parameters.output.png_dither must be none or tpdf.")
    if int(png_bit_depth) == 16 and png_dither != "none":
        raise ValueError("PNG dithering is only supported for 8-bit PNG output.")
    normalized["jpeg_quality"] = int(jpeg_quality)
    normalized["png_compress"] = int(png_compress)
    normalized["png_bit_depth"] = int(png_bit_depth)
    normalized["png_dither"] = png_dither
    expanded_recipe = dict(recipe)
    expanded_recipe["parameters"] = {
        "basic": expanded_basic,
        "curve": curve,
        "channel_curves": expanded_channel_curves,
        "presence": expanded_presence,
        "color_management": {
            "rendering": rendering,
            "gamut_mapping": gamut_mapping,
        },
        "hsl": expanded_hsl,
        "color_grading": expanded_grading,
        "local_corrections": local_corrections,
        "local_adjustments": local_adjustments,
        "detail": {
            "denoise": denoise,
            "sharpen": sharpen,
            "sharpen_radius": sharpen_radius,
        },
        "output": {
            "jpeg_quality": int(jpeg_quality),
            "png_compress": int(png_compress),
            "png_bit_depth": int(png_bit_depth),
            "png_dither": png_dither,
        },
    }
    return argparse.Namespace(**normalized), expanded_recipe


def require_supported(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Only JPEG and PNG are supported by this skill.")


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    rgb = np.maximum(rgb, 0.0)
    return np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)


def extended_srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """Decode finite extended sRGB without evaluating fractional powers of negatives."""
    values = np.asarray(rgb, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError("Color processing requires finite RGB values.")
    result = np.empty_like(values)
    linear_segment = values <= 0.04045
    result[linear_segment] = values[linear_segment] / 12.92
    result[~linear_segment] = ((values[~linear_segment] + 0.055) / 1.055) ** 2.4
    return result


def extended_linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    """Encode finite extended linear sRGB using a sign-preserving transfer curve."""
    values = np.asarray(rgb, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError("Color processing requires finite linear RGB values.")
    result = np.empty_like(values)
    linear_segment = values <= 0.0031308
    result[linear_segment] = 12.92 * values[linear_segment]
    result[~linear_segment] = 1.055 * np.power(values[~linear_segment], 1.0 / 2.4) - 0.055
    return result


def linear_srgb_to_xyz(linear_rgb: np.ndarray) -> np.ndarray:
    values = np.asarray(linear_rgb, dtype=np.float64)
    if values.shape[-1] != 3 or not np.all(np.isfinite(values)):
        raise ValueError("linear_srgb_to_xyz expects finite RGB triples.")
    return values @ SRGB_TO_XYZ.T


def xyz_to_linear_srgb(xyz: np.ndarray) -> np.ndarray:
    values = np.asarray(xyz, dtype=np.float64)
    if values.shape[-1] != 3 or not np.all(np.isfinite(values)):
        raise ValueError("xyz_to_linear_srgb expects finite XYZ triples.")
    return values @ XYZ_TO_SRGB.T


def xyz_to_oklab(xyz: np.ndarray) -> np.ndarray:
    values = np.asarray(xyz, dtype=np.float64)
    if values.shape[-1] != 3 or not np.all(np.isfinite(values)):
        raise ValueError("xyz_to_oklab expects finite XYZ triples.")
    lms = values @ XYZ_TO_LMS.T
    result = np.cbrt(lms) @ LMS_CUBERT_TO_OKLAB.T
    if not np.all(np.isfinite(result)):
        raise ValueError("XYZ to OKLab conversion produced non-finite values.")
    return result


def oklab_to_xyz(oklab: np.ndarray) -> np.ndarray:
    values = np.asarray(oklab, dtype=np.float64)
    if values.shape[-1] != 3 or not np.all(np.isfinite(values)):
        raise ValueError("oklab_to_xyz expects finite OKLab triples.")
    lms_root = values @ OKLAB_TO_LMS_CUBERT.T
    result = (lms_root**3) @ LMS_TO_XYZ.T
    if not np.all(np.isfinite(result)):
        raise ValueError("OKLab to XYZ conversion produced non-finite values.")
    return result


def srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    return xyz_to_oklab(linear_srgb_to_xyz(extended_srgb_to_linear(rgb)))


def oklab_to_srgb(oklab: np.ndarray) -> np.ndarray:
    return extended_linear_to_srgb(xyz_to_linear_srgb(oklab_to_xyz(oklab)))


def oklab_to_oklch(oklab: np.ndarray) -> np.ndarray:
    values = np.asarray(oklab, dtype=np.float64)
    chroma = np.hypot(values[..., 1], values[..., 2])
    hue = np.degrees(np.arctan2(values[..., 2], values[..., 1])) % 360.0
    hue = np.where(chroma <= 1e-12, 0.0, hue)
    return np.stack((values[..., 0], chroma, hue), axis=-1)


def oklch_to_oklab(oklch: np.ndarray) -> np.ndarray:
    values = np.asarray(oklch, dtype=np.float64)
    angle = np.radians(values[..., 2])
    return np.stack(
        (
            values[..., 0],
            values[..., 1] * np.cos(angle),
            values[..., 1] * np.sin(angle),
        ),
        axis=-1,
    )


def out_of_gamut_ratio(rgb: np.ndarray) -> float:
    values = np.asarray(rgb)
    if not np.all(np.isfinite(values)):
        raise ValueError("Gamut inspection encountered non-finite RGB values.")
    return float(np.mean(np.any((values < 0.0) | (values > 1.0), axis=-1)))


def _oklch_compress_block(source: np.ndarray, iterations: int) -> np.ndarray:
    oklch = oklab_to_oklch(srgb_to_oklab(source))
    lightness = np.clip(oklch[..., 0], 0.0, 1.0)
    chroma = np.maximum(oklch[..., 1], 0.0)
    hue = oklch[..., 2]
    low = np.zeros_like(chroma)
    high = np.full_like(chroma, 0.02)
    direction = np.stack((np.cos(np.radians(hue)), np.sin(np.radians(hue))), axis=-1)

    def candidate_rgb(candidate_chroma: np.ndarray) -> np.ndarray:
        lab = np.concatenate(
            (
                lightness[..., None],
                direction * candidate_chroma[..., None],
            ),
            axis=-1,
        )
        return oklab_to_srgb(lab)

    # Grow outward from the neutral axis so the binary search brackets the
    # first gamut boundary instead of accidentally landing on a later cubic
    # re-entry of an individual linear-RGB channel.
    for _ in range(10):
        candidate = candidate_rgb(high)
        still_in = np.all((candidate >= 0.0) & (candidate <= 1.0), axis=-1)
        low = np.where(still_in, high, low)
        high = np.where(still_in, high * 2.0, high)
    for _ in range(iterations):
        midpoint = (low + high) * 0.5
        candidate = candidate_rgb(midpoint)
        in_gamut = np.all((candidate >= 0.0) & (candidate <= 1.0), axis=-1)
        low = np.where(in_gamut, midpoint, low)
        high = np.where(in_gamut, high, midpoint)
    maximum = low
    # A fixed conservative knee avoids exposing the non-convex blue cusp of
    # the sRGB gamut as a visible contour. The per-pixel search remains the
    # hard safety boundary, while the fixed shoulder provides a continuous
    # hue-independent compression response before that boundary is reached.
    knee = 0.10
    shoulder = 0.08
    excess = np.maximum(chroma - knee, 0.0)
    compressed = knee + excess / (1.0 + excess / shoulder)
    target_chroma = np.where(chroma <= knee, chroma, np.minimum(compressed, maximum))
    target_chroma = np.where(chroma <= 1e-12, 0.0, target_chroma)
    result = candidate_rgb(target_chroma)
    if not np.all(np.isfinite(result)):
        raise ValueError("OKLCh gamut compression produced non-finite RGB values.")
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def oklch_compress(rgb: np.ndarray, iterations: int = 24) -> np.ndarray:
    """Compress OKLCh chroma with bounded temporary storage and fixed settings."""
    source = np.asarray(rgb, dtype=np.float64)
    if source.shape[-1] != 3 or not np.all(np.isfinite(source)):
        raise ValueError("OKLCh gamut compression expects finite RGB triples.")
    flat = source.reshape(-1, 3)
    compressed = np.empty(flat.shape, dtype=np.float32)
    block_pixels = 262_144
    for start in range(0, flat.shape[0], block_pixels):
        end = min(start + block_pixels, flat.shape[0])
        compressed[start:end] = _oklch_compress_block(flat[start:end], iterations)
    return compressed.reshape(source.shape)


def apply_gamut_mapping(rgb: np.ndarray, mode: str) -> tuple[np.ndarray, dict[str, float]]:
    before = out_of_gamut_ratio(rgb)
    if mode == "clip":
        result = np.clip(rgb, 0.0, 1.0)
    elif mode == "oklch_compress":
        result = oklch_compress(rgb)
    else:
        raise ValueError(f"Unsupported gamut mapping mode: {mode}")
    after = out_of_gamut_ratio(result)
    return result.astype(np.float32, copy=False), {
        "out_of_gamut_ratio_before": round(before, 8),
        "out_of_gamut_ratio_after": round(after, 8),
    }


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


def srgb_profile_bytes() -> bytes:
    profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    # LittleCMS stamps generated profiles with the wall-clock time. Normalize
    # only the ICC header creation date so separate CLI processes encode the
    # same canonical sRGB profile bytes; the generated profile ID is zero.
    profile[24:36] = b"\x07\xd0\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00"
    return bytes(profile)


def profile_is_srgb(profile_bytes: bytes) -> bool:
    profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
    description = ImageCms.getProfileDescription(profile).strip().lower()
    return "srgb" in description


def image_source_bit_depth(path: Path, format_name: str | None = None) -> int:
    if (format_name or "").upper() == "PNG":
        return int(inspect_ihdr(path)["bit_depth"])
    return 8


def runtime_versions() -> dict[str, str]:
    try:
        pypng_version = importlib.metadata.version("pypng")
    except importlib.metadata.PackageNotFoundError:
        pypng_version = "unavailable"
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pillow": Image.__version__,
        "pypng": pypng_version,
    }


def load_image(
    path: Path,
    *,
    strict_color_management: bool = False,
    preserve_png16: bool = False,
) -> tuple[np.ndarray, np.ndarray | None, dict[str, Any]]:
    require_supported(path)
    with Image.open(path) as source:
        source.load()
        source_bit_depth = image_source_bit_depth(path, source.format)
        metadata: dict[str, Any] = {
            "format": source.format,
            "source_mode": source.mode,
            "source_bit_depth": source_bit_depth,
            "exif": source.info.get("exif"),
            "icc_profile": source.info.get("icc_profile"),
            "dpi": source.info.get("dpi"),
            "png_text": {k: v for k, v in source.info.items() if isinstance(v, str)},
            "icc_status": "absent_assumed_srgb" if not source.info.get("icc_profile") else "present",
            "warnings": [],
        }
        has_alpha = source.mode in {"RGBA", "LA"} or (
            source.mode == "P" and "transparency" in source.info
        )
        if preserve_png16 and source.format == "PNG" and source_bit_depth == 16:
            rgb, alpha, direct = read_png16(path)
            has_alpha = alpha is not None
            if metadata["icc_profile"]:
                try:
                    if not profile_is_srgb(metadata["icc_profile"]):
                        raise ValueError(
                            "16-bit PNG input uses a non-sRGB ICC profile; convert it externally to sRGB16 first."
                        )
                except ValueError:
                    raise
                except Exception as exc:
                    raise ValueError("16-bit PNG input has an invalid ICC profile.") from exc
                metadata["icc_status"] = "source_srgb_profile"
            else:
                metadata["icc_status"] = "absent_assumed_srgb"
            if strict_color_management:
                metadata["icc_profile"] = srgb_profile_bytes()
            metadata["size"] = [direct["width"], direct["height"]]
            metadata["has_alpha"] = has_alpha
            return rgb, alpha, metadata

        if strict_color_management:
            if source.mode == "CMYK" and not metadata["icc_profile"]:
                raise ValueError("CMYK input requires a valid ICC profile for perceptual or high-bit-depth processing.")
            if metadata["icc_profile"]:
                try:
                    in_profile = ImageCms.ImageCmsProfile(io.BytesIO(metadata["icc_profile"]))
                    out_profile = ImageCms.createProfile("sRGB")
                    alpha_pixels = (
                        np.asarray(source.convert("RGBA"), dtype=np.float32)[..., 3:4] / 255.0
                        if has_alpha
                        else None
                    )
                    color_source = source if source.mode == "CMYK" else source.convert("RGB")
                    image = ImageCms.profileToProfile(
                        color_source,
                        in_profile,
                        out_profile,
                        outputMode="RGB",
                    )
                    metadata["icc_profile"] = srgb_profile_bytes()
                    metadata["icc_status"] = "converted_to_srgb"
                    rgb = np.asarray(image, dtype=np.float32) / 255.0
                    alpha = None if alpha_pixels is None else alpha_pixels.astype(np.float32)
                except Exception as exc:
                    raise ValueError("ICC conversion to sRGB failed for the selected new processing path.") from exc
            else:
                image = source.convert("RGBA") if has_alpha else source.convert("RGB")
                pixels = np.asarray(image, dtype=np.float32) / 255.0
                alpha = pixels[..., 3:4].copy() if has_alpha else None
                rgb = pixels[..., :3].copy()
                metadata["icc_profile"] = srgb_profile_bytes()
                metadata["icc_status"] = "absent_assumed_srgb"
        else:
            image = source.convert("RGBA") if has_alpha else source.convert("RGB")
            if metadata["icc_profile"]:
                try:
                    in_profile = ImageCms.ImageCmsProfile(metadata["icc_profile"])
                    out_profile = ImageCms.createProfile("sRGB")
                    output_mode = "RGBA" if has_alpha else "RGB"
                    image = ImageCms.profileToProfile(image, in_profile, out_profile, outputMode=output_mode)
                    metadata["icc_profile"] = ImageCms.ImageCmsProfile(out_profile).tobytes()
                    metadata["icc_status"] = "converted_to_srgb"
                except Exception:
                    metadata["icc_status"] = "conversion_failed_legacy_fallback"
                    metadata["warnings"].append(
                        "ICC conversion failed; legacy processing continued with the original profile and pixel behavior."
                    )
            pixels = np.asarray(image, dtype=np.float32) / 255.0
            alpha = pixels[..., 3:4].copy() if has_alpha else None
            rgb = pixels[..., :3].copy()

        metadata["size"] = [int(source.width), int(source.height)]
        metadata["has_alpha"] = has_alpha
        return rgb.astype(np.float32, copy=False), alpha, metadata


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
    percentile_keys = [1, 5, 25, 50, 75, 95, 99]
    channel_percentiles = np.percentile(values, percentile_keys, axis=0)
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
    spatial_rgb_grid: list[list[list[float] | None]] = []
    cells: list[tuple[float, int, int]] = []
    for row in range(3):
        row_values: list[float | None] = []
        row_rgb_values: list[list[float] | None] = []
        y0, y1 = round(row * height / 3), round((row + 1) * height / 3)
        for column in range(3):
            x0, x1 = round(column * width / 3), round((column + 1) * width / 3)
            cell_visible = visible_map[y0:y1, x0:x1]
            cell_luma = luma_map[y0:y1, x0:x1][cell_visible]
            if cell_luma.size:
                mean = round(float(np.mean(cell_luma)), 5)
                cells.append((mean, row, column))
                row_values.append(mean)
                cell_rgb = rgb[y0:y1, x0:x1][cell_visible]
                row_rgb_values.append([round(float(value), 5) for value in np.mean(cell_rgb, axis=0)])
            else:
                row_values.append(None)
                row_rgb_values.append(None)
        spatial_grid.append(row_values)
        spatial_rgb_grid.append(row_rgb_values)
    brightest = max(cells)
    darkest = min(cells)
    rgb_channels: dict[str, Any] = {}
    for channel_index, channel in enumerate(CHANNEL_NAMES):
        counts, _ = np.histogram(values[:, channel_index], bins=64, range=(0.0, 1.0))
        histogram = counts.astype(np.float64) / values.shape[0]
        histogram = np.round(histogram, 10)
        correction_index = int(np.argmax(histogram))
        histogram[correction_index] += 1.0 - float(np.sum(histogram))
        rgb_channels[channel] = {
            "mean": round(float(channel_mean[channel_index]), 5),
            "percentiles": {
                str(percentile): round(float(channel_percentiles[index, channel_index]), 5)
                for index, percentile in enumerate(percentile_keys)
            },
            "low_clip_ratio": round(float(np.mean(values[:, channel_index] <= 0.002)), 6),
            "high_clip_ratio": round(float(np.mean(values[:, channel_index] >= 0.998)), 6),
            "histogram_64": [float(value) for value in histogram],
        }
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
        "rgb_channels": rgb_channels,
        "neutral_candidate_ratio": round(float(np.mean(neutral)), 5),
        "neutral_candidate_mean_rgb": [None if np.isnan(v) else round(float(v), 5) for v in neutral_mean],
        "spatial_luma_grid_3x3": spatial_grid,
        "spatial_rgb_mean_grid_3x3": spatial_rgb_grid,
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
    result = {
        "file": str(path),
        "format": meta["format"],
        "width": meta["size"][0],
        "height": meta["size"][1],
        "has_alpha": meta["has_alpha"],
        "bit_depth": meta["source_bit_depth"],
        "color_management": {
            "icc_status": meta["icc_status"],
        },
        "metrics": image_metrics(rgb, alpha),
    }
    if meta["warnings"]:
        result["warnings"] = list(meta["warnings"])
    return result


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


def apply_perceptual_color(rgb: np.ndarray, vibrance: float, saturation: float) -> np.ndarray:
    """Apply global colorfulness controls to OKLCh chroma while preserving L and hue."""
    if max(abs(vibrance), abs(saturation)) < 1e-12:
        return rgb
    source = np.asarray(rgb, dtype=np.float32)
    if not np.all(np.isfinite(source)):
        raise ValueError("Perceptual color processing requires finite RGB values.")
    lch = oklab_to_oklch(srgb_to_oklab(source))
    original_chroma = lch[..., 1].copy()
    hsv_hue, hsv_saturation, _ = rgb_hsv_components(np.clip(source, 0.0, 1.0))
    skin = (
        circular_hue_weight(hsv_hue, 28.0, 22.0)
        * smoothstep(0.08, 0.35, hsv_saturation)
        * (1.0 - smoothstep(0.72, 1.0, hsv_saturation))
    )
    vibrance_value = float(np.clip(vibrance, -1.0, 1.0))
    normalized_chroma = np.clip(original_chroma / 0.32, 0.0, 1.0)
    if vibrance_value >= 0.0:
        vibrance_factor = 1.0 + vibrance_value * (1.0 - normalized_chroma) * (1.0 - 0.65 * skin)
    else:
        vibrance_factor = 1.0 + vibrance_value * (0.45 + 0.55 * normalized_chroma)
    saturation_factor = 1.0 + float(np.clip(saturation, -1.0, 1.0))
    lch[..., 1] = np.maximum(original_chroma * vibrance_factor * saturation_factor, 0.0)
    result = oklab_to_srgb(oklch_to_oklab(lch))
    neutral = original_chroma <= 2e-7
    if np.any(neutral):
        result[neutral] = source[neutral]
    if not np.all(np.isfinite(result)):
        raise ValueError("Perceptual color processing produced non-finite RGB values.")
    return result.astype(np.float32)


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


def apply_channel_curves(
    rgb: np.ndarray,
    specifications: dict[str, str | None] | None,
) -> np.ndarray:
    if not specifications or not any(specifications.get(channel) for channel in CHANNEL_NAMES):
        return rgb
    result = rgb.copy()
    for channel_index, channel in enumerate(CHANNEL_NAMES):
        points = parse_curve(specifications.get(channel))
        if points is None:
            continue
        x, y = points
        channel_input = np.clip(result[..., channel_index], 0.0, 1.0)
        result[..., channel_index] = np.interp(channel_input, x, y).astype(np.float32)
    return result


def box_blur_float(values: np.ndarray, radius: int) -> np.ndarray:
    """Return an edge-extended separable box blur without integer quantization."""
    if radius <= 0:
        return values
    if values.ndim != 2:
        raise ValueError("Float box blur expects a two-dimensional luminance array.")
    window = radius * 2 + 1
    result = values.astype(np.float32, copy=False)
    for axis in (0, 1):
        padding = [(0, 0), (0, 0)]
        padding[axis] = (radius, radius)
        extended = np.pad(result, padding, mode="edge")
        cumulative = np.cumsum(extended, axis=axis, dtype=np.float64)
        zero_shape = list(cumulative.shape)
        zero_shape[axis] = 1
        cumulative = np.concatenate(
            (np.zeros(zero_shape, dtype=np.float64), cumulative),
            axis=axis,
        )
        leading = [slice(None), slice(None)]
        trailing = [slice(None), slice(None)]
        leading[axis] = slice(window, None)
        trailing[axis] = slice(None, -window)
        result = ((cumulative[tuple(leading)] - cumulative[tuple(trailing)]) / window).astype(
            np.float32
        )
    return result


def local_luma_envelope(luma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    padded = np.pad(luma, 1, mode="edge")
    neighborhoods = [
        padded[y : y + luma.shape[0], x : x + luma.shape[1]]
        for y in range(3)
        for x in range(3)
    ]
    return np.minimum.reduce(neighborhoods), np.maximum.reduce(neighborhoods)


def luma_gradient(luma: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    padded = np.pad(luma, 1, mode="edge")
    dx = 0.5 * (padded[1:-1, 2:] - padded[1:-1, :-2])
    dy = 0.5 * (padded[2:, 1:-1] - padded[:-2, 1:-1])
    magnitude = np.sqrt(dx * dx + dy * dy).astype(np.float32)
    return dx.astype(np.float32), dy.astype(np.float32), magnitude


def coherent_detail_gate(detail: np.ndarray, scale: int) -> np.ndarray:
    """Prefer spatially coherent detail over random residuals in nominally flat areas."""
    dx, dy, magnitude = luma_gradient(detail)
    radius = max(1, 2 * scale)
    mean_dx = box_blur_float(dx, radius)
    mean_dy = box_blur_float(dy, radius)
    mean_magnitude = box_blur_float(magnitude, radius)
    coherence = np.sqrt(mean_dx * mean_dx + mean_dy * mean_dy) / np.maximum(
        mean_magnitude,
        1e-6,
    )
    return (0.12 + 0.88 * smoothstep(0.08, 0.72, coherence)).astype(np.float32)


def reconstruct_from_luma(
    rgb: np.ndarray,
    target_luma: np.ndarray,
    chroma_factor: np.ndarray | float = 1.0,
) -> np.ndarray:
    """Set encoded-sRGB luminance while preserving hue and constraining gamut."""
    source = np.clip(rgb, 0.0, 1.0).astype(np.float32, copy=False)
    current = source @ LUMA
    ratio = np.divide(
        target_luma,
        np.maximum(current, 1e-6),
        out=np.ones_like(target_luma, dtype=np.float32),
        where=current > 1e-6,
    )
    ratio = np.maximum(ratio, 0.0)
    scaled = source * ratio[..., None]
    black = current <= 1e-6
    if np.any(black):
        scaled[black] = target_luma[black, None]

    factor = np.broadcast_to(np.asarray(chroma_factor, dtype=np.float32), target_luma.shape)
    factor = np.maximum(factor, 0.0)
    chroma = scaled - target_luma[..., None]
    positive_chroma = chroma > 1e-7
    negative_chroma = chroma < -1e-7
    allowed = np.full_like(chroma, np.inf, dtype=np.float32)
    np.divide(
        1.0 - target_luma[..., None],
        chroma,
        out=allowed,
        where=positive_chroma,
    )
    negative_allowed = np.full_like(chroma, np.inf, dtype=np.float32)
    np.divide(
        -target_luma[..., None],
        chroma,
        out=negative_allowed,
        where=negative_chroma,
    )
    allowed[negative_chroma] = negative_allowed[negative_chroma]
    factor = np.minimum(factor, np.min(allowed, axis=2))
    result = target_luma[..., None] + chroma * factor[..., None]
    if not np.all(np.isfinite(result)):
        raise ValueError("Presence processing produced non-finite RGB values.")
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def apply_presence(
    rgb: np.ndarray,
    dehaze: float = 0.0,
    clarity: float = 0.0,
    texture: float = 0.0,
) -> np.ndarray:
    """Apply deterministic low-, mid-, and high-frequency luminance shaping."""
    dehaze = float(np.clip(dehaze, -1.0, 1.0))
    clarity = float(np.clip(clarity, -1.0, 1.0))
    texture = float(np.clip(texture, -1.0, 1.0))
    if max(abs(dehaze), abs(clarity), abs(texture)) < 1e-12:
        return rgb
    if not np.all(np.isfinite(rgb)):
        raise ValueError("Presence processing requires finite RGB values.")

    source = np.clip(rgb, 0.0, 1.0).astype(np.float32, copy=False)
    original_luma = (source @ LUMA).astype(np.float32)
    height, width = original_luma.shape
    scale = max(1, min(8, int(round(min(height, width) / 512.0))))
    low, high = local_luma_envelope(original_luma)
    allowance = 0.02 * max(abs(dehaze), abs(clarity), abs(texture))
    lower_bound = np.maximum(0.0, low - allowance)
    upper_bound = np.minimum(1.0, high + allowance)
    result = source

    if abs(dehaze) >= 1e-12:
        luma = (result @ LUMA).astype(np.float32)
        medium = box_blur_float(luma, 4 * scale)
        broad = box_blur_float(luma, 16 * scale)
        dehaze_band = medium - broad
        _, _, gradient = luma_gradient(luma)
        edge_guard = 1.0 - smoothstep(0.055, 0.28, gradient)
        tone_guard = smoothstep(0.015, 0.14, luma) * (1.0 - smoothstep(0.88, 0.995, luma))
        p05, p95 = np.percentile(luma, [5, 95])
        scene_range = float(p95 - p05)
        haze_weight = float(np.clip((0.62 - scene_range) / 0.62, 0.0, 1.0))
        midpoint = float((p05 + p95) * 0.5)
        low_range = dehaze_band + 0.32 * haze_weight * (broad - midpoint)
        target = luma + dehaze * 0.62 * low_range * tone_guard * edge_guard
        target = np.clip(target, lower_bound, upper_bound)
        chroma_factor = 1.0 + 0.08 * dehaze * tone_guard
        result = reconstruct_from_luma(result, target.astype(np.float32), chroma_factor)

    if abs(clarity) >= 1e-12:
        luma = (result @ LUMA).astype(np.float32)
        small = box_blur_float(luma, scale)
        medium = box_blur_float(luma, 4 * scale)
        clarity_band = small - medium
        _, _, gradient = luma_gradient(luma)
        edge_guard = 1.0 - smoothstep(0.055, 0.28, gradient)
        clarity_gate = coherent_detail_gate(clarity_band, 2 * scale)
        midtone_guard = smoothstep(0.08, 0.32, luma) * (1.0 - smoothstep(0.68, 0.94, luma))
        target = luma + clarity * 0.92 * clarity_band * clarity_gate * midtone_guard * edge_guard
        target = np.clip(target, lower_bound, upper_bound)
        result = reconstruct_from_luma(result, target.astype(np.float32))

    if abs(texture) >= 1e-12:
        luma = (result @ LUMA).astype(np.float32)
        small = box_blur_float(luma, scale)
        texture_band = luma - small
        _, _, gradient = luma_gradient(luma)
        edge_guard = 1.0 - smoothstep(0.055, 0.28, gradient)
        tone_guard = smoothstep(0.015, 0.14, luma) * (1.0 - smoothstep(0.88, 0.995, luma))
        texture_gate = coherent_detail_gate(texture_band, scale)
        target = luma + texture * 0.72 * texture_band * texture_gate * tone_guard * edge_guard
        target = np.clip(target, lower_bound, upper_bound)
        result = reconstruct_from_luma(result, target.astype(np.float32))
    return result


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


def apply_perceptual_selective_color(
    rgb: np.ndarray,
    adjustments: dict[str, tuple[float, float, float]],
) -> np.ndarray:
    if not any(max(abs(value) for value in controls) >= 1e-12 for controls in adjustments.values()):
        return rgb
    source = np.asarray(rgb, dtype=np.float32)
    if not np.all(np.isfinite(source)):
        raise ValueError("Perceptual HSL processing requires finite RGB values.")
    base = np.clip(source, 0.0, 1.0)
    selection_hue, selection_saturation, _ = rgb_hsv_components(base)
    presence = smoothstep(0.025, 0.2, selection_saturation)
    lch = oklab_to_oklch(srgb_to_oklab(source))
    original_chroma = lch[..., 1].copy()
    hue_shift = np.zeros_like(selection_hue, dtype=np.float64)
    chroma_delta = np.zeros_like(selection_hue, dtype=np.float64)
    lightness_stops = np.zeros_like(selection_hue, dtype=np.float64)
    for name, (hue_adjust, saturation_adjust, luminance_adjust) in adjustments.items():
        if max(abs(hue_adjust), abs(saturation_adjust), abs(luminance_adjust)) < 1e-12:
            continue
        weight = circular_hue_weight(selection_hue, HUE_CENTERS[name]) * presence
        hue_shift += float(np.clip(hue_adjust, -90.0, 90.0)) * weight
        chroma_delta += float(np.clip(saturation_adjust, -1.0, 1.5)) * weight
        lightness_stops += 0.45 * float(np.clip(luminance_adjust, -1.0, 1.0)) * weight
    lch[..., 2] = (lch[..., 2] + np.clip(hue_shift, -90.0, 90.0)) % 360.0
    lch[..., 1] = np.maximum(original_chroma * (1.0 + np.clip(chroma_delta, -1.0, 1.5)), 0.0)
    lch[..., 0] = np.clip(lch[..., 0] * np.exp2(lightness_stops), 0.0, 1.0)
    result = oklab_to_srgb(oklch_to_oklab(lch))
    neutral = original_chroma <= 2e-7
    if np.any(neutral):
        result[neutral] = source[neutral]
    if not np.all(np.isfinite(result)):
        raise ValueError("Perceptual HSL processing produced non-finite RGB values.")
    return result.astype(np.float32)


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


def apply_perceptual_color_grading(
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
    if max(abs(shadows_sat), abs(midtones_sat), abs(highlights_sat)) < 1e-12:
        return rgb
    source = np.asarray(rgb, dtype=np.float32)
    lab = srgb_to_oklab(source)
    lightness = np.clip(lab[..., 0], 0.0, 1.0)
    balance = float(np.clip(balance, -1.0, 1.0))
    blending = float(np.clip(blending, 0.0, 1.0))
    pivot = 0.5 - 0.16 * balance
    width = 0.16 + 0.18 * blending
    shadow_weight = 1.0 - smoothstep(pivot - width, pivot + width, lightness)
    highlight_weight = smoothstep(pivot - width, pivot + width, lightness)
    midtone_weight = np.exp(-0.5 * ((lightness - pivot) / width) ** 2)
    zones = (
        (shadows_hue, shadows_sat, shadow_weight),
        (midtones_hue, midtones_sat, midtone_weight),
        (highlights_hue, highlights_sat, highlight_weight),
    )
    result = lab.copy()
    for hue_value, saturation_value, weight in zones:
        chroma = 0.12 * float(np.clip(saturation_value, 0.0, 1.0))
        if chroma <= 0.0:
            continue
        angle = math.radians(float(hue_value) % 360.0)
        result[..., 1] += math.cos(angle) * chroma * weight
        result[..., 2] += math.sin(angle) * chroma * weight
    output = oklab_to_srgb(result)
    if not np.all(np.isfinite(output)):
        raise ValueError("Perceptual color grading produced non-finite RGB values.")
    return output.astype(np.float32)


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
    result = apply_curve(result, getattr(parameters, "curve", None))
    return apply_channel_curves(result, getattr(parameters, "channel_curves", None))


def apply_adjustment_bundle(rgb: np.ndarray, parameters: Any) -> np.ndarray:
    result = apply_tonal_adjustments(rgb, parameters)
    result = apply_presence(
        result,
        clarity=getattr(parameters, "clarity", 0.0),
        texture=getattr(parameters, "texture", 0.0),
    )
    if getattr(parameters, "rendering", "legacy") == "perceptual":
        return apply_perceptual_color(result, parameters.vibrance, parameters.saturation)
    return apply_color(result, parameters.vibrance, parameters.saturation)


def local_parameters(adjustments: dict[str, Any], rendering: str = "legacy") -> SimpleNamespace:
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
        "channel_curves",
        "clarity",
        "texture",
    }
    unknown = set(adjustments) - allowed
    if unknown:
        raise ValueError(f"Unsupported local adjustment keys: {sorted(unknown)}")
    values = {name: 0.0 for name in allowed if name not in {"curve", "channel_curves"}}
    values["curve"] = None
    values["channel_curves"] = {}
    values["rendering"] = rendering
    values.update(adjustments)
    return SimpleNamespace(**values)


def finalize_local_mask(mask: np.ndarray, specification: dict[str, Any]) -> np.ndarray:
    if not np.all(np.isfinite(mask)):
        raise ValueError("Local mask produced non-finite coverage values.")
    if specification.get("invert", False):
        mask = 1.0 - mask
    opacity = float(np.clip(specification.get("opacity", 1.0), 0.0, 1.0))
    result = np.clip(mask * opacity, 0.0, 1.0)
    if not np.all(np.isfinite(result)):
        raise ValueError("Local mask produced non-finite coverage values.")
    return result


def _build_local_mask(
    rgb: np.ndarray,
    specification: dict[str, Any],
    x: np.ndarray,
    y: np.ndarray,
    depth: int,
    leaf_counter: list[int],
) -> np.ndarray:
    if depth > MAX_MASK_DEPTH:
        raise ValueError(f"Local mask exceeds the maximum mask depth of {MAX_MASK_DEPTH}.")
    mask_type = specification.get("type")
    if mask_type == "luminance":
        leaf_counter[0] += 1
        luma = np.clip(rgb @ LUMA, 0.0, 1.0)
        low = float(specification.get("min", 0.0))
        high = float(specification.get("max", 1.0))
        feather = max(float(specification.get("feather", 0.08)), 1e-4)
        mask = smoothstep(low - feather, low + feather, luma)
        mask *= 1.0 - smoothstep(high - feather, high + feather, luma)
    elif mask_type == "color":
        leaf_counter[0] += 1
        hue, sat, _ = rgb_hsv_components(np.clip(rgb, 0.0, 1.0))
        center = float(specification.get("hue", 0.0))
        width_degrees = max(float(specification.get("width", 30.0)), 1.0)
        minimum_sat = float(specification.get("min_saturation", 0.05))
        mask = circular_hue_weight(hue, center, width_degrees)
        mask *= smoothstep(minimum_sat, min(minimum_sat + 0.2, 1.0), sat)
    elif mask_type == "linear":
        leaf_counter[0] += 1
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
        leaf_counter[0] += 1
        center = specification.get("center", [0.5, 0.5])
        radius = specification.get("radius", [0.35, 0.35])
        cx, cy = float(center[0]), float(center[1])
        rx, ry = max(float(radius[0]), 1e-4), max(float(radius[1]), 1e-4)
        distance = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
        feather = float(np.clip(specification.get("feather", 0.35), 0.0, 0.99))
        mask = 1.0 - smoothstep(1.0 - feather, 1.0, distance)
    elif mask_type == "composite":
        operation = specification.get("operation")
        inputs = specification.get("inputs")
        if (
            not isinstance(operation, str)
            or operation not in COMPOSITE_MASK_OPERATIONS
            or not isinstance(inputs, list)
        ):
            raise ValueError("Composite mask requires a valid operation and inputs array.")
        if operation == "and":
            if not 2 <= len(inputs) <= 8:
                raise ValueError("Composite and mask requires between 2 and 8 inputs.")
        elif operation == "or":
            if not 2 <= len(inputs) <= 8:
                raise ValueError("Composite or mask requires between 2 and 8 inputs.")
        elif len(inputs) != 2:
            raise ValueError("Composite subtract mask requires exactly two inputs.")
        child_masks = [
            _build_local_mask(rgb, child, x, y, depth + 1, leaf_counter)
            for child in inputs
        ]
        if operation == "and":
            mask = child_masks[0]
            for child_mask in child_masks[1:]:
                mask = np.minimum(mask, child_mask)
        elif operation == "or":
            mask = child_masks[0]
            for child_mask in child_masks[1:]:
                mask = np.maximum(mask, child_mask)
        else:
            mask = np.clip(child_masks[0] - child_masks[1], 0.0, 1.0)
    else:
        raise ValueError("Local mask type must be luminance, color, linear, radial, or composite.")
    if leaf_counter[0] > MAX_MASK_LEAVES:
        raise ValueError(f"Local mask exceeds the maximum of {MAX_MASK_LEAVES} leaf masks.")
    return finalize_local_mask(mask, specification)


def build_local_mask(rgb: np.ndarray, specification: dict[str, Any]) -> np.ndarray:
    height, width = rgb.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    x = xx.astype(np.float32) / max(width - 1, 1)
    y = yy.astype(np.float32) / max(height - 1, 1)
    return _build_local_mask(rgb, specification, x, y, depth=1, leaf_counter=[0])


def apply_local_adjustments(
    rgb: np.ndarray,
    payload: Any,
    rendering: str = "legacy",
) -> np.ndarray:
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
        variant = apply_adjustment_bundle(result, local_parameters(adjustments, rendering))
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


def grade_pixels(
    rgb: np.ndarray,
    args: argparse.Namespace,
    diagnostics: dict[str, Any] | None = None,
) -> np.ndarray:
    result = apply_denoise(rgb, args.denoise)
    result = apply_tonal_adjustments(result, args)
    rendering = getattr(args, "rendering", "legacy")
    result = apply_local_adjustments(result, args.local_corrections, rendering)
    result = apply_presence(
        result,
        getattr(args, "dehaze", 0.0),
        getattr(args, "clarity", 0.0),
        getattr(args, "texture", 0.0),
    )
    gamut_mapping = getattr(args, "gamut_mapping", "clip")
    if rendering == "perceptual":
        result = apply_perceptual_color(result, args.vibrance, args.saturation)
    else:
        result = apply_color(result, args.vibrance, args.saturation)
    adjustments = {
        name: (
            getattr(args, f"{name}_hue"),
            getattr(args, f"{name}_sat"),
            getattr(args, f"{name}_lum"),
        )
        for name in HUE_CENTERS
    }
    if rendering == "perceptual":
        result = apply_perceptual_selective_color(result, adjustments)
        result = apply_perceptual_color_grading(
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
    else:
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
    mapping_stages: list[dict[str, Any]] = []
    if rendering != "legacy" or gamut_mapping != "clip":
        result, mapping = apply_gamut_mapping(result, gamut_mapping)
        mapping_stages.append({"stage": "post_color", **mapping})
    result = apply_local_adjustments(result, args.local_adjustments, rendering)
    if rendering != "legacy" or gamut_mapping != "clip":
        result, mapping = apply_gamut_mapping(result, gamut_mapping)
        mapping_stages.append({"stage": "final", **mapping})
        if diagnostics is not None:
            diagnostics["gamut_mapping_stages"] = mapping_stages
    result = apply_sharpen(result, args.sharpen, args.sharpen_radius)
    return np.clip(result, 0.0, 1.0)


def deterministic_tpdf(shape: tuple[int, int, int]) -> np.ndarray:
    """Return coordinate-hashed zero-mean TPDF noise in one-LSB units."""
    if len(shape) != 3 or shape[2] != 3:
        raise ValueError("TPDF noise expects an RGB image shape.")
    height, width, _ = shape
    y, x, channel = np.ogrid[:height, :width, :3]

    def uniform(salt: int) -> np.ndarray:
        value = (
            x.astype(np.uint64) * np.uint64(0x1F123BB5)
            + y.astype(np.uint64) * np.uint64(0x5F356495)
            + channel.astype(np.uint64) * np.uint64(0x9E3779B9)
            + np.uint64(salt)
        ) & np.uint64(0xFFFFFFFF)
        value ^= value >> np.uint64(16)
        value = (value * np.uint64(0x7FEB352D)) & np.uint64(0xFFFFFFFF)
        value ^= value >> np.uint64(15)
        value = (value * np.uint64(0x846CA68B)) & np.uint64(0xFFFFFFFF)
        value ^= value >> np.uint64(16)
        return (value.astype(np.float64) + 0.5) / 4294967296.0

    return (uniform(0xA511E9B3) - uniform(0x63D83595)).astype(np.float32)


def save_image(
    path: Path,
    rgb: np.ndarray,
    alpha: np.ndarray | None,
    meta: dict[str, Any],
    jpeg_quality: int = 95,
    png_compress: int = 6,
    png_bit_depth: int = 8,
    png_dither: str = "none",
) -> None:
    require_supported(path)
    suffix = path.suffix.lower()
    if png_bit_depth not in {8, 16}:
        raise ValueError("PNG bit depth must be 8 or 16.")
    if png_dither not in PNG_DITHER_MODES:
        raise ValueError("PNG dither must be none or tpdf.")
    if suffix in {".jpg", ".jpeg"} and (png_bit_depth != 8 or png_dither != "none"):
        raise ValueError("png_bit_depth and png_dither apply only to PNG output.")
    if png_bit_depth == 16 and png_dither != "none":
        raise ValueError("TPDF dithering is only supported for 8-bit PNG output.")
    if suffix == ".png" and png_bit_depth == 16:
        rgb16 = np.rint(np.clip(rgb, 0.0, 1.0) * 65535.0).astype(np.uint16)
        alpha16 = (
            None
            if alpha is None
            else np.rint(np.clip(alpha, 0.0, 1.0) * 65535.0).astype(np.uint16)
        )
        write_png16(path, rgb16, alpha16, meta, compression=png_compress)
        return

    quantization_input = np.clip(rgb, 0.0, 1.0)
    if suffix == ".png" and png_dither == "tpdf":
        quantization_input = np.clip(
            quantization_input + deterministic_tpdf(quantization_input.shape) / 255.0,
            0.0,
            1.0,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb8 = np.rint(quantization_input * 255.0).astype(np.uint8)
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

    if suffix in {".jpg", ".jpeg"}:
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
    output_is_png = output.suffix.lower() == ".png"
    if not output_is_png and (settings.png_bit_depth != 8 or settings.png_dither != "none"):
        raise ValueError("png_bit_depth and png_dither require a PNG output path.")
    if settings.png_bit_depth == 16 and not output_is_png:
        raise ValueError("16-bit output is supported only for PNG.")
    if settings.png_dither == "tpdf" and (not output_is_png or settings.png_bit_depth != 8):
        raise ValueError("TPDF dithering requires 8-bit PNG output.")
    strict_color = (
        settings.rendering != "legacy"
        or settings.gamut_mapping != "clip"
        or settings.png_bit_depth == 16
    )
    rgb, alpha, meta = load_image(
        source,
        strict_color_management=strict_color,
        preserve_png16=settings.png_bit_depth == 16,
    )
    before = image_metrics(rgb, alpha)
    diagnostics: dict[str, Any] = {}
    graded = grade_pixels(rgb, settings, diagnostics)
    save_image(
        output,
        graded,
        alpha,
        meta,
        settings.jpeg_quality,
        settings.png_compress,
        settings.png_bit_depth,
        settings.png_dither,
    )
    check_rgb, check_alpha, check_meta = load_image(
        output,
        preserve_png16=output_is_png and settings.png_bit_depth == 16,
    )
    if meta["size"] != check_meta["size"]:
        output.unlink(missing_ok=True)
        raise RuntimeError("Output dimensions changed; output was removed.")
    if bool(alpha is not None) != bool(check_alpha is not None):
        output.unlink(missing_ok=True)
        raise RuntimeError("Output alpha presence changed; output was removed.")
    alpha_scale = 65535.0 if output_is_png and settings.png_bit_depth == 16 else 255.0
    alpha_dtype = np.uint16 if alpha_scale == 65535.0 else np.uint8
    if alpha is not None and not np.array_equal(
        np.rint(alpha * alpha_scale).astype(alpha_dtype),
        np.rint(check_alpha * alpha_scale).astype(alpha_dtype),
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
        "processing": {
            "curve_working_space": "encoded_srgb_[0,1]",
            "curve_interpolation": "piecewise_linear",
            "curve_order": ["master_luma_curve", "rgb_channel_curves"],
            "active_channel_curves": [
                channel
                for channel in CHANNEL_NAMES
                if settings.channel_curves.get(channel) is not None
            ],
        },
        "output_encoding": {
            "format": check_meta["format"],
            "source_bit_depth": meta["source_bit_depth"],
            "output_bit_depth": check_meta["source_bit_depth"],
            "png_dither": settings.png_dither if output_is_png else "not_applicable",
            "icc_input_status": meta["icc_status"],
            "icc_output": "srgb" if meta.get("icc_profile") else "none",
            "libraries": runtime_versions(),
        },
    }
    if strict_color or diagnostics.get("gamut_mapping_stages"):
        stages = diagnostics.get("gamut_mapping_stages", [])
        result["processing"]["color_management"] = {
            "rendering": settings.rendering,
            "working_space": "oklab_oklch_d65_srgb" if settings.rendering == "perceptual" else "legacy_srgb_hsv",
            "gamut_mapping": settings.gamut_mapping,
            "gamut_mapping_stages": stages,
            "out_of_gamut_ratio_before": max(
                (stage["out_of_gamut_ratio_before"] for stage in stages),
                default=0.0,
            ),
            "out_of_gamut_ratio_after": (
                stages[-1]["out_of_gamut_ratio_after"] if stages else 0.0
            ),
        }
    if meta["warnings"]:
        result["warnings"] = list(meta["warnings"])
    active_global_presence = [
        name
        for name in ("dehaze", "clarity", "texture")
        if abs(float(getattr(settings, name, 0.0))) >= 1e-12
    ]
    active_local_presence: list[dict[str, Any]] = []
    for stage_name in ("local_corrections", "local_adjustments"):
        for index, item in enumerate(getattr(settings, stage_name, [])):
            controls = [
                name
                for name in ("clarity", "texture")
                if abs(float(item["adjustments"].get(name, 0.0))) >= 1e-12
            ]
            if controls:
                active_local_presence.append(
                    {"stage": stage_name, "index": index, "controls": controls}
                )
    if active_global_presence or active_local_presence:
        result["processing"]["presence"] = {
            "working_signal": "encoded_srgb_luminance_float32",
            "method": "deterministic_multiscale_luminance_reconstruction",
            "global_order": ["dehaze", "clarity", "texture"],
            "active_global": active_global_presence,
            "active_local": active_local_presence,
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
    channel_difference = None
    if same_geometry:
        first_rgb, first_alpha, _ = load_image(original)
        second_rgb, _, _ = load_image(graded)
        visible = (
            np.ones(first_rgb.shape[:2], dtype=bool)
            if first_alpha is None
            else first_alpha[..., 0] > 0.01
        )
        differences = second_rgb[visible] - first_rgb[visible]
        absolute = np.abs(differences)
        channel_difference = {
            channel: {
                "mean_signed": round(float(np.mean(differences[:, index])), 6),
                "mean_absolute": round(float(np.mean(absolute[:, index])), 6),
                "p95_absolute": round(float(np.percentile(absolute[:, index], 95)), 6),
                "max_absolute": round(float(np.max(absolute[:, index])), 6),
            }
            for index, channel in enumerate(CHANNEL_NAMES)
        }
    return {
        "original": first,
        "graded": second,
        "rgb_channel_difference": channel_difference,
        "output_encoding_difference": {
            "original_bit_depth": first["bit_depth"],
            "graded_bit_depth": second["bit_depth"],
            "same_bit_depth": first["bit_depth"] == second["bit_depth"],
            "original_icc_status": first["color_management"]["icc_status"],
            "graded_icc_status": second["color_management"]["icc_status"],
        },
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
    parser.add_argument(
        "--skip-update-check",
        action="store_true",
        help="Skip the best-effort update check when another grade in this batch already performs it",
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
        if args.command == "grade" and not args.skip_update_check:
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
