#!/usr/bin/env python3
"""Deterministic 16-bit RGB/RGBA PNG I/O with explicit metadata chunks."""

from __future__ import annotations

import binascii
import struct
import zlib
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import png


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    if len(chunk_type) != 4:
        raise ValueError("PNG chunk types must contain four bytes.")
    checksum = binascii.crc32(chunk_type)
    checksum = binascii.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def _iter_chunks(payload: bytes) -> Iterable[tuple[bytes, bytes]]:
    if not payload.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid PNG signature.")
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(payload):
            raise ValueError("Truncated PNG chunk stream.")
        data = payload[offset + 8 : offset + 8 + length]
        expected = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        actual = binascii.crc32(chunk_type)
        actual = binascii.crc32(data, actual) & 0xFFFFFFFF
        if actual != expected:
            raise ValueError(f"PNG chunk {chunk_type!r} has an invalid CRC.")
        yield chunk_type, data
        offset = end
        if chunk_type == b"IEND":
            if offset != len(payload):
                raise ValueError("Unexpected data after PNG IEND chunk.")
            return
    raise ValueError("PNG stream has no complete IEND chunk.")


def inspect_ihdr(path: Path) -> dict[str, int]:
    payload = path.read_bytes()
    chunks = _iter_chunks(payload)
    chunk_type, data = next(chunks)
    if chunk_type != b"IHDR" or len(data) != 13:
        raise ValueError("PNG IHDR chunk is missing or invalid.")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", data
    )
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "compression": compression,
        "filter": filtering,
        "interlace": interlace,
    }


def chunk_types(path: Path) -> list[bytes]:
    return [chunk_type for chunk_type, _ in _iter_chunks(path.read_bytes())]


def read_png16(path: Path) -> tuple[np.ndarray, np.ndarray | None, dict[str, Any]]:
    """Decode a direct 16-bit PNG into float32 RGB/alpha without 8-bit truncation."""
    header = inspect_ihdr(path)
    if header["bit_depth"] != 16:
        raise ValueError("Expected a 16-bit PNG input.")
    width, height, rows, info = png.Reader(filename=str(path)).asDirect()
    bit_depth = int(info["bitdepth"])
    if bit_depth != 16:
        raise ValueError("PyPNG did not return 16-bit source samples.")
    planes = int(info["planes"])
    samples = np.vstack(
        [np.fromiter(row, dtype=np.uint16, count=width * planes) for row in rows]
    ).reshape(height, width, planes)
    if bool(info.get("greyscale")):
        luminance = samples[..., :1]
        rgb16 = np.repeat(luminance, 3, axis=2)
        alpha16 = samples[..., 1:2] if bool(info.get("alpha")) else None
    else:
        rgb16 = samples[..., :3]
        alpha16 = samples[..., 3:4] if bool(info.get("alpha")) else None
    rgb = (rgb16.astype(np.float32) / 65535.0).astype(np.float32)
    alpha = None if alpha16 is None else (alpha16.astype(np.float32) / 65535.0).astype(np.float32)
    return rgb, alpha, {
        "width": int(width),
        "height": int(height),
        "bit_depth": bit_depth,
        "has_alpha": alpha is not None,
        "color_type": header["color_type"],
    }


def _text_chunk(keyword: str, value: str) -> bytes:
    try:
        keyword_bytes = keyword.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError("PNG text keywords must be Latin-1.") from exc
    if not keyword_bytes or len(keyword_bytes) > 79 or b"\x00" in keyword_bytes:
        raise ValueError("PNG text keywords must contain 1 to 79 non-null bytes.")
    try:
        value_bytes = value.encode("latin-1")
    except UnicodeEncodeError:
        payload = keyword_bytes + b"\x00\x00\x00\x00\x00" + value.encode("utf-8")
        return _chunk(b"iTXt", payload)
    return _chunk(b"tEXt", keyword_bytes + b"\x00" + value_bytes)


def _metadata_chunks(metadata: dict[str, Any]) -> list[bytes]:
    chunks: list[bytes] = []
    icc_profile = metadata.get("icc_profile")
    if icc_profile:
        compressed = zlib.compress(bytes(icc_profile), level=9)
        chunks.append(_chunk(b"iCCP", b"ICC Profile\x00\x00" + compressed))
    exif = metadata.get("exif")
    if exif:
        exif_bytes = bytes(exif)
        if exif_bytes.startswith(b"Exif\x00\x00"):
            exif_bytes = exif_bytes[6:]
        chunks.append(_chunk(b"eXIf", exif_bytes))
    for key, value in metadata.get("png_text", {}).items():
        if isinstance(key, str) and isinstance(value, str):
            chunks.append(_text_chunk(key, value))
    return chunks


def write_png16(
    path: Path,
    rgb16: np.ndarray,
    alpha16: np.ndarray | None,
    metadata: dict[str, Any],
    compression: int = 6,
) -> None:
    """Write RGB16/RGBA16 samples and preserve the currently supported metadata."""
    if rgb16.dtype != np.uint16 or rgb16.ndim != 3 or rgb16.shape[2] != 3:
        raise ValueError("rgb16 must be a height x width x 3 uint16 array.")
    if alpha16 is not None and (
        alpha16.dtype != np.uint16
        or alpha16.shape != (*rgb16.shape[:2], 1)
    ):
        raise ValueError("alpha16 must match rgb16 geometry and contain one uint16 channel.")
    height, width = rgb16.shape[:2]
    samples = rgb16 if alpha16 is None else np.concatenate((rgb16, alpha16), axis=2)
    dpi = metadata.get("dpi")
    writer_options: dict[str, Any] = {}
    if isinstance(dpi, (tuple, list)) and len(dpi) >= 2:
        x_ppm = int(round(float(dpi[0]) / 0.0254))
        y_ppm = int(round(float(dpi[1]) / 0.0254))
        if x_ppm > 0 and y_ppm > 0:
            writer_options = {
                "x_pixels_per_unit": x_ppm,
                "y_pixels_per_unit": y_ppm,
                "unit_is_meter": True,
            }
    writer = png.Writer(
        width=width,
        height=height,
        greyscale=False,
        alpha=alpha16 is not None,
        bitdepth=16,
        compression=int(np.clip(compression, 0, 9)),
        **writer_options,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer.write(handle, (row.reshape(-1) for row in samples))

    payload = path.read_bytes()
    chunks = list(_iter_chunks(payload))
    if not chunks or chunks[0][0] != b"IHDR":
        path.unlink(missing_ok=True)
        raise RuntimeError("PyPNG output is missing IHDR.")
    ancillary = _metadata_chunks(metadata)
    rebuilt = bytearray(PNG_SIGNATURE)
    rebuilt.extend(_chunk(*chunks[0]))
    for encoded in ancillary:
        rebuilt.extend(encoded)
    for chunk_type, data in chunks[1:]:
        rebuilt.extend(_chunk(chunk_type, data))
    path.write_bytes(bytes(rebuilt))
    header = inspect_ihdr(path)
    if header["bit_depth"] != 16 or header["width"] != width or header["height"] != height:
        path.unlink(missing_ok=True)
        raise RuntimeError("PNG16 verification failed; invalid output was removed.")
