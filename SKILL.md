---
name: python-photo-color-grade
description: Provide a deterministic Lightroom-style Python workflow for grading uploaded JPEG or PNG photographs into a complete set of final scene-adaptive variants without an initial aesthetic consultation. Use for 调色, exposure or white-balance correction, tone curves, HSL, color grading, deterministic masks, detail, and natural through bold cinematic looks. Analyze technical state plus latent light and tonal opportunities; internally define three to six distinct choices labeled from A onward, including one structurally bold option when supported, then default to selecting every offered choice at intensity 3 and render every full-resolution final image. Explicit user constraints override this default. Before every render, commit all aesthetic decisions and exact settings to a validated internal structured recipe; keep those settings private unless the user explicitly asks for them. Preserve content and geometry. Exclude generative edits, retouching, object removal, inpainting, semantic segmentation, HEIC, and RAW.
---

# Python Photo Color Grade

Follow the same Lightroom-style deterministic reasoning pipeline for every image: inspect it, design scene-adaptive aesthetic directions, translate each direction into a recipe, render from the original, and verify the results. Do not pause for an initial aesthetic consultation. By default, internally treat the user as having replied “都要”: select every offered direction at intensity `3` and return every full-resolution final image in the first processing turn. Reserve conservative rendering for the natural direction; do not dilute cinematic, editorial, or bold directions into mild corrections. Never call generation, inpainting, or content-aware tools.

## Default-all execution rule

- Grade in the same turn as the initial photo request. Do not ask the user to choose styles before processing unless a true blocker prevents execution.
- First inspect and measure the image, then internally define three to six scene-appropriate choices labeled sequentially from `A`. Preserve the original aesthetic reasoning step; only remove the pause for user selection.
- Label style choices sequentially with uppercase letters: `A`, `B`, `C`, and so on. Never number the style choices.
- Label intensity with digits: `1 = 轻度`, `2 = 中等`, `3 = 明显`. Never use letters for intensity.
- For the default first render, behave exactly as if the user selected all internally offered letters without an intensity digit: render every direction at intensity `3` as full-quality final output, not a preview, sample, contact sheet, or reduced-quality proof.
- An explicit user constraint overrides only the conflicting part of the default. For example, “只要自然版” requests one natural final, “不要胶片” excludes film directions, and a named style or intensity narrows the internally selected set accordingly.
- For follow-up requests, accept a valid style letter with or without an intensity digit. A letter without a digit defaults to `3`; several letters request several variants; one trailing digit applies to every selected letter.
- Choose exact parameters without asking the user to understand numerical sliders. Do not show a proposed parameter table, ask “按这组参数执行吗？”, or wait for confirmation.
- Keep exact settings and mask definitions internal by default. Do not include them in the final response unless the user explicitly asks what settings were used.
- After delivery, accept natural-language refinements that refer to one or more labeled finals. Translate the feedback into revised recipes and rerender from the original file, never by stacking another grade onto an exported JPEG.
- Ask again only for a true blocker: missing original file, unsupported format, or an internally contradictory request that cannot be executed safely.

## Aesthetic breadth rule

Build three to six choices from the actual scene rather than copying a fixed preset list. Use as few as needed for strong coverage and add choices only when they introduce a genuinely different visual idea.

- Cover the range from faithful correction to strong authorship. Always include a natural direction, at least one clearly creative direction, and at least one bold cinematic/editorial/blockbuster direction. Add bright/clean, commercial, film, warm/cool, or alternative creative directions only when the scene supports them.
- Include one maximum-authorship candidate when the source supports meaningful structural transformation. Build it around the scene's strongest latent opportunity rather than a genre cliché.
- Adapt the bold direction to the scene: for example, directional spotlight and silver highlights underwater, golden epic backlight at sunset, sculpted magazine light for portraiture, neon light-zone separation on a night street, or monumental tonal depth for landscape. These are structural examples, not permanent looks; never equate “bold” with a fixed palette such as dark blue.
- Describe observable consequences, not vague synonyms: state brightness key, contrast shape, light geometry, dominant/supporting palette, subject treatment, saturation behavior, and texture in a short phrase.
- Prevent option clustering. Before finalizing the internal set, ensure each neighboring choice differs on at least two primary axes among palette, tonal contrast, exposure key, saturation strategy, local light design, and texture/detail treatment. Do not produce a list of slight variations on “natural/clear/bright.”
- Do not pad the list to reach `F`. Use `A-C` for a simple scene with three strong ideas, `A-D` or `A-E` when more useful alternatives exist, and `A-F` only when all six remain distinct and achievable.
- Keep every offered direction technically plausible for the source. If a direction would depend on invented light, missing detail, or generative reconstruction, replace it with another bold but achievable direction.

