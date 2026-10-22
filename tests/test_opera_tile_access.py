"""Pure fail-closed request-policy regression; no Home Assistant installation."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

PATH = (Path(__file__).resolve().parents[1] /
        "custom_components/weather_router/opera_tile_access.py")
spec = importlib.util.spec_from_file_location("opera_tile_access", PATH)
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)

class OperaTileAccessTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,19,13,47,tzinfo=timezone.utc)
        self.args = dict(product="DBZH",stamp="20261019T134000Z",
                         z="6",x="33",y="19",query_present=False)

    def test_exact_and_geo_edge_paths(self):
        self.assertEqual(access.validated_route(**self.args),(6,33,19))
        for x in ("0","63"):
            self.assertEqual(access.validated_route(**dict(self.args,x=x))[1],int(x))

    def test_reject_query_and_untrusted_products(self):
        for changes in (dict(query_present=True),dict(product="RATES"),
                        dict(stamp="../../bad"),dict(stamp="20261019T136000Z"),
                        dict(x="-1"),dict(x="64"),dict(y="99"),
                        dict(y="01"),dict(z="17"),dict(z="true")):
            with self.assertRaises(access.TileAccessDenied):
                access.validated_route(**dict(self.args,**changes))

    def test_reauthorization_requires_session_and_permission(self):
        base=dict(authenticated_user=object(),profile_and_provider_allowed=True,
                  valid_at=self.now-timedelta(seconds=900),now=self.now)
        access.assert_authorized(**base)
        for changes in (dict(authenticated_user=None),
                        dict(profile_and_provider_allowed=False),
                        dict(profile_and_provider_allowed=1),
                        dict(valid_at=self.now-timedelta(seconds=901)),
                        dict(valid_at=self.now+timedelta(seconds=1)),
                        dict(valid_at=self.now.replace(tzinfo=None))):
            with self.assertRaises(access.TileAccessDenied):
                access.assert_authorized(**dict(base,**changes))

    def test_immutable_frame_not_current_permission(self):
        old=self.now-timedelta(seconds=899)
        access.assert_authorized(authenticated_user=object(),profile_and_provider_allowed=True,
                                 valid_at=old,now=self.now)
        with self.assertRaises(access.TileAccessDenied):
            access.assert_authorized(authenticated_user=object(),profile_and_provider_allowed=True,
                                     valid_at=old,now=self.now+timedelta(seconds=2))

if __name__=="__main__":
    unittest.main()
