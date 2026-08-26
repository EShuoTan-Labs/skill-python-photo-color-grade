from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from test_legacy_regression import load_module, recipe


def load_settings(tmp_path: Path, parameters: dict):
    photo_grade = load_module()
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe(parameters)), encoding="utf-8")
    return photo_grade, photo_grade.load_recipe(recipe_path)


def test_master_curve_runs_before_channel_curves(tmp_path: Path) -> None:
    photo_grade, (parameters, _) = load_settings(
        tmp_path,
        {
            "curve": [[0, 0], [0.5, 0.65], [1, 1]],
            "channel_curves": {"red": [[0, 0.1], [0.5, 0.4], [1, 0.9]]},
        },
    )
    rgb = np.array([[[0.18, 0.42, 0.76], [0.8, 0.3, 0.1]]], dtype=np.float32)

    after_master = photo_grade.apply_curve(rgb, parameters.curve)
    expected = after_master.copy()
    expected[..., 0] = np.interp(
        np.clip(after_master[..., 0], 0.0, 1.0),
        [0.0, 0.5, 1.0],
        [0.1, 0.4, 0.9],
    )

    actual = photo_grade.apply_tonal_adjustments(rgb, parameters)
    assert np.array_equal(actual, expected)


def test_only_red_curve_preserves_green_and_blue_exactly() -> None:
    photo_grade = load_module()
    rgb = np.array(
        [[[0.0, 0.2, 0.8], [0.25, 0.4, 0.6], [0.75, 0.6, 0.4], [1.0, 0.8, 0.2]]],
        dtype=np.float32,
    )
    output = photo_grade.apply_channel_curves(rgb, {"red": "0:0.1,0.5:0.65,1:0.9"})

    assert np.array_equal(output[..., 1:], rgb[..., 1:])
    assert np.allclose(output[..., 0], [0.1, 0.375, 0.775, 0.9])


@pytest.mark.parametrize(("active_channel", "active_index"), [("red", 0), ("green", 1), ("blue", 2)])
def test_each_channel_curve_operates_independently(active_channel: str, active_index: int) -> None:
    photo_grade = load_module()
    rgb = np.array([[[0.2, 0.4, 0.6], [0.8, 0.6, 0.4]]], dtype=np.float32)

    output = photo_grade.apply_channel_curves(rgb, {active_channel: "0:0.1,1:0.9"})

    inactive = [index for index in range(3) if index != active_index]
    assert np.array_equal(output[..., inactive], rgb[..., inactive])
    assert np.allclose(output[..., active_index], 0.1 + 0.8 * rgb[..., active_index])


def test_omitted_and_empty_curves_skip_without_clipping(tmp_path: Path) -> None:
    photo_grade, (omitted, _) = load_settings(tmp_path, {})
    outside_domain = np.array([[[-0.25, 0.5, 1.25]]], dtype=np.float32)

    assert photo_grade.apply_channel_curves(outside_domain, None) is outside_domain
    assert photo_grade.apply_channel_curves(outside_domain, {}) is outside_domain
    assert photo_grade.apply_channel_curves(outside_domain, omitted.channel_curves) is outside_domain


def test_identity_lifted_black_compressed_white_and_s_curves() -> None:
    photo_grade = load_module()
    ramp = np.linspace(0.0, 1.0, 257, dtype=np.float32)[None, :, None]
    rgb = np.repeat(ramp, 3, axis=2)

    identity = photo_grade.apply_channel_curves(
        rgb,
        {channel: "0:0,1:1" for channel in photo_grade.CHANNEL_NAMES},
    )
    lifted = photo_grade.apply_channel_curves(rgb, {"red": "0:0.1,1:1"})
    compressed = photo_grade.apply_channel_curves(rgb, {"green": "0:0,1:0.85"})
    s_curve = photo_grade.apply_channel_curves(rgb, {"blue": "0:0,0.25:0.18,0.75:0.82,1:1"})

    assert np.array_equal(identity, rgb)
    assert lifted[0, 0, 0] == pytest.approx(0.1)
    assert compressed[0, -1, 1] == pytest.approx(0.85)
    assert s_curve[0, 64, 2] < rgb[0, 64, 2]
    assert s_curve[0, 192, 2] > rgb[0, 192, 2]


