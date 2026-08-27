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
- For a broad request such as “调色” or “make this look better,” render `3–6` intensity-`3` finals. Choose the count from the number of materially distinct, useful directions the source supports; do not default to the lower bound simply because a reference spectrum has been covered.
- Let explicit constraints replace only conflicting defaults. For example, “只要自然版” produces one natural result, “不要胶片” excludes film looks, and a named style or intensity narrows the set.
- Label styles sequentially with uppercase letters (`A`, `B`, `C`); label intensity with digits (`1`, `2`, `3`). Never swap these roles.
- Deliver full-quality finals, not proofs, contact sheets, or reduced previews.
- Block only when no valid output can be produced: missing, corrupt, undecodable, or unsupported input; a required dependency or permission failure; a script or color-conversion failure; insufficient resources; or irreconcilable instructions. Report the actionable cause instead of asking for an aesthetic choice.
- If incomplete or ambiguous skill documentation forces you to inspect implementation code to proceed, finish the photo task when safe, then tell the user what was undocumented and what behavior you confirmed so the skill can be improved. Routine use should not require reading code.

## Boundaries

- Accept JPEG and PNG only. Use the uploaded file, not a screenshot or reduced substitute.
- Render each recipe from the original to a new path. Never stack a new grade onto an exported result.
- Use only the bundled deterministic controls and geometric, luminance, or color masks. Never use image generation, inpainting, semantic segmentation, content-aware editing, or claimed subject/sky masks.
- Do not retouch, transform geometry, synthesize detail, add grain, or simulate depth of field.
- Enable denoise or sharpening only when justified or requested, and keep them conservative.
- Treat `detected_format` as authoritative. By default, deliver the same detected format and use `recommended_extension` when the source suffix is misleading. Convert formats only when the user requests it.
- Choose 16-bit PNG when retaining a 16-bit sRGB PNG source, delivering a high-precision intermediate, or protecting newly shaped gradients from an additional 8-bit quantization. It cannot recover precision already absent from an 8-bit source. For an 8-bit PNG delivery with long smooth gradients, deterministic dithering may reduce visible banding.
- Ordinary JPEG and 8-bit PNG work does not require PyPNG. Before selecting 16-bit PNG, ensure the pinned dependencies in `requirements.txt` are installed; if PyPNG is unavailable, keep unrelated work running and treat only the requested 16-bit operation as blocked.
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
- Mine the scene before naming styles. Identify the primary subject, secondary subject and their relationship; existing light events such as reflections, caustics, backlight, haze, or silhouettes; foreground-to-background depth; negative space; motion lines; scale cues; dominant color relationships; and surfaces that can carry focal highlights. Look for what the photograph could become, not only what needs correction.
- Define the strongest coherent transformation the source can support without sacrificing important subject structure.

When the user supplies a visual reference, decompose it into transferable properties such as contrast topology, focal brightness, palette separation, depth, highlight placement, saturation strategy, and emotional scale. Treat those properties as an ambition bar, not as a LUT or composition to copy. Do not import content, geometry, typography, or a palette that the source does not support.

Note the reported bit depth, ICC state, detected format, and extension agreement; apply the input/output policy above.

### 2. Design the directions

Before designing directions or recipes, read [references/capabilities-and-recipes.md](references/capabilities-and-recipes.md) completely. It is the authoritative capability map and recipe contract, not a checklist of controls to activate. Read [references/technical-behavior.md](references/technical-behavior.md) only when selecting a strict color-management, high-bit-depth, or dithering path; diagnosing artifacts or failures; interpreting extended reports; or explaining implementation details.

For the default set, choose directions from the scene's strongest opportunities rather than filling fixed categories. A useful set may range from faithful natural correction through creative scene-adaptive work to bold editorial or cinematic interpretations; these are reference points, not required slots. Make every pair differ on at least two primary axes: exposure key, contrast structure, palette, saturation strategy, local-light design, depth treatment, or texture treatment.

When bold work is supported, generate `3–5` scene-specific blockbuster theses internally before writing recipes. Vary the narrative and large-scale tonal architecture, not merely the palette. Explore different ways to amplify existing light, turn negative space and depth into scale, strengthen the relationship or motion between subjects, and reinterpret the scene's dominant color contrast. Select and render the strongest `1–3` when they express genuinely different and useful readings of the scene. Stop when another direction would be cosmetic.

Build tonal architecture before polishing color. Preserve the scene's evidence, then amplify its strongest premise decisively. When the source offers bright focal surfaces, reflections, or caustics against open negative space, deliberately extend toward brilliant localized highlights and deep supporting tones; controlled local clipping and near-black regions are acceptable when important structure survives. A high-key, hazy, muted, or low-contrast blockbuster is valid only when its large-scale hierarchy, depth, focal separation, and emotional scale are still unmistakably authored. “Preserving the mood” must never justify a merely safer grade.

Keep every direction achievable from existing pixels and never impose a genre preset or contradictory light. Define observable success criteria for each direction. A bold concept must visibly transform the scene's hierarchy without depending only on a global hue wash, uniform darkening, added saturation, or a generic vignette.

### 3. Commit one recipe per output

After inspection, write one internal `schema_version: 1` recipe for each output before invoking `grade`. Include every required structural field but only active parameter values; the script supplies neutral defaults and rejects unknown fields. Make every active control serve the visual intent. Retain the original path, final recipe, report, output settings, and pipeline version through the active conversation so follow-up refinements remain reproducible. Do not expose recipes for confirmation.

### 4. Render every selected final

Render each recipe from the original:

```bash
python3 <skill-dir>/scripts/photo_grade.py grade <input> <output> \
  --recipe <internal-recipe.json>
```

Keep each complete JSON report attributable to its output. Parallel rendering is allowed only when reports cannot become mixed.

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

Inspect all variants together. Redesign any pair separated only by cosmetic changes. A natural result may remain restrained, but a creative or bold result fails if it reads as merely corrected, uniformly darker or cooler, palette-shifted, or dependent on side-by-side comparison to reveal its intent. Confirm that the bold result amplifies a scene-specific light, depth, scale, motion, or subject relationship and that its hierarchy remains strong in grayscale.

If a bold result misses its thesis, strengthen the responsible large-scale tone and local-light stages before adding more saturation or texture. If it introduces damage, reduce only the responsible controls. Rerender from the original without asking for confirmation.

If targeted revisions cannot make a bold recipe meet its thesis safely, abandon it and try the next-ranked bold thesis rather than shipping a conservative fallback.

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
