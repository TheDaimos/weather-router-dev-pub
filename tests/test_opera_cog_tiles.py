"""Isolated regression checks: no HA imports or network."""
import importlib.util
from datetime import datetime,timedelta,timezone
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/"custom_components/weather_router/opera_cog_tiles.py"
spec=importlib.util.spec_from_file_location("opera_cog_tiles",path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class OperaCogTileTests(unittest.TestCase):
    def setUp(self):
        self.t=datetime(2026,10,19,13,40,tzinfo=timezone.utc)
        self.k=dict(product="DBZH",source_time=self.t,source_sha256="a"*64,z=6,x=33,y=19,palette_rev="v1",quality_rev="u1")
    def test_revision_changes_identity(self):
        base=module.immutable_key(**self.k)
        self.assertNotEqual(base,module.immutable_key(**dict(self.k,source_sha256="b"*64)))
        self.assertNotEqual(base,module.immutable_key(**dict(self.k,palette_rev="v2")))
    def test_cache_identity_does_not_grant_freshness(self):
        key=module.immutable_key(**self.k)
        module.authorize_current(self.t,self.t+timedelta(seconds=900))
        self.assertEqual(key,module.immutable_key(**self.k))
        with self.assertRaises(module.OperaRasterError):
            module.authorize_current(self.t,self.t+timedelta(seconds=901))
    def test_invalid_coordinates_and_clock(self):
        for changes in (dict(z=17),dict(x=64),dict(quality_rev="../bad"),dict(source_sha256="a"*63)):
            with self.assertRaises(module.OperaRasterError):
                module.immutable_key(**dict(self.k,**changes))
        with self.assertRaises(module.OperaRasterError):
            module.authorize_current(self.t.replace(tzinfo=None),self.t)
    def test_filename_policy_preserved(self):
        other=Path(__file__).resolve().parents[1]/"custom_components/weather_router/opera_tile_security.py"
        self.assertTrue(other.is_file())

if __name__=="__main__":
    unittest.main()
