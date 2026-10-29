"""Isolated F7 native GDAL concurrency probe with OPERA-sized *synthetic* CoG.

Run on CI or an explicitly approved disposable test host only.
No HA imports, original OPERA bytes, network calls, provider activation or
scientific colour/quality claims. NOT a live HA mainloop/OOM acceptance.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import platform
import resource
import sys
import tempfile
import threading
import time
import types


def _load_wr():
    root = Path(__file__).resolve().parents[1] / "custom_components" / "weather_router"
    package = "_wr_opera_concurrent_probe"
    module = types.ModuleType(package)
    module.__path__ = [str(root)]
    sys.modules[package] = module
    for name in ("opera_frame_cache", "opera_cog_tiles"):
        spec = importlib.util.spec_from_file_location(
            package + "." + name, root / (name + ".py"))
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = loaded
        spec.loader.exec_module(loaded)
    return (sys.modules[package + ".opera_frame_cache"],
            sys.modules[package + ".opera_cog_tiles"])


def _prepare_fixture(folder):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.shutil import copy as cog_copy

    raw, cog = folder / "source.tiff", folder / "source.cog.tiff"
    laea = ("+proj=laea +lat_0=55 +lon_0=10 +x_0=1950000 "
            "+y_0=-2100000 +datum=WGS84 +units=m +no_defs")
    rng = np.random.default_rng(20102026)
    width, height = 3800, 4400  # real CIRRUS DBZH pixel dimensions, fake values
    with rasterio.open(
        raw, "w", driver="GTiff", width=width, height=height, count=2,
        dtype="float32", crs=laea,
        transform=from_origin(1850000, -1850000, 1000, 1000),
        nodata=-9999000, tiled=True, blockxsize=256, blockysize=256,
        compress="DEFLATE",
    ) as dst:
        from rasterio.windows import Window
        for start in range(0, height, 128):
            count = min(128, height - start)
            pixels = np.full((count, width), -9999000, dtype=np.float32)
            mask = rng.random((count, width)) < 0.045
            pixels[mask] = rng.uniform(-8.0, 60.0, size=int(mask.sum()))
            # Synthetic only: includes valid negative reflectivity, zero,
            # NaNs, sentinel, and an uninterpreted second data band.
            pixels[0, :8] = np.nan
            pixels[1, :8] = 0.0
            dst.write(pixels, 1, window=Window(0, start, width, count))
            dst.write(np.full((count, width), 0.5, dtype=np.float32),
                      2, window=Window(0, start, width, count))
        dst.set_band_description(1, "DBZH")
        dst.set_band_description(2, "quality1")
    cog_copy(raw, cog, driver="COG", blocksize=512,
             compress="DEFLATE", overview_resampling="nearest")
    if not 0 < cog.stat().st_size <= 12 * 1024 * 1024:
        raise AssertionError("synthetic_fixture_exceeds_existing_WR_source_limit")
    return cog


async def _run_jobs(frame, renderer):
    from PIL import Image
    job_coordinates = [(6, 33, 19), (6, 33, 20), (6, 34, 19),
                       (6, 33, 19), (6, 33, 20), (6, 34, 19)]
    lock = threading.Lock()
    stats = {"active": 0, "peak": 0, "completed": 0}
    max_slots = 2
    semaphore = asyncio.Semaphore(max_slots)
    stop = asyncio.Event()
    intervals = []

    def work(coordinates):
        with lock:
            stats["active"] += 1
            stats["peak"] = max(stats["peak"], stats["active"])
        try:
            z, x, y = coordinates
            return renderer.render_verified_cog(
                trusted_path=frame.path, expected_sha256=frame.digest,
                z=z, x=x, y=y, verified_frame=frame,
                palette=lambda val: (160, 32, 18, 255)
                    if val < 0 else (24, 105, 190, 255))
        finally:
            with lock:
                stats["active"] -= 1
                stats["completed"] += 1

    async def heartbeat():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.02)
            now = time.perf_counter()
            intervals.append(now - last)
            last = now

    pool = ThreadPoolExecutor(max_workers=max_slots,
                              thread_name_prefix="wr-f7-native-probe")
    loop = asyncio.get_running_loop()
    ticker = asyncio.create_task(heartbeat())
    start = time.perf_counter()
    try:
        async def submit(coordinates):
            async with semaphore:
                return await loop.run_in_executor(pool, work, coordinates)
        tasks = [asyncio.create_task(submit(coord))
                 for coord in job_coordinates]
        result = await asyncio.wait_for(asyncio.gather(*tasks), timeout=35)
    finally:
        stop.set()
        await ticker
        pool.shutdown(wait=True)
    assert stats["active"] == 0 and stats["completed"] == len(job_coordinates)
    assert 1 <= stats["peak"] <= max_slots
    assert intervals, "event_loop_heartbeat_never_ran"
    nontransparent = 0
    for png in result:
        with Image.open(BytesIO(png)) as image:
            assert image.size == (256, 256) and image.format == "PNG"
            nontransparent += sum(a > 0 for *_, a in
                                  image.convert("RGBA").getdata())
    assert nontransparent > 0, "synthetic_tiles_have_no_pixels"
    return {
        "jobs": len(result), "peak_native_workers": stats["peak"],
        "worker_limit": max_slots, "loop_heartbeat_samples": len(intervals),
        "loop_max_gap_ms": round(1000 * max(intervals), 2),
        "wall_seconds": round(time.perf_counter() - start, 4),
        "rgba_pixels_nontransparent": nontransparent,
        "png_total_bytes": sum(map(len, result)),
    }


def run():
    import numpy as np
    import rasterio
    import PIL
    overall = time.perf_counter()
    cpu_start = time.process_time()
    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    frames, renderer = _load_wr()
    with tempfile.TemporaryDirectory(prefix="wr-f7-native-concurrent-") as tmp:
        source = _prepare_fixture(Path(tmp))
        digest = sha256(source.read_bytes()).hexdigest()
        cache = frames.ImmutableFrameCache(max_frames=1)
        try:
            frame = cache.admit(
                source_path=source, product="DBZH",
                valid_at=datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc),
                expected_sha256=digest)
            result = asyncio.run(_run_jobs(frame, renderer))
            assert cache.hash_operations == 1
            result.update({
                "schema": "weather_router.opera.native_concurrent_probe.v1",
                "fixture": "synthetic_3800x4400_two_band_cog_not_OPERA",
                "python": platform.python_version(),
                "machine": platform.machine(),
                "numpy": np.__version__, "pillow": PIL.__version__,
                "rasterio": rasterio.__version__,
                "gdal": rasterio.__gdal_version__,
                "proj": rasterio.__proj_version__,
                "source_cog_bytes": source.stat().st_size,
                "cpu_seconds_total": round(time.process_time() - cpu_start, 4),
                "rss_peak_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "rss_peak_increase_kib": max(
                    0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss_start),
                "end_to_end_wall_seconds": round(time.perf_counter() - overall, 4),
                "frame_hash_count": cache.hash_operations,
            })
            print(json.dumps(result, sort_keys=True))
            return result
        finally:
            cache.close()


if __name__ == "__main__":
    run()