### Scene-opportunity scan

Before drafting the choices, inspect both the image and the analysis report for:

- existing or implied light direction, brightest region, and plausible light falloff;
- highlight latitude and surfaces that can carry brilliant or specular treatment;
- subject/background separation available through luminance, hue, saturation, or temperature;
- negative space that can be brightened, subdued, or used to frame the focal region;
- haze, noise, softness, clipped detail, and other limits on texture treatment;
- the most ambitious non-generative tonal transformation the source can support.

Use the `spatial_luma_grid_3x3` and brightest/darkest-cell metrics as evidence, then confirm them visually. Do not let global averages hide directional light opportunities.

### Creative-ceiling and anti-filter checks

- Reject a bold candidate if it differs mainly through global darkness, hue, or saturation. A bold concept must change tonal hierarchy, local-light structure, subject/background separation, or another compositional reading while preserving geometry.
- Run a mental monochrome test: if the proposed look would lose its authorship when color is removed, strengthen the light/contrast design before offering it.
- Avoid cinematic shortcuts: uniform teal washes, global saturation sold as drama, broad undirected center dodges, and lowering every region equally.
- Do not protect every highlight and shadow by default. Allow controlled brilliant highlights and deep negative space when they serve the concept and important texture remains intentional.

Use this compact four-choice pattern as a structural example, rewriting the count, labels, and descriptions for the photo:

> A. 自然还原｜中性、克制、真实层次；B. 明亮商业｜亮净、鲜活、清晰主体；C. 低饱和叙事｜收色、柔和曲线、故事感；D. 大片冲击｜大胆曲线、明确主色、局部塑光、强主体分离。

Treat these as composition principles, not permanent presets. Replace incompatible choices, vary the option count, and make the bold option specific to the scene.

## Boundaries

- Accept JPEG and PNG only; do not substitute screenshots for originals.
- Preserve content, faces, skin texture, objects, text, edges, geometry, composition, dimensions, aspect ratio, and alpha.
- Never overwrite the original.
- Use only deterministic global adjustments, point curves, HSL, three-way color grading, and luminance/color/linear/radial masks.
- Do not use subject/sky segmentation models or claim that a mask understands semantic content.
- Enable denoise or sharpening only when technically justified or requested; keep strengths conservative. Apply denoise early and output sharpening last.
- Do not crop, rotate, resize, beautify, remove blemishes, liquify, add grain, or simulate depth of field unless a separately supported deterministic task is explicitly requested.

## Workflow

### 1. Inspect and define the full set

Inspect the uploaded original and run:

```bash
python3 <skill-dir>/scripts/photo_grade.py analyze <input> --pretty
```

Assess brightness distribution, spatial light pattern, clipping, dynamic range, measurable cast, saturation, and scene constraints. Complete the scene-opportunity scan, then internally define the full coded choice set following the aesthetic breadth rule. Do not expose the choices as a pre-processing question and do not stop. Unless the user explicitly narrowed the request, select every internally offered letter at intensity `3` and continue immediately.

### 2. Commit every selected direction to a structured recipe

For the initial render, create one recipe for every internally offered style at intensity `3`. If the user explicitly supplied a subset, style, exclusion, or intensity, apply it instead. For later coded replies, normalize and interpret the choice as before: a valid letter selects the corresponding style, a following digit selects intensity, and letters without a digit use intensity `3`. Render one output per selected letter. Then choose exact values without asking the user to understand technical sliders.

