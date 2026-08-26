# Parameter Reference

## Contents

- [Required internal recipe](#required-internal-recipe)
- [Intensity and creative range](#intensity-and-creative-range)
- [Creative structure and controlled extremes](#creative-structure-and-controlled-extremes)
- [Basic and tone controls](#basic-and-tone-controls)
- [Point curve](#point-curve)
- [RGB channel curves](#rgb-channel-curves)
- [Presence](#presence)
- [Color management](#color-management)
- [HSL](#hsl)
- [Color grading](#color-grading)
- [Local masks](#local-masks)
- [Detail and output](#detail-and-output)
- [Analysis and reports](#analysis-and-reports)

## Required internal recipe

Include every top-level key shown below. Within `parameters`, include only active sections and controls. The script expands omitted controls to deterministic neutral defaults and rejects unknown fields.

```json
{
  "schema_version": 1,
  "style": {
    "id": "A",
    "name": "自然还原",
    "intensity": 3
  },
  "visual_intent": {
    "brightness_key": "中等亮度，保留高光空气感",
    "contrast_structure": "柔和中间调与稳定黑位",
    "light_geometry": "顺应原图既有亮暗方向",
    "palette": "中性主色，克制暖色支持",
    "subject_separation": "通过明度和局部色彩纯度分离",
    "texture": "自然清晰，不放大噪点"
  },
  "success_criteria": [
    "主体与背景有清楚但自然的明度分离",
    "重要高光保留纹理",
    "中性色不出现可见偏色"
  ],
  "parameters": {
    "basic": {
      "exposure": 0.15,
      "highlights": -0.1,
      "vibrance": 0.06
    },
    "curve": [[0.0, 0.0], [0.5, 0.52], [1.0, 1.0]],
    "channel_curves": {
      "red": [[0.0, 0.0], [0.5, 0.52], [1.0, 1.0]]
    },
    "presence": {
      "clarity": 0.12,
      "texture": 0.08
    },
    "color_management": {
      "rendering": "perceptual",
      "gamut_mapping": "oklch_compress"
    },
    "hsl": {
      "blue": {"saturation": 0.08, "luminance": -0.03}
    },
    "detail": {
      "sharpen": 0.15
    }
  }
}
```

The structured fields record observable decisions, not private chain-of-thought. Use exactly the recipe, `style`, and `visual_intent` keys shown above. Set `schema_version` to `1`, use one uppercase letter for `style.id`, set intensity to `1`, `2`, or `3`, and provide three to five non-empty `success_criteria`. Accepted `parameters` sections are `basic`, `curve`, `channel_curves`, `presence`, `color_management`, `hsl`, `color_grading`, `local_corrections`, `local_adjustments`, `detail`, and `output`; omit inactive sections.

Omitted defaults are:

- `0` for basic, HSL, and color-grading controls, except `color_grading.blending: 0.5`;
- `0` for `presence.dehaze`, `presence.clarity`, and `presence.texture`;
- `color_management.rendering: "legacy"` and `color_management.gamut_mapping: "clip"`;
- `[]` for the point curve, each RGB channel curve, and both local-mask arrays;
- `detail.denoise: 0`, `detail.sharpen: 0`, and `detail.sharpen_radius: 1`;
- `output.jpeg_quality: 95`, `output.png_compress: 6`, `output.png_bit_depth: 8`, and `output.png_dither: "none"`.

## Intensity and creative range

Choose intensity from the intended perceptual result and source latitude before consulting any parameter baseline:

| Level | Intended result | Typical strategy |
|---|---|---|
| `1` | Close to source | Correct cast/exposure, gentle curve, minimal HSL |
| `2` | Clearly styled | Distinct curve and palette, selective HSL, optional subtle local shaping |
| `3` natural | Polished but faithful | Stronger correction without changing the scene's emotional key |
| `3` creative/bold | Obvious authorship at first glance | Decisive curve, controlled deep blacks or brilliant highlights, clear dominant palette, color separation, and local light design where useful |

For a level-3 creative or bold choice, values may move beyond the natural/correction baselines below when the source supports them. Prefer coordinated moves across tone, HSL, grading, and masks over one extreme slider. The goal is a coherent visual concept, not numerical aggression.

For a bold recipe, complete `visual_intent` and its three to five observable success criteria before choosing parameters. After rendering, strengthen only the stages responsible for any unmet criterion. Never weaken a bold selection merely because it differs strongly from the source.

## Creative structure and controlled extremes

Build the tonal architecture before polishing the palette. A cinematic result must not depend on color alone.

| Visual need | Prefer |
|---|---|
| Establish global light/dark hierarchy | Exposure, whites/blacks, contrast, point curve |
| Extend an existing directional light source | Broad linear mask aligned with the source, then a feathered radial refinement if useful |
| Separate a focal region from negative space | Coordinated focal dodge and restrained inverted radial or edge burn |
| Make reflective texture luminous | Whites/highlights plus a luminance mask; accept localized brilliance when intentional |
| Separate foreground and background color | HSL luminance/saturation plus three-way grading |
| Create filmic softness without flatness | Lift the black endpoint selectively while retaining midtone shape and local contrast |

Use the smallest mask set that expresses the light design. A single undirected center radial is not a substitute for a directional concept. Do not invent a light direction that contradicts the source; when the source is flat, use broad plausible zoning rather than fake hard beams.

Run these anti-filter checks before accepting a level-3 creative render:

- In a mental grayscale preview, does the light hierarchy remain distinctive?
- Is the focal region separated by more than saturation alone?
- Did one global hue wash contaminate neutrals, skin, or reflective surfaces?
- Are local masks shaping light, or merely making the center brighter?
- Does the result show a clear concept at first glance without the original beside it?

Do not optimize for zero clipping. Controlled localized specular clipping, near-white reflective highlights, or deep near-black negative space can be intentional. Reject broad accidental clipping, posterization, hue breakage, lost facial/subject structure, or crushed texture across important regions. Judge the spatial location and visual purpose of extremes, not only their global ratio.

## Basic and tone controls

These are **natural/correction baselines only**, not implicit limits for a creative level-3 recipe.

Accepted `basic` controls and ranges:

| Recipe control | Meaning | Validator accepts | Natural/correction baseline |
|---|---|---:|---:|
| `temperature` | Warm (+) or cool (-) | `-1` to `+1` | `-0.15` to `+0.15` |
| `tint` | Magenta (+) or green (-) | `-1` to `+1` | `-0.08` to `+0.08` |
| `exposure` | Photographic exposure stops | `-4` to `+4` | `-0.50` to `+0.50` |
| `highlights` | Bright-region tone | `-1` to `+1` | `-0.30` to `+0.30` |
| `shadows` | Dark-region tone | `-1` to `+1` | `-0.30` to `+0.30` |
| `whites` | White point region | `-1` to `+1` | `-0.20` to `+0.20` |
| `blacks` | Black point region | `-1` to `+1` | `-0.20` to `+0.20` |
| `contrast` | Midpoint contrast | `-1` to `+1` | `-0.20` to `+0.20` |
| `vibrance` | Low-saturation-weighted color | `-1` to `+1` | `-0.20` to `+0.20` |
| `saturation` | Global saturation | `-1` to `+1` | `-0.15` to `+0.15` |

Values are normalized except exposure. Prefer vibrance over saturation for portraits.

## Point curve

Use an empty array or at least two increasing `[x, y]` points from `x=0` to `x=1`; omit `curve` when inactive:

```json
"curve": [[0.0, 0.0], [0.25, 0.22], [0.5, 0.52], [0.75, 0.8], [1.0, 1.0]]
```

Keep x coordinates strictly increasing and all coordinates within `[0,1]`. Use a gentle S-curve or lifted/faded endpoints only when the selected look calls for it.

The main `curve` operates on encoded-sRGB luminance. The pipeline maps luminance through the piecewise-linear curve and scales RGB to the mapped luminance. It runs before any RGB channel curve.

## RGB channel curves

`channel_curves` is an optional object with only `red`, `green`, and `blue` keys. Each value uses the same empty-or-two-plus-point validation as the main curve. Omitted channels and empty arrays are fully neutral and are skipped without clipping their input:

```json
"channel_curves": {
  "red": [[0.0, 0.04], [0.5, 0.55], [1.0, 1.0]],
  "green": [],
  "blue": [[0.0, 0.08], [0.5, 0.5], [1.0, 0.94]]
}
```

Processing is deterministic and fixed:

1. Apply the main luminance `curve` first.
2. In encoded sRGB, independently map R, G, then B over the `[0,1]` domain.
3. Use piecewise-linear interpolation between control points.
4. For an active channel only, clip its input to `[0,1]` before interpolation. Endpoints at `x=0` and `x=1`, plus validated `y` coordinates in `[0,1]`, define the boundary output.

This order also applies inside each local adjustment: local main curve first, then local channel curves. A lifted channel endpoint introduces a channel-specific black tint; a lowered white endpoint reduces that channel in highlights. Prefer coordinated, restrained endpoint moves when neutral blacks or whites must remain neutral.

## Presence

`presence` is an optional object with only `dehaze`, `clarity`, and `texture`. Every included value must be a finite JSON number from `-1` to `+1`; booleans, non-finite values, unknown keys, and values outside the range are validation errors. Omitted controls expand to `0`, and an omitted or all-zero section is an exact processing skip.

```json
"presence": {
  "dehaze": 0.18,
  "clarity": 0.22,
  "texture": 0.12
}
```

| Control | Scale and effect | Guidance |
|---|---|---|
| `dehaze` | Low-frequency luminance-range recovery with black/highlight protection and restrained chroma recovery | Use positive values for genuine atmospheric veiling or compressed low-frequency separation; ordinary range `0.05–0.25`. Negative values gently flatten low-frequency separation. |
| `clarity` | Mid-frequency, midtone-weighted local contrast | Use for architecture, landscape structure, or dimensional separation; ordinary range `0.05–0.30`. Negative values soften mid-scale structure. |
| `texture` | Small-scale detail gain with a spatial-coherence noise gate | Use for foliage, fabric, stone, or fine reflective detail; ordinary range `0.04–0.25`. Negative values soften fine texture without replacing denoise. |

The fixed global order is `dehaze` → `clarity` → `texture`, after `local_corrections` and before vibrance, saturation, HSL, and color grading. The implementation performs deterministic NumPy `float32` luminance decomposition with edge-extended floating-point box filters; it does not round-trip through an 8-bit Pillow filter image. Filter scale is derived only from image dimensions and is capped, so repeated runs with the same inputs and dependency versions are deterministic.

All three controls reconstruct RGB from adjusted encoded-sRGB luminance instead of independently sharpening R, G, and B. A highlight/shadow envelope, strong-gradient guard, and local 3×3 luminance envelope limit halos and full-strength step-edge overshoot/undershoot to at most `0.02`. Clarity and texture additionally use signed-gradient coherence to reduce amplification of random residuals in flat regions. Dehaze applies a small, gamut-constrained chroma factor while preserving the source hue vector; constant images remain unchanged.

Use the three controls for distinct scales rather than stacking them by default. Dehaze is not a substitute for exposure or black-point work, clarity is not output sharpening, and texture is not denoise. Strong positive values may reveal existing noise or compression artifacts even with the guards, so inspect smooth skies, skin, foliage, building edges, and backlit haze at full resolution.

## Color management

`color_management` is optional and accepts exactly two string fields:

```json
"color_management": {
  "rendering": "perceptual",
  "gamut_mapping": "oklch_compress"
}
```

| Field | Accepted values | Default | Behavior |
|---|---|---|---|
| `rendering` | `"legacy"`, `"perceptual"` | `"legacy"` | Selects the existing encoded-sRGB/HSV color algorithms or the fixed D65 sRGB/OKLab/OKLCh path. |
| `gamut_mapping` | `"clip"`, `"oklch_compress"` | `"clip"` | Selects hard RGB clipping or fixed soft-knee OKLCh chroma compression. |

The omitted/default pair is the compatibility path and does not change legacy pixels. `rendering: "perceptual"` changes only the global vibrance/saturation, HSL, and three-way color-grading stages:

- vibrance and saturation scale OKLCh chroma while keeping OKLab lightness and hue;
- the existing HSV hue ranges still determine HSL selection weights, but hue, chroma, and lightness changes are applied in OKLCh;
- the full validated HSL saturation range through `+1.5` is effective in this path;
- three-way grading adds color on the OKLab opponent axes and preserves OKLab lightness.

`oklch_compress` uses a fixed OKLCh chroma knee of `0.10` and shoulder of `0.08`, plus a deterministic 24-iteration binary search for the per-pixel in-gamut safety boundary. The fixed response avoids turning the non-convex blue edge of the sRGB gamut into a visible contour. It preserves in-range OKLCh lightness and hue while reducing chroma; neutral colors keep zero chroma and do not receive an arbitrary hue. Gamut mapping runs after global color shaping and again after creative local adjustments. Processing rejects NaN or infinity at color-conversion and gamut boundaries rather than silently replacing invalid values.

The strict ICC behavior applies when perceptual rendering, OKLCh compression, or 16-bit PNG output is selected:

- an absent profile is explicitly treated as sRGB and the output is tagged with sRGB ICC;
- a valid 8-bit source profile is converted to sRGB before grading; CMYK conversion starts from the original CMYK image mode;
- conversion failure is an error before output creation;
- a 16-bit PNG with no ICC or an sRGB ICC retains 16-bit samples, while a non-sRGB or invalid ICC is rejected with an instruction to convert externally to sRGB16.

The legacy path keeps its prior fallback pixel behavior if ICC conversion fails and adds a `warnings` report entry. Unknown fields, non-string modes, or values outside the enumerations are validation errors. Recipe validation and all strict ICC checks finish before a new output is written.

## HSL

Accepted HSL color keys are `red`, `orange`, `yellow`, `green`, `aqua`, `blue`, `purple`, and `magenta`. Each included color object may contain `hue`, `saturation`, and `luminance`; omitted controls remain neutral.

```json
"blue": {"hue": -8.0, "saturation": 0.12, "luminance": -0.05}
```

The validator accepts `hue` from `-90` to `+90` degrees, `saturation` from `-1` to `+1.5`, and `luminance` from `-1` to `+1`. For backward compatibility, the legacy HSL execution path clips the effective per-range saturation adjustment to `+1.0`; values from `+1.0` through `+1.5` remain accepted but produce the legacy `+1.0` effect. Keep ordinary hue corrections around `-20` to `+20` and saturation/luminance around `-0.25` to `+0.25`. Change only visibly relevant ranges.

## Color grading

Accepted color-grading keys are `shadows`, `midtones`, `highlights`, `balance`, and `blending`. Each zone may contain `hue` and `saturation`; omitted zones or controls remain neutral.

```json
"color_grading": {
  "shadows": {"hue": 220.0, "saturation": 0.08},
  "midtones": {"hue": 30.0, "saturation": 0.03},
  "highlights": {"hue": 40.0, "saturation": 0.06},
  "balance": 0.05,
  "blending": 0.55
}
```

Zone `hue` runs from `0` to `360` degrees and zone `saturation` from `0` to `1`. Keep saturation subtle for natural work, commonly `0.02` to `0.12`. A level-3 creative look may use stronger separation when skin and neutral objects remain intentional. `balance` runs from `-1` toward shadows to `+1` toward highlights. `blending` runs from `0` to `1`.

## Local masks

Embed the same mask-item schema in one of two recipe arrays. Each array item contains exactly one `mask` object and one `adjustments` object:

- `local_corrections`: apply after global tone/curve and before vibrance, saturation, HSL, and color grading. Use for local exposure, white-balance, tonal, or corrective color work.
- `local_adjustments`: apply after HSL and color grading. Use for final creative dodge, burn, or color accents.

Place each mask in one stage according to its purpose. Every mask node requires `type`, `opacity` from `0` to `1`, and boolean `invert`; these fields have no implicit recipe defaults and must be present. Each node accepts exactly the fields listed for its type:

| Mask type | Required type-specific fields |
|---|---|
| `luminance` | `min` and `max` from `0` to `1`, with `max > min`; `feather` from `0.0001` to `1` |
| `color` | `hue` from `0` to `360`; `width` from `1` to `180`; `min_saturation` from `0` to `1` |
| `linear` | distinct `start: [x,y]` and `end: [x,y]`, with every coordinate from `0` to `1` |
| `radial` | `center: [x,y]` from `0` to `1`; `radius: [rx,ry]` from `0.0001` to `1`; `feather` from `0` to `0.99` |
| `composite` | `operation`: `"and"`, `"or"`, or `"subtract"`; `inputs`: an array of child mask nodes |

A composite mask combines already feathered mask coverage without semantic segmentation or a second feathering pass. Its deterministic operations are:

- `and`: pixel-wise `min` over `2–8` child masks.
- `or`: pixel-wise `max` over `2–8` child masks.
- `subtract`: exactly two child masks, evaluated as `clip(A - B, 0, 1)`; subtraction is directional, and additional subtraction requires explicit nesting.

Processing is post-order and fixed. Each leaf computes coverage from the same RGB snapshot for that local-adjustment item, then applies its own `invert` followed by `opacity`. A composite combines those completed child coverages, then applies the composite node's own `invert` followed by `opacity`. Sibling masks never observe one another's adjustments. Separate items in `local_corrections` or `local_adjustments` remain sequential, so a later item reads the result of the preceding item.

A mask tree may contain at most `6` node levels, counting its root as level `1`, and at most `32` leaf masks. The leaf limit applies independently to each local-adjustment item's root mask. Composite nodes do not accept `feather`; feathering remains an explicit property of eligible leaf nodes. Every node is checked for finite coverage in `[0,1]` after its own inversion and opacity.

For example, this mask selects bright pixels only where they also lie inside a feathered radial region:

```json
{
  "type": "composite",
  "operation": "and",
  "inputs": [
    {
      "type": "luminance",
      "min": 0.55,
      "max": 0.98,
      "feather": 0.12,
      "opacity": 1,
      "invert": false
    },
    {
      "type": "radial",
      "center": [0.55, 0.45],
      "radius": [0.35, 0.42],
      "feather": 0.5,
      "opacity": 1,
      "invert": false
    }
  ],
  "opacity": 0.8,
  "invert": false
}
```

To select a color range while excluding highlights, use `subtract` with the color mask as input `A` and the luminance mask as input `B`. Reversing the inputs produces a different mask.

`adjustments` contains one or more basic-control names from above, `curve`, `channel_curves`, `clarity`, or `texture`. Local `exposure` accepts `-4` to `+4`; other numeric adjustments accept `-1` to `+1`; local main and channel curves follow the curve rules above. Local `dehaze` is intentionally unsupported and is rejected as an unknown adjustment because its low-frequency estimate cannot be made mask-local without boundary mismatch.

Inside one local item, processing is fixed as local tone/curves → local clarity → local texture → local vibrance/saturation. The full-frame floating-point variant is calculated first and then blended with the completed mask. This keeps feathered coverage continuous and means mask coverage `0` returns the stage input exactly while coverage `1` returns the complete local variant.

```json
"local_adjustments": [
  {
    "mask": {
      "type": "radial",
      "center": [0.5, 0.45],
      "radius": [0.3, 0.4],
      "feather": 0.5,
      "opacity": 0.8,
      "invert": false
    },
    "adjustments": {
      "exposure": 0.2,
      "shadows": 0.1,
      "clarity": 0.12
    }
  }
]
```

Use masks to implement photographic light design rather than semantic editing. For bold work, combine only the masks the scene needs, such as a broad linear burn to deepen an edge, a radial dodge placed over the existing focal region, or a luminance mask to control brilliant highlights. Keep feathering broad enough to avoid visible transitions. Do not add light that contradicts the source direction.

For a directional concept, align linear masks with the observed bright-to-dark path and use radial masks only to refine focal emphasis. Inspect the result in color and mentally in monochrome. If removing color would reveal only a generic vignette, redesign the mask geometry.

Validation is recursive. Unknown or missing node fields, unsupported operations, invalid child counts, excessive depth or leaf count, non-finite numbers, and out-of-range values are errors. The `grade` CLI reports them on stderr with exit code `2` before creating an output file.

## Detail and output

Accepted `detail` and `output` controls and ranges:

| Recipe control | Meaning | Validator accepts | Guidance |
|---|---|---:|---|
| `detail.denoise` | Early blend with deterministic 3×3 median result | `0` to `1` | `0` off; use `0.05–0.25` cautiously |
| `detail.sharpen` | Unsharp amount | `0` to `2` | `0` off; use `0.10–0.40` cautiously |
| `detail.sharpen_radius` | Blur radius used by unsharp | `0.1` to `5` | Commonly `0.6–1.2` |
| `output.jpeg_quality` | JPEG quality | integer `1` to `100` | Use `95` by default |
| `output.png_compress` | PNG compression level | integer `0` to `9` | Use `6` by default; lossless |
| `output.png_bit_depth` | PNG samples per RGB/alpha channel | integer `8` or `16` | Use `8` by default; `16` requires a PNG output path |
| `output.png_dither` | RGB quantization dither | `"none"` or `"tpdf"` | Use `"none"` by default; `"tpdf"` requires 8-bit PNG |

The script applies denoise before tonal amplification and sharpening after all grading. Keep both off unless technically justified or explicitly requested.

For 16-bit PNG, RGB is quantized as `round(clip(value, 0, 1) * 65535)`. Alpha is never graded or dithered: 8-bit source alpha expands exactly as `value * 257`, while retained 16-bit source alpha samples are written unchanged. The isolated PyPNG encoder writes RGB16 or RGBA16, preserves supported ICC, EXIF, DPI, and PNG text metadata, and verifies the IHDR bit depth after writing. PyPNG is loaded only when 16-bit PNG I/O is invoked; when it is unavailable, that operation exits with code `2`, gives the `requirements.txt` install command, and leaves no output, while JPEG and 8-bit PNG commands remain usable. JPEG and 16-bit PNG reject `png_dither: "tpdf"`; JPEG also rejects non-default `png_bit_depth` or `png_dither` settings.

For 8-bit PNG, `png_dither: "tpdf"` adds deterministic coordinate-hashed, zero-mean triangular noise to encoded-sRGB RGB immediately before quantization. It has no configurable seed or strength, never touches alpha, and produces byte-identical output for the same input, recipe, and dependency versions. Use it only when long smooth gradients show or risk visible 8-bit platforms; it does not restore precision already absent from an 8-bit source.

## Analysis and reports

`analyze.metrics`, plus the `before` and `after` metric objects returned by `grade`, retain all legacy fields and add:

- `rgb_channels.red|green|blue.mean`: visible-pixel channel mean.
- `rgb_channels.*.percentiles`: visible-pixel `1`, `5`, `25`, `50`, `75`, `95`, and `99` percentiles.
- `rgb_channels.*.low_clip_ratio` and `high_clip_ratio`: independent channel clipping ratios using the legacy thresholds `<= 0.002` and `>= 0.998`.
- `rgb_channels.*.histogram_64`: 64 normalized bins spanning encoded sRGB `[0,1]`; each channel sums to `1` within floating-point representation.
- `spatial_rgb_mean_grid_3x3`: row-major 3×3 cells, each containing `[red, green, blue]` means or `null` when the cell has no visible pixels.

As with legacy metrics, a pixel is visible only when alpha is absent or alpha is greater than `0.01`. These arrays are intended for machine-readable cast, channel clipping, tonal separation, and spatial color-balance decisions; `analyze` does not create parade images.

`grade.processing` reports the fixed curve working space, interpolation, order, and active channel names without exposing curve points unless `--show-parameters` is explicitly set. `compare.rgb_channel_difference` provides signed mean, mean absolute, p95 absolute, and maximum absolute encoded-sRGB differences for each channel when geometry matches.

When any global or local presence control is nonzero, `grade.processing.presence` is added with the fixed working signal, method and global order, the names of active global controls, and each local stage/index with active local control names. It does not expose numeric settings; use `--show-parameters` only when the expanded recipe is explicitly required. For recipes with no active presence control, this optional technical block is omitted so legacy reports retain their prior `processing` structure.

`analyze` adds top-level `bit_depth`, `color_management.icc_status`, `source_extension`, `detected_format`, `extension_matches_format`, and `recommended_extension`; the existing `format` field remains the decoder-detected format. A mismatched supported extension produces a warning, and a supported extension cannot make another payload type valid. Treat the detected format as authoritative when choosing a default output name.

`grade` repeats the source format fields and adds `output_format_conversion`, which is `null` when the detected format is preserved or a `{ "from": ..., "to": ... }` object when the caller-selected output suffix explicitly converts it. `grade.output_encoding` reports actual format, extension agreement, input and output bit depth, dither mode, input/output ICC state, and Python/NumPy/Pillow/PyPNG versions. When a new color-management path is active, `grade.processing.color_management` reports rendering and gamut modes, mapping stages, and the maximum pre-map plus final post-map out-of-gamut pixel ratios. `compare.output_encoding_difference` summarizes both bit depths and ICC states without changing the existing `checks` meanings. The optional `warnings` array is present for a recoverable legacy ICC fallback, source extension mismatch, or explicit output format conversion.
