from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import png
import pytest
from PIL import Image

from test_legacy_regression import ROOT, SCRIPT, load_module, recipe


def decode_direct(path: Path) -> tuple[np.ndarray, dict]:
    width, height, rows, info = png.Reader(filename=str(path)).asDirect()
    planes = int(info["planes"])
    values = np.vstack(
        [np.fromiter(row, dtype=np.uint16, count=width * planes) for row in rows]
    ).reshape(height, width, planes)
    return values, info


@pytest.mark.parametrize("with_alpha", [False, True])
def test_png16_writer_sets_ihdr_and_preserves_exact_samples(tmp_path: Path, with_alpha: bool) -> None:
    photo_grade = load_module()
    y, x = np.mgrid[0:19, 0:23]
    rgb = np.stack((x * 2711, y * 3301, (x * 997 + y * 1237)), axis=2)
    rgb = np.mod(rgb, 65536).astype(np.uint16)
    alpha = np.mod(x * 1877 + y * 3559, 65536).astype(np.uint16)[..., None] if with_alpha else None
    output = tmp_path / "direct.png"
    photo_grade.write_png16(output, rgb, alpha, {}, compression=4)
    header = photo_grade.inspect_ihdr(output)
    decoded, info = decode_direct(output)
    expected = rgb if alpha is None else np.concatenate((rgb, alpha), axis=2)
    assert header["bit_depth"] == 16
    assert int(info["bitdepth"]) == 16
    assert np.array_equal(decoded, expected)
    with Image.open(output) as reopened:
        reopened.load()
        assert reopened.size == (23, 19)


def test_cli_png16_rgb_and_rgba_are_deterministic_and_alpha_expands_exactly(tmp_path: Path) -> None:
    photo_grade = load_module()
    y, x = np.mgrid[0:37, 0:71]
    rgb8 = np.stack(((x * 9) % 256, (y * 13) % 256, (x * 5 + y * 7) % 256), axis=2).astype(np.uint8)
    alpha8 = ((x * 17 + y * 19) % 256).astype(np.uint8)[..., None]
    source = tmp_path / "source.png"
    outputs = [tmp_path / "first.png", tmp_path / "second.png"]
    recipe_path = tmp_path / "recipe.json"
    Image.fromarray(np.concatenate((rgb8, alpha8), axis=2), "RGBA").save(source)
    recipe_path.write_text(
        json.dumps(recipe({"output": {"png_bit_depth": 16, "png_compress": 5}})),
        encoding="utf-8",
    )
    for output in outputs:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "grade", str(source), str(output), "--recipe", str(recipe_path), "--skip-update-check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        report = json.loads(completed.stdout)
        assert report["output_encoding"]["output_bit_depth"] == 16
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    decoded, info = decode_direct(outputs[0])
    assert int(info["bitdepth"]) == 16
    assert np.array_equal(decoded[..., 3], alpha8[..., 0].astype(np.uint16) * 257)


def test_16bit_source_round_trips_identity_grade_without_sample_loss(tmp_path: Path) -> None:
    photo_grade = load_module()
    rng = np.random.default_rng(160016)
    rgb16 = rng.integers(0, 65536, size=(31, 47, 3), dtype=np.uint16)
    alpha16 = rng.integers(0, 65536, size=(31, 47, 1), dtype=np.uint16)
    source = tmp_path / "source16.png"
    output = tmp_path / "output16.png"
    recipe_path = tmp_path / "recipe.json"
    photo_grade.write_png16(source, rgb16, alpha16, {}, compression=6)
    recipe_path.write_text(
        json.dumps(recipe({"output": {"png_bit_depth": 16}})), encoding="utf-8"
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "grade", str(source), str(output), "--recipe", str(recipe_path), "--skip-update-check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    decoded, _ = decode_direct(output)
    assert np.array_equal(decoded, np.concatenate((rgb16, alpha16), axis=2))


def test_tpdf_is_deterministic_unbiased_and_breaks_long_gradient_platforms() -> None:
    photo_grade = load_module()
    gradient = np.linspace(0.0, 1.0, 131072, dtype=np.float32)
    rgb = np.repeat(gradient[None, :, None], 3, axis=2)
    first_noise = photo_grade.deterministic_tpdf(rgb.shape)
    second_noise = photo_grade.deterministic_tpdf(rgb.shape)
    assert np.array_equal(first_noise, second_noise)
    no_dither = np.rint(rgb * 255.0)
    dithered = np.rint(np.clip(rgb + first_noise / 255.0, 0.0, 1.0) * 255.0)
    mean_bias = np.mean(dithered - rgb * 255.0, axis=(0, 1))
    assert float(np.max(np.abs(mean_bias))) < 0.05

    def longest_platform(values: np.ndarray) -> int:
        changes = np.flatnonzero(np.diff(values) != 0)
        return int(np.max(np.diff(np.r_[-1, changes, len(values) - 1])))

    assert longest_platform(dithered[0, :, 0]) < longest_platform(no_dither[0, :, 0])


@pytest.mark.parametrize(
    ("output_suffix", "output_parameters", "message"),
    [
        (".jpg", {"png_bit_depth": 16}, "require a PNG output path"),
        (".jpg", {"png_dither": "tpdf"}, "require a PNG output path"),
        (".png", {"png_bit_depth": 16, "png_dither": "tpdf"}, "only supported for 8-bit"),
    ],
)
def test_invalid_output_combinations_fail_before_writing(
    tmp_path: Path, output_suffix: str, output_parameters: dict, message: str
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"output{output_suffix}"
    recipe_path = tmp_path / "recipe.json"
    Image.new("RGB", (8, 8), "gray").save(source)
    recipe_path.write_text(
        json.dumps(recipe({"output": output_parameters})), encoding="utf-8"
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "grade", str(source), str(output), "--recipe", str(recipe_path), "--skip-update-check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert message in completed.stderr
    assert not output.exists()
