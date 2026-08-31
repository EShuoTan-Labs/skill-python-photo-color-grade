---
name: python-photo-color-grade
description: Analyze and color-grade an uploaded JPEG or PNG photograph with a deterministic Lightroom-style Python pipeline. Use when a provided photo needs 调色, exposure or white-balance correction, tone curves, HSL, three-way color grading, dehaze, clarity, texture, deterministic local masks, denoise, sharpening, or a natural through bold creative look. Apply non-generative tonal, color, and detail adjustments only. Do not use for conceptual editing questions without an input photo, retouching, object removal, inpainting, semantic editing, HEIC, or RAW.
---

# Python Photo Color Grade

Use the bundled Python pipeline to inspect, design, render, verify, and deliver final-quality grades from the actual photograph.

## Core requirements

- Preserve the source: render every output non-generatively from the original to a new path; never overwrite it.
- Treat explicit user constraints on style, count, intensity, and format as authoritative unless they conflict with the skill's boundaries.
- Verify the actual encoded full-resolution outputs before delivery; iterate when a result misses its intent or fails quality checks.

## Defaults and blockers

- Start the first pass without asking the user to choose a style or understand controls.
- For a broad zero-direction request such as “调色” or “make this look better,” render `3–6` materially distinct full-quality finals at intensity level `3`. The set must include at least one bold **hero final** unless an explicit user constraint rules bold work out; let the remaining directions range from source-faithful refinement to other transformative interpretations the photograph supports.
- Let explicit constraints replace only conflicting defaults. For example, “只要自然版” produces one natural result, “不要胶片” excludes film looks, and a named style or intensity narrows the set.
- Label styles sequentially with uppercase letters (`A`, `B`, `C`); label intensity with digits (`1`, `2`, `3`).
- Deliver full-quality finals, not proofs, contact sheets, or reduced previews.
- Block only when no valid output can be produced: missing, corrupt, undecodable, or unsupported input; a required dependency or permission failure; a script or color-conversion failure; insufficient resources; or irreconcilable instructions. Report the actionable cause instead of asking for an aesthetic choice.

## Boundaries

- Accept JPEG and PNG only. Use the uploaded file, not a screenshot or reduced substitute.
- Never stack a new grade onto an exported result.
- Use only the bundled deterministic controls and geometric, luminance, or color masks. Never use image generation, inpainting, semantic segmentation, content-aware editing, or claimed subject/sky masks.
- Enable denoise or sharpening only when justified or requested, and keep them conservative.
- Treat `detected_format` as authoritative. By default, deliver the same detected format and use `recommended_extension` when the source suffix is misleading. Convert formats only when the user requests it.
- Choose 16-bit PNG when retaining a 16-bit sRGB PNG source, delivering a high-precision intermediate, or protecting newly shaped gradients from an additional 8-bit quantization. It cannot recover precision already absent from an 8-bit source. For an 8-bit PNG delivery with long smooth gradients, deterministic dithering may reduce visible banding.
- Ordinary JPEG and 8-bit PNG work does not require PyPNG. Before selecting 16-bit PNG, ensure the pinned dependencies in `requirements.txt` are installed; if PyPNG is unavailable, keep unrelated work running and treat only the requested 16-bit operation as blocked.
- For strict perceptual or high-bit-depth processing, require a valid conversion to tagged sRGB. Never silently use unmanaged color.

## Workflow

### 1. Inspect the source

First read the photograph directly and form a provisional visual judgment of its light, color, hierarchy, depth, texture, and strongest creative opportunities. Only then run:

```bash
python3 <skill-dir>/scripts/photo_grade.py analyze <input> --report agent
```

Let the direct visual reading drive the assessment and the creative directions. Treat `rgb_channels`, percentiles, `spatial_luma_grid_3x3`, `spatial_rgb_mean_grid_3x3`, and other Python statistics as secondary diagnostic evidence: use them to corroborate or question a visual interpretation, locate possible technical risks, and inspect properties that are hard to judge from a preview. They must not originate an aesthetic direction, dictate a correction, or determine parameter magnitude. When statistics and the image appear to disagree, reinspect the relevant pixels at appropriate scale and decide from the photograph; let statistics override only for objective encoding or pipeline facts such as bit depth, clipping, ICC state, and format. The default report is sufficient for routine diagnostics. Request `--report full` only when extra histogram detail is needed to investigate a specific uncertainty or artifact.

