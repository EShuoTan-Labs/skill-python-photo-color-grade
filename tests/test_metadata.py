from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms, PngImagePlugin

from test_legacy_regression import ROOT, SCRIPT, load_module, recipe


def run_grade(source: Path, output: Path, recipe_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "grade", str(source), str(output), "--recipe", str(recipe_path), "--skip-update-check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_png16_preserves_icc_exif_dpi_and_text(tmp_path: Path) -> None:
    photo_grade = load_module()
    source = tmp_path / "metadata.png"
    output = tmp_path / "metadata16.png"
    recipe_path = tmp_path / "recipe.json"
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "测试作者")
    exif = Image.Exif()
    exif[0x010E] = "phase-4 metadata"
    icc = photo_grade.srgb_profile_bytes()
    Image.new("RGB", (19, 13), (31, 127, 233)).save(
        source,
        pnginfo=info,
        icc_profile=icc,
        exif=exif,
        dpi=(144, 96),
    )
    recipe_path.write_text(
        json.dumps(recipe({"output": {"png_bit_depth": 16}})), encoding="utf-8"
    )
    completed = run_grade(source, output, recipe_path)
    assert completed.returncode == 0, completed.stderr
    with Image.open(output) as reopened:
        reopened.load()
        assert reopened.info["Author"] == "测试作者"
        assert reopened.info["icc_profile"] == icc
        assert reopened.getexif()[0x010E] == "phase-4 metadata"
        assert reopened.info["dpi"] == pytest.approx((144, 96), abs=0.02)
    chunks = photo_grade.chunk_types(output)
    assert chunks[0] == b"IHDR"
    assert chunks[-1] == b"IEND"
    assert chunks.index(b"iCCP") < chunks.index(b"IDAT")
    assert chunks.index(b"eXIf") < chunks.index(b"IDAT")


def test_invalid_icc_warns_on_legacy_but_fails_new_path_before_output(tmp_path: Path) -> None:
    source = tmp_path / "invalid-icc.png"
    legacy_output = tmp_path / "legacy.png"
    strict_output = tmp_path / "strict.png"
    legacy_recipe = tmp_path / "legacy.json"
    strict_recipe = tmp_path / "strict.json"
    Image.new("RGB", (16, 12), (80, 100, 120)).save(source, icc_profile=b"not-an-icc-profile")
    legacy_recipe.write_text(json.dumps(recipe({})), encoding="utf-8")
    strict_recipe.write_text(
        json.dumps(recipe({"color_management": {"rendering": "perceptual"}})),
        encoding="utf-8",
    )
    legacy = run_grade(source, legacy_output, legacy_recipe)
    assert legacy.returncode == 0, legacy.stderr
    legacy_report = json.loads(legacy.stdout)
    assert legacy_report["warnings"]
    assert legacy_report["output_encoding"]["icc_input_status"] == "conversion_failed_legacy_fallback"
    strict = run_grade(source, strict_output, strict_recipe)
    assert strict.returncode == 2
    assert "ICC conversion to sRGB failed" in strict.stderr
    assert not strict_output.exists()


def test_perceptual_no_icc_is_explicitly_assumed_srgb_and_output_is_tagged(tmp_path: Path) -> None:
    source = tmp_path / "untagged.png"
    output = tmp_path / "tagged.png"
    recipe_path = tmp_path / "recipe.json"
    Image.new("RGB", (11, 9), (120, 150, 200)).save(source)
    recipe_path.write_text(
        json.dumps(recipe({"color_management": {"rendering": "perceptual"}})),
        encoding="utf-8",
    )
    completed = run_grade(source, output, recipe_path)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["output_encoding"]["icc_input_status"] == "absent_assumed_srgb"
    assert report["output_encoding"]["icc_output"] == "srgb"
    with Image.open(output) as reopened:
        assert reopened.info.get("icc_profile")


def test_non_srgb_icc_on_png16_is_rejected_with_actionable_error(tmp_path: Path) -> None:
    photo_grade = load_module()
    source = tmp_path / "lab-tagged16.png"
    output = tmp_path / "output.png"
    recipe_path = tmp_path / "recipe.json"
    lab_icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    rgb16 = np.full((8, 9, 3), 32768, dtype=np.uint16)
    photo_grade.write_png16(source, rgb16, None, {"icc_profile": lab_icc})
    recipe_path.write_text(
        json.dumps(recipe({"output": {"png_bit_depth": 16}})), encoding="utf-8"
    )
    completed = run_grade(source, output, recipe_path)
    assert completed.returncode == 2
    assert "convert it externally to sRGB16 first" in completed.stderr
    assert not output.exists()


def test_cmyk_strict_path_passes_original_mode_to_icc_transform(tmp_path: Path, monkeypatch) -> None:
    photo_grade = load_module()
    source = tmp_path / "cmyk.jpg"
    srgb_icc = photo_grade.srgb_profile_bytes()
    Image.new("CMYK", (7, 5), (10, 40, 90, 5)).save(source, icc_profile=srgb_icc)
    observed = []

    def fake_transform(image, _in_profile, _out_profile, outputMode):
        observed.append((image.mode, outputMode))
        return image.convert("RGB")

    monkeypatch.setattr(photo_grade.ImageCms, "profileToProfile", fake_transform)
    rgb, alpha, metadata = photo_grade.load_image(source, strict_color_management=True)
    assert observed == [("CMYK", "RGB")]
    assert rgb.shape == (5, 7, 3)
    assert alpha is None
    assert metadata["icc_status"] == "converted_to_srgb"


def test_supported_extension_with_jpeg_payload_keeps_legacy_pillow_detection(tmp_path: Path) -> None:
    photo_grade = load_module()
    mislabeled = tmp_path / "mislabeled.png"
    Image.new("RGB", (6, 4), (20, 40, 60)).save(mislabeled, format="JPEG")
    rgb, alpha, metadata = photo_grade.load_image(mislabeled)
    assert rgb.shape == (4, 6, 3)
    assert alpha is None
    assert metadata["format"] == "JPEG"
    assert metadata["source_bit_depth"] == 8
