from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from test_legacy_regression import ROOT, SCRIPT, recipe


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def run_cli_without_pypng(*arguments: str) -> subprocess.CompletedProcess[str]:
    script = str(SCRIPT)
    argv = [script, *arguments]
    bootstrap = f"""
import builtins
import runpy
import sys

real_import = builtins.__import__

def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "png":
        raise ModuleNotFoundError("No module named 'png'", name="png")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = blocked_import
sys.argv = {argv!r}
runpy.run_path({script!r}, run_name="__main__")
"""
    return subprocess.run(
        [sys.executable, "-c", bootstrap],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def write_inputs(tmp_path: Path, suffix: str, alpha: bool = False) -> tuple[Path, Path, Path]:
    y, x = np.mgrid[0:18, 0:24]
    rgb = np.stack((x / 23, y / 17, (x + 2 * y) / 57), axis=2)
    rgb8 = np.rint(rgb * 255).astype(np.uint8)
    source = tmp_path / f"source{suffix}"
    if alpha:
        alpha8 = ((x * 13 + y * 7) % 256).astype(np.uint8)[..., None]
        Image.fromarray(np.concatenate((rgb8, alpha8), axis=2), "RGBA").save(source)
    else:
        Image.fromarray(rgb8, "RGB").save(source, quality=96 if suffix == ".jpg" else None)
    output = tmp_path / f"output{suffix}"
    recipe_path = tmp_path / f"recipe-{suffix[1:]}.json"
    recipe_path.write_text(
        json.dumps(
            recipe(
                {
                    "curve": [[0, 0.05], [0.25, 0.2], [0.75, 0.82], [1, 0.95]],
                    "channel_curves": {
                        "red": [[0, 0.04], [0.5, 0.58], [1, 1]],
                        "green": [[0, 0], [0.5, 0.46], [1, 0.94]],
                        "blue": [[0, 0.08], [0.5, 0.5], [1, 0.9]],
                    },
                }
            )
        ),
        encoding="utf-8",
    )
    return source, output, recipe_path


@pytest.mark.parametrize("suffix", [".png", ".jpg"])
def test_analyze_grade_compare_json_extensions(tmp_path: Path, suffix: str) -> None:
    source, output, recipe_path = write_inputs(tmp_path, suffix)

    analyzed = run_cli("analyze", str(source), "--pretty")
    graded = run_cli(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
        "--show-parameters",
        "--skip-update-check",
        "--pretty",
    )
    compared = run_cli("compare", str(source), str(output), "--pretty")

    assert analyzed.returncode == graded.returncode == compared.returncode == 0
    analyze_report = json.loads(analyzed.stdout)
    grade_report = json.loads(graded.stdout)
    compare_report = json.loads(compared.stdout)
    assert set(analyze_report["metrics"]["rgb_channels"]) == {"red", "green", "blue"}
    assert len(analyze_report["metrics"]["spatial_rgb_mean_grid_3x3"]) == 3
    assert analyze_report["source_extension"] == suffix
    assert analyze_report["detected_format"] == ("PNG" if suffix == ".png" else "JPEG")
    assert analyze_report["extension_matches_format"] is True
    assert analyze_report["recommended_extension"] == suffix
    assert grade_report["output_format_conversion"] is None
    assert grade_report["output_encoding"]["extension"] == suffix
    assert grade_report["output_encoding"]["extension_matches_format"] is True
    assert grade_report["processing"] == {
        "curve_working_space": "encoded_srgb_[0,1]",
        "curve_interpolation": "piecewise_linear",
        "curve_order": ["master_luma_curve", "rgb_channel_curves"],
        "active_channel_curves": ["red", "green", "blue"],
    }
    assert grade_report["parameters"]["channel_curves"]["red"]
    assert set(compare_report["rgb_channel_difference"]) == {"red", "green", "blue"}
    assert compare_report["checks"]["passed"] is True


def test_non_16bit_cli_commands_work_without_pypng(tmp_path: Path) -> None:
    png_source, png_output, png_recipe = write_inputs(tmp_path, ".png")
    jpg_source, jpg_output, jpg_recipe = write_inputs(tmp_path, ".jpg")

    completed = [
        run_cli_without_pypng("--help"),
        run_cli_without_pypng("analyze", str(png_source)),
        run_cli_without_pypng(
            "grade",
            str(png_source),
            str(png_output),
            "--recipe",
            str(png_recipe),
            "--skip-update-check",
        ),
        run_cli_without_pypng(
            "grade",
            str(jpg_source),
            str(jpg_output),
            "--recipe",
            str(jpg_recipe),
            "--skip-update-check",
        ),
        run_cli_without_pypng("compare", str(png_source), str(png_output)),
    ]

    assert all(result.returncode == 0 for result in completed), [
        result.stderr for result in completed
    ]
    assert png_output.exists()
    assert jpg_output.exists()


def test_png16_output_without_pypng_fails_cleanly_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    recipe_path = tmp_path / "recipe.json"
    Image.new("RGB", (8, 6), (20, 40, 60)).save(source)
    recipe_path.write_text(
        json.dumps(recipe({"output": {"png_bit_depth": 16}})),
        encoding="utf-8",
    )

    completed = run_cli_without_pypng(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
        "--skip-update-check",
    )

    assert completed.returncode == 2
    assert "16-bit PNG processing requires pypng" in completed.stderr
    assert "pip install -r requirements.txt" in completed.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    ("payload_format", "source_suffix", "detected_format", "recommended_suffix"),
    [
        ("JPEG", ".png", "JPEG", ".jpg"),
        ("PNG", ".jpg", "PNG", ".png"),
    ],
)
def test_analyze_reports_mismatched_payload_and_extension(
    tmp_path: Path,
    payload_format: str,
    source_suffix: str,
    detected_format: str,
    recommended_suffix: str,
) -> None:
    source = tmp_path / f"mislabeled{source_suffix}"
    Image.new("RGB", (8, 6), (20, 40, 60)).save(source, format=payload_format)

    completed = run_cli("analyze", str(source))

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["format"] == detected_format
    assert report["source_extension"] == source_suffix
    assert report["detected_format"] == detected_format
    assert report["extension_matches_format"] is False
    assert report["recommended_extension"] == recommended_suffix
    assert source_suffix in report["warnings"][0]
    assert detected_format in report["warnings"][0]


