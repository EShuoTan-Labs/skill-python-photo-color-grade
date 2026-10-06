---
name: python-photo-color-grade
description: Color-grade a provided JPEG or PNG photograph with the bundled deterministic Python pipeline. Use for photo color grading, 调色, exposure, white balance, curves, HSL, local tonal/color adjustments, and detail finishing. Supports multiple creative interpretations and follow-up refinement.
---

# Python Photo Color Grade

Produce finished photographs from the original pixels using `scripts/photo_grade.py`.

## Outcome

For an open-ended first request, deliver **3–6 materially distinct full-resolution finals**, including at least one bold **hero final** with the visual authorship of an exceptional photographic colorist. Choose the directions from the photograph itself. The hero should have a coherent, decisive interpretation across tone, palette, or spatial hierarchy and retain important subject structure.

Explicit user choices of style, count, strength, and format take precedence. Start directly when a usable photograph is available. Use uppercase style IDs (`A`, `B`, …) and intensity `1` (subtle), `2` (clearly styled), or `3` (fully expressed, including natural work).

## Inspect and design

View the actual source first. Let its light, color relationships, subject hierarchy, depth, and texture lead the creative judgment. Then run:

```bash
python "<skill-dir>/scripts/photo_grade.py" analyze "<input>" --report agent
```

Statistics are secondary evidence for technical diagnosis; they do not prescribe aesthetics or slider values. Resolve visual uncertainty by inspecting the image at the relevant scale. Encoding facts such as format, bit depth, and ICC status come from the report.

Read the recipe contract and relevant control sections in [references/capabilities-and-recipes.md](references/capabilities-and-recipes.md). Design each result's observable intent before choosing parameters. Use the structured `visual_intent` and `success_criteria` fields to record its target and important structure to preserve. Select directions with visible differences in at least two of tone, palette, saturation, spatial emphasis, depth, or texture. Derive active values and mask geometry from this image.

## Render

Write a `schema_version: 1` manifest containing one complete recipe and output path per result. Include only active parameter sections; neutral defaults are supplied by the script. Relative paths resolve from the manifest directory. Render each recipe independently from the original:

```bash
python "<skill-dir>/scripts/photo_grade.py" grade-batch "<input>" --manifest "<batch.json>" --report agent
```

For one result, use `grade "<input>" "<output>" --recipe "<recipe.json>" --report agent`. Both commands verify encoded outputs before publishing. The batch validates all recipes first and publishes the complete set after verification.

Keep the original, manifest, final recipes, and render report available for reproducible follow-ups. Name finals `<original-stem>_<style-id><intensity>_<direction-name><extension>`; sanitize characters forbidden in filenames.

## Verify and deliver

View every encoded final at full frame and inspect representative 100% detail: focal region, strongest edges, smooth gradients, and fine texture where present. Check intent, important tonal structure, credible color, banding, halos, noise, and detail. Use the returned `before`, `after`, `transformation_summary`, and encoding diagnostics to investigate issues. `--report full` adds histogram detail when needed; `compare` is available if the render report was lost.

Judge the set together for meaningful aesthetic range and a compelling hero. Revise a result that misses its intent, duplicates another, or develops artifacts, then render it again from the original. Successful directions can stay as they are.

Show every final with its own short heading, image, and download link, using absolute local paths supported by the host (Such as: `![label](D:/absolute/path/photo.jpg)` and `[label](D:/absolute/path/photo.jpg)`). Identify the hero in its heading. Describe visible differences briefly; provide exact settings when requested.

## Processing contract

- Accept original JPEG and PNG files. Preserve the source and dimensions; write to a new path. Supported work is tonal, color, and detail processing using the bundled controls and geometric/luminance/color masks.
- Use `detected_format` and `recommended_extension` to retain the source format by default. Convert formats when requested. Preserve PNG alpha.
- Retain 16-bit sRGB PNG source precision with `output.png_bit_depth: 16`. It is also available for high-precision intermediates; it requires PyPNG from `requirements.txt`. For 8-bit PNG gradients, `output.png_dither: "tpdf"` is available when quantization is visible.
- Verify ICC handling. Perceptual rendering, gamut compression, and 16-bit output require managed sRGB. Resolve an ICC conversion warning before delivering a color-critical result.
- Enable denoise and sharpening when justified by the image or requested, then inspect encoded detail.
- Report actionable input, dependency, conversion, or execution failures when they prevent a valid result.

## Follow-ups

A letter alone keeps intensity `3`; a trailing digit applies to every selected letter (`B` → `B3`, `AC2` → `A2` and `C2`). Interpret natural-language refinements against the referenced direction, revise its recipe, and render from the original. Return the requested revised finals.
