from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from test_legacy_regression import load_module, recipe


def load_settings(tmp_path: Path, detail: dict):
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(
        json.dumps(recipe({"detail": detail})),
        encoding="utf-8",
    )
    return load_module().load_recipe(recipe_path)


def grayscale(values: np.ndarray) -> np.ndarray:
    return np.repeat(values[..., None], 3, axis=2).astype(np.float32)


def test_detail_schema_expands_defaults_and_accepts_boundaries(tmp_path: Path) -> None:
    settings, expanded = load_settings(
        tmp_path,
        {
            "denoise": 0.2,
            "sharpen": 1.1,
            "sharpen_radius": 1.4,
            "sharpen_threshold": 0.012,
            "sharpen_edge_protection": 0.75,
        },
    )

    assert settings.sharpen_threshold == 0.012
    assert settings.sharpen_edge_protection == 0.75
    assert expanded["parameters"]["detail"] == {
        "denoise": 0.2,
        "sharpen": 1.1,
        "sharpen_radius": 1.4,
        "sharpen_threshold": 0.012,
        "sharpen_edge_protection": 0.75,
    }

    defaults, default_recipe = load_settings(tmp_path, {})
    assert defaults.sharpen_threshold == defaults.sharpen_edge_protection == 0.0
    assert default_recipe["parameters"]["detail"] == {
        "denoise": 0.0,
        "sharpen": 0.0,
        "sharpen_radius": 1.0,
        "sharpen_threshold": 0.0,
        "sharpen_edge_protection": 0.0,
    }


