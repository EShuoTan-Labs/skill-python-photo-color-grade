from __future__ import annotations

import json

import numpy as np
import pytest

from test_color_management import load_settings
from test_legacy_regression import load_module, synthetic_rgb8


@pytest.mark.parametrize("mode,coordinate", [("legacy", "hsv"), ("perceptual", "oklch")])
def test_explicit_hues_render_identically_and_round_trip(tmp_path, mode, coordinate):
    grade = load_module()
    common = {"color_management": {"rendering": mode}, "basic": {"exposure": .2}}
    old, expanded_old = load_settings(tmp_path, {
        **common, "hsl": {"yellow": {"hue": 25, "saturation": .2}},
        "color_grading": {"shadows": {"hue": 240, "saturation": .3}},
    })
    new, expanded = load_settings(tmp_path, {
        **common, "hsl": {"yellow": {f"hue_shift_{coordinate}": 25, "saturation": .2}},
        "color_grading": {"shadows": {f"target_hue_{coordinate}": 240, "saturation": .3}},
    })
    assert expanded_old["parameters"]["hsl"]["yellow"]["hue"] == 25
    assert expanded["parameters"]["hsl"]["yellow"][f"hue_shift_{coordinate}"] == 25
    assert expanded["parameters"]["color_grading"]["shadows"][f"target_hue_{coordinate}"] == 240
    path = tmp_path / "expanded.json"
    path.write_text(json.dumps(expanded), encoding="utf-8")
    restored, _ = grade.load_recipe(path)
    rgb = synthetic_rgb8().astype(np.float32) / 255
    assert np.array_equal(grade.grade_pixels(rgb, old), grade.grade_pixels(rgb, new))
    assert np.array_equal(grade.grade_pixels(rgb, new), grade.grade_pixels(rgb, restored))


@pytest.mark.parametrize("mode,coordinate", [("legacy", "oklch"), ("perceptual", "hsv")])
@pytest.mark.parametrize("section,item,kind", [("hsl", "yellow", "hue_shift"),
                                              ("color_grading", "shadows", "target_hue")])
def test_coordinate_mismatch_rejected(tmp_path, mode, coordinate, section, item, kind):
    with pytest.raises(ValueError, match="requires rendering"):
        load_settings(tmp_path, {"color_management": {"rendering": mode},
                                 section: {item: {f"{kind}_{coordinate}": 0}}})


@pytest.mark.parametrize("section,item,kind", [("hsl", "yellow", "hue_shift"),
                                              ("color_grading", "midtones", "target_hue")])
@pytest.mark.parametrize("fields", [lambda kind: {"hue": 0, f"{kind}_oklch": 0},
                                    lambda kind: {f"{kind}_hsv": 0, f"{kind}_oklch": 0}])
def test_ambiguous_hue_controls_rejected(tmp_path, section, item, kind, fields):
    with pytest.raises(ValueError, match="only one hue control"):
        load_settings(tmp_path, {"color_management": {"rendering": "perceptual"},
                                 section: {item: fields(kind)}})


@pytest.mark.parametrize("mode,coordinate", [("legacy", "hsv"), ("perceptual", "oklch")])
@pytest.mark.parametrize("section,item,kind,valid,invalid", [
    ("hsl", "blue", "hue_shift", [-90, 90], [-90.1, 90.1, True, float("nan")]),
    ("color_grading", "highlights", "target_hue", [0, 360], [-.1, 360.1, True, float("inf")]),
])
def test_explicit_hue_bounds(tmp_path, mode, coordinate, section, item, kind, valid, invalid):
    for value in valid:
        load_settings(tmp_path, {"color_management": {"rendering": mode},
                                 section: {item: {f"{kind}_{coordinate}": value}}})
    for value in invalid:
        with pytest.raises(ValueError):
            load_settings(tmp_path, {"color_management": {"rendering": mode},
                                     section: {item: {f"{kind}_{coordinate}": value}}})


def test_perceptual_shift_is_weighted_oklch_rotation_of_hsv_selected_pixels():
    grade = load_module()
    hsv_hue = np.array([[60, 90, 180]], dtype=np.float32)
    rgb = grade.hsv_to_rgb(hsv_hue, np.full_like(hsv_hue, .6), np.full_like(hsv_hue, .7))
    before = grade.oklab_to_oklch(grade.srgb_to_oklab(rgb))
    after_rgb = grade.apply_perceptual_selective_color(rgb, {"yellow": (20, 0, 0)})
    after = grade.oklab_to_oklch(grade.srgb_to_oklab(after_rgb))
    delta = (after[..., 2] - before[..., 2] + 180) % 360 - 180
    expected = 20 * grade.circular_hue_weight(hsv_hue, 60)
    np.testing.assert_allclose(delta, expected, atol=2e-4)
    np.testing.assert_allclose(after[..., :2], before[..., :2], atol=2e-7)
    # The selected yellow starts near OKLCh 110 degrees; 20 is a rotation, not a target.
    assert after[0, 0, 2] > 100


def test_documented_srgb_hue_anchors():
    grade = load_module()
    rgb = np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 1, 1],
                    [0, 0, 1], [1, 0, 1]], dtype=np.float32)
    hue = grade.oklab_to_oklch(grade.srgb_to_oklab(rgb))[:, 2]
    np.testing.assert_allclose(hue, [29.2, 109.8, 142.5, 194.8, 264.1, 328.4], atol=.06)
