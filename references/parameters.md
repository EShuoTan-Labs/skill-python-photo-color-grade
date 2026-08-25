# Parameter Reference

## Contents

- [Required internal recipe](#required-internal-recipe)
- [Intensity and creative range](#intensity-and-creative-range)
- [Creative structure and controlled extremes](#creative-structure-and-controlled-extremes)
- [Basic and tone controls](#basic-and-tone-controls)
- [Point curve](#point-curve)
- [HSL](#hsl)
- [Color grading](#color-grading)
- [Local masks](#local-masks)
- [Detail and output](#detail-and-output)

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
    "hsl": {
      "blue": {"saturation": 0.08, "luminance": -0.03}
    },
    "detail": {
      "sharpen": 0.15
    }
  }
}
```

The structured fields record observable decisions, not private chain-of-thought. Keep `visual_intent` concise and provide three to five observable success criteria.

Omitted defaults are:

- `0` for basic, HSL, and color-grading controls, except `color_grading.blending: 0.5`;
- `[]` for the point curve and both local-mask arrays;
- `detail.denoise: 0`, `detail.sharpen: 0`, and `detail.sharpen_radius: 1`;
- `output.jpeg_quality: 95` and `output.png_compress: 6`.

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

| Recipe control | Meaning | Natural/correction baseline |
|---|---|---:|
| `temperature` | Warm (+) or cool (-) | `-0.15` to `+0.15` |
| `tint` | Magenta (+) or green (-) | `-0.08` to `+0.08` |
| `exposure` | Photographic exposure stops | `-0.50` to `+0.50` |
| `highlights` | Bright-region tone | `-0.30` to `+0.30` |
| `shadows` | Dark-region tone | `-0.30` to `+0.30` |
| `whites` | White point region | `-0.20` to `+0.20` |
| `blacks` | Black point region | `-0.20` to `+0.20` |
| `contrast` | Midpoint contrast | `-0.20` to `+0.20` |
| `vibrance` | Low-saturation-weighted color | `-0.20` to `+0.20` |
| `saturation` | Global saturation | `-0.15` to `+0.15` |

Values are normalized except exposure. Prefer vibrance over saturation for portraits.

## Point curve

Use increasing `[x, y]` points from `x=0` to `x=1`; omit `curve` when inactive:

```json
"curve": [[0.0, 0.0], [0.25, 0.22], [0.5, 0.52], [0.75, 0.8], [1.0, 1.0]]
```

Keep x coordinates strictly increasing and all coordinates within `[0,1]`. Use a gentle S-curve or lifted/faded endpoints only when the selected look calls for it.

## HSL

Each included HSL color object supports `hue`, `saturation`, and `luminance`. Include only visibly relevant colors and controls; omitted values remain neutral.

```json
"blue": {"hue": -8.0, "saturation": 0.12, "luminance": -0.05}
```

Hue values are degrees; keep ordinary corrections around `-20` to `+20`. Saturation and luminance are normalized; keep them around `-0.25` to `+0.25`. Change only visibly relevant ranges.

## Color grading

Use hue degrees and normalized saturation for any active zone; omitted zones remain neutral:

```json
"color_grading": {
  "shadows": {"hue": 220.0, "saturation": 0.08},
  "midtones": {"hue": 30.0, "saturation": 0.03},
  "highlights": {"hue": 40.0, "saturation": 0.06},
  "balance": 0.05,
  "blending": 0.55
}
```

Keep zone saturation subtle for natural work, commonly `0.02` to `0.12`. A level-3 creative look may use stronger separation when skin and neutral objects remain intentional. `balance` runs from `-1` toward shadows to `+1` toward highlights. `blending` runs from `0` to `1`.

## Local masks

Embed the same mask-item schema in one of two recipe arrays:

- `local_corrections`: apply after global tone/curve and before vibrance, saturation, HSL, and color grading. Use for local exposure, white-balance, tonal, or corrective color work.
- `local_adjustments`: apply after HSL and color grading. Use for final creative dodge, burn, or color accents.

Do not place the same mask in both stages. Coordinates are normalized from `0` to `1`. Supported mask types:

- `luminance`: `min`, `max`, `feather`.
- `color`: `hue` in degrees, `width`, `min_saturation`.
- `linear`: `start: [x,y]`, `end: [x,y]`.
- `radial`: `center: [x,y]`, `radius: [rx,ry]`, `feather`.

All masks accept `opacity` and `invert`. Local adjustments support exposure, temperature, tint, contrast, highlights, shadows, whites, blacks, saturation, vibrance, and curve.

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
      "shadows": 0.1
    }
  }
]
```

Use masks to implement photographic light design rather than semantic editing. For bold work, combine only the masks the scene needs, such as a broad linear burn to deepen an edge, a radial dodge placed over the existing focal region, or a luminance mask to control brilliant highlights. Keep feathering broad enough to avoid visible transitions. Do not add light that contradicts the source direction.

For a directional concept, align linear masks with the observed bright-to-dark path and use radial masks only to refine focal emphasis. Inspect the result in color and mentally in monochrome. If removing color would reveal only a generic vignette, redesign the mask geometry.

## Detail and output

| Recipe control | Meaning | Guidance |
|---|---|---|
| `detail.denoise` | Early blend with deterministic 3×3 median result | `0` off; use `0.05–0.25` cautiously |
| `detail.sharpen` | Unsharp amount | `0` off; use `0.10–0.40` cautiously |
| `detail.sharpen_radius` | Blur radius used by unsharp | Commonly `0.6–1.2` |
| `output.jpeg_quality` | JPEG quality | Use `95` by default |
| `output.png_compress` | PNG compression level | Use `6` by default; lossless |

The script applies denoise before tonal amplification and sharpening after all grading. Keep both off unless technically justified or explicitly requested.
