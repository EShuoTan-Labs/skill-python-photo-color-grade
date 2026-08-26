---
name: python-photo-color-grade
description: Analyze and color-grade an uploaded JPEG or PNG photograph with a deterministic Lightroom-style Python pipeline. Use when a provided photo needs 调色, exposure or white-balance correction, tone curves, HSL, three-way color grading, dehaze, clarity, texture, deterministic local masks, denoise, sharpening, or a natural through bold creative look. Apply non-generative tonal, color, and detail adjustments only. Do not use for conceptual editing questions without an input photo, retouching, object removal, inpainting, semantic editing, HEIC, or RAW.
---

# Python Photo Color Grade

Use the bundled Python pipeline to inspect, design, render, verify, and deliver final-quality grades from the actual photograph.

## Priorities

Apply these in order:

1. Preserve the source: work non-generatively, render from the original, and never overwrite it.
2. Honor explicit user constraints on style, count, intensity, and format.
3. Make every delivered direction coherent, useful, and materially distinct.
4. Inspect the encoded full-resolution outputs and iterate before delivery.

## Defaults and blockers

- Start the first pass without asking the user to choose a style or understand controls.
- For a broad request such as “调色” or “make this look better,” render three intensity-`3` finals: one faithful natural correction, one clearly creative scene-adaptive interpretation, and one bold editorial or cinematic interpretation. If a bold treatment would fight the source, replace it with a different strong but scene-faithful concept. Add a fourth direction only when the image supports a genuinely different and useful idea.
- For a singular correction such as “提亮一点” or “修正白平衡,” render one faithful result unless the user requests alternatives.
- Let explicit constraints replace only conflicting defaults. For example, “只要自然版” produces one natural result, “不要胶片” excludes film looks, and a named style or intensity narrows the set.
- Label styles sequentially with uppercase letters (`A`, `B`, `C`); label intensity with digits (`1`, `2`, `3`). Never swap these roles.
- Deliver full-quality finals, not proofs, contact sheets, or reduced previews.
- Block only when no valid output can be produced: missing, corrupt, undecodable, or unsupported input; a required dependency or permission failure; a script or color-conversion failure; insufficient resources; or irreconcilable instructions. Report the actionable cause instead of asking for an aesthetic choice.

## Boundaries

- Accept JPEG and PNG only. Use the uploaded file, not a screenshot or reduced substitute.
- Render each recipe from the original to a new path. Never stack a new grade onto an exported result.
- Use only the bundled deterministic controls and geometric, luminance, or color masks. Never use image generation, inpainting, semantic segmentation, content-aware editing, or claimed subject/sky masks.
- Do not retouch, transform geometry, synthesize detail, add grain, or simulate depth of field.
- Enable denoise or sharpening only when justified or requested, and keep them conservative.
- Treat `detected_format` as authoritative. By default, deliver the same detected format and use `recommended_extension` when the source suffix is misleading. Convert formats only when the user requests it.
- Choose 16-bit PNG only when retaining a 16-bit sRGB PNG source or when the user requests a high-precision PNG delivery. It cannot restore precision missing from an 8-bit source. PyPNG is required only for 16-bit PNG operations; if unavailable, keep JPEG and 8-bit PNG work running.
- For strict perceptual or high-bit-depth processing, require a valid conversion to tagged sRGB. Never silently use unmanaged color.

## Workflow

### 1. Inspect the source

Inspect the photograph visually, then run:

```bash
python3 <skill-dir>/scripts/photo_grade.py analyze <input> --pretty
```

Assess exposure, clipping, usable dynamic range, white balance, saturation, noise, softness, and composition. Use `rgb_channels`, `spatial_luma_grid_3x3`, `spatial_rgb_mean_grid_3x3`, and histograms as evidence, not as automatic correction targets. Confirm every interpretation visually.

- Do not infer illumination direction from a bright-to-dark gradient alone; subject reflectance, clothing, sky, and background can create the same pattern. Prefer consistent cues such as cast shadows, specular highlights, shading across one surface, window or sun position, and facial modeling. If direction remains ambiguous, use broad tonal zoning instead of directional relighting.
- Do not neutralize an intentional warm, cool, or colorful scene from global RGB averages. Base white-balance correction on credible neutral surfaces or repeated spatial evidence when available. Use skin only as a plausibility constraint, never as a neutral reference.
- Identify highlight latitude, important texture, negative space, and separation available through luminance, hue, saturation, or temperature. Define the strongest coherent transformation the source can support without sacrificing important subject structure.

