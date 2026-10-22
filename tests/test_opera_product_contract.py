"""Scientific OPERA format checking without genuine confidential radar files."""
from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from types import SimpleNamespace

BASE=Path(__file__).resolve().parents[1]/"custom_components/weather_router"
PKG="_wr_opera_contract_test"
if PKG not in sys.modules:
    mod=types.ModuleType(PKG)
    mod.__path__=[str(BASE)]
    sys.modules[PKG]=mod

def load(name):
    key=PKG+"."+name
    if key not in sys.modules:
        spec=importlib.util.spec_from_file_location(key,BASE/(name+".py"))
        module=importlib.util.module_from_spec(spec)
        sys.modules[key]=module
        spec.loader.exec_module(module)
    return sys.modules[key]

load("opera_tile_security")
contract=load("opera_product_contract")

class CRS:
    def __init__(self, **override):
        self.values=dict(proj="laea",lat_0=55.0,lon_0=10.0,x_0=1950000.0,y_0=-2100000.0)
        self.values.update(override)
    def to_dict(self):
        return self.values.copy()

def dataset(code, **overrides):
    size=(3800,4400,1000) if code=="DBZH" else (1900,2200,2000)
    out=dict(driver="GTiff",width=size[0],height=size[1],count=2,
             crs=CRS(),transform=SimpleNamespace(a=size[2],e=-size[2],b=0,d=0),
             nodata=-9999000,descriptions=(code,"quality1"),
             dtypes=("float32","float32"))
    out.update(overrides)
    return SimpleNamespace(**out)

class ProductContracts(unittest.TestCase):
    def setUp(self):
        self.dates={"DBZH":datetime(2026,10,19,13,40,tzinfo=timezone.utc),
                    "RATE":datetime(2026,10,19,13,15,tzinfo=timezone.utc)}
    def filename(self,code):
        return "OPERA@"+self.dates[code].strftime("%Y%m%dT%H%M")+"@0@"+code+".tiff"
    def check(self,code,source=None,**overrides):
        return contract.check_opera_raster(filename=self.filename(code),
                     valid_at=self.dates[code] if source is None else source,
                     dataset=dataset(code,**overrides))

    def test_two_independent_products_not_quality_approved(self):
        for code,unit,pixel,cadence in (("DBZH","dBZ",1000,5),("RATE","mm/h",2000,15)):
            info=self.check(code)
            self.assertEqual(info.product.unit,unit)
            self.assertEqual(info.product.resolution_m,pixel)
            self.assertEqual(info.product.cadence_minutes,cadence)
            self.assertEqual(info.valid_at,self.dates[code])
            self.assertEqual(info.quality_status,"unverified")
            self.assertFalse(info.ready_for_public_tiles)

    def test_strict_utc_source_time_not_retrieval_time(self):
        for code in ("DBZH","RATE"):
            with self.assertRaises(contract.OperaProductError):
                self.check(code,source=self.dates[code]+timedelta(minutes=1))
            with self.assertRaises(contract.OperaProductError):
                self.check(code,source=self.dates[code].replace(tzinfo=None))

    def test_wrong_physics_crs_geometry_and_quality_inventory_rejected(self):
        cases=({"width":1900},{"count":1},{"crs":CRS(lon_0=15)},
               {"crs":CRS(proj="merc")},{"nodata":0},
               {"descriptions":("RATE","quality1")},
               {"descriptions":("DBZH","quality_unverified")},
               {"dtypes":("int16","float32")},
               {"transform":SimpleNamespace(a=2000,e=-1000,b=0,d=0)})
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(contract.OperaProductError):
                    self.check("DBZH",**change)

    def test_unknown_filename_path_or_product_rejected(self):
        for filename in ("../OPERA@20261019T1340@0@DBZH.tiff",
                         "OPERA@20261019T1340@0@ACRR.tiff",
                         "OPERA@20261019T1340@0@RATE.tiff"):
            with self.assertRaises(contract.OperaProductError):
                contract.check_opera_raster(filename=filename,
                    valid_at=self.dates["DBZH"],dataset=dataset("DBZH"))

if __name__=="__main__":
    unittest.main()
