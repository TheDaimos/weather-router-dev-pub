"""Dormant HA view: authentication and authorization gates under isolated stubs.

This is NOT a live Home Assistant / browser acceptance test.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/"custom_components/weather_router"
PKG="_wr_opera_http_staging"
pkg=types.ModuleType(PKG)
pkg.__path__=[str(ROOT)]
sys.modules[PKG]=pkg

# Only the HomeAssistantView class is stubbed; aiohttp is real and must import.
ha=types.ModuleType("homeassistant")
ha.__path__=[]
components=types.ModuleType("homeassistant.components")
components.__path__=[]
http=types.ModuleType("homeassistant.components.http")
class HomeAssistantView:
    pass
http.HomeAssistantView=HomeAssistantView

def load(name):
    full=PKG+"."+name
    if full not in sys.modules:
        spec=importlib.util.spec_from_file_location(full,ROOT/(name+".py"))
        module=importlib.util.module_from_spec(spec)
        sys.modules[full]=module
        spec.loader.exec_module(module)
    return sys.modules[full]

frame_lib=load("opera_frame_cache")
load("opera_tile_access")
load("opera_cog_tiles")

# This stub scope remains deliberately limited to this module's loading.
old_modules={name:sys.modules.get(name) for name in
             ("homeassistant","homeassistant.components","homeassistant.components.http")}
sys.modules["homeassistant"]=ha
sys.modules["homeassistant.components"]=components
sys.modules["homeassistant.components.http"]=http
try:
    tile_http=load("opera_tile_http")
finally:
    for name,previous in old_modules.items():
        if previous is None:
            sys.modules.pop(name,None)
        else:
            sys.modules[name]=previous

from aiohttp import web

class FakeRequest(dict):
    secure=True
    query={}

class FakeHass:
    def async_add_executor_job(self, func):
        return asyncio.get_running_loop().run_in_executor(None,func)

class TileRouteTests(unittest.TestCase):
    def setUp(self):
        self.cache=frame_lib.ImmutableFrameCache()
        self.t=datetime.now(timezone.utc).replace(microsecond=0)
        self.tmp=tempfile.TemporaryDirectory()
        source=Path(self.tmp.name)/"trusted.tiff"
        source.write_bytes(b"test only")
        digest=sha256(source.read_bytes()).hexdigest()
        frame=self.cache.admit(source_path=source,product="DBZH",
                               valid_at=self.t,expected_sha256=digest)
        self.registration=tile_http.TileRegistration(frame,"dBZ",lambda v:(1,2,3,255),
                                                     True,"EUMETNET CC BY 4.0")
        self.stamp=self.t.strftime("%Y%m%dT%H%M%SZ")
        self.req=FakeRequest(hass_user=object())
        self.calls=0

    def tearDown(self):
        self.cache.close()
        self.tmp.cleanup()

    def view(self,allowed=None):
        allowed=allowed or (lambda _u,_p: True)
        return tile_http.OperaTileView(FakeHass(),
               registry_lookup=lambda product,stamp: self.registration,
               is_permitted=allowed,is_enabled=lambda:True)

    def request(self,view=None,req=None):
        view=view or self.view()
        req=self.req if req is None else req
        return asyncio.run(view.get(req,"DBZH",self.stamp,"6","33","19"))

    def test_authenticated_endpoint_returns_no_store_png_and_two_checks(self):
        calls=[]
        def allow(user,product):
            calls.append((user,product))
            return True
        with patch.object(tile_http,"render_verified_cog",return_value=b"\x89PNG\r\n\x1a\nabc"):
            response=self.request(view=self.view(allow))
        self.assertEqual(response.content_type,"image/png")
        self.assertIn("no-store",response.headers["Cache-Control"])
        self.assertEqual(len(calls),2)

    def test_permission_revoked_before_cached_response(self):
        calls=iter((True,False))
        with patch.object(tile_http,"render_verified_cog",return_value=b"PNGdummy"):
            with self.assertRaises(web.HTTPForbidden):
                self.request(view=self.view(lambda _u,_p: next(calls)))

    def test_unauthenticated_and_insecure_fail_closed(self):
        with self.assertRaises(web.HTTPUnauthorized):
            self.request(req=FakeRequest())
        req=FakeRequest(hass_user=object())
        req.secure=False
        with self.assertRaises(web.HTTPForbidden):
            self.request(req=req)

    def test_unverified_palette_or_source_rejected(self):
        self.registration=tile_http.TileRegistration(self.registration.frame,"mm/h",
                lambda v:(1,2,3,255),True,"EUMETNET")
        with self.assertRaises(web.HTTPForbidden):
            self.request()

    def test_untrusted_query_rejected_even_with_authenticated_user(self):
        req=FakeRequest(hass_user=object())
        req.query={"authSig":"unacceptable"}
        with self.assertRaises(web.HTTPForbidden):
            self.request(req=req)

    def test_executor_concurrency_budget_rejects_excess(self):
        import time
        # A long-running worker must keep its slot; requests cannot spawn
        # unbounded parallel GDAL work while earlier jobs are incomplete.
        gate=tile_http.OperaTileView(FakeHass(),
            registry_lookup=lambda product,stamp:self.registration,
            is_permitted=lambda user,product:True,is_enabled=lambda:True,
            max_active=1,wait_seconds=0.02,render_seconds=1.0)
        def slow_render(**kwargs):
            time.sleep(0.25)
            return b"PNG dummy"
        async def exercise():
            first=asyncio.create_task(gate.get(
                self.req,"DBZH",self.stamp,"6","33","19"))
            await asyncio.sleep(0.05)
            with self.assertRaises(web.HTTPServiceUnavailable):
                await gate.get(self.req,"DBZH",self.stamp,"6","33","19")
            response=await first
            self.assertEqual(response.content_type,"image/png")
        with patch.object(tile_http,"render_verified_cog",side_effect=slow_render):
            asyncio.run(exercise())

    def test_no_public_proxy_and_disabled_by_default(self):
        self.assertTrue(tile_http.OperaTileView.requires_auth)
        self.assertNotIn("token",tile_http.OperaTileView.url)
        self.assertFalse("s3" in tile_http.OperaTileView.url)
        view=tile_http.OperaTileView(FakeHass(),registry_lookup=lambda p,s:self.registration,
                                     is_permitted=lambda u,p:True)
        with self.assertRaises(web.HTTPForbidden):
            self.request(view=view)

if __name__=="__main__":
    unittest.main()
