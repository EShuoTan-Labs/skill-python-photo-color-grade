from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from test_legacy_regression import load_module, recipe


def leaf(mask_type: str, **overrides):
    specifications = {
        "luminance": {
            "type": "luminance",
            "min": 0.2,
            "max": 0.82,
            "feather": 0.12,
            "opacity": 1.0,
            "invert": False,
        },
        "color": {
            "type": "color",
            "hue": 38.0,
            "width": 24.0,
            "min_saturation": 0.08,
            "opacity": 1.0,
            "invert": False,
        },
        "linear": {
            "type": "linear",
            "start": [0.08, 0.12],
            "end": [0.92, 0.78],
            "opacity": 1.0,
            "invert": False,
        },
        "radial": {
            "type": "radial",
            "center": [0.52, 0.46],
            "radius": [0.38, 0.31],
            "feather": 0.42,
            "opacity": 1.0,
            "invert": False,
        },
    }[mask_type]
    return {**specifications, **overrides}


def composite(operation: str, inputs: list[dict], **overrides):
    return {
        "type": "composite",
        "operation": operation,
        "inputs": inputs,
        "opacity": 1.0,
        "invert": False,
        **overrides,
    }


def gradient_rgb(height: int = 67, width: int = 131) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width]
    return np.stack(
        (
            0.05 + 0.9 * x / max(width - 1, 1),
            0.08 + 0.84 * y / max(height - 1, 1),
            0.12 + 0.74 * (x + y) / max(width + height - 2, 1),
        ),
        axis=2,
    ).astype(np.float32)


def legacy_reference_mask(photo_grade, rgb: np.ndarray, specification: dict) -> np.ndarray:
    height, width = rgb.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    x = xx.astype(np.float32) / max(width - 1, 1)
    y = yy.astype(np.float32) / max(height - 1, 1)
    mask_type = specification.get("type")
    if mask_type == "luminance":
        luma = np.clip(rgb @ photo_grade.LUMA, 0.0, 1.0)
        low = float(specification.get("min", 0.0))
        high = float(specification.get("max", 1.0))
        feather = max(float(specification.get("feather", 0.08)), 1e-4)
        mask = photo_grade.smoothstep(low - feather, low + feather, luma)
        mask *= 1.0 - photo_grade.smoothstep(high - feather, high + feather, luma)
    elif mask_type == "color":
        hue, sat, _ = photo_grade.rgb_hsv_components(np.clip(rgb, 0.0, 1.0))
        center = float(specification.get("hue", 0.0))
        width_degrees = max(float(specification.get("width", 30.0)), 1.0)
        minimum_sat = float(specification.get("min_saturation", 0.05))
        mask = photo_grade.circular_hue_weight(hue, center, width_degrees)
        mask *= photo_grade.smoothstep(minimum_sat, min(minimum_sat + 0.2, 1.0), sat)
    elif mask_type == "linear":
        start = specification.get("start", [0.0, 0.0])
        end = specification.get("end", [1.0, 1.0])
        sx, sy = float(start[0]), float(start[1])
        ex, ey = float(end[0]), float(end[1])
        dx, dy = ex - sx, ey - sy
        projection = ((x - sx) * dx + (y - sy) * dy) / (dx * dx + dy * dy)
        mask = photo_grade.smoothstep(0.0, 1.0, projection)
    else:
        center = specification.get("center", [0.5, 0.5])
        radius = specification.get("radius", [0.35, 0.35])
        cx, cy = float(center[0]), float(center[1])
        rx, ry = max(float(radius[0]), 1e-4), max(float(radius[1]), 1e-4)
        distance = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
        feather = float(np.clip(specification.get("feather", 0.35), 0.0, 0.99))
        mask = 1.0 - photo_grade.smoothstep(1.0 - feather, 1.0, distance)
    if specification.get("invert", False):
        mask = 1.0 - mask
    opacity = float(np.clip(specification.get("opacity", 1.0), 0.0, 1.0))
    return np.clip(mask * opacity, 0.0, 1.0)


def validate_tree(tmp_path: Path, mask: dict):
    photo_grade = load_module()
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(
        json.dumps(
            recipe(
                {
                    "local_adjustments": [
                        {"mask": mask, "adjustments": {"exposure": 0.2}}
                    ]
                }
            )
        ),
        encoding="utf-8",
    )
    return photo_grade.load_recipe(recipe_path)


@pytest.mark.parametrize("mask_type", ["luminance", "color", "linear", "radial"])
def test_legacy_leaf_masks_remain_pixel_exact(mask_type: str) -> None:
    photo_grade = load_module()
    rgb = gradient_rgb()
    specification = leaf(mask_type, opacity=0.63, invert=True)

    expected = legacy_reference_mask(photo_grade, rgb, specification)
    actual = photo_grade.build_local_mask(rgb, specification)

    assert np.array_equal(actual, expected)