@pytest.mark.parametrize(
    ("detail", "message"),
    [
        ({"sharpen_threshold": -0.01}, "between 0.0 and 1.0"),
        ({"sharpen_threshold": 1.01}, "between 0.0 and 1.0"),
        ({"sharpen_edge_protection": float("nan")}, "finite number"),
        ({"sharpen_edge_protection": True}, "finite number"),
        ({"unknown": 0.1}, "unsupported keys"),
    ],
)
def test_detail_schema_rejects_invalid_new_values(
    tmp_path: Path,
    detail: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        load_settings(tmp_path, detail)


def test_neutral_sharpen_controls_are_exact_skips() -> None:
    photo_grade = load_module()
    rng = np.random.default_rng(20260827)
    rgb = rng.random((43, 67, 3), dtype=np.float32)

    legacy_call = photo_grade.apply_sharpen(rgb, 0.8, 1.2)
    explicit_zero = photo_grade.apply_sharpen(rgb, 0.8, 1.2, 0.0, 0.0)
    disabled = photo_grade.apply_sharpen(rgb, 0.0, 1.2, 0.2, 1.0)

    assert np.array_equal(explicit_zero, legacy_call)
    assert np.array_equal(disabled, rgb)


def test_existing_denoise_reduces_flat_area_impulse_noise() -> None:
    photo_grade = load_module()
    values = np.full((96, 128), 0.5, dtype=np.float32)
    values[::5, ::7] = 0.2
    values[2::5, 3::7] = 0.8
    rgb = grayscale(values)

    output = photo_grade.apply_denoise(rgb, 0.8)

    assert float(np.std(output[..., 0])) < 0.35 * float(np.std(values))
    assert np.all(np.isfinite(output))


def test_sharpen_threshold_suppresses_flat_area_noise() -> None:
    photo_grade = load_module()
    rng = np.random.default_rng(4817)
    values = np.clip(
        0.5 + rng.normal(0.0, 0.004, (128, 192)),
        0.0,
        1.0,
    ).astype(np.float32)
    rgb = grayscale(values)

    unguarded = photo_grade.apply_sharpen(rgb, 1.5, 1.0)
    guarded = photo_grade.apply_sharpen(rgb, 1.5, 1.0, threshold=0.012)
    source_std = float(np.std(values))

    assert float(np.std(unguarded[..., 0])) > 1.5 * source_std
    assert float(np.std(guarded[..., 0])) < 0.6 * float(np.std(unguarded[..., 0]))
    assert float(np.std(guarded[..., 0])) <= 1.08 * source_std


def test_edge_protection_reduces_step_overshoot_and_keeps_fine_texture() -> None:
    photo_grade = load_module()
    step = np.full((64, 257), 0.2, dtype=np.float32)
    step[:, 128:] = 0.8
    step_rgb = grayscale(step)
    unguarded_step = photo_grade.apply_sharpen(step_rgb, 1.5, 1.2)
    guarded_step = photo_grade.apply_sharpen(
        step_rgb,
        1.5,
        1.2,
        edge_protection=1.0,
    )
    baseline_overshoot = max(
        0.2 - float(np.min(unguarded_step)),
        float(np.max(unguarded_step)) - 0.8,
    )
    guarded_overshoot = max(
        0.2 - float(np.min(guarded_step)),
        float(np.max(guarded_step)) - 0.8,
    )

    x = np.arange(512, dtype=np.float32)
    texture = 0.5 + 0.035 * np.sin(2.0 * np.pi * 48.0 * x / 512.0)
    texture_rgb = grayscale(np.repeat(texture[None, :], 48, axis=0))
    unguarded_texture = photo_grade.apply_sharpen(texture_rgb, 1.5, 1.2)
    guarded_texture = photo_grade.apply_sharpen(
        texture_rgb,
        1.5,
        1.2,
        edge_protection=1.0,
    )
    unguarded_gain = float(np.std(unguarded_texture[..., 0]) - np.std(texture))
    guarded_gain = float(np.std(guarded_texture[..., 0]) - np.std(texture))

    assert baseline_overshoot > 0.05
    assert guarded_overshoot < 0.2 * baseline_overshoot
    assert guarded_gain >= 0.75 * unguarded_gain


def test_highlights_blacks_and_saturated_edges_remain_finite_without_fringe() -> None:
    photo_grade = load_module()
    rgb = np.zeros((48, 180, 3), dtype=np.float32)
    rgb[:, 30:60] = 1.0
    rgb[:, 60:90] = [1.0, 0.0, 0.0]
    rgb[:, 90:120] = [0.0, 1.0, 0.0]
    rgb[:, 120:150] = [0.0, 0.0, 1.0]
    rgb[:, 150:] = 0.5

    output = photo_grade.apply_sharpen(rgb, 2.0, 1.5, 0.006, 1.0)

    assert np.all(np.isfinite(output))
    assert np.all((output >= 0.0) & (output <= 1.0))
    assert np.max(np.ptp(output[:, :60], axis=2)) < 1e-6
    assert np.max(output[:, 65:85, 1:]) == 0.0
    assert np.max(output[:, 95:115, (0, 2)]) == 0.0
    assert np.max(output[:, 125:145, :2]) == 0.0


def test_alpha_aware_sharpen_does_not_pull_hidden_color_into_opaque_edge() -> None:
    photo_grade = load_module()
    blue = np.array([32, 64, 192], dtype=np.float32) / 255.0
    red = np.array([255, 0, 0], dtype=np.float32) / 255.0
    rgb = np.empty((48, 96, 3), dtype=np.float32)
    rgb[:, :48] = blue
    rgb[:, 48:] = red
    alpha = np.zeros((48, 96, 1), dtype=np.float32)
    alpha[:, :48] = 1.0

    output = photo_grade.apply_sharpen(
        rgb,
        1.5,
        1.5,
        edge_protection=1.0,
        alpha=alpha,
    )

    assert np.max(np.abs(output[:, :48] - blue)) < 0.006
    assert np.array_equal(alpha[:, :48], np.ones((48, 48, 1), dtype=np.float32))
    assert np.array_equal(alpha[:, 48:], np.zeros((48, 48, 1), dtype=np.float32))
