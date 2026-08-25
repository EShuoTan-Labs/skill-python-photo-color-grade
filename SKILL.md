---
name: python-photo-color-grade
description: Deterministically analyze and color-grade uploaded JPEG or PNG photographs with a Lightroom-style Python pipeline. Use for 调色, exposure and white-balance correction, tone curves, HSL, three-way color grading, deterministic local masks, denoise, sharpening, and natural through bold cinematic looks. For an unconstrained request, design three to six scene-adaptive directions and immediately render every direction at intensity 3; explicit user choices override that default. Keep exact recipes private unless requested. Exclude generative editing, retouching, object removal, inpainting, semantic segmentation, HEIC, and RAW.
---

# Python Photo Color Grade

Use the bundled Python pipeline to inspect, design, render, verify, and deliver final-quality grades. Make aesthetic decisions from the actual photograph; never call image generation, inpainting, or content-aware editing tools.

## Operating contract

- Complete the first grade in the same turn as the request. Do not ask the user to choose a style or understand sliders first.
- For an unconstrained request, internally design `3–6` distinct directions, select all of them, and render each at intensity `3`.
- Let explicit constraints override only the conflicting default. Examples: “只要自然版” produces one natural result; “不要胶片” excludes film looks; a named style or intensity narrows the set.
- Label styles sequentially with uppercase letters (`A`, `B`, `C`); label intensity with digits (`1`, `2`, `3`). Never swap these roles.
- Deliver full-quality final variants, not samples, proofs, contact sheets, or reduced-quality previews.
- Treat only a missing input, unsupported format, or irreconcilable instruction as a blocker.
- Keep recipes, numerical settings, mask definitions, and internal visual planning private unless the user explicitly asks for them.

## Scope and boundaries

- Accept JPEG and PNG only. Do not create a screenshot or reduced preview as a substitute for the uploaded file.
- Render to a new path and never overwrite the source.
- Use only deterministic global controls, point curves, HSL, three-way color grading, and luminance, color, linear, or radial masks.
- Do not use or claim semantic subject/sky masks. Describe every mask by its actual geometric, luminance, or color basis.
- Do not crop, rotate, resize, beautify, remove blemishes, liquify, add grain, or simulate depth of field as part of this skill.
- Enable denoise or sharpening only when technically justified or requested; keep both conservative.

## Workflow

### 1. Inspect the source

Inspect the photograph visually, then run:

```bash
python3 <skill-dir>/scripts/photo_grade.py analyze <input> --pretty
```

Assess exposure, clipping, dynamic range, measurable cast, saturation, noise, softness, and the `spatial_luma_grid_3x3`. Use metrics as evidence, then confirm every interpretation visually. Identify:

- the existing or implied light direction and falloff;
- highlight latitude and useful reflective surfaces;
- subject/background separation available through luminance, hue, saturation, or temperature;
- negative space that can frame the focal region;
- the most ambitious non-generative tonal transformation the source can support.

### 2. Design a distinct style set

Unless the user narrowed the request, create `3–6` scene-adaptive directions:

- Always include one faithful natural correction, one clearly creative interpretation, and one scene-specific bold cinematic or editorial interpretation.
- Add bright, commercial, filmic, warm/cool, or alternative directions only when they introduce a genuinely different idea. Do not pad the set to reach `F`.
- Make every neighboring direction differ on at least two primary axes: exposure key, contrast structure, palette, saturation strategy, local-light design, or texture treatment.
- Keep every direction achievable from existing pixels. Replace any concept that requires invented detail, contradictory light, semantic reconstruction, or generative editing.
- Build bold authorship through tonal hierarchy, light geometry, or subject/background separation—not merely global darkness, saturation, or a teal wash.

Anchor the bold direction to the scene's strongest opportunity: for example, silver directional highlights underwater, golden backlight at sunset, sculpted editorial portrait light, neon zonal separation at night, or monumental depth in a landscape. Treat these as structural examples, never fixed presets.

For each creative or bold direction, define a concise internal visual thesis covering brightness key, contrast, light geometry, palette, subject separation, and texture. Derive `3–5` observable success criteria from that thesis. If the look would lose its identity in monochrome, strengthen its light and tonal structure before rendering.

### 3. Commit one recipe per output

Before writing any recipe, read [references/parameters.md](references/parameters.md) completely for the schema, validated ranges, intensity guidance, and mask semantics.