- Do not infer illumination direction from a bright-to-dark gradient alone; subject reflectance, clothing, sky, and background can create the same pattern. Prefer consistent cues such as cast shadows, specular highlights, shading across one surface, window or sun position, and facial modeling. If direction remains ambiguous, use broad tonal zoning instead of directional relighting.
- Do not neutralize an intentional warm, cool, or colorful scene from global RGB averages. Base white-balance correction on credible neutral surfaces or repeated spatial evidence when available. Use skin only as a plausibility constraint, never as a neutral reference.
- Mine the scene before naming directions. Identify the subject relationships, existing light, depth, negative space, motion, scale, dominant colors, and important surfaces from the photograph itself. Look for several things the photograph could become, not only what needs correction; use the numeric report afterward only to test those readings and flag technical risks.

Note the reported bit depth, ICC state, detected format, and extension agreement; apply the input/output policy above.

### 2. Design the directions

Before designing directions or recipes, read [references/capabilities-and-recipes.md](references/capabilities-and-recipes.md) completely. It is the authoritative capability map and recipe contract, not a checklist of controls to activate.

For a zero-direction request, draft more candidates than you will render. Briefly locate each against the source on tonal key, contrast shape, color purity, palette relationship, spatial emphasis, and texture, then choose `3–6` directions from the scene's strongest opportunities rather than filling fixed categories. Prefer `4` when the source has enough latitude; use fewer when another result would be cosmetic. Make every pair differ materially on at least two primary axes: exposure key, contrast structure, palette, saturation strategy, local-light design, depth treatment, or texture treatment. Across the set, vary combinations rather than moving every axis together: do not assume, for example, that a darker interpretation must also be more saturated, or that a muted interpretation must be brighter.

Design the required hero final as the strongest photograph-specific editorial interpretation, not the recipe with the largest slider values. It must combine multiple substantial source-relative departures into one coherent visual thesis, with decisive tonal architecture, intentional palette relationships, and authored focal or spatial hierarchy. It should feel complete and unmistakably authored at first glance without relying on novelty, a global color wash, indiscriminate saturation, generic vignetting, or damaged important structure. If the source has narrow latitude, pursue boldness through hierarchy, color relationships, and spatial emphasis rather than unsafe extremes.

Build every direction from the photograph's own evidence. For each candidate, identify what should carry the eye, what should support or recede, which existing light, color, depth, scale, or motion relationship the grade develops, and what visible change separates it from the other candidates. Derive active hues, curves, mask geometry, and magnitudes from this photograph. Do not begin from a scene class, style taxonomy, reusable recipe, numeric example, or previous photograph. Keep every move achievable from existing pixels.

Write three to five observable success criteria for each direction. Together they should state what must visibly change relative to this source, what must remain intact, and the most likely artifact. Choose parameters only after the intended result is clear enough to reject a render. Any axis claimed in a level-3 creative intent must be obvious in the full frame; a recipe that merely names a low key, muted palette, warm/cool shift, or spatial emphasis without visibly achieving it fails. Use large tonal, palette, or spatial moves when the concept needs them; do not reduce a creative direction to a global tint or minor correction.

### 3. Commit all selected recipes in one manifest

After inspection, write one internal `schema_version: 1` batch manifest containing one recipe and final output path per selected result. Include every required recipe structural field but only active parameter values; the script supplies neutral defaults and rejects unknown fields. Make every active control serve the visual intent. Relative output paths resolve from the manifest's directory. Retain the original path, manifest, final recipes, report, output settings, and pipeline version through the active conversation so follow-up refinements remain reproducible. Do not expose recipes for confirmation.

### 4. Render every selected final

Render the complete set with one command:

```bash
python3 <skill-dir>/scripts/photo_grade.py grade-batch <input> \
  --manifest <internal-batch.json> --report agent
```

The batch command validates the entire manifest before rendering, applies every recipe independently from the original, reopens every encoded output, and keeps each report attributable to its output. It renders to sibling temporary files and publishes the final paths only after the complete set passes; a failure preserves pre-existing finals and removes temporary renders. Its default report retains the clipping, percentile, spatial, encoding, and processing evidence required for routine QA; `before_ref` identifies the applicable source metrics for each output. Request `--report full` whenever complete 64-bin histograms or extended diagnostics could improve the quality judgment.