def test_matching_jpeg_extension_is_preserved_as_recommendation(tmp_path: Path) -> None:
    source = tmp_path / "matching.jpeg"
    Image.new("RGB", (8, 6), (20, 40, 60)).save(source, format="JPEG")

    completed = run_cli("analyze", str(source))

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["detected_format"] == "JPEG"
    assert report["extension_matches_format"] is True
    assert report["recommended_extension"] == ".jpeg"
    assert "warnings" not in report


def test_grade_mislabeled_source_with_normalized_extension_preserves_format(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mislabeled.png"
    output = tmp_path / "mislabeled_A3_test.jpg"
    recipe_path = tmp_path / "recipe.json"
    Image.new("RGB", (8, 6), (20, 40, 60)).save(source, format="JPEG")
    recipe_path.write_text(json.dumps(recipe()), encoding="utf-8")

    completed = run_cli(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
        "--skip-update-check",
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    with Image.open(output) as decoded:
        assert decoded.format == "JPEG"
    assert report["detected_format"] == "JPEG"
    assert report["extension_matches_format"] is False
    assert report["recommended_extension"] == ".jpg"
    assert report["output_format_conversion"] is None
    assert report["output_encoding"]["extension"] == ".jpg"
    assert report["output_encoding"]["extension_matches_format"] is True


def test_grade_explicit_format_conversion_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "mislabeled.png"
    output = tmp_path / "mislabeled_A3_test.png"
    recipe_path = tmp_path / "recipe.json"
    Image.new("RGB", (8, 6), (20, 40, 60)).save(source, format="JPEG")
    recipe_path.write_text(json.dumps(recipe()), encoding="utf-8")

    completed = run_cli(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
        "--skip-update-check",
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    with Image.open(output) as decoded:
        assert decoded.format == "PNG"
    assert report["output_format_conversion"] == {"from": "JPEG", "to": "PNG"}
    assert report["output_encoding"]["format"] == "PNG"
    assert report["output_encoding"]["extension"] == ".png"
    assert report["output_encoding"]["extension_matches_format"] is True
    assert any("explicitly converts" in warning for warning in report["warnings"])


def test_supported_extension_cannot_hide_unsupported_payload(tmp_path: Path) -> None:
    source = tmp_path / "not-really-png.png"
    Image.new("RGB", (8, 6), (20, 40, 60)).save(source, format="GIF")

    completed = run_cli("analyze", str(source))

    assert completed.returncode == 2
    assert "Decoded payload format GIF is unsupported" in completed.stderr


def test_png_alpha_is_preserved_exactly(tmp_path: Path) -> None:
    source, output, recipe_path = write_inputs(tmp_path, ".png", alpha=True)
    completed = run_cli(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
        "--skip-update-check",
    )

    assert completed.returncode == 0, completed.stderr
    assert np.array_equal(np.asarray(Image.open(source))[..., 3], np.asarray(Image.open(output))[..., 3])


def test_composite_mask_cli_is_deterministic_and_preserves_alpha(tmp_path: Path) -> None:
    source, output, recipe_path = write_inputs(tmp_path, ".png", alpha=True)
    second_output = tmp_path / "output-second.png"
    mask_tree = {
        "type": "composite",
        "operation": "and",
        "inputs": [
            {
                "type": "luminance",
                "min": 0.2,
                "max": 0.9,
                "feather": 0.12,
                "opacity": 1,
                "invert": False,
            },
            {
                "type": "radial",
                "center": [0.55, 0.48],
                "radius": [0.42, 0.38],
                "feather": 0.5,
                "opacity": 0.85,
                "invert": False,
            },
        ],
        "opacity": 0.75,
        "invert": False,
    }
    recipe_path.write_text(
        json.dumps(
            recipe(
                {
                    "local_adjustments": [
                        {"mask": mask_tree, "adjustments": {"exposure": 0.3, "contrast": 0.1}}
                    ]
                }
            )
        ),
        encoding="utf-8",
    )

    first = run_cli(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
        "--show-parameters",
        "--skip-update-check",
    )
    second = run_cli(
        "grade",
        str(source),
        str(second_output),
        "--recipe",
        str(recipe_path),
        "--skip-update-check",
    )

    assert first.returncode == second.returncode == 0
    assert output.read_bytes() == second_output.read_bytes()
    assert json.loads(first.stdout)["parameters"]["local_adjustments"][0]["mask"] == mask_tree
    source_alpha = np.asarray(Image.open(source))[..., 3]
    assert np.array_equal(source_alpha, np.asarray(Image.open(output))[..., 3])
    assert np.array_equal(source_alpha, np.asarray(Image.open(second_output))[..., 3])


@pytest.mark.parametrize(
    "channel_curves",
    [
        {"red": [[0.1, 0], [1, 1]]},
        {"green": [[0, 0], [0.8, 0.8], [0.7, 0.7], [1, 1]]},
        {"blue": [[0, 0], [0.5, -0.1], [1, 1]]},
        {"unknown": []},
    ],
)
def test_invalid_recipe_exits_two_before_writing_output(tmp_path: Path, channel_curves: dict) -> None:
    source, output, recipe_path = write_inputs(tmp_path, ".png")
    recipe_path.write_text(json.dumps(recipe({"channel_curves": channel_curves})), encoding="utf-8")

    completed = run_cli(
        "grade",
        str(source),
        str(output),
        "--recipe",
        str(recipe_path),
        "--skip-update-check",
    )

    assert completed.returncode == 2
    assert completed.stderr.startswith("error: ")
    assert not output.exists()


@pytest.mark.parametrize(
    "mask_tree",
    [
        {
            "type": "composite",
            "operation": "and",
            "inputs": [],
            "opacity": 1,
            "invert": False,
        },
        {
            "type": "composite",
            "operation": "subtract",
            "inputs": [
                {
                    "type": "linear",
                    "start": [0, 0],
                    "end": [1, 1],
                    "opacity": 1,
                    "invert": False,
                }
            ],
            "opacity": 1,
            "invert": False,
        },
        {
            "type": "composite",
            "operation": "xor",
            "inputs": [
                {
                    "type": "linear",
                    "start": [0, 0],
                    "end": [1, 1],
                    "opacity": 1,
                    "invert": False,
                },
                {
                    "type": "radial",
                    "center": [0.5, 0.5],
                    "radius": [0.4, 0.4],
                    "feather": 0.5,
                    "opacity": 1,
                    "invert": False,
                },
            ],
            "opacity": 1,
            "invert": False,
        },
    ],
)
def test_invalid_composite_tree_exits_two_before_writing_output(tmp_path: Path, mask_tree: dict) -> None:
    source, output, recipe_path = write_inputs(tmp_path, ".png")
    recipe_path.write_text(
        json.dumps(
            recipe(
                {
                    "local_adjustments": [
                        {"mask": mask_tree, "adjustments": {"exposure": 0.2}}
                    ]
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
        "--skip-update-check",
    )

    assert completed.returncode == 2
    assert completed.stderr.startswith("error: ")
    assert not output.exists()


@pytest.mark.parametrize("command", [(), ("analyze", "--help"), ("grade", "--help"), ("compare", "--help")])
def test_existing_help_commands_remain_available(command: tuple[str, ...]) -> None:
    completed = run_cli(*command, "--help") if not command else run_cli(*command)
    assert completed.returncode == 0
    assert "usage:" in completed.stdout
