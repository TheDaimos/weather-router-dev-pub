"""Read-only, synthetic CoG runtime probe for public CI and future HA test host.

Never installs packages, uses network, opens real OPERA files, or alters HA.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import platform
import resource
import tempfile
import time

def run():
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.shutil import copy as raster_copy
    from PIL import Image

    started=time.perf_counter()
    cpu_start=time.process_time()
    mem_before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with tempfile.TemporaryDirectory(prefix="opera-probe-") as folder:
        base=Path(folder)
        raw=base/"fixture.tif"
        cog=base/"fixture.cog.tif"
        arr=np.full((256,256), -9999000, dtype=np.float32)
        arr[40:190,40:190]=-8.0
        arr[110:120,110:130]=np.nan
        laea="+proj=laea +lat_0=55 +lon_0=10 +x_0=1950000 +y_0=-2100000 +datum=WGS84 +units=m +no_defs"
        with rasterio.open(raw,"w",driver="GTiff",width=256,height=256,
                           count=1,dtype="float32",crs=laea,
                           transform=from_origin(1850000,-1850000,1000,1000),
                           nodata=-9999000,tiled=True,blockxsize=256,blockysize=256,
                           compress="DEFLATE") as target:
            target.write(arr,1)
        raster_copy(raw,cog,driver="COG",blocksize=512,compress="DEFLATE",
                    overview_resampling="nearest")
        from datetime import datetime, timezone
        # Load isolated WR implementation without importing Home Assistant.
        import importlib.util,sys,types
        root=Path(__file__).resolve().parents[1]/"custom_components/weather_router"
        pkg="_wr_opera_probe"
        stub=types.ModuleType(pkg)
        stub.__path__=[str(root)]
        sys.modules[pkg]=stub
        for name in ("opera_frame_cache","opera_cog_tiles"):
            spec=importlib.util.spec_from_file_location(pkg+"."+name,root/(name+".py"))
            module=importlib.util.module_from_spec(spec)
            sys.modules[spec.name]=module
            spec.loader.exec_module(module)
        cache_module=sys.modules[pkg+".opera_frame_cache"]
        render_module=sys.modules[pkg+".opera_cog_tiles"]
        digest=sha256(cog.read_bytes()).hexdigest()
        cache=cache_module.ImmutableFrameCache(max_frames=1)
        try:
            frame=cache.admit(source_path=cog,product="DBZH",
                    valid_at=datetime(2026,10,19,13,40,tzinfo=timezone.utc),
                    expected_sha256=digest)
            png=render_module.render_verified_cog(
                trusted_path=frame.path,expected_sha256=digest,z=6,x=33,y=19,
                verified_frame=frame,palette=lambda v:(255,0,255,255))
            with Image.open(BytesIO(png)) as image:
                valid=sum(pixel[3]!=0 for pixel in image.convert("RGBA").getdata())
                assert image.size==(256,256) and 0<valid<256*256
            assert cache.hash_operations==1
            with rasterio.open(cog) as sample:
                assert sample.crs is not None and sample.driver=="GTiff"
                layout=sample.tags(ns="IMAGE_STRUCTURE").get("LAYOUT")
                assert layout=="COG", f"unexpected_tiff_layout: {layout!r}"
            report={
                "schema":"weather_router.opera.runtime_probe.v1",
                "fixture":"synthetic_COG_only",
                "python":platform.python_version(),
                "machine":platform.machine(),
                "rasterio":rasterio.__version__,
                "gdal":rasterio.__gdal_version__,
                "proj":rasterio.__proj_version__,
                "numpy":np.__version__,
                "wall_seconds":round(time.perf_counter()-started,4),
                "cpu_seconds":round(time.process_time()-cpu_start,4),
                "rss_peak_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "rss_peak_increase_kib":max(0,resource.getrusage(resource.RUSAGE_SELF).ru_maxrss-mem_before),
                "source_cog_bytes":cog.stat().st_size,
                "png_bytes":len(png),
                "rendered_pixels":valid,
                "admission_hash_count":cache.hash_operations,
            }
            print(json.dumps(report,sort_keys=True))
            return report
        finally:
            cache.close()

if __name__=="__main__":
    run()