Note the reported bit depth, ICC state, detected format, and extension agreement; apply the input/output policy above.

### 2. Design the directions

Use [references/parameters.md](references/parameters.md) progressively:

1. Always read `Required internal recipe`, `Intensity and creative range`, `Creative structure and controlled extremes`, and `Basic and tone controls`.
2. Read a control's complete section before including that control in any recipe.
3. Read `Local masks`, `Detail and output`, or `Analysis and reports` only when the task uses those capabilities. Do not load unrelated sections.

For the default set, make every pair differ on at least two primary axes: exposure key, contrast structure, palette, saturation strategy, local-light design, or texture treatment. Stop when another direction would be cosmetic.

Build tonal architecture before polishing color, but preserve the scene's native premise. A bold result need not force deep blacks and brilliant whites: a high-key, hazy, muted, or low-contrast image can be strongly authored through controlled hierarchy, palette, and separation. Never impose a genre preset or contradictory light merely to make a result look stronger.

Keep every direction achievable from existing pixels. Define observable success criteria for each direction, and make the bold concept visibly authored without depending only on a global hue wash or generic vignette.

### 3. Commit one recipe per output

After inspection, write one internal `schema_version: 1` recipe for each output before invoking `grade`. Include every required structural field but only active parameter values; the script supplies neutral defaults and rejects unknown fields. Make every active control serve the visual intent. Retain the original path, final recipe, report, output settings, and pipeline version through the active conversation so follow-up refinements remain reproducible. Do not expose recipes for confirmation.

### 4. Render every selected final

Render each recipe from the original:

```bash
python3 <skill-dir>/scripts/photo_grade.py grade <input> <output> \
  --recipe <internal-recipe.json> --skip-update-check
```

Keep each complete JSON report attributable to its output. Parallel rendering is allowed only when reports cannot become mixed. Check for skill updates only when the user explicitly asks; never couple maintenance traffic to photo rendering.

Name each file `<original-stem>_<style-id><intensity>_<direction-description><extension>`, for example `IMG_1234_A3_自然通透.jpg`.

- Preserve the source stem and apply the input/output policy above.
- Use the recipe's uppercase ID and numeric intensity without a separator.
- Use a concise direction name matching the recipe and the user's language. Remove line breaks and `/`, `\\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`; do not add timestamps or random IDs.

### 5. Verify and iterate

Each successful `grade` call reopens the encoded output, checks dimensions and alpha, and returns `before` and `after` metrics. Use that report instead of rerunning `compare`; use `compare` only when the original grade report is unavailable.

Visually inspect every encoded output with an original-detail viewer or representative 100% crops; a fit-to-window chat preview is insufficient for detail QA. Cover at least smooth gradients, the focal subject, fine texture, and the strongest edge. Judge metrics spatially and in context rather than accepting or rejecting a result from a global clipping ratio alone. Check:

- tonal hierarchy, important highlight and shadow structure, white balance, skin and credible neutrals;
- banding, halos, color contamination, noise smearing, brittle texture, and oversharpening;
- smooth skies and shadows when presence or sharpening is active, plus strong edges when edge protection is active;
- the output ICC declaration matches the intended tagged sRGB path;
- saturated colors and highlights for hue breaks or gamut-edge contours when perceptual rendering or gamut compression is active; use the pre-map excursion and visible mapping effect to judge severity because a final zero out-of-gamut ratio alone proves only that mapping completed;
- actual IHDR bit depth and an independent decoder for 16-bit PNG, or gradients at 100% for both banding and structured texture when dithering is active.

Inspect all variants together. Redesign any pair separated only by cosmetic changes. A creative or bold result must meet its declared thesis, while a natural result may remain restrained. If a result misses its thesis, revise only the responsible coordinated stages; if it introduces damage, reduce only the responsible controls. Rerender from the original without asking for confirmation.

Allow at most two corrective rerenders per output. If it still fails, use a conservative valid fallback or omit that variant and state the concrete limitation; never loop indefinitely.

### 6. Deliver visible finals

Show every final before extended explanation. Give each result its own heading, visible preview, and ordinary link; do not place multiple images on one line, in a table, or in a list.

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
