from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "photo_grade.py"


def load_module():
    specification = importlib.util.spec_from_file_location("photo_grade", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def synthetic_rgb8() -> np.ndarray:
    y, x = np.mgrid[0:9, 0:11]
    return np.stack(
        (
            (17 * x + 3 * y) % 256,
            (5 * x + 29 * y + 31) % 256,
            (41 * x + 7 * y + 13) % 256,
        ),
        axis=2,
    ).astype(np.uint8)


def legacy_settings() -> argparse.Namespace:
    return argparse.Namespace(
        denoise=0.25,
        temperature=0.13,
        tint=-0.07,
        exposure=0.2,
        highlights=-0.15,
        shadows=0.22,
        whites=0.08,
        blacks=-0.11,
        contrast=0.17,
        curve="0:0,0.25:0.2,0.5:0.56,0.8:0.86,1:1",
        local_corrections=[],
        vibrance=0.12,
        saturation=-0.04,
        red_hue=3.0,
        red_sat=0.1,
        red_lum=-0.03,
        orange_hue=-4.0,
        orange_sat=0.05,
        orange_lum=0.02,
        yellow_hue=0.0,
        yellow_sat=0.0,
        yellow_lum=0.0,
        green_hue=5.0,
        green_sat=-0.08,
        green_lum=0.04,
        aqua_hue=0.0,
        aqua_sat=0.0,
        aqua_lum=0.0,
        blue_hue=-7.0,
        blue_sat=0.14,
        blue_lum=-0.05,
        purple_hue=0.0,
        purple_sat=0.0,
        purple_lum=0.0,
        magenta_hue=0.0,
        magenta_sat=0.0,
        magenta_lum=0.0,
        grade_shadows_hue=215.0,
        grade_shadows_sat=0.08,
        grade_midtones_hue=34.0,
        grade_midtones_sat=0.03,
        grade_highlights_hue=48.0,
        grade_highlights_sat=0.06,
        grading_balance=0.08,
        grading_blending=0.6,
        local_adjustments=[],
        sharpen=0.2,
        sharpen_radius=0.9,
    )


def recipe(parameters: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "style": {"id": "A", "name": "baseline", "intensity": 3},
        "visual_intent": {
            "brightness_key": "x",
            "contrast_structure": "x",
            "light_geometry": "x",
            "palette": "x",
            "subject_separation": "x",
            "texture": "x",
        },
        "success_criteria": ["a", "b", "c"],
        "parameters": parameters or {},
    }


def test_legacy_grade_pixels_is_exact() -> None:
    photo_grade = load_module()
    rgb = synthetic_rgb8().astype(np.float32) / 255.0

    output = photo_grade.grade_pixels(rgb, legacy_settings())
    output8 = np.rint(output * 255.0).astype(np.uint8)

    assert hashlib.sha256(output.tobytes()).hexdigest() == (
        "bd2e1920b1d7fae0f3a8e07d07e633312f6a8a498b1a3349cc69e1f0085a608e"
    )
    assert hashlib.sha256(output8.tobytes()).hexdigest() == (
        "01688de216590984c725b8c549b7a6c662b3ae163120e4fa95b94bd76e712d1b"
    )


def test_legacy_png_pixels_and_report_subtree_are_exact(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "graded.png"
    recipe_path = tmp_path / "recipe.json"
    Image.fromarray(synthetic_rgb8(), "RGB").save(source)
    recipe_path.write_text(
        json.dumps(
            recipe(
                {
                    "basic": {"exposure": 0.2},
                    "curve": [[0, 0], [0.5, 0.55], [1, 1]],
                    "detail": {"sharpen": 0.2},
                }
            )
        ),
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
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    decoded = np.asarray(Image.open(output).convert("RGB"))
    assert hashlib.sha256(decoded.tobytes()).hexdigest() == (
        "89b02bdb832afecb9d1f14e0052a49687a5119c88304595eec5bcab2c27b3b20"
    )

    legacy_metric_keys = (
            "luma_mean",
            "luma_percentiles",
            "shadow_clip_ratio",
            "highlight_clip_ratio",
            "any_channel_low_clip_ratio",
            "any_channel_high_clip_ratio",
            "dynamic_range_p95_p05",
            "saturation_mean",
            "saturation_p95",
            "channel_mean_rgb",
            "neutral_candidate_ratio",
            "neutral_candidate_mean_rgb",
            "spatial_luma_grid_3x3",
            "brightest_cell",
            "darkest_cell",
        )
    legacy_before = {
        key: report["before"][key]
        for key in legacy_metric_keys
    }
    assert hashlib.sha256(
        json.dumps(legacy_before, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest() == "40e263fbd0166076aa818047be57df2b9ccb323a2fdd26fe8ba64f1e9baa4fde"
    legacy_report = {
        "width": report["width"],
        "height": report["height"],
        "style": report["style"],
        "recipe_validated": report["recipe_validated"],
        "before": legacy_before,
        "after": {key: report["after"][key] for key in legacy_metric_keys},
    }
    assert hashlib.sha256(
        json.dumps(legacy_report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest() == "ac0c5428aa43fae33b90507a2a8fd041f8c640c5962b066ec1aa443c9a3ca0c3"
