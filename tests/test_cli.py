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
    assert grade_report["processing"] == {
        "curve_working_space": "encoded_srgb_[0,1]",
        "curve_interpolation": "piecewise_linear",
        "curve_order": ["master_luma_curve", "rgb_channel_curves"],
        "active_channel_curves": ["red", "green", "blue"],
    }
    assert grade_report["parameters"]["channel_curves"]["red"]
    assert set(compare_report["rgb_channel_difference"]) == {"red", "green", "blue"}
    assert compare_report["checks"]["passed"] is True


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


@pytest.mark.parametrize("command", [(), ("analyze", "--help"), ("grade", "--help"), ("compare", "--help")])
def test_existing_help_commands_remain_available(command: tuple[str, ...]) -> None:
    completed = run_cli(*command, "--help") if not command else run_cli(*command)
    assert completed.returncode == 0
    assert "usage:" in completed.stdout