@pytest.mark.parametrize(
    ("channel_curves", "message"),
    [
        ({"cyan": []}, "unsupported keys"),
        ({"red": [[0.1, 0], [1, 1]]}, "begin at x=0"),
        ({"red": [[0, 0], [0.7, 0.6], [0.6, 0.7], [1, 1]]}, "strictly increasing"),
        ({"red": [[0, 0], [0.5, 1.1], [1, 1]]}, "between 0.0 and 1.0"),
        ({"red": [[0, 0]]}, "at least two points"),
        ({"red": [[0, 0], [float("nan"), 0.5], [1, 1]]}, "finite number"),
        ({"red": [[0, 0], [True, 0.5], [1, 1]]}, "finite number"),
    ],
)
def test_channel_curve_validation_is_strict(
    tmp_path: Path,
    channel_curves: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        load_settings(tmp_path, {"channel_curves": channel_curves})


def test_local_channel_curves_are_validated_and_run_after_local_master_curve(tmp_path: Path) -> None:
    photo_grade, (parameters, expanded) = load_settings(
        tmp_path,
        {
            "local_adjustments": [
                {
                    "mask": {
                        "type": "linear",
                        "start": [0, 0],
                        "end": [1, 0],
                        "opacity": 1,
                        "invert": False,
                    },
                    "adjustments": {
                        "curve": [[0, 0], [0.5, 0.6], [1, 1]],
                        "channel_curves": {"blue": [[0, 0.2], [1, 0.8]]},
                    },
                }
            ]
        },
    )
    rgb = np.full((2, 3, 3), 0.5, dtype=np.float32)
    output = photo_grade.apply_local_adjustments(rgb, parameters.local_adjustments)

    local = photo_grade.local_parameters(parameters.local_adjustments[0]["adjustments"])
    variant = photo_grade.apply_tonal_adjustments(rgb, local)
    mask = photo_grade.build_local_mask(rgb, parameters.local_adjustments[0]["mask"])
    expected = rgb * (1 - mask[..., None]) + variant * mask[..., None]
    assert np.array_equal(output, expected)
    assert expanded["parameters"]["local_adjustments"][0]["adjustments"]["channel_curves"]["blue"]


def test_channel_analysis_matches_numpy_and_ignores_transparent_pixels() -> None:
    photo_grade = load_module()
    y, x = np.mgrid[0:6, 0:6]
    rgb = np.stack((x / 5, y / 5, (x + y) / 10), axis=2).astype(np.float32)
    alpha = np.ones((6, 6, 1), dtype=np.float32)
    rgb[0, 0] = [1, 0, 1]
    alpha[0, 0, 0] = 0
    visible_values = rgb[alpha[..., 0] > 0.01]

    metrics = photo_grade.image_metrics(rgb, alpha)

    for index, channel in enumerate(photo_grade.CHANNEL_NAMES):
        report = metrics["rgb_channels"][channel]
        assert report["mean"] == round(float(np.mean(visible_values[:, index])), 5)
        expected_percentiles = np.percentile(visible_values[:, index], [1, 5, 25, 50, 75, 95, 99])
        assert list(report["percentiles"]) == ["1", "5", "25", "50", "75", "95", "99"]
        assert list(report["percentiles"].values()) == [round(float(value), 5) for value in expected_percentiles]
        assert len(report["histogram_64"]) == 64
        assert sum(report["histogram_64"]) == pytest.approx(1.0, abs=1e-12)
    assert metrics["rgb_channels"]["red"]["high_clip_ratio"] == round(
        float(np.mean(visible_values[:, 0] >= 0.998)), 6
    )
    assert len(metrics["spatial_rgb_mean_grid_3x3"]) == 3
    assert metrics["spatial_rgb_mean_grid_3x3"][0][0] == [0.13333, 0.13333, 0.13333]


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.floats(min_value=-2, max_value=3, allow_nan=False, allow_infinity=False, width=32),
        min_size=3,
        max_size=60,
    )
)
def test_active_identity_channel_curve_clips_only_its_defined_input(values: list[float]) -> None:
    photo_grade = load_module()
    red = np.asarray(values, dtype=np.float32)
    rgb = np.stack((red, red * 0.25 - 0.1, red * -0.5 + 0.2), axis=1)[None, ...]

    output = photo_grade.apply_channel_curves(rgb, {"red": "0:0,1:1"})

    assert np.all(np.isfinite(output))
    assert np.all((output[..., 0] >= 0) & (output[..., 0] <= 1))
    assert np.allclose(output[..., 0], np.clip(rgb[..., 0], 0, 1), atol=1e-7)
    assert np.array_equal(output[..., 1:], rgb[..., 1:])
