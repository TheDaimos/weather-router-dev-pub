"""Bounded WCS GeoTIFF NoData acquisition for exact DWD radar analysis frames.

This helper has no Home Assistant dependency. It only accepts the documented,
uncompressed, Float32, tiled GeoTIFF layout and fails closed otherwise.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode

from .dwd_frame_mask import MAX_CELLS, SCHEMA, _stamp, validate_mask

WCS_URL = "https://maps.dwd.de/geoserver/dwd/wcs"
MAX_TIFF_BYTES = 16_000_000


async def read_tiff_chunks(chunks):
    """Read the whole bounded HTTP entity across partial network reads."""
    payload = bytearray()
    async for chunk in chunks:
        if len(payload) + len(chunk) > MAX_TIFF_BYTES:
            raise ValueError("DWD TIFF byte budget exceeded")
        payload.extend(chunk)
    return payload


def wcs_url(valid_at: str) -> str:
    """Fetch a precise analysis from the official, fixed DWD service."""
    _stamp(valid_at)
    value = valid_at.replace("Z", ".000Z")
    query = urlencode({
        "service": "WCS", "version": "2.0.1", "request": "GetCoverage",
        "coverageId": "dwd__Niederschlagsradar", "format": "image/tiff",
        "subset": f'time("{value}")',
    })
    return f"{WCS_URL}?{query}"


def decode_mask(tiff: bytes, valid_at: str):
    """Recognize the real DWD tiled Float32 GeoTIFF; reject unknown layouts."""
    if len(tiff) > MAX_TIFF_BYTES or len(tiff) < 128:
        raise ValueError("DWD TIFF byte budget exceeded")
    byteorder = tiff[:2]
    if byteorder not in (b"MM", b"II"):
        raise ValueError("Not a TIFF")
    endian = ">" if byteorder == b"MM" else "<"
    u16 = lambda offset: struct.unpack_from(endian + "H", tiff, offset)[0]
    u32 = lambda offset: struct.unpack_from(endian + "I", tiff, offset)[0]
    if u16(2) != 42:
        raise ValueError("BigTIFF or invalid TIFF unsupported")
    index = u32(4)
    if index + 2 > len(tiff):
        raise ValueError("Invalid TIFF directory")
    count = u16(index)
    if count > 256 or index + 2 + 12 * count + 4 > len(tiff):
        raise ValueError("Invalid TIFF field count")
    tags = {}
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}
    for idx in range(count):
        off = index + 2 + idx * 12
        tag, kind = struct.unpack_from(endian + "HH", tiff, off)
        n = u32(off + 4)
        length = sizes.get(kind, 0) * n
        if not length or length > MAX_TIFF_BYTES:
            raise ValueError("Unsupported TIFF field")
        start = off + 8 if length <= 4 else u32(off + 8)
        if start + length > len(tiff):
            raise ValueError("Invalid TIFF field offset")
        tags[tag] = (kind, n, tiff[start:start + length])

    def values(tag, kind):
        typ, n, raw = tags[tag]
        if typ != kind or n > MAX_CELLS:
            raise ValueError("Wrong TIFF field type")
        codes = {3: "H", 4: "I", 12: "d"}
        return struct.unpack(endian + str(n) + codes[kind], raw)

    def scalar(tag, kind):
        values_ = values(tag, kind)
        if len(values_) != 1:
            raise ValueError("Wrong TIFF scalar")
        return values_[0]

    width, height = scalar(256, 3), scalar(257, 3)
    if not 1 <= width * height <= MAX_CELLS or width > 4096 or height > 4096:
        raise ValueError("DWD TIFF raster too large")
    if (scalar(258, 3) != 32 or scalar(259, 3) != 1 or scalar(262, 3) != 1
            or scalar(277, 3) != 1 or scalar(339, 3) != 3):
        raise ValueError("Expected uncompressed single-band Float32")
    tile_width, tile_height = scalar(322, 3), scalar(323, 3)
    offsets, lengths = values(324, 4), values(325, 4)
    cols = (width + tile_width - 1) // tile_width
    rows = (height + tile_height - 1) // tile_height
    if len(offsets) != cols * rows or len(lengths) != len(offsets):
        raise ValueError("Incomplete TIFF tile directory")
    geo = values(34264, 12)
    keys = values(34735, 3)
    if (len(geo) != 16 or geo[0] <= 0 or geo[5] >= 0
            or any(geo[k] != 0 for k in (1, 2, 4, 6, 8, 9, 11, 12, 13, 14))
            or geo[15] != 1 or (2048, 0, 1, 4326) not in
            [tuple(keys[k:k + 4]) for k in range(4, len(keys), 4)]):
        raise ValueError("Unsupported DWD georeference")
    if 42113 not in tags or tags[42113][2].rstrip(b"\0") != b"4.294967296E9":
        raise ValueError("Unknown DWD TIFF NoData sentinel")

    bits = bytearray((width * height + 7) // 8)
    for tile_idx, (offset, length) in enumerate(zip(offsets, lengths)):
        if length != tile_width * tile_height * 4 or offset + length > len(tiff):
            raise ValueError("Unsupported TIFF tile payload")
        tile_x, tile_y = tile_idx % cols, tile_idx // cols
        for row in range(tile_height):
            y = tile_y * tile_height + row
            if y >= height:
                break
            max_col = min(tile_width, width - tile_x * tile_width)
            for col in range(max_col):
                x = tile_x * tile_width + col
                value = struct.unpack_from(endian + "f", tiff,
                    offset + (row * tile_width + col) * 4)[0]
                if value == -999 or value == 4294967296:
                    bit = y * width + x
                    bits[bit // 8] |= 1 << (bit % 8)
    west, north = geo[3], geo[7]
    return validate_mask({
        "kind": SCHEMA, "valid_at": valid_at, "reference_at": valid_at,
        "width": width, "height": height,
        "bounds": [west, north + geo[5] * height, west + geo[0] * width, north],
        "bits": base64.b64encode(bits).decode("ascii"),
    })


def stage_mask(cache, mask):
    directory = Path(cache)
    directory.mkdir(parents=True, exist_ok=True)
    output = json.dumps(mask, separators=(",", ":"))
    if len(output.encode()) > 350_000:
        raise ValueError("DWD mask too large for cache")
    with NamedTemporaryFile(mode="w", dir=directory, encoding="utf-8", delete=False) as handle:
        handle.write(output)
        temp = Path(handle.name)
    temp.replace(directory / f"{_stamp(mask['valid_at'])}.json")