After visual inspection and `analyze`, but before any `grade` invocation, write a separate internal JSON recipe for each output. Treat this file as a required execution manifest, not user-facing documentation. Never call `grade` while parameters are still undecided or assemble loose adjustment flags opportunistically at the command line.

Each recipe must use `schema_version: 1` and explicitly contain:

- `style`: one uppercase style `id`, a non-empty `name`, and intensity `1`, `2`, or `3`;
- `visual_intent`: non-empty decisions for brightness key, contrast structure, light geometry, palette, subject separation, and texture;
- `success_criteria`: three to five observable result checks;
- `parameters`: complete `basic`, `curve`, eight-color `hsl`, `color_grading`, `local_corrections`, `local_adjustments`, `detail`, and `output` sections.

Represent every unused global stage explicitly with zero values or an empty array. Do not rely on script defaults to complete an aesthetic decision. Read [references/parameters.md](references/parameters.md) for the exact recipe schema before writing it. Keep the recipe in temporary workspace storage; do not deliver or persist it unless the user explicitly requests the settings or recipe.

Translate intensity into perceptual distance from the original, not a universal multiplier:

- `1 = 轻度`: correct the image and hint at the selected look; keep the result believable and close to the source.
- `2 = 中等`: make the style immediately visible in a side-by-side comparison through clear tonal and color decisions.
- `3 = 明显`: make the selected authorship obvious at first glance. For bold directions, use decisive curve shape, palette control, color separation, and deterministic local light shaping when useful. Do not stop at a slightly stronger level-2 render.

Keep level 3 controlled rather than timid: preserve important texture and geometry, avoid catastrophic clipping, halos, and broken skin color, but allow purposeful deep blacks, brilliant highlights, strong color contrast, and selective saturation when the chosen look calls for them. Read [references/parameters.md](references/parameters.md) for intensity guidance before building a level-3 creative recipe.

For every creative or bold recipe, define an internal style signature before selecting parameters:

1. Write a one-sentence visual thesis covering brightness key, contrast architecture, light geometry, palette, subject separation, and texture.
2. Define three to five observable success criteria, such as “upper-left light pool is visibly brighter than the lower-right,” “the focal highlights read silver-white,” or “the background settles into navy rather than green-cyan.”
3. Map each criterion to a processing stage. Do not expect HSL or saturation alone to create cinematic authorship.
4. Keep the thesis and criteria internal; execute without adding another user confirmation.

Use this fixed processing order:

1. Decode, color-manage, and optionally denoise before tonal amplification.
2. White balance: temperature and tint.
3. Exposure.
4. Highlights and shadows.
5. Whites, blacks, and contrast.
6. Point curve.
7. Optional corrective local masks for exposure, white balance, tone, or color corrections.
8. Vibrance, then global saturation.
9. HSL refinement for red, orange, yellow, green, aqua, blue, purple, and magenta.
10. Three-way color grading for shadows, midtones, and highlights, then balance/blending.
11. Optional creative local masks for final dodge, burn, or color accents.
12. Output sharpening.
13. Output quality and metadata handling.

Leave unnecessary stages at zero. Make every active stage serve the selected visual concept. Prefer mild values only for natural or light-intensity choices; honor stronger selections with visibly stronger decisions.

For parameter semantics, validated ranges, the required recipe schema, curve syntax, color grading, and embedded local masks, read [references/parameters.md](references/parameters.md).

### 3. Execute all selected final renders immediately

Run each selected recipe once from the original. The script rejects a missing, incomplete, malformed, or out-of-range recipe before rendering. Do not bypass the required recipe by modifying the script or recreating the removed loose-parameter interface.

```bash
python3 <skill-dir>/scripts/photo_grade.py grade <input> <output> \
  --recipe <internal-recipe.json>
```

Name every rendered file as `<original-stem>_<style-id><intensity>_<direction-description><extension>`. For example, style `A` at intensity `3` with direction `自然通透` from `IMG_1234.jpg` must be saved as `IMG_1234_A3_自然通透.jpg`.

