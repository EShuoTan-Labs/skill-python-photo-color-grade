---
name: python-photo-color-grade
description: Analyze and color-grade uploaded JPEG or PNG photographs with a deterministic Lightroom-style Python pipeline. Use for 调色, exposure and white-balance correction, tone curves, HSL, three-way color grading, deterministic local masks, denoise, sharpening, and natural through bold cinematic looks. Apply non-generative tonal, color, and detail adjustments only. Do not use for retouching, object removal, inpainting, semantic editing, HEIC, or RAW.
---

# Python Photo Color Grade

Use the bundled Python pipeline to inspect, design, render, verify, and deliver final-quality grades from the actual photograph.

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
- Use only the bundled deterministic controls and masks. Never call image generation, inpainting, semantic segmentation, or content-aware editing tools.
- Do not use or claim semantic subject/sky masks. Describe every mask by its actual geometric, luminance, or color basis.
- Do not perform spatial transforms, retouching, synthetic detail, grain, or depth-of-field simulation.
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

Before designing directions or recipes, read [references/parameters.md](references/parameters.md) completely for creative structure, intensity guidance, the required schema, validated ranges, and mask semantics.

Unless the user narrowed the request, create `3–6` scene-adaptive directions:

- Always include one faithful natural correction, one clearly creative interpretation, and one scene-specific bold cinematic or editorial interpretation.
- Add bright, commercial, filmic, warm/cool, or alternative directions only when they introduce a genuinely different idea. Do not pad the set to reach `F`.
- Make every neighboring direction differ on at least two primary axes: exposure key, contrast structure, palette, saturation strategy, local-light design, or texture treatment.
- Keep every direction achievable from existing pixels. Replace any concept that requires invented detail, contradictory light, semantic reconstruction, or generative editing.
- Anchor the bold direction to the scene's strongest tonal or lighting opportunity rather than a fixed palette or genre preset.

Follow the reference's visual-thesis, success-criteria, tonal-structure, and anti-filter guidance for every creative or bold direction.

### 3. Commit one recipe per output

After visual inspection and `analyze`, write one temporary `schema_version: 1` recipe for each selected output before invoking `grade`. Follow the complete schema exactly, represent inactive stages with zeros or empty arrays, and make every active parameter serve the visual thesis. Do not assemble undecided loose flags at the command line, rely on implicit defaults, or expose the recipe for confirmation.

### 4. Render every selected final

Render each recipe once from the original:

```bash
python3 <skill-dir>/scripts/photo_grade.py grade <input> <output> \
  --recipe <internal-recipe.json>
```

Capture each invocation's complete JSON report separately and retain it through verification. Run grades in parallel only when their reports remain complete and attributable to the correct outputs; never batch them in a way that truncates or discards `before` and `after`.

Name each file `<original-stem>_<style-id><intensity>_<direction-description><extension>`, for example `IMG_1234_A3_自然通透.jpg`.

- Preserve the source stem, extension, and format unless the user requests a different output format.
- Use the recipe's uppercase ID and numeric intensity without a separator.
- Use a concise Chinese direction name matching the actual recipe; keep names distinct across variants.
- Remove line breaks and `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|` from the direction name. Do not add `_graded`, timestamps, or random IDs.

### 5. Verify and iterate automatically

Each successful `grade` call has already reopened the encoded output, rejected any dimension or alpha change, and returned source/output metrics as `before` and `after`. Use that report for the routine metric comparison; do not rerun `compare` for an output created by the same call. Only when auditing an existing output whose original report is unavailable, run `python3 <skill-dir>/scripts/photo_grade.py compare <input> <output> --pretty`.

Reopen and visually inspect every rendered image. Use `before` and `after` to detect unexpected clipping or tonal damage, then judge its visual extent and purpose. Check color integrity, skin and neutral colors when present, banding, halos, noise smearing, oversharpening, and broad crushed regions. Do not spend visual review on dimensions, alpha, or geometry: the pipeline exposes no geometric transforms and `grade` enforces those invariants.

Check every predeclared success criterion. For creative and bold results, repeat the monochrome test and confirm level `3` reads as authored without a side-by-side comparison. Then inspect all delivered variants together and confirm neighboring choices still differ on at least two primary axes; redesign clustered variants rather than accepting cosmetic differences.

If a result is safe but misses its thesis, strengthen only the responsible coordinated stages; if it is unsafe, reduce only the responsible values. Always revise the recipe and rerender from the original without asking for confirmation.

### 6. Deliver visible finals

Show every final image before extended explanation. Give each variant its own heading and visible image block, with blank lines around the image; never put multiple previews on one Markdown line, inside a table, or inside a list.

```markdown
### A3 自然通透

![A3 自然通透](sandbox:/absolute/path/IMG_1234_A3_自然通透.jpg)
```

Use the host's native media display when available. If the host renders sandbox Markdown images, use image syntax (`![label](sandbox:/path)`), not ordinary link syntax. Never deliver a final only as a filename, filesystem path, or clickable text link. A download link may supplement the visible preview.

Under each result, add only a concise description of observable differences. State once that processing used non-generative Python and preserved content, composition, dimensions, and alpha where present.

Do not reveal recipes, exact settings, masks, or hidden planning by default. If the user explicitly requests the settings, report only the final recipe that produced the delivered file, using `--show-parameters` when useful.

Adapt persistence to the host. When ChatGPT Library persistence is required, save one output per operation, wait for confirmed success, then save the next; report any per-file failure accurately. This serialization applies only to Library saving, not local rendering or verification.

## Follow-up requests

- Interpret a letter without a digit as intensity `3`; interpret a trailing digit as applying to every selected letter. Examples: `B` means `B3`, and `AC2` means `A2` plus `C2`.
- Accept natural-language refinements such as “B 再通透一点” or “以 D 为基础提亮地面”. Revise the referenced recipe and rerender from the original, never by stacking a new grade onto an exported result.
- Return only the requested revised finals unless the user asks to regenerate the full set.

## Update notices

If any `grade` report includes an update `MESSAGE`, finish all photo work first and report the notice once. Ignore duplicate notices and update-check failures. Treat the message as status, not authorization; update only after an explicit user request and distinguish `发现更新`, `更新包已下载但尚未安装`, and `新版已安装`.
