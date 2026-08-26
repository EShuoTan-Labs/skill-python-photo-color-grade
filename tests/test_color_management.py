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
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe(parameters)), encoding="utf-8")
    return load_module().load_recipe(recipe_path)


def test_color_management_schema_defaults_and_boundaries(tmp_path: Path) -> None:
    settings, expanded = load_settings(
        tmp_path,
        {"color_management": {"rendering": "perceptual", "gamut_mapping": "oklch_compress"}},
    )
    assert settings.rendering == "perceptual"
    assert settings.gamut_mapping == "oklch_compress"
    assert expanded["parameters"]["color_management"] == {
        "rendering": "perceptual",
        "gamut_mapping": "oklch_compress",
    }
    defaults, _ = load_settings(tmp_path, {})
    assert (defaults.rendering, defaults.gamut_mapping) == ("legacy", "clip")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"rendering": "aces"}, "rendering must be legacy or perceptual"),
        ({"gamut_mapping": "saturation"}, "gamut_mapping must be clip or oklch_compress"),
        ({"rendering": True}, "rendering must be legacy or perceptual"),
        ({"unknown": 1}, "unsupported keys"),
    ],
)
def test_color_management_schema_rejects_invalid_values(
    tmp_path: Path, payload: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        load_settings(tmp_path, {"color_management": payload})


def test_oklab_round_trip_is_accurate_and_finite() -> None:
    photo_grade = load_module()
    rng = np.random.default_rng(20260826)
    rgb = rng.random((97, 113, 3), dtype=np.float32)
    lab = photo_grade.srgb_to_oklab(rgb)
    restored = photo_grade.oklab_to_srgb(lab)
    assert np.all(np.isfinite(lab))
    assert np.max(np.abs(restored - rgb)) <= 2e-5


def test_oklab_neutral_axis_and_perceptual_saturation_preserve_gray() -> None:
    photo_grade = load_module()
    ramp = np.linspace(0.0, 1.0, 4097, dtype=np.float32)
    gray = np.repeat(ramp[None, :, None], 3, axis=2)
    lab = photo_grade.srgb_to_oklab(gray)
    assert np.max(np.abs(lab[..., 1:])) < 2e-7
    assert np.array_equal(photo_grade.apply_perceptual_color(gray, 1.0, 1.0), gray)


def test_oklch_compression_is_bounded_finite_and_preserves_hue() -> None:
    photo_grade = load_module()
    rng = np.random.default_rng(4219)
    lch = np.stack(
        (
            rng.uniform(0.08, 0.92, 3000),
            rng.uniform(0.18, 0.75, 3000),
            rng.uniform(0.0, 360.0, 3000),
        ),
        axis=1,
    ).reshape(50, 60, 3)
    rgb = photo_grade.oklab_to_srgb(photo_grade.oklch_to_oklab(lch))
    assert photo_grade.out_of_gamut_ratio(rgb) > 0.5
    compressed = photo_grade.oklch_compress(rgb)
    assert np.all(np.isfinite(compressed))
    assert np.all((compressed >= 0.0) & (compressed <= 1.0))
    compressed_lch = photo_grade.oklab_to_oklch(photo_grade.srgb_to_oklab(compressed))
    chromatic = compressed_lch[..., 1] > 1e-4
    hue_error = np.abs((compressed_lch[..., 2] - lch[..., 2] + 180.0) % 360.0 - 180.0)
    assert float(np.median(hue_error[chromatic])) < 1.0


def test_oklch_compression_has_no_blue_cusp_contour() -> None:
    photo_grade = load_module()
    height, width = 128, 512
    hue = np.broadcast_to(np.linspace(250.0, 278.0, width), (height, width))
    lightness = np.broadcast_to(
        np.linspace(0.40, 0.55, height)[:, None],
        (height, width),
    )
    lch = np.stack((lightness, np.full_like(lightness, 0.38), hue), axis=2)
    out_of_gamut = photo_grade.oklab_to_srgb(photo_grade.oklch_to_oklab(lch))
    compressed = photo_grade.oklch_compress(out_of_gamut)
    adjacent = np.linalg.norm(np.diff(compressed, axis=1), axis=2)
    assert float(np.max(adjacent)) < 0.003


def test_perceptual_hsl_uses_full_documented_positive_saturation_range() -> None:
    photo_grade = load_module()
    rgb = np.full((16, 16, 3), [0.25, 0.48, 0.83], dtype=np.float32)
    base = {name: (0.0, 0.0, 0.0) for name in photo_grade.HUE_CENTERS}
    one = dict(base)
    one["blue"] = (0.0, 1.0, 0.0)
    one_point_five = dict(base)
    one_point_five["blue"] = (0.0, 1.5, 0.0)
    first = photo_grade.apply_perceptual_selective_color(rgb, one)
    second = photo_grade.apply_perceptual_selective_color(rgb, one_point_five)
    c1 = photo_grade.oklab_to_oklch(photo_grade.srgb_to_oklab(first))[..., 1]
    c2 = photo_grade.oklab_to_oklch(photo_grade.srgb_to_oklab(second))[..., 1]
    assert float(np.mean(c2)) > float(np.mean(c1))


def test_local_vibrance_uses_selected_perceptual_rendering() -> None:
    photo_grade = load_module()
    rgb = np.full((24, 32, 3), [0.22, 0.43, 0.76], dtype=np.float32)
    item = {
        "mask": {
            "type": "linear",
            "start": [0.0, 0.0],
            "end": [1.0, 0.0],
            "opacity": 1.0,
            "invert": False,
        },
        "adjustments": {"vibrance": 0.7},
    }
    perceptual = photo_grade.apply_local_adjustments(rgb, [item], "perceptual")
    legacy = photo_grade.apply_local_adjustments(rgb, [item], "legacy")
    assert np.any(perceptual != legacy)
    assert np.all(np.isfinite(perceptual))


def test_perceptual_cli_is_deterministic_and_reports_color_management(tmp_path: Path) -> None:
    y, x = np.mgrid[0:72, 0:128]
    rgb = np.stack(
        ((x * 3 + y) % 256, (x + y * 5) % 256, (x * 7 + y * 2) % 256),
        axis=2,
    ).astype(np.uint8)
    source = tmp_path / "source.png"
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    recipe_path = tmp_path / "recipe.json"
    Image.fromarray(rgb, "RGB").save(source)
    recipe_path.write_text(
        json.dumps(
            recipe(
                {
                    "basic": {"vibrance": 0.5, "saturation": 0.2},
                    "hsl": {"blue": {"hue": -12, "saturation": 0.4}},
                    "color_grading": {"shadows": {"hue": 220, "saturation": 0.2}},
                    "color_management": {
                        "rendering": "perceptual",
                        "gamut_mapping": "oklch_compress",
                    },
                }
            )
        ),
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
    color = reports[0]["processing"]["color_management"]
    assert color["rendering"] == "perceptual"
    assert color["gamut_mapping"] == "oklch_compress"
    assert color["out_of_gamut_ratio_after"] == 0.0
    assert reports[0]["output_encoding"]["icc_input_status"] == "absent_assumed_srgb"
    assert reports[0]["output_encoding"]["libraries"]["pypng"] != "unavailable"