- Use the source filename without its final extension as `<original-stem>`; preserve any earlier dots in the stem.
- Use the recipe's uppercase `style.id` and numeric `style.intensity` without a separator, such as `A3` or `D2`.
- Use a concise, human-readable Chinese direction name that matches the recipe's actual aesthetic intent. Keep direction descriptions distinct across variants; prefer the recipe's `style.name` when it is already concise and specific.
- Remove line breaks and filename-forbidden characters (`/`, `\\`, `:`, `*`, `?`, `\"`, `<`, `>`, `|`) from the direction description. Do not add `_graded`, timestamps, random IDs, or other suffixes unless the user explicitly requests them.
- Preserve the source extension and format by default. If the user explicitly requests another output format, change only the final extension accordingly.

Process in float precision, preserve alpha and safe metadata, and encode only once. Default to JPEG quality 95 with 4:4:4 chroma.

Each `grade` invocation starts `update.py --check` in parallel with image processing. If the final JSON contains a `MESSAGE` field, treat it as an updater instruction addressed to the model and handle it after the render. If `MESSAGE` is absent, ignore the update check. Update-check failures must not be treated as grading failures.

### 4. Verify automatically

Inspect the result and run:

```bash
python3 <skill-dir>/scripts/photo_grade.py compare <input> <output> --pretty
```

Check dimensions, alpha, clipping, color, banding, halos, noise smearing, and oversharpening. Also verify that every output basename exactly follows `<original-stem>_<style-id><intensity>_<direction-description>` before delivery. Treat zero clipping as neither a goal nor proof of quality: distinguish small localized specular extremes or deep negative space from broad accidental damage.

Then verify every predeclared style-signature criterion by inspecting the rendered image and the spatial metrics. For a creative or bold result, also repeat the monochrome test mentally: the light and tonal hierarchy must still read without relying on hue. If the result is technically safe but misses the signature, strengthen the responsible coordinated stages and rerender from the original. If it is unsafe, reduce only the responsible values; never flatten the whole concept back into a generic grade. For level `3`, confirm that authorship is obvious at first glance and not merely a stronger level `2`. Do not introduce another confirmation step.

### 5. Deliver the results without exposing the internal recipe

Return all processed final images first, labeled with their internal style letters and names. Add only a concise observable description of each look. State that the images were processed with non-generative Python and that content, composition, and dimensions were preserved.

Do not expose numerical settings, curve points, HSL values, color-grading values, mask definitions, the recipe JSON, or hidden planning by default. If the user explicitly asks what parameters were used, rerun reporting with `--show-parameters` or read the final recipe and report only the exact settings that produced the delivered file. Never report planned values that differ from the final render. Keep the explanation compact unless the user asks for details.

Adapt persistence and delivery to the host platform instead of assuming that ChatGPT Library is always available. Only save outputs to a library or external destination when the user requests it or the host workflow explicitly requires it.

- When saving multiple outputs to **ChatGPT Library**, save exactly one file per operation, wait for that file's success result, and only then save the next file. Do not use a batch or multi-file Library transfer even if one is available.
- Confirm Library success per file. If a save fails, identify the affected file accurately and do not claim that the whole set was saved.
- This sequential rule applies to the Library persistence step only. It does not require grading, rendering, local verification, downloading, or delivery through other platforms to be serialized; use the capabilities and safe conventions of the current host elsewhere.

## Minimal interaction

- First turn, uploaded photo plus “调一下”: analyze it; internally design three to six visibly distinct styles labeled sequentially from `A`, including a natural direction and a scene-specific bold direction; treat the selection as all letters at intensity `3`; commit one validated structured recipe per output; render, verify, and return every full-resolution final image without exposing actual parameters.
- Do not call these outputs samples or previews. They are final-quality alternatives produced from the original.
- Follow-up feedback such as “B 再通透一点”, “以 D 为基础提亮地面”, `D2`, or `AC2`: identify the referenced direction, revise its recipe, rerender from the original, verify, and return the new final without another confirmation.