@pytest.mark.parametrize(("operation", "reference"), [("and", np.minimum), ("or", np.maximum)])
def test_and_or_match_reference_are_commutative_idempotent_and_bounded(operation, reference) -> None:
    photo_grade = load_module()
    rgb = gradient_rgb()
    first = leaf("luminance")
    second = leaf("radial")
    first_mask = photo_grade.build_local_mask(rgb, first)
    second_mask = photo_grade.build_local_mask(rgb, second)

    forward = photo_grade.build_local_mask(rgb, composite(operation, [first, second]))
    reverse = photo_grade.build_local_mask(rgb, composite(operation, [second, first]))
    idempotent = photo_grade.build_local_mask(rgb, composite(operation, [first, first]))

    assert np.array_equal(forward, reference(first_mask, second_mask))
    assert np.array_equal(forward, reverse)
    assert np.array_equal(idempotent, first_mask)
    assert np.all(np.isfinite(forward))
    assert np.all((forward >= 0.0) & (forward <= 1.0))


def test_subtract_is_directional_and_matches_clipped_difference() -> None:
    photo_grade = load_module()
    rgb = gradient_rgb()
    color = leaf("color")
    highlights = leaf("luminance", min=0.62, max=0.98, feather=0.1)
    color_mask = photo_grade.build_local_mask(rgb, color)
    highlight_mask = photo_grade.build_local_mask(rgb, highlights)

    forward = photo_grade.build_local_mask(rgb, composite("subtract", [color, highlights]))
    reverse = photo_grade.build_local_mask(rgb, composite("subtract", [highlights, color]))

    assert np.array_equal(forward, np.clip(color_mask - highlight_mask, 0.0, 1.0))
    assert np.array_equal(reverse, np.clip(highlight_mask - color_mask, 0.0, 1.0))
    assert not np.array_equal(forward, reverse)


def test_nested_node_invert_and_opacity_run_after_composition() -> None:
    photo_grade = load_module()
    rgb = gradient_rgb()
    luminance = leaf("luminance", opacity=0.8, invert=True)
    radial = leaf("radial", opacity=0.65)
    linear = leaf("linear", opacity=0.7)
    inner = composite("or", [radial, linear], opacity=0.75, invert=True)
    tree = composite("and", [luminance, inner], opacity=0.4, invert=True)

    luminance_mask = photo_grade.build_local_mask(rgb, luminance)
    radial_mask = photo_grade.build_local_mask(rgb, radial)
    linear_mask = photo_grade.build_local_mask(rgb, linear)
    inner_expected = (1.0 - np.maximum(radial_mask, linear_mask)) * 0.75
    expected = (1.0 - np.minimum(luminance_mask, inner_expected)) * 0.4

    actual = photo_grade.build_local_mask(rgb, tree)
    assert np.array_equal(actual, expected)


def test_composite_opacity_boundaries_are_exact() -> None:
    photo_grade = load_module()
    rgb = gradient_rgb()
    inputs = [leaf("linear"), leaf("radial")]
    full = photo_grade.build_local_mask(rgb, composite("or", inputs, opacity=1.0))
    zero = photo_grade.build_local_mask(rgb, composite("or", inputs, opacity=0.0))

    assert np.array_equal(
        full,
        np.maximum(
            photo_grade.build_local_mask(rgb, inputs[0]),
            photo_grade.build_local_mask(rgb, inputs[1]),
        ),
    )
    assert np.count_nonzero(zero) == 0


def test_composite_siblings_use_the_same_stage_rgb_snapshot() -> None:
    photo_grade = load_module()
    rgb = gradient_rgb()
    luminance = leaf("luminance", min=0.3, max=0.9, feather=0.08)
    color = leaf("color", hue=45, width=36, min_saturation=0.03)
    tree = composite("and", [luminance, color])

    expected_mask = np.minimum(
        photo_grade.build_local_mask(rgb, luminance),
        photo_grade.build_local_mask(rgb, color),
    )
    actual_mask = photo_grade.build_local_mask(rgb, tree)
    output = photo_grade.apply_local_adjustments(
        rgb,
        [{"mask": tree, "adjustments": {"exposure": 0.35}}],
    )
    variant = photo_grade.apply_adjustment_bundle(
        rgb,
        photo_grade.local_parameters({"exposure": 0.35}),
    )
    expected_output = rgb * (1.0 - expected_mask[..., None]) + variant * expected_mask[..., None]

    assert np.array_equal(actual_mask, expected_mask)
    assert np.array_equal(output, expected_output)


