"""F7: only isolated Alpine native runtime. No HA or OPERA provider activation.

Observe registered GDAL drivers and run a tiny in-memory GeoTIFF + warp probe;
this does not establish original OPERA data or resource-safe HA performance.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import reproject,Resampling

def probe():
    with rasterio.Env() as env:
        drivers=env.drivers()
    essential=("GTiff","VRT","MEM","PNG")
    input_pixels=np.arange(256,dtype="float32").reshape(16,16)
    with MemoryFile() as mem:
        with mem.open(driver="GTiff",width=16,height=16,count=1,
                      dtype="float32",crs="EPSG:4326",
                      transform=from_origin(-2,60,0.25,0.25)) as dst:
            dst.write(input_pixels,1)
        with mem.open() as src:
            output=np.zeros((16,16),dtype="float32")
            reproject(source=src.read(1),destination=output,
                      src_transform=src.transform,src_crs=src.crs,
                      dst_transform=src.transform,dst_crs=src.crs,
                      resampling=Resampling.nearest,num_threads=1)
    return {
        "schema":"weather_router.f7.native_driver_scope.v1",
        "status":"ISOLATED_RUNTIME_TEST_ONLY",
        "rasterio":rasterio.__version__,
        "gdal":rasterio.__gdal_version__,"proj":rasterio.__proj_version__,
        "registered_driver_count":len(drivers),
        "required_raster_drivers":{d:d in drivers for d in essential},
        "cog_driver_present":"COG" in drivers,
        "synthetic_geotiff_warp_pass":bool(np.array_equal(input_pixels,output)),
        "gdal_driver_minimization_permitted":False,
        "native_dependency_pruning_permitted":False,
        "authentic_opera_tiff_driver_verified":False,
        "memory_limit_proven_on_ha":False,
        "ha_installation":"BLOCKED",
        "opera_activation":"BLOCKED"}

def main(argv):
    if len(argv)!=2:return 2
    result=probe()
    dst=Path(argv[1])
    if dst.is_symlink():return 1
    dst.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    if not all(result["required_raster_drivers"].values()) or not result["synthetic_geotiff_warp_pass"]:
        return 1
    print("F7 synthetic GTiff & reproject scope PASS, optimization and HA import BLOCKED")
    return 0

if __name__=="__main__":raise SystemExit(main(sys.argv))
