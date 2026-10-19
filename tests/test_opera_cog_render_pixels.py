"""Synthetic pixel/projected XYZ regression for dormant CoG renderer.

The synthetic fixture is NOT an OPERA observation and its test palette is NOT
an approved meteorological product legend.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import importlib.util
import sys
import tempfile
import types
import unittest

BASE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
PACKAGE = "_opera_pixel_package"
if PACKAGE not in sys.modules:
    pkg = types.ModuleType(PACKAGE)
    pkg.__path__ = [str(BASE)]
    sys.modules[PACKAGE] = pkg

def load(name):
    fullname = PACKAGE + "." + name
    if fullname not in sys.modules:
        spec = importlib.util.spec_from_file_location(fullname, BASE / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = module
        spec.loader.exec_module(module)
    return sys.modules[fullname]

frames = load("opera_frame_cache")
renderer = load("opera_cog_tiles")

class OperaPixels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import numpy
            import rasterio
            import PIL
        except ImportError:
            raise unittest.SkipTest("Rasterio/NumPy/Pillow are not installed")
    def test_true_render_path_with_admitted_frame(self):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from PIL import Image
        from io import BytesIO
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "local_synthetic.tiff"
            laea = "+proj=laea +lat_0=55 +lon_0=10 +x_0=1950000 +y_0=-2100000 +datum=WGS84 +units=m +no_defs"
            arr = np.full((256,256), -9999000, np.float32)
            arr[20:210,25:210] = -4.5
            arr[70:100,75:100] = 20
            arr[110:135,95:120] = np.nan
            with rasterio.open(p,"w",driver="GTiff",width=256,height=256,count=1,
                dtype="float32",crs=laea,transform=from_origin(1850000,-1850000,1000,1000),
                nodata=-9999000) as dst:
                dst.write(arr,1)
            digest = sha256(p.read_bytes()).hexdigest()
            clock = datetime(2026,10,19,13,40,tzinfo=timezone.utc)
            cache = frames.ImmutableFrameCache(max_frames=1)
            try:
                admitted = cache.admit(source_path=p, product="DBZH",valid_at=clock,
                                      expected_sha256=digest)
                pixels = renderer.render_verified_cog(
                    trusted_path=admitted.path,expected_sha256=digest,z=6,x=33,y=19,
                    verified_frame=admitted,
                    palette=lambda v: (255,10,20,255) if v < 0 else (10,255,20,255))
                with Image.open(BytesIO(pixels)) as im:
                    self.assertEqual(im.size,(256,256))
                    rgba=np.asarray(im.convert("RGBA"))
                    self.assertGreater(np.count_nonzero(rgba[:,:,3]),0)
                    self.assertGreater(np.count_nonzero(rgba[:,:,3]==0),0)
                    self.assertGreater(np.count_nonzero((rgba[:,:,0]==255)&(rgba[:,:,3]==255)),0)
                self.assertEqual(cache.hash_operations,1)
                edge=renderer.render_verified_cog(
                    trusted_path=admitted.path,expected_sha256=digest,z=6,x=33,y=20,
                    verified_frame=admitted,
                    palette=lambda v: (255,10,20,255))
                with Image.open(BytesIO(edge)) as im:
                    self.assertIsNotNone(im.getbbox()) # Real georeferenced edge coverage
                blank=renderer.render_verified_cog(
                    trusted_path=admitted.path,expected_sha256=digest,z=6,x=33,y=21,
                    verified_frame=admitted,
                    palette=lambda v: (255,10,20,255))
                with Image.open(BytesIO(blank)) as im:
                    self.assertEqual(im.getbbox(),None)
                self.assertEqual(cache.hash_operations,1)
            finally:
                cache.close()

    def test_antimeridian_and_xyz_bounds(self):
        t=datetime(2026,10,19,13,40,tzinfo=timezone.utc)
        for z in (0,1,6,16):
            for x in (0,(1<<z)-1):
                renderer.immutable_key(product="DBZH",source_time=t,
                    source_sha256="a"*64,z=z,x=x,y=0,
                    palette_rev="verified",quality_rev="unknown")
        for x in (-1,64):
            with self.assertRaises(renderer.OperaRasterError):
                renderer.immutable_key(product="DBZH",source_time=t,
                    source_sha256="a"*64,z=6,x=x,y=0,
                    palette_rev="verified",quality_rev="unknown")

if __name__ == "__main__":
    unittest.main()
