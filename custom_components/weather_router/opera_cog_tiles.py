"""Dormant, fail-closed OPERA CoG tile renderer; no HTTP route/provider activation."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re

class OperaRasterError(ValueError):
    pass

def immutable_key(*, product, source_time, source_sha256, z, x, y, palette_rev, quality_rev):
    """Kachelidentität ohne Abrufzeit; Freigabe bei jedem Zugriff separat prüfen."""
    if product not in ("DBZH", "RATE") or not isinstance(source_time, datetime) or source_time.tzinfo is None:
        raise OperaRasterError("invalid_source")
    if not isinstance(source_sha256, str) or not re.fullmatch("[a-f0-9]{64}", source_sha256):
        raise OperaRasterError("invalid_revision")
    if any(type(v) is not int for v in (z, x, y)) or not (0 <= z <= 16 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise OperaRasterError("invalid_xyz")
    if any(not isinstance(v,str) or not re.fullmatch("[A-Za-z0-9_-]{1,32}",v) for v in (palette_rev,quality_rev)):
        raise OperaRasterError("invalid_style")
    return (product,source_time.astimezone(timezone.utc).isoformat(),source_sha256,z,x,y,palette_rev,quality_rev)

def authorize_current(source_time, now):
    """Muss auch bei einem Cachetreffer nach der Sitzungsfreigabe erfolgen."""
    if not all(isinstance(t,datetime) and t.tzinfo is not None for t in (source_time,now)):
        raise OperaRasterError("invalid_clock")
    age=(now.astimezone(timezone.utc)-source_time.astimezone(timezone.utc)).total_seconds()
    if not 0 <= age <= 900:
        raise OperaRasterError("stale_or_future")

def render_verified_cog(*, trusted_path, expected_sha256, z, x, y, palette, verified_frame=None):
    """Intern freigegebene lokale CoG-Datei zu georeferenziertem PNG; kein Netz-Proxy.

    Palette muss vom Aufrufer fachlich nachgewiesen werden; nie automatisch dBZ
    als Regenrate interpretieren. Caller schützt Pfad, Auth, Concurrency, Timeout.
    """
    import numpy as np
    import rasterio
    from rasterio.warp import reproject
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from PIL import Image
    immutable_key(product="DBZH",source_time=datetime(2026,1,1,tzinfo=timezone.utc),
                  source_sha256=expected_sha256,z=z,x=x,y=y,
                  palette_rev="internal",quality_rev="unverified")
    file=Path(trusted_path)
    if not file.is_file() or not 0 < file.stat().st_size <= 12*1024*1024 or not callable(palette):
        raise OperaRasterError("invalid_source_file")
    if verified_frame is not None:
        # Only a private immutable admission snapshot is permitted to bypass hashing.
        from .opera_frame_cache import VerifiedFrame
        if (not isinstance(verified_frame, VerifiedFrame)
                or file != verified_frame.path
                or expected_sha256 != verified_frame.digest
                or file.stat().st_size != verified_frame.byte_size):
            raise OperaRasterError("unverified_frame")
    else:
        digest=sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda:stream.read(65536),b""):
                digest.update(chunk)
        if digest.hexdigest()!=expected_sha256:
            raise OperaRasterError("hash_mismatch")
    half=20037508.342789244
    step=2*half/(2**z)
    left=-half+x*step
    top=half-y*step
    transform=from_bounds(left,top-step,left+step,top,256,256)
    pixels=np.full((256,256),np.nan,dtype="float32")
    with rasterio.Env(GDAL_CACHEMAX=8,GDAL_NUM_THREADS="1"):
        with rasterio.open(file) as src:
            if src.crs is None or src.count < 1 or src.width*src.height>50_000_000:
                raise OperaRasterError("invalid_georeference")
            reproject(source=rasterio.band(src,1),destination=pixels,
                      src_transform=src.transform,src_crs=src.crs,src_nodata=src.nodata,
                      dst_transform=transform,dst_crs="EPSG:3857",dst_nodata=np.nan,
                      resampling=Resampling.nearest,num_threads=1,warp_mem_limit=8)
    rgba=np.zeros((256,256,4),dtype="uint8")
    valid=np.argwhere(np.isfinite(pixels)&(pixels!=-9999000))
    for row,col in valid:
        color=palette(float(pixels[row,col]))
        if not isinstance(color,(tuple,list)) or len(color)!=4 or any(type(v)!=int or not 0<=v<=255 for v in color):
            raise OperaRasterError("invalid_palette")
        rgba[row,col]=color
    buffer=BytesIO()
    Image.fromarray(rgba).save(buffer,format="PNG")
    return buffer.getvalue()
