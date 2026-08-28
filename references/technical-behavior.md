# Technical Behavior Reference

This reference preserves implementation, encoding, compatibility, and report details that do not expand the recipe capability set. Read only the relevant section when selecting a strict color-management or high-bit-depth path, diagnosing artifacts or failures, interpreting extended reports, or explaining implementation behavior. The available controls and recipe contract remain authoritative in [capabilities-and-recipes.md](capabilities-and-recipes.md).

## Contents

- [Presence implementation](#presence-implementation)
- [Color management and ICC](#color-management-and-icc)
- [Detail and output encoding](#detail-and-output-encoding)
- [Analysis and reports](#analysis-and-reports)

## Presence implementation

The fixed global order is `dehaze` → `clarity` → `texture`, after `local_corrections` and before vibrance, saturation, HSL, and color grading. The implementation performs deterministic NumPy `float32` luminance decomposition with edge-extended floating-point box filters; it does not round-trip through an 8-bit Pillow filter image. Filter scale is derived only from image dimensions and is capped, so repeated runs with the same inputs and dependency versions are deterministic.

All three controls reconstruct RGB from adjusted encoded-sRGB luminance instead of independently sharpening R, G, and B. A highlight/shadow envelope, strong-gradient guard, and local 3×3 luminance envelope limit halos and full-strength step-edge overshoot/undershoot to at most `0.02`. Clarity and texture additionally use signed-gradient coherence to reduce amplification of random residuals in flat regions. Dehaze applies a small, gamut-constrained chroma factor while preserving the source hue vector; constant images remain unchanged.

## Color management and ICC

`oklch_compress` uses a fixed OKLCh chroma knee of `0.10` and shoulder of `0.08`, plus a deterministic 24-iteration binary search for the per-pixel in-gamut safety boundary. The fixed response avoids turning the non-convex blue edge of the sRGB gamut into a visible contour. It preserves in-range OKLCh lightness and hue while reducing chroma; neutral colors keep zero chroma and do not receive an arbitrary hue. Gamut mapping runs after global color shaping and again after creative local adjustments. Processing rejects NaN or infinity at color-conversion and gamut boundaries rather than silently replacing invalid values.

The strict ICC behavior applies when perceptual rendering, OKLCh compression, or 16-bit PNG output is selected:

- an absent profile is explicitly treated as sRGB and the output is tagged with sRGB ICC;
- a valid 8-bit source profile is converted to sRGB before grading; CMYK conversion starts from the original CMYK image mode;
- conversion failure is an error before output creation;
- a 16-bit PNG with no ICC or an sRGB ICC retains 16-bit samples, while a non-sRGB or invalid ICC is rejected with an instruction to convert externally to sRGB16.

The legacy path keeps its prior fallback pixel behavior if ICC conversion fails and adds a `warnings` report entry. Unknown fields, non-string modes, or values outside the enumerations are validation errors. Recipe validation and all strict ICC checks finish before a new output is written.

## Detail and output encoding

The script applies denoise before tonal amplification and sharpening after all grading. Keep both off unless technically justified or explicitly requested. `sharpen_threshold` gates the absolute luminance component of the unsharp residual with a smooth transition; it is responsible for preventing low-amplitude flat-area noise from being amplified, not for protecting high-contrast boundaries. `sharpen_edge_protection` instead derives a radius-expanded local luminance gradient and attenuates the RGB unsharp increment around strong edges; it is responsible for reducing step-edge overshoot while leaving moderate texture available. A zero value for either field skips its weighting branch exactly, and `sharpen: 0` skips the blur and every sharpening control. The blur is alpha-aware so hidden color behind transparent pixels is not pulled into visible edges; alpha samples themselves are never filtered or sharpened.

For 16-bit PNG, RGB is quantized as `round(clip(value, 0, 1) * 65535)`. Alpha is never graded or dithered: 8-bit source alpha expands exactly as `value * 257`, while retained 16-bit source alpha samples are written unchanged. The isolated PyPNG encoder writes RGB16 or RGBA16, preserves supported ICC, EXIF, DPI, and PNG text metadata, and verifies the IHDR bit depth after writing. PyPNG is loaded only when 16-bit PNG I/O is invoked; when it is unavailable, that operation exits with code `2`, gives the `requirements.txt` install command, and leaves no output, while JPEG and 8-bit PNG commands remain usable. JPEG and 16-bit PNG reject `png_dither: "tpdf"`; JPEG also rejects non-default `png_bit_depth` or `png_dither` settings.

For 8-bit PNG, `png_dither: "tpdf"` adds deterministic coordinate-hashed, zero-mean triangular noise to encoded-sRGB RGB immediately before quantization. It has no configurable seed or strength, never touches alpha, and produces byte-identical output for the same input, recipe, and dependency versions. Use it only when long smooth gradients show or risk visible 8-bit platforms; it does not restore precision already absent from an 8-bit source.

## Analysis and reports

`analyze`, `grade`, `grade-batch`, and `compare` default to the agent report. It contains the percentiles, clipping ratios, channel means, spatial grids, encoding checks, comparison checks, and processing diagnostics required for routine QA. `--report full` additionally includes the three 64-bin RGB histograms in every metric object; select it whenever histogram shape can resolve uncertainty, diagnose artifacts, or validate unusual tonal or channel distributions. `--pretty` changes formatting only.

`grade-batch` accepts one validated manifest and defaults to the agent report. Every item still runs independently from the original and reopens its encoded output through the same `grade` path. Each render uses a temporary file beside its requested final path so verification and publication stay on the same filesystem. Finals are published only after the complete set succeeds; publication backs up existing finals and rolls them back if a later replacement fails. Rendering failures remove temporary files without changing pre-existing finals. `before_metrics` contains the source metric objects used by the batch, and each output's `before_ref` identifies which object applies; different strict or high-bit-depth decode results receive distinct references. `--report full` returns the complete report for every item.

`analyze.metrics`, plus the `before` and `after` metric objects returned by `grade`, retain all legacy fields and add:

- `rgb_channels.red|green|blue.mean`: visible-pixel channel mean.
- `rgb_channels.*.percentiles`: visible-pixel `1`, `5`, `25`, `50`, `75`, `95`, and `99` percentiles.
- `rgb_channels.*.low_clip_ratio` and `high_clip_ratio`: independent channel clipping ratios using the legacy thresholds `<= 0.002` and `>= 0.998`.
- `rgb_channels.*.histogram_64`: 64 normalized bins spanning encoded sRGB `[0,1]`; each channel sums to `1` within floating-point representation.
- `spatial_rgb_mean_grid_3x3`: row-major 3×3 cells, each containing `[red, green, blue]` means or `null` when the cell has no visible pixels.

As with legacy metrics, a pixel is visible only when alpha is absent or alpha is greater than `0.01`. These arrays are intended for machine-readable cast, channel clipping, tonal separation, and spatial color-balance decisions; `analyze` does not create parade images.

`grade.processing` reports the fixed curve working space, interpolation, order, and active channel names without exposing curve points unless `--show-parameters` is explicitly set. `compare.rgb_channel_difference` provides signed mean, mean absolute, p95 absolute, and maximum absolute encoded-sRGB differences for each channel when geometry matches.

When any global or local presence control is nonzero, `grade.processing.presence` is added with the fixed working signal, method and global order, the names of active global controls, and each local stage/index with active local control names. It does not expose numeric settings; use `--show-parameters` only when the expanded recipe is explicitly required. For recipes with no active presence control, this optional technical block is omitted so legacy reports retain their prior `processing` structure.

When sharpening is active and either new guard is nonzero, `grade.processing.sharpening` reports the unsharp method, active guard names, luminance signals, and alpha handling without exposing numeric settings. Omitted or all-zero guards do not add this block.

`analyze` adds top-level `bit_depth`, `color_management.icc_status`, `source_extension`, `detected_format`, `extension_matches_format`, and `recommended_extension`; the existing `format` field remains the decoder-detected format. A mismatched supported extension produces a warning, and a supported extension cannot make another payload type valid. Treat the detected format as authoritative when choosing a default output name.

`grade` repeats the source format fields and adds `output_format_conversion`, which is `null` when the detected format is preserved or a `{ "from": ..., "to": ... }` object when the caller-selected output suffix explicitly converts it. `grade.output_encoding` reports actual format, extension agreement, input and output bit depth, dither mode, input/output ICC state, and Python/NumPy/Pillow/PyPNG versions. When a new color-management path is active, `grade.processing.color_management` reports rendering and gamut modes, mapping stages, and the maximum pre-map plus final post-map out-of-gamut pixel ratios. `compare.output_encoding_difference` summarizes both bit depths and ICC states without changing the existing `checks` meanings. The optional `warnings` array is present for a recoverable legacy ICC fallback, source extension mismatch, or explicit output format conversion.
