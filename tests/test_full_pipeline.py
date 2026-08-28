from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from test_legacy_regression import ROOT, SCRIPT, load_module, recipe


VISUAL_REGRESSION = ROOT / "tests" / "visual_regression.py"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def synthetic_rgba8(height: int = 96, width: int = 144) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width]
    horizontal = x / max(width - 1, 1)
    vertical = y / max(height - 1, 1)
    texture = 0.04 * np.sin(2.0 * np.pi * x / 7.0) * (x < width // 2)
    rng = np.random.default_rng(6197)
    noise = rng.normal(0.0, 0.012, (height, width)) * (y > height // 2)
    rgb = np.stack(
        (
            0.04 + 0.9 * horizontal + texture + noise,
            0.03 + 0.78 * vertical - 0.5 * texture + noise,
            0.08 + 0.62 * (1.0 - horizontal) + 0.25 * vertical - noise,
        ),
        axis=2,
    )
    rgb[:, width // 2 - 2 : width // 2 + 2] = [1.0, 1.0, 1.0]
    rgb[height // 3 : 2 * height // 3, 3 * width // 4 :] = [1.0, 0.0, 0.85]
    rgb[-12:, :24] = 0.0
    alpha = ((x * 17 + y * 29) % 256).astype(np.uint8)[..., None]
    alpha[:, :8] = 0
    return np.concatenate(
        (np.rint(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8), alpha),
        axis=2,
    )


def assert_json_finite(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            assert_json_finite(child)
    elif isinstance(value, list):
        for child in value:
            assert_json_finite(child)
    elif isinstance(value, float):
        assert math.isfinite(value)


def full_pipeline_parameters() -> dict[str, Any]:
    return {
        "basic": {
            "temperature": 0.06,
            "tint": -0.03,
            "exposure": 0.12,
            "highlights": -0.18,
            "shadows": 0.12,
            "whites": 0.05,
            "blacks": -0.06,
            "contrast": 0.1,
            "vibrance": 0.16,
            "saturation": -0.03,
        },
        "curve": [[0, 0.01], [0.2, 0.16], [0.5, 0.53], [0.8, 0.86], [1, 0.99]],
        "channel_curves": {
            "red": [[0, 0.015], [0.5, 0.52], [1, 1]],
            "green": [[0, 0], [0.5, 0.49], [1, 0.99]],
            "blue": [[0, 0.02], [0.5, 0.485], [1, 0.98]],
        },
        "presence": {"dehaze": 0.1, "clarity": 0.18, "texture": 0.14},
        "color_management": {
            "rendering": "perceptual",
            "gamut_mapping": "oklch_compress",
        },
        "hsl": {
            "orange": {"hue": -3, "saturation": 0.08, "luminance": 0.03},
            "blue": {"hue": -8, "saturation": 0.16, "luminance": -0.05},
            "magenta": {"saturation": -0.08},
        },
        "color_grading": {
            "shadows": {"hue": 218, "saturation": 0.06},
            "midtones": {"hue": 28, "saturation": 0.025},
            "highlights": {"hue": 44, "saturation": 0.05},
            "balance": 0.06,
            "blending": 0.58,
        },
        "local_corrections": [
            {
                "mask": {
                    "type": "composite",
                    "operation": "and",
                    "inputs": [
                        {
                            "type": "luminance",
                            "min": 0.18,
                            "max": 0.86,
                            "feather": 0.1,
                            "opacity": 1,
                            "invert": False,
                        },
                        {
                            "type": "radial",
                            "center": [0.52, 0.48],
                            "radius": [0.44, 0.4],
                            "feather": 0.58,
                            "opacity": 0.9,
                            "invert": False,
                        },
                    ],
                    "opacity": 0.72,
                    "invert": False,
                },
                "adjustments": {
                    "exposure": 0.14,
                    "curve": [[0, 0], [0.5, 0.54], [1, 1]],
                    "channel_curves": {"red": [[0, 0], [0.5, 0.515], [1, 1]]},
                    "clarity": 0.08,
                },
            }
        ],
        "local_adjustments": [
            {
                "mask": {
                    "type": "composite",
                    "operation": "subtract",
                    "inputs": [
                        {
                            "type": "linear",
                            "start": [0.0, 0.1],
                            "end": [1.0, 0.9],
                            "opacity": 0.8,
                            "invert": False,
                        },
                        {
                            "type": "luminance",
                            "min": 0.9,
                            "max": 1.0,
                            "feather": 0.06,
                            "opacity": 1,
                            "invert": False,
                        },
                    ],
                    "opacity": 0.5,
                    "invert": False,
                },
                "adjustments": {"exposure": -0.08, "texture": 0.08, "vibrance": 0.05},
            }
        ],
        "detail": {
            "denoise": 0.12,
            "sharpen": 0.55,
            "sharpen_radius": 1.1,
            "sharpen_threshold": 0.008,
            "sharpen_edge_protection": 0.75,
        },
        "output": {"png_bit_depth": 16, "png_dither": "none"},
    }


def test_explicit_neutral_full_schema_is_exact_for_rgb_and_alpha(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "neutral.png"
    recipe_path = tmp_path / "neutral.json"
    rgba = synthetic_rgba8(48, 72)
    Image.fromarray(rgba, "RGBA").save(source)
    recipe_path.write_text(
        json.dumps(
            recipe(
                {
                    "basic": {
                        "temperature": 0,
                        "tint": 0,
                        "exposure": 0,
                        "highlights": 0,
                        "shadows": 0,
                        "whites": 0,
                        "blacks": 0,
                        "contrast": 0,
                        "vibrance": 0,
                        "saturation": 0,
                    },
                    "curve": [],
                    "channel_curves": {"red": [], "green": [], "blue": []},
                    "presence": {"dehaze": 0, "clarity": 0, "texture": 0},
                    "color_management": {"rendering": "legacy", "gamut_mapping": "clip"},
                    "hsl": {},
                    "color_grading": {"balance": 0, "blending": 0.5},
                    "local_corrections": [],
                    "local_adjustments": [],
                    "detail": {
                        "denoise": 0,
                        "sharpen": 0,
                        "sharpen_radius": 1,
                        "sharpen_threshold": 0,
                        "sharpen_edge_protection": 0,
                    },
                    "output": {
                        "jpeg_quality": 95,
                        "png_compress": 6,
                        "png_bit_depth": 8,
                        "png_dither": "none",
                    },
                }
            )
        ),
        encoding="utf-8",
    )

    completed = run_cli(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
    )

    assert completed.returncode == 0, completed.stderr
    assert np.array_equal(np.asarray(Image.open(output)), rgba)


def test_cli_analyze_grade_compare_full_pipeline_is_finite_and_preserves_invariants(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "full.png"
    recipe_path = tmp_path / "full.json"
    rgba = synthetic_rgba8()
    Image.fromarray(rgba, "RGBA").save(source)
    recipe_path.write_text(
        json.dumps(recipe(full_pipeline_parameters())),
        encoding="utf-8",
    )

    analyzed = run_cli("analyze", str(source), "--pretty")
    graded = run_cli(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
        "--show-parameters",
        "--pretty",
    )
    compared = run_cli("compare", str(source), str(output), "--pretty")

    assert analyzed.returncode == 0, analyzed.stderr
    assert graded.returncode == 0, graded.stderr
    assert compared.returncode == 0, compared.stderr
    reports = [json.loads(item.stdout) for item in (analyzed, graded, compared)]
    for report in reports:
        assert_json_finite(report)
    grade_report = reports[1]
    compare_report = reports[2]
    assert (grade_report["width"], grade_report["height"]) == (144, 96)
    assert grade_report["output_encoding"]["output_bit_depth"] == 16
    assert grade_report["processing"]["color_management"]["out_of_gamut_ratio_after"] == 0.0
    assert grade_report["processing"]["presence"]["active_global"] == [
        "dehaze",
        "clarity",
        "texture",
    ]
    assert grade_report["processing"]["sharpening"]["active_controls"] == [
        "sharpen_threshold",
        "sharpen_edge_protection",
    ]
    assert grade_report["parameters"]["detail"]["sharpen_threshold"] == 0.008
    assert compare_report["checks"]["passed"] is True

    photo_grade = load_module()
    rgb16, alpha16, metadata = photo_grade.read_png16(output)
    assert metadata["bit_depth"] == 16
    assert rgb16.shape == (96, 144, 3)
    assert alpha16 is not None
    assert np.array_equal(
        np.rint(alpha16[..., 0] * 65535.0).astype(np.uint16),
        rgba[..., 3].astype(np.uint16) * 257,
    )
    assert np.all(np.isfinite(rgb16))


def test_visual_regression_runner_generates_all_stage_reports(tmp_path: Path) -> None:
    specification = importlib.util.spec_from_file_location("visual_regression", VISUAL_REGRESSION)
    assert specification is not None and specification.loader is not None
    visual_regression = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(visual_regression)

    input_dir = tmp_path / "external-photos"
    output_dir = tmp_path / "visual-output"
    input_dir.mkdir()
    source = input_dir / "sample.png"
    Image.fromarray(synthetic_rgba8(36, 54), "RGBA").save(source)

    report = visual_regression.run_visual_regression(input_dir, output_dir)

    assert report["summary"] == {
        "images": 1,
        "stages_passed": 4,
        "stages_failed": 0,
        "analyze_failed": 0,
    }
    assert Path(report["report_path"]).is_file()
    stages = report["images"][0]["stages"]
    assert [stage["stage"] for stage in stages] == [name for name, _ in visual_regression.STAGES]
    assert all(stage["compare"]["checks"]["passed"] for stage in stages)
    assert all((output_dir / stage["output"]).is_file() for stage in stages)
    assert all(
        "histogram_64" in channel
        for channel in report["images"][0]["analyze"]["metrics"]["rgb_channels"].values()
    )
    assert all(
        "histogram_64" in channel
        for stage in stages
        for metrics in (
            stage["grade"]["before"],
            stage["grade"]["after"],
            stage["compare"]["original"]["metrics"],
            stage["compare"]["graded"]["metrics"],
        )
        for channel in metrics["rgb_channels"].values()
    )
    assert_json_finite(report)
