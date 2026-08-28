#!/usr/bin/env python3
"""Generate deterministic visual-regression renders from an external photo directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PHOTO_GRADE = ROOT / "scripts" / "photo_grade.py"
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png"}


def recipe(style_id: str, name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "style": {"id": style_id, "name": name, "intensity": 3},
        "visual_intent": {
            "brightness_key": "保持源画面的整体亮度关系",
            "contrast_structure": "逐阶段验证全局与局部对比结构",
            "light_geometry": "仅顺应原图亮暗方向",
            "palette": "逐阶段验证兼容与感知色彩路径",
            "subject_separation": "通过明度、色彩和几何蒙版验证分离",
            "texture": "检查平坦区、细纹理和强边缘的细节响应",
        },
        "success_criteria": [
            "尺寸和透明通道保持不变",
            "输出有限且能够重新打开",
            "无明显光晕、色相折断或蒙版接缝",
        ],
        "parameters": parameters,
    }


STAGES = (
    (
        "A_neutral",
        recipe(
            "A",
            "中性管线",
            {
                "presence": {"dehaze": 0, "clarity": 0, "texture": 0},
                "detail": {
                    "denoise": 0,
                    "sharpen": 0,
                    "sharpen_radius": 1,
                    "sharpen_threshold": 0,
                    "sharpen_edge_protection": 0,
                },
            },
        ),
    ),
    (
        "B_structure",
        recipe(
            "B",
            "曲线与组合蒙版",
            {
                "basic": {"exposure": 0.08, "highlights": -0.08, "shadows": 0.06},
                "curve": [[0, 0.01], [0.25, 0.22], [0.5, 0.52], [0.75, 0.79], [1, 0.99]],
                "channel_curves": {
                    "red": [[0, 0.01], [0.5, 0.515], [1, 1]],
                    "blue": [[0, 0.015], [0.5, 0.49], [1, 0.99]],
                },
                "local_corrections": [
                    {
                        "mask": {
                            "type": "composite",
                            "operation": "and",
                            "inputs": [
                                {
                                    "type": "luminance",
                                    "min": 0.28,
                                    "max": 0.92,
                                    "feather": 0.12,
                                    "opacity": 1,
                                    "invert": False,
                                },
                                {
                                    "type": "radial",
                                    "center": [0.5, 0.48],
                                    "radius": [0.42, 0.46],
                                    "feather": 0.65,
                                    "opacity": 1,
                                    "invert": False,
                                },
                            ],
                            "opacity": 0.55,
                            "invert": False,
                        },
                        "adjustments": {"exposure": 0.12, "contrast": 0.05},
                    }
                ],
            },
        ),
    ),
    (
        "C_presence",
        recipe(
            "C",
            "多尺度细节",
            {
                "basic": {"exposure": 0.08, "highlights": -0.08, "shadows": 0.06},
                "curve": [[0, 0.01], [0.25, 0.22], [0.5, 0.52], [0.75, 0.79], [1, 0.99]],
                "presence": {"dehaze": 0.08, "clarity": 0.16, "texture": 0.12},
                "local_adjustments": [
                    {
                        "mask": {
                            "type": "linear",
                            "start": [0.0, 0.15],
                            "end": [1.0, 0.85],
                            "opacity": 0.35,
                            "invert": False,
                        },
                        "adjustments": {"clarity": 0.1, "texture": 0.08},
                    }
                ],
            },
        ),
    ),
    (
        "D_full_pipeline",
        recipe(
            "D",
            "阶段一至四完整管线与保护锐化",
            {
                "basic": {
                    "temperature": 0.04,
                    "tint": -0.02,
                    "exposure": 0.1,
                    "highlights": -0.12,
                    "shadows": 0.08,
                    "whites": 0.04,
                    "blacks": -0.04,
                    "contrast": 0.08,
                    "vibrance": 0.12,
                    "saturation": -0.02,
                },
                "curve": [[0, 0.01], [0.25, 0.21], [0.5, 0.52], [0.75, 0.8], [1, 0.99]],
                "channel_curves": {
                    "red": [[0, 0.01], [0.5, 0.52], [1, 1]],
                    "green": [[0, 0], [0.5, 0.5], [1, 0.99]],
                    "blue": [[0, 0.015], [0.5, 0.49], [1, 0.985]],
                },
                "presence": {"dehaze": 0.08, "clarity": 0.14, "texture": 0.1},
                "color_management": {
                    "rendering": "perceptual",
                    "gamut_mapping": "oklch_compress",
                },
                "hsl": {
                    "orange": {"saturation": 0.04, "luminance": 0.02},
                    "blue": {"hue": -4, "saturation": 0.08, "luminance": -0.02},
                },
                "color_grading": {
                    "shadows": {"hue": 220, "saturation": 0.035},
                    "highlights": {"hue": 42, "saturation": 0.03},
                    "balance": 0.05,
                    "blending": 0.55,
                },
                "local_adjustments": [
                    {
                        "mask": {
                            "type": "composite",
                            "operation": "subtract",
                            "inputs": [
                                {
                                    "type": "radial",
                                    "center": [0.52, 0.46],
                                    "radius": [0.4, 0.44],
                                    "feather": 0.7,
                                    "opacity": 1,
                                    "invert": False,
                                },
                                {
                                    "type": "luminance",
                                    "min": 0.88,
                                    "max": 1,
                                    "feather": 0.08,
                                    "opacity": 1,
                                    "invert": False,
                                },
                            ],
                            "opacity": 0.45,
                            "invert": False,
                        },
                        "adjustments": {"exposure": 0.1, "texture": 0.06},
                    }
                ],
                "detail": {
                    "denoise": 0.08,
                    "sharpen": 0.45,
                    "sharpen_radius": 1.0,
                    "sharpen_threshold": 0.008,
                    "sharpen_edge_protection": 0.7,
                },
                "output": {"png_bit_depth": 8, "png_dither": "tpdf"},
            },
        ),
    ),
)


def run_json_command(arguments: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(PHOTO_GRADE), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_photos(input_dir: Path, output_dir: Path) -> list[Path]:
    output_resolved = output_dir.resolve()
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_SUFFIXES
        and output_resolved not in path.resolve().parents
    )


def run_visual_regression(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    if not input_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    photos = discover_photos(input_dir, output_dir)
    if not photos:
        raise ValueError("Input directory contains no JPEG or PNG photographs.")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "input_directory": str(input_dir),
        "output_directory": str(output_dir),
        "stages": [stage_name for stage_name, _ in STAGES],
        "images": [],
    }

    for source in photos:
        relative = source.relative_to(input_dir)
        source_key = relative.with_suffix("")
        source_token = f"{source_key.name}_{source.suffix.lower().lstrip('.')}"
        target_dir = output_dir / source_key.parent / source_token
        target_dir.mkdir(parents=True, exist_ok=True)
        image_entry: dict[str, Any] = {
            "source": str(relative),
            "source_sha256": sha256(source),
            "stages": [],
        }
        try:
            image_entry["analyze"] = run_json_command(
                ["analyze", str(source), "--report", "full"]
            )
        except Exception as exc:
            image_entry["error"] = str(exc)
            manifest["images"].append(image_entry)
            continue

        for stage_name, stage_recipe in STAGES:
            output = target_dir / f"{source_token}_{stage_name}.png"
            recipe_path = target_dir / f"{stage_name}.json"
            recipe_path.write_text(
                json.dumps(stage_recipe, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            stage_entry: dict[str, Any] = {
                "stage": stage_name,
                "output": str(output.relative_to(output_dir)),
            }
            try:
                stage_entry["grade"] = run_json_command(
                    [
                        "grade",
                        str(source),
                        str(output),
                        "--recipe",
                        str(recipe_path),
                        "--report",
                        "full",
                    ]
                )
                stage_entry["compare"] = run_json_command(
                    ["compare", str(source), str(output), "--report", "full"]
                )
                stage_entry["output_sha256"] = sha256(output)
                stage_entry["status"] = "passed"
            except Exception as exc:
                stage_entry["status"] = "failed"
                stage_entry["error"] = str(exc)
            image_entry["stages"].append(stage_entry)
        manifest["images"].append(image_entry)

    manifest["summary"] = {
        "images": len(manifest["images"]),
        "stages_passed": sum(
            stage.get("status") == "passed"
            for image in manifest["images"]
            for stage in image.get("stages", [])
        ),
        "stages_failed": sum(
            stage.get("status") == "failed"
            for image in manifest["images"]
            for stage in image.get("stages", [])
        ),
        "analyze_failed": sum("error" in image for image in manifest["images"]),
    }
    report_path = output_dir / "visual-regression-report.json"
    report_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest["report_path"] = str(report_path)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path, help="External directory containing legal JPEG/PNG photos")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "tests" / "output" / "visual-regression",
        help="Ignored output directory for renders, recipes, and the JSON report",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_visual_regression(args.input_dir, args.output_dir)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(report["report_path"])
    summary = report["summary"]
    return 1 if summary["stages_failed"] or summary["analyze_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
