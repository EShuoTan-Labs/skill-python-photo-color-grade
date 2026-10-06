from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from test_legacy_regression import load_module, recipe


def test_valid_icc_converts_on_default_path(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "tagged.png"
    Image.new("RGBA", (8, 6), (40, 110, 170, 128)).save(
        source, icc_profile=module.srgb_profile_bytes()
    )
    rgb, alpha, meta = module.load_image(source)
    assert meta["icc_status"] == "converted_to_srgb"
    assert not meta["warnings"]
    assert np.allclose(rgb, np.array([40, 110, 170]) / 255, atol=1 / 255)
    assert np.allclose(alpha, 128 / 255)


@pytest.mark.parametrize("mode,color,transparent", [("RGB", (20, 40, 60), (20, 40, 60)), ("L", 80, 80)])
def test_png_transparent_color_survives_grade(tmp_path: Path, mode, color, transparent) -> None:
    module = load_module()
    source = tmp_path / "transparent.png"
    output = tmp_path / "graded.png"
    image = Image.new(mode, (8, 6), color)
    image.putpixel((0, 0), (90, 100, 110) if mode == "RGB" else 120)
    image.save(source, transparency=transparent)
    settings, parsed = module.parse_recipe(recipe({"basic": {"exposure": 0.2}}))
    module.run_grade(argparse.Namespace(input=source, output=output, show_parameters=False), settings, parsed)
    with Image.open(output) as result:
        expected = np.zeros((6, 8), dtype=np.uint8)
        expected[0, 0] = 255
        assert np.array_equal(np.asarray(result)[..., 3], expected)


def test_single_grade_failure_preserves_final_and_cleans_temporary(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    source = tmp_path / "source.png"
    output = tmp_path / "final.png"
    Image.new("RGB", (8, 6), (80, 110, 140)).save(source)
    output.write_bytes(b"existing final")
    source_bytes = source.read_bytes()
    settings, parsed = module.parse_recipe(recipe({}))

    def failed_save(path, *_args):
        path.write_bytes(b"partial encoding")
        raise OSError("encoder failed")

    monkeypatch.setattr(module, "save_image", failed_save)
    with pytest.raises(OSError, match="encoder failed"):
        module.run_grade(argparse.Namespace(input=source, output=output, show_parameters=False), settings, parsed)
    assert output.read_bytes() == b"existing final"
    assert source.read_bytes() == source_bytes
    assert not list(tmp_path.glob(".*.grade-render-*"))


def test_single_grade_verification_failure_preserves_final(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    source, output = tmp_path / "source.png", tmp_path / "final.png"
    Image.new("RGB", (8, 6), (80, 110, 140)).save(source)
    output.write_bytes(b"existing final")
    settings, parsed = module.parse_recipe(recipe({}))

    def wrong_size_save(path, *_args):
        Image.new("RGB", (2, 3), (90, 100, 110)).save(path)

    monkeypatch.setattr(module, "save_image", wrong_size_save)
    with pytest.raises(RuntimeError, match="dimensions changed"):
        module.run_grade(argparse.Namespace(input=source, output=output, show_parameters=False), settings, parsed)
    assert output.read_bytes() == b"existing final"
    assert not list(tmp_path.glob(".*.grade-render-*"))


def test_hard_link_to_source_is_rejected(tmp_path: Path) -> None:
    module = load_module()
    source, output = tmp_path / "source.png", tmp_path / "alias.png"
    Image.new("RGB", (8, 6), (80, 110, 140)).save(source)
    try:
        output.hardlink_to(source)
    except OSError:
        pytest.skip("Filesystem does not support hard links")
    settings, parsed = module.parse_recipe(recipe({}))
    original = source.read_bytes()
    with pytest.raises(ValueError, match="overwrite the original"):
        module.run_grade(argparse.Namespace(input=source, output=output, show_parameters=False), settings, parsed)
    assert output.read_bytes() == source.read_bytes() == original


def test_compare_detects_one_unit_alpha_change_in_png16(tmp_path: Path) -> None:
    module = load_module()
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    rgb = np.full((6, 8, 3), 30000, dtype=np.uint16)
    alpha = np.full((6, 8, 1), 40000, dtype=np.uint16)
    module.write_png16(first, rgb, alpha, {})
    alpha[0, 0, 0] += 1
    module.write_png16(second, rgb, alpha, {})
    result = module.compare_images(first, second)
    assert result["checks"]["same_alpha_values"] is False
    assert result["checks"]["passed"] is False


def test_compare_detects_sub_8bit_rgb_change_in_png16(tmp_path: Path) -> None:
    module = load_module()
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    rgb = np.full((6, 8, 3), 30000, dtype=np.uint16)
    module.write_png16(first, rgb, None, {})
    rgb[..., 0] += 1
    module.write_png16(second, rgb, None, {})
    result = module.compare_images(first, second)
    assert result["rgb_channel_difference"]["red"]["mean_absolute"] == pytest.approx(1 / 65535, abs=1e-6)


def test_compare_different_rgba_dimensions_returns_failed_checks(tmp_path: Path) -> None:
    module = load_module()
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGBA", (8, 6), (90, 100, 110, 180)).save(first)
    Image.new("RGBA", (9, 7), (90, 100, 110, 180)).save(second)
    result = module.compare_images(first, second)
    assert result["checks"]["passed"] is False
    assert result["rgb_channel_difference"] is None


def test_grade_8bit_output_uses_native_png16_source_precision(tmp_path: Path) -> None:
    module = load_module()
    source, output = tmp_path / "source.png", tmp_path / "output.png"
    rgb16 = np.full((6, 8, 3), 30000, dtype=np.uint16)
    module.write_png16(source, rgb16, None, {})
    settings, parsed = module.parse_recipe(recipe({"basic": {"exposure": 0.2}}))
    report = module.run_grade(argparse.Namespace(input=source, output=output, show_parameters=False), settings, parsed)
    expected = np.rint(module.grade_pixels(rgb16.astype(np.float32) / 65535, settings) * 255).astype(np.uint8)
    assert np.array_equal(np.asarray(Image.open(output)), expected)
    assert report["before"]["rgb_channels"]["red"]["mean"] == pytest.approx(30000 / 65535, abs=1e-5)


def test_sparse_transparent_image_reports_valid_json(tmp_path: Path) -> None:
    module = load_module()
    source, output = tmp_path / "sparse.png", tmp_path / "final.png"
    image = Image.new("RGBA", (9, 9), (0, 0, 0, 0))
    image.putpixel((4, 4), (90, 100, 110, 255))
    image.save(source)
    settings, parsed = module.parse_recipe(recipe({"basic": {"exposure": 0.2}}))
    result = module.run_grade(argparse.Namespace(input=source, output=output, show_parameters=False), settings, parsed)
    json.dumps(result, allow_nan=False)
    zone = result["before"]["perceptual_palette"]["tonal_zones"]["midtones_interquartile"]
    assert zone["pixel_ratio"] == 0
    assert zone["luma_mean"] is None
    spatial = result["transformation_summary"]["spatial_luma"]
    assert spatial["cell_delta_3x3"][0][0] is None
    assert spatial["mean_absolute_cell_delta"] > 0