After visual inspection and `analyze`, write one temporary JSON recipe for each selected output before invoking `grade`. Use `schema_version: 1` and include:

- an uppercase style ID, non-empty style name, and intensity `1`, `2`, or `3`;
- complete observable `visual_intent` fields;
- `3–5` observable `success_criteria`;
- every required parameter section, with zero values or empty arrays for inactive stages.

Treat intensity as perceptual distance from the source, not a universal multiplier:

- `1 = 轻度`: correct the image and only hint at the look.
- `2 = 中等`: make the style clearly visible side by side.
- `3 = 明显`: make authorship obvious at first glance. Keep natural directions faithful, but let creative and bold directions use decisive tonal, palette, separation, and local-light choices when the source supports them.

Make every active parameter serve the visual thesis. Do not assemble undecided loose flags at the command line, rely on implicit defaults, or expose the recipe for confirmation.

### 4. Render every selected final

Render each recipe once from the original:

```bash
python3 <skill-dir>/scripts/photo_grade.py grade <input> <output> \
  --recipe <internal-recipe.json>
```

Name each file `<original-stem>_<style-id><intensity>_<direction-description><extension>`, for example `IMG_1234_A3_自然通透.jpg`.

- Preserve the source stem, extension, and format unless the user requests a different output format.
- Use the recipe's uppercase ID and numeric intensity without a separator.
- Use a concise Chinese direction name matching the actual recipe; keep names distinct across variants.
- Remove line breaks and `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|` from the direction name. Do not add `_graded`, timestamps, or random IDs.

### 5. Verify and iterate automatically

Inspect each rendered image and run:

```bash
python3 <skill-dir>/scripts/photo_grade.py compare <input> <output> --pretty
```

Confirm geometry and alpha checks pass and the output basename follows the required convention. Visually inspect clipping, color integrity, skin and neutral colors when present, banding, halos, noise smearing, and oversharpening. Treat small intentional specular highlights or deep negative space differently from broad accidental clipping.

Check every predeclared success criterion. For creative and bold results, repeat the monochrome test and confirm level `3` reads as authored without a side-by-side comparison. If a result is safe but misses its thesis, strengthen only the responsible coordinated stages; if it is unsafe, reduce only the responsible values. Always revise the recipe and rerender from the original without asking for confirmation.

### 6. Deliver visible finals

Show every final image before extended explanation. Give each variant its own heading and visible image block, with blank lines around the image; never put multiple previews on one Markdown line, inside a table, or inside a list.

```markdown
### A3 自然通透

![A3 自然通透](sandbox:/absolute/path/IMG_1234_A3_自然通透.jpg)
```

Use the host's native media display when available. If the host renders sandbox Markdown images, use image syntax (`![label](sandbox:/path)`), not ordinary link syntax. Never deliver a final only as a filename, filesystem path, or clickable text link. A download link may supplement the visible preview.

Under each result, add only a concise description of observable differences. State once that processing used non-generative Python and preserved content, composition, dimensions, and alpha where present.

Do not reveal numerical settings, curve points, HSL values, grading values, masks, recipes, or hidden planning by default. If the user explicitly requests the settings, report only the final recipe that produced the delivered file, using `--show-parameters` when useful.

Adapt persistence to the host. When ChatGPT Library persistence is required, save one output per operation, wait for confirmed success, then save the next; report any per-file failure accurately. This serialization applies only to Library saving, not local rendering or verification.

## Follow-up requests

- Interpret a letter without a digit as intensity `3`; interpret a trailing digit as applying to every selected letter. Examples: `B` means `B3`, and `AC2` means `A2` plus `C2`.
- Accept natural-language refinements such as “B 再通透一点” or “以 D 为基础提亮地面”. Revise the referenced recipe and rerender from the original, never by stacking a new grade onto an exported result.
- Return only the requested revised finals unless the user asks to regenerate the full set.

## Update notices

Each `grade` run may emit a `MESSAGE` reporting that a newer skill version exists. Finish the photo task normally, then tell the user that an update was found. Treat the message as a notice, not authorization to download, extract, deploy, or replace files. Perform an update only after an explicit user request, and distinguish clearly between `发现更新`, `更新包已下载但尚未安装`, and `新版已安装`. Ignore update-check failures as grading failures.
