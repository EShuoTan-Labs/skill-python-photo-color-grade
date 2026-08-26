from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from test_legacy_regression import ROOT, SCRIPT, load_module, recipe


def load_settings(tmp_path: Path, parameters: dict):
    photo_grade = load_module()
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe(parameters)), encoding="utf-8")
    return photo_grade, photo_grade.load_recipe(recipe_path)


def grayscale_wave(cycles: int, width: int = 1024, height: int = 64) -> np.ndarray:
    x = np.arange(width, dtype=np.float32)
    luma = 0.5 + 0.1 * np.sin(2.0 * np.pi * cycles * x / width)
    return np.repeat(np.repeat(luma[None, :, None], height, axis=0), 3, axis=2).astype(np.float32)


def response_rms(photo_grade, rgb: np.ndarray, **controls: float) -> float:
    before = rgb @ photo_grade.LUMA
    after = photo_grade.apply_presence(rgb, **controls) @ photo_grade.LUMA
    return float(np.sqrt(np.mean((after - before) ** 2)))


def test_presence_schema_expands_defaults_and_accepts_boundaries(tmp_path: Path) -> None:
    _, (settings, expanded) = load_settings(
        tmp_path,
        {"presence": {"dehaze": -1, "clarity": 1, "texture": 0.25}},
    )

    assert settings.dehaze == -1.0
    assert settings.clarity == 1.0
    assert settings.texture == 0.25
    assert expanded["parameters"]["presence"] == {
        "dehaze": -1.0,
        "clarity": 1.0,
        "texture": 0.25,
    }

    _, (omitted, omitted_expanded) = load_settings(tmp_path, {})
    assert (omitted.dehaze, omitted.clarity, omitted.texture) == (0.0, 0.0, 0.0)
    assert omitted_expanded["parameters"]["presence"] == {
        "dehaze": 0.0,
        "clarity": 0.0,
        "texture": 0.0,
    }


@pytest.mark.parametrize(
    ("presence", "message"),
    [
        ({"dehaze": 1.01}, "between -1.0 and 1.0"),
        ({"clarity": -1.01}, "between -1.0 and 1.0"),
        ({"texture": float("nan")}, "finite number"),
        ({"texture": True}, "finite number"),
        ({"amount": 0.2}, "unsupported keys"),
    ],
)
def test_presence_schema_rejects_invalid_values(tmp_path: Path, presence: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_settings(tmp_path, {"presence": presence})


def test_neutral_presence_is_an_exact_skip_and_constants_stay_constant() -> None:
    photo_grade = load_module()
    rng = np.random.default_rng(20260826)
    rgb = rng.random((31, 47, 3), dtype=np.float32)
    assert photo_grade.apply_presence(rgb, 0, 0, 0) is rgb

    for level in (0.0, 0.18, 0.5, 0.92, 1.0):
        constant = np.full((37, 53, 3), level, dtype=np.float32)
        for controls in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1), (1, 1, 1)):
            output = photo_grade.apply_presence(constant, *controls)
            assert np.array_equal(output, constant)


def test_multiscale_frequency_responses_are_distinct() -> None:
    photo_grade = load_module()
    low = grayscale_wave(2)
    middle = grayscale_wave(64)
    high = grayscale_wave(256)

    low_dehaze = response_rms(photo_grade, low, dehaze=1)
    low_clarity = response_rms(photo_grade, low, clarity=1)
    middle_clarity = response_rms(photo_grade, middle, clarity=1)
    middle_texture = response_rms(photo_grade, middle, texture=1)
    high_clarity = response_rms(photo_grade, high, clarity=1)
    high_texture = response_rms(photo_grade, high, texture=1)

    assert low_dehaze > 8.0 * low_clarity
    assert middle_clarity > 4.0 * middle_texture
    assert high_texture > 1.5 * high_clarity


def test_step_edges_are_finite_and_limited_to_two_percent_overshoot() -> None:
    photo_grade = load_module()
    rgb = np.full((96, 513, 3), 0.2, dtype=np.float32)
    rgb[:, 256:, :] = 0.8

    output = photo_grade.apply_presence(rgb, 1, 1, 1)

    assert np.all(np.isfinite(output))
    assert float(np.min(output)) >= 0.18 - 1e-6
    assert float(np.max(output)) <= 0.82 + 1e-6
    assert np.all((output >= 0.0) & (output <= 1.0))


def test_dehaze_expands_low_contrast_range_without_breaking_gray_monotonicity() -> None:
    photo_grade = load_module()
    ramp = np.linspace(0.35, 0.65, 513, dtype=np.float32)
    rgb = np.repeat(np.repeat(ramp[None, :, None], 64, axis=0), 3, axis=2)

    output = photo_grade.apply_presence(rgb, dehaze=1)
    before_luma = rgb @ photo_grade.LUMA
    after_luma = output @ photo_grade.LUMA

    assert float(np.ptp(after_luma)) > float(np.ptp(before_luma)) + 0.02
    assert float(np.min(np.diff(after_luma[32]))) >= -1e-7


