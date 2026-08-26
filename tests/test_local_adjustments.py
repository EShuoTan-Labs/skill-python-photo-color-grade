from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from test_legacy_regression import load_module, recipe
from test_masks import gradient_rgb, leaf


def load_settings(tmp_path: Path, parameters: dict):
    photo_grade = load_module()
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe(parameters)), encoding="utf-8")
    return photo_grade, photo_grade.load_recipe(recipe_path)


def local_item(adjustments: dict, *, opacity: float = 1.0) -> dict:
    return {
        "mask": leaf(
            "radial",
            center=[0.5, 0.5],
            radius=[0.42, 0.7],
            feather=0.65,
            opacity=opacity,
        ),
        "adjustments": adjustments,
    }


@pytest.mark.parametrize("stage", ["local_corrections", "local_adjustments"])
def test_local_clarity_and_texture_validate_in_both_stages(tmp_path: Path, stage: str) -> None:
    _, (settings, expanded) = load_settings(
        tmp_path,
        {stage: [local_item({"clarity": 1, "texture": -1})]},
    )

    assert settings.__dict__[stage][0]["adjustments"] == {"clarity": 1, "texture": -1}
    assert expanded["parameters"][stage][0]["adjustments"] == {"clarity": 1, "texture": -1}


@pytest.mark.parametrize(
    ("adjustments", "message"),
    [
        ({"dehaze": 0.2}, "unsupported keys"),
        ({"clarity": 1.01}, "between -1.0 and 1.0"),
        ({"texture": -1.01}, "between -1.0 and 1.0"),
        ({"clarity": float("inf")}, "finite number"),
        ({"texture": False}, "finite number"),
    ],
)
def test_local_presence_rejects_dehaze_and_invalid_values(
    tmp_path: Path,
    adjustments: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        load_settings(tmp_path, {"local_adjustments": [local_item(adjustments)]})


def test_local_presence_computes_full_variant_then_blends_float_mask() -> None:
    photo_grade = load_module()
    rgb = gradient_rgb(81, 151)
    item = local_item({"clarity": 0.75, "texture": 0.55})
    mask = photo_grade.build_local_mask(rgb, item["mask"])
    variant = photo_grade.apply_adjustment_bundle(
        rgb,
        photo_grade.local_parameters(item["adjustments"]),
    )
    expected = rgb * (1.0 - mask[..., None]) + variant * mask[..., None]

    actual = photo_grade.apply_local_adjustments(rgb, [item])

    assert np.array_equal(actual, expected)
    assert np.any(mask == 0.0)
    assert np.any(mask == 1.0)
    assert np.any((mask > 0.0) & (mask < 1.0))
    assert np.array_equal(actual[mask == 0.0], rgb[mask == 0.0])
    assert np.array_equal(actual[mask == 1.0], variant[mask == 1.0])


def test_zero_opacity_local_presence_is_pixel_exact() -> None:
    photo_grade = load_module()
    rgb = gradient_rgb(65, 129)
    output = photo_grade.apply_local_adjustments(
        rgb,
        [local_item({"clarity": 1.0, "texture": 1.0}, opacity=0.0)],
    )
    assert np.array_equal(output, rgb)


def test_feathered_local_presence_has_no_hard_mask_seam() -> None:
    photo_grade = load_module()
    width = 513
    x = np.arange(width, dtype=np.float32)
    luma = 0.5 + 0.08 * np.sin(2.0 * np.pi * 32.0 * x / width)
    rgb = np.repeat(np.repeat(luma[None, :, None], 65, axis=0), 3, axis=2)
    output = photo_grade.apply_local_adjustments(
        rgb,
        [local_item({"clarity": 0.8, "texture": 0.5})],
    )
    delta = (output - rgb) @ photo_grade.LUMA

    assert np.all(np.isfinite(output))
    assert float(np.max(np.abs(np.diff(delta, axis=1)))) < 0.012


def test_runtime_local_parameter_guard_rejects_dehaze_if_validation_is_bypassed() -> None:
    photo_grade = load_module()
    with pytest.raises(ValueError, match="Unsupported local adjustment keys"):
        photo_grade.local_parameters({"dehaze": 0.2})