def test_depth_limit_accepts_six_levels_and_rejects_seven(tmp_path: Path) -> None:
    valid = leaf("linear")
    for _ in range(5):
        valid = composite("and", [valid, leaf("radial")])
    validate_tree(tmp_path, valid)

    invalid = composite("and", [valid, leaf("luminance")])
    with pytest.raises(ValueError, match="maximum mask depth of 6"):
        validate_tree(tmp_path, invalid)


def test_leaf_limit_accepts_32_and_rejects_33(tmp_path: Path) -> None:
    groups = [composite("or", [leaf("linear") for _ in range(8)]) for _ in range(4)]
    validate_tree(tmp_path, composite("and", groups))

    too_many = composite("and", [*groups, leaf("radial")])
    with pytest.raises(ValueError, match="maximum of 32 leaf masks"):
        validate_tree(tmp_path, too_many)


def test_runtime_builder_cannot_bypass_depth_or_leaf_limits() -> None:
    photo_grade = load_module()
    rgb = gradient_rgb(9, 11)
    too_deep = leaf("linear")
    for _ in range(6):
        too_deep = composite("and", [too_deep, leaf("radial")])
    groups = [composite("or", [leaf("linear") for _ in range(8)]) for _ in range(4)]
    too_many = composite("and", [*groups, leaf("radial")])

    with pytest.raises(ValueError, match="maximum mask depth of 6"):
        photo_grade.build_local_mask(rgb, too_deep)
    with pytest.raises(ValueError, match="maximum of 32 leaf masks"):
        photo_grade.build_local_mask(rgb, too_many)


@pytest.mark.parametrize(
    ("mask", "message"),
    [
        (composite("and", [leaf("linear")]), "between 2 and 8"),
        (composite("or", [leaf("linear") for _ in range(9)]), "between 2 and 8"),
        (composite("subtract", [leaf("linear")]), "exactly two"),
        (composite("subtract", [leaf("linear") for _ in range(3)]), "exactly two"),
        (composite("xor", [leaf("linear"), leaf("radial")]), "must be one of: and, or, subtract"),
        ({**composite("and", [leaf("linear"), leaf("radial")]), "operation": []}, "must be one of"),
        ({**composite("and", [leaf("linear"), leaf("radial")]), "inputs": {}}, "must be an array"),
        ({**composite("and", [leaf("linear"), leaf("radial")]), "opacity": -0.01}, "between 0.0 and 1.0"),
        ({**composite("and", [leaf("linear"), leaf("radial")]), "opacity": float("nan")}, "finite number"),
        ({**composite("and", [leaf("linear"), leaf("radial")]), "invert": 1}, "true or false"),
        ({**composite("and", [leaf("linear"), leaf("radial")]), "feather": 0.2}, "unsupported keys"),
        ({**leaf("linear"), "feather": 0.2}, "unsupported keys"),
        ({key: value for key, value in leaf("radial").items() if key != "radius"}, "missing required keys"),
    ],
)
def test_recursive_validation_rejects_invalid_nodes(tmp_path: Path, mask: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_tree(tmp_path, mask)


def test_composite_masks_are_continuous_and_finite_on_feathered_boundaries() -> None:
    photo_grade = load_module()
    width = 1025
    hue = np.linspace(0.0, 120.0, width, dtype=np.float32)[None, :]
    saturation = np.ones_like(hue) * 0.8
    value = np.linspace(0.15, 0.95, width, dtype=np.float32)[None, :]
    rgb = np.repeat(photo_grade.hsv_to_rgb(hue, saturation, value), 33, axis=0)
    highlight_radial = composite(
        "and",
        [
            leaf("luminance", min=0.35, max=0.9, feather=0.12),
            leaf("radial", center=[0.55, 0.5], radius=[0.45, 0.7], feather=0.55),
        ],
    )
    color_minus_highlights = composite(
        "subtract",
        [
            leaf("color", hue=55, width=28, min_saturation=0.1),
            leaf("luminance", min=0.72, max=0.99, feather=0.1),
        ],
    )

    for tree in (highlight_radial, color_minus_highlights):
        mask = photo_grade.build_local_mask(rgb, tree)
        assert np.all(np.isfinite(mask))
        assert np.all((mask >= 0.0) & (mask <= 1.0))
        assert float(np.max(np.abs(np.diff(mask, axis=1)))) < 0.03


def test_non_finite_leaf_result_is_rejected() -> None:
    photo_grade = load_module()
    rgb = gradient_rgb()
    rgb[3, 4, 0] = np.nan

    with pytest.raises(ValueError, match="non-finite"):
        photo_grade.build_local_mask(rgb, leaf("luminance"))