When exactly one output is needed, `grade ... --recipe ... --report agent` remains valid. Do not split a multi-output set into separate `grade` calls.

Name each file `<original-stem>_<style-id><intensity>_<direction-description><extension>`, for example `IMG_1234_A3_自然通透.jpg`.

- Preserve the source stem and apply the input/output policy above.
- Use the recipe's uppercase ID and numeric intensity without a separator.
- Use a concise direction name matching the recipe and the user's language. Remove line breaks and `/`, `\\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`; do not add timestamps or random IDs.

### 5. Verify and iterate

Each successful `grade` or `grade-batch` item reopens the encoded output, checks dimensions and alpha, and returns `before`, `after`, and a source-relative `transformation_summary`. Use that report instead of rerunning `compare`; use `compare` only when the original grade report is unavailable.

Judge each result through two independent gates: it must visibly fit its own intent at first glance, and it must retain technical integrity. Inspect the complete image before consulting metrics. Use `transformation_summary` only to challenge a visual claim or locate the responsible stage; numbers cannot approve an aesthetic result.

Visually inspect every encoded output with an original-detail viewer or representative 100% crops; a fit-to-window chat preview is insufficient for detail QA. Cover the focal region and strongest edge, plus smooth gradients and fine texture where present. Judge metrics spatially and in context rather than accepting or rejecting a result from a global clipping ratio alone. Check:

- tonal hierarchy, important highlight and shadow structure, white balance, skin and credible neutrals;
- banding, halos, color contamination, noise smearing, brittle texture, and oversharpening;
- smooth skies and shadows when presence or sharpening is active, plus strong edges when edge protection is active;
- the output ICC declaration matches the intended tagged sRGB path;
- saturated colors and highlights for hue breaks or gamut-edge contours when perceptual rendering or gamut compression is active; use the pre-map excursion and visible mapping effect to judge severity because a final zero out-of-gamut ratio alone proves only that mapping completed;
- actual IHDR bit depth and an independent decoder for 16-bit PNG, or gradients at 100% for both banding and structured texture when dithering is active.

Inspect all `3–6` finals together and redesign any pair separated only by cosmetic changes. The set fails when every result occupies the same tonal key, saturation regime, palette relationship, or spatial treatment. For a zero-direction set, it also fails if no result qualifies as the hero final defined above. The hero must stand on its own as a finished photograph, show deliberate authorship across at least two primary axes, retain important subject structure, and remain the strongest result when judged at full frame and at representative 100% crops. A creative result must read clearly without the original beside it, while a source-faithful result may remain restrained. Treat metric changes as diagnostics, not substitutes for this visual judgment.

Rerender only a direction that visibly misses its stated intent, duplicates another result, loses important structure, or has a technical defect. There is no minimum number of calibration passes and no privileged `A3`; a strong first render may be delivered directly. When revision is needed, change the smallest responsible control family, render again from the original, and keep already successful directions unchanged.

If targeted revisions cannot make the hero recipe meet its thesis safely, abandon it and try the next-ranked bold thesis. Do not ship a zero-direction set without a qualifying hero final or silently relabel a conservative result as bold.

### 6. Deliver visible finals

Show every final before extended explanation. Give each result its own heading, visible preview, and ordinary link; do not place multiple images on one line, in a table, or in a list.

For a zero-direction set, identify the qualifying bold result as the **hero final** in its heading or concise description so the user can recognize the intended centerpiece.

```markdown
### A3 自然通透

![A3 自然通透](sandbox:/absolute/path/IMG_1234_A3_自然通透.jpg)

[A3 自然通透](sandbox:/absolute/path/IMG_1234_A3_自然通透.jpg)
```

Under each result, describe only the observable differences concisely. Provide exact settings only when the user asks; report the final recipe that produced the delivered file, using `--show-parameters` when useful.

## Follow-up requests

- Interpret a letter without a digit as intensity `3`; apply a trailing digit to every selected letter. `B` means `B3`, and `AC2` means `A2` plus `C2`.
- Accept natural-language refinements such as “B 再通透一点” or “以 C 为基础提亮地面”. Revise the referenced recipe and rerender from the original.
- Return only the requested revised finals unless the user asks to regenerate the full set.