def test_presence_preserves_neutrals_and_hue_on_skin_and_blue_gradients() -> None:
    photo_grade = load_module()
    x = np.linspace(0.0, 1.0, 513, dtype=np.float32)
    gray = np.stack((0.18 + 0.65 * x,) * 3, axis=1)
    skin = np.stack((0.32 + 0.34 * x, 0.18 + 0.22 * x, 0.11 + 0.14 * x), axis=1)
    blue = np.stack((0.08 + 0.12 * x, 0.22 + 0.25 * x, 0.42 + 0.38 * x), axis=1)
    rgb = np.stack((gray, skin, blue), axis=0).astype(np.float32)

    output = photo_grade.apply_presence(rgb, 1, 1, 1)
    assert np.max(np.abs(output[0, :, 0] - output[0, :, 1])) < 2e-6
    assert np.max(np.abs(output[0, :, 1] - output[0, :, 2])) < 2e-6

    before_hue, before_sat, _ = photo_grade.rgb_hsv_components(rgb)
    after_hue, _, _ = photo_grade.rgb_hsv_components(output)
    hue_error = np.abs((after_hue - before_hue + 180.0) % 360.0 - 180.0)
    colored = before_sat > 0.05
    assert float(np.max(hue_error[colored])) < 0.01


def test_flat_white_noise_is_not_aggressively_amplified() -> None:
    photo_grade = load_module()
    rng = np.random.default_rng(1937)
    luma = np.clip(0.5 + rng.normal(0.0, 0.025, (128, 256)), 0.0, 1.0).astype(np.float32)
    rgb = np.repeat(luma[..., None], 3, axis=2)
    source_std = float(np.std(luma))

    for controls in ((0, 1, 0), (0, 0, 1), (0, 1, 1)):
        output_luma = photo_grade.apply_presence(rgb, *controls) @ photo_grade.LUMA
        assert float(np.std(output_luma)) <= 1.16 * source_std


@pytest.mark.parametrize(
    "controls",
    [
        (-1.0, -1.0, -1.0),
        (1.0, 1.0, 1.0),
        (1.0, -1.0, 0.5),
        (-0.6, 0.8, -0.4),
    ],
)
def test_extreme_presence_is_finite_in_gamut_and_deterministic(controls: tuple[float, float, float]) -> None:
    photo_grade = load_module()
    rng = np.random.default_rng(7103)
    rgb = rng.random((73, 119, 3), dtype=np.float32)

    first = photo_grade.apply_presence(rgb, *controls)
    second = photo_grade.apply_presence(rgb, *controls)

    assert np.array_equal(first, second)
    assert np.all(np.isfinite(first))
    assert np.all((first >= 0.0) & (first <= 1.0))


def test_invalid_presence_cli_fails_before_creating_output(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    recipe_path = tmp_path / "recipe.json"
    Image.fromarray(np.full((12, 16, 3), 128, dtype=np.uint8), "RGB").save(source)
    recipe_path.write_text(
        json.dumps(recipe({"presence": {"clarity": 1.2}})),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "grade",
            str(source),
            str(output),
            "--recipe",
            str(recipe_path),
            "--skip-update-check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stderr.startswith("error: ")
    assert not output.exists()


def test_presence_cli_is_deterministic_preserves_alpha_and_reports_active_stages(tmp_path: Path) -> None:
    y, x = np.mgrid[0:48, 0:72]
    rgb = np.stack((x / 71, y / 47, (x + y) / 118), axis=2)
    alpha = ((x * 17 + y * 11) % 256).astype(np.uint8)[..., None]
    rgba = np.concatenate((np.rint(rgb * 255).astype(np.uint8), alpha), axis=2)
    source = tmp_path / "source.png"
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    recipe_path = tmp_path / "recipe.json"
    Image.fromarray(rgba, "RGBA").save(source)
    recipe_path.write_text(
        json.dumps(recipe({"presence": {"dehaze": 0.4, "clarity": 0.6, "texture": 0.3}})),
        encoding="utf-8",
    )

    reports = []
    for output in (first, second):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "grade",
                str(source),
                str(output),
                "--recipe",
                str(recipe_path),
                "--show-parameters",
                "--skip-update-check",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        reports.append(json.loads(completed.stdout))

    assert first.read_bytes() == second.read_bytes()
    assert np.array_equal(np.asarray(Image.open(source))[..., 3], np.asarray(Image.open(first))[..., 3])
    assert reports[0]["parameters"]["presence"] == {
        "dehaze": 0.4,
        "clarity": 0.6,
        "texture": 0.3,
    }
    assert reports[0]["processing"]["presence"]["active_global"] == [
        "dehaze",
        "clarity",
        "texture",
    ]
