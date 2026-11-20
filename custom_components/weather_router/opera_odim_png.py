"""Authenticated-route worker for a previously admitted, immutable ODIM RATE frame.

Uses the existing bounded LAEA window renderer. It is not a registration
function and must never be exposed without server-owned scientific admission.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
from pathlib import Path


class OperaOdimPngError(ValueError):
    pass


def render_verified_odim_rate(*, trusted_path: Path, expected_sha256: str,
                              grid, projection: str, dataset_path: str,
                              x: int, y: int, z: int,
                              orientation_verified: bool) -> bytes:
    """Digest-verified, bounded RGBA->PNG; no arbitrary user-supplied paths."""
    path=Path(trusted_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 12*1024*1024:
        raise OperaOdimPngError("untrusted_frame")
    if not isinstance(expected_sha256,str) or len(expected_sha256)!=64:
        raise OperaOdimPngError("invalid_frame_digest")
    h=sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536),b""):
            h.update(block)
    if h.hexdigest()!=expected_sha256:
        raise OperaOdimPngError("frame_digest_mismatch")
    if orientation_verified is not True:
        raise OperaOdimPngError("orientation_unverified")
    try:
        from .opera_odim_tile import decode_rate_tile
        from PIL import Image
        rgba, _ = decode_rate_tile(path,grid=grid,projection=projection,
            dataset_path=dataset_path,x=x,y=y,z=z,
            orientation_verified=True)
        buffer=BytesIO()
        Image.fromarray(rgba,mode="RGBA").save(buffer,format="PNG",optimize=False)
        png=buffer.getvalue()
    except (OSError, ValueError, ImportError) as exc:
        raise OperaOdimPngError("odim_png_unavailable") from exc
    if not 0 < len(png) <= 512*1024:
        raise OperaOdimPngError("png_size_invalid")
    return png
