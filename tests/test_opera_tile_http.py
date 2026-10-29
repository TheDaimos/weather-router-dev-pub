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
                                                     True,"EUMETNET CC BY 4.0",quality_verified=True,raster_metadata_verified=True)
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
               is_permitted=allowed,is_enabled=lambda:True,frame_cache=self.cache)

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
        self.assertEqual(len(calls),3)

    def test_permission_revoked_before_cached_response(self):
        # First two decisions allow the work, but the last check must deny
        # a result that may already be cached or computed.
        calls=iter((True,True,False))
        with patch.object(tile_http,"render_verified_cog",return_value=b"PNGdummy"):
            with self.assertRaises(web.HTTPForbidden):
                self.request(view=self.view(lambda _u,_p: next(calls)))

    def test_permission_revoked_in_executor_queue_does_not_start_raster(self):
        """Fail closed after queue wait, without wasting native GDAL work.

        This is an isolated HomeAssistantView stub test, not a HA deployment.
        """
        import threading
        render_started=threading.Event()
        unblock=threading.Event()
        second_user=object()
        first_req=FakeRequest(hass_user=object())
        second_req=FakeRequest(hass_user=second_user)
        checks=[]
        revoked=False
        workers=[]
        second_prechecked=asyncio.Event()

        def permitted(user, product):
            checks.append((user,product))
            if user is second_user:
                second_prechecked.set()
                return not revoked
            return True

        def blocked_render(**kwargs):
            workers.append(kwargs["z"])
            render_started.set()
            if not unblock.wait(timeout=2):
                raise AssertionError("test_worker_not_released")
            return b"PNG dummy"

        gate=tile_http.OperaTileView(
            FakeHass(),
            registry_lookup=lambda product,stamp:self.registration,
            is_permitted=permitted,is_enabled=lambda:True,frame_cache=self.cache,
            max_active=1,wait_seconds=0.5,render_seconds=1.0,
        )
        async def exercise():
            nonlocal revoked
            first=asyncio.create_task(gate.get(
                first_req,"DBZH",self.stamp,"6","33","19"))
            self.assertTrue(await asyncio.to_thread(render_started.wait,1.0))
            second=asyncio.create_task(gate.get(
                second_req,"DBZH",self.stamp,"6","33","19"))
            await asyncio.wait_for(second_prechecked.wait(),timeout=1.0)
            revoked=True
            unblock.set()
            first_reply=await first
            self.assertEqual(first_reply.content_type,"image/png")
            with self.assertRaises(web.HTTPForbidden):
                await second
            # Native executor was never entered on behalf of revoked user.
            self.assertEqual(len(workers),1)
            self.assertGreaterEqual(
                sum(1 for user,_ in checks if user is second_user),2)
            await asyncio.wait_for(gate._limit.acquire(),timeout=1.0)
            gate._limit.release()
        with patch.object(tile_http,"render_verified_cog",side_effect=blocked_render):
            try:
                asyncio.run(exercise())
            finally:
                unblock.set()

    def test_unauthenticated_and_insecure_fail_closed(self):
        with self.assertRaises(web.HTTPUnauthorized):
            self.request(req=FakeRequest())
        req=FakeRequest(hass_user=object())
        req.secure=False
        with self.assertRaises(web.HTTPForbidden):
            self.request(req=req)

    def test_unapproved_quality_or_geometry_rejected_before_rendering(self):
        for quality_ok,geometry_ok in ((False,True),(True,False),(False,False)):
            self.registration=tile_http.TileRegistration(
                self.registration.frame,"dBZ",lambda v:(1,2,3,255),
                True,"EUMETNET CC BY 4.0",
                quality_verified=quality_ok,raster_metadata_verified=geometry_ok)
            with self.assertRaises(web.HTTPForbidden):
                self.request()

    def test_unverified_palette_or_source_rejected(self):
        self.registration=tile_http.TileRegistration(self.registration.frame,"mm/h",
                lambda v:(1,2,3,255),True,"EUMETNET",quality_verified=True,raster_metadata_verified=True)
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
            is_permitted=lambda user,product:True,is_enabled=lambda:True,frame_cache=self.cache,
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

    def test_render_deadline_keeps_native_worker_slot(self):
        """HTTP timeout must not release the slot of a still-running GDAL worker.

        Isolated stub regression only; does not claim real HA thread/CPU budget.
        """
        import threading
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        gate = tile_http.OperaTileView(
            FakeHass(),
            registry_lookup=lambda product,stamp:self.registration,
            is_permitted=lambda user,product:True,
            is_enabled=lambda:True,frame_cache=self.cache,
            max_active=1,wait_seconds=0.02,render_seconds=0.05,
        )
        def blocked_render(**kwargs):
            started.set()
            try:
                if not release.wait(timeout=3.0):
                    raise AssertionError("native_worker_test_not_released")
                return b"PNG dummy"
            finally:
                finished.set()

        async def exercise():
            first = asyncio.create_task(gate.get(
                self.req,"DBZH",self.stamp,"6","33","19"))
            self.assertTrue(await asyncio.to_thread(started.wait,1.0))
            # HTTP deadline expires while the shielded executor still runs.
            with self.assertRaises(web.HTTPServiceUnavailable):
                await first
            self.assertFalse(finished.is_set())
            # Starting a second worker would violate the concurrency budget.
            with self.assertRaises(web.HTTPServiceUnavailable):
                await gate.get(self.req,"DBZH",self.stamp,"6","33","19")
            self.assertFalse(finished.is_set())
            release.set()
            self.assertTrue(await asyncio.to_thread(finished.wait,1.0))
            # The completion callback, not the HTTP timeout, releases the slot.
            await asyncio.wait_for(gate._limit.acquire(),timeout=1.0)
            gate._limit.release()
            response = await gate.get(self.req,"DBZH",self.stamp,"6","33","19")
            self.assertEqual(response.content_type,"image/png")

        with patch.object(tile_http,"render_verified_cog",side_effect=blocked_render):
            try:
                asyncio.run(exercise())
            finally:
                release.set()

    def test_cancellation_keeps_native_worker_slot(self):
        """Client cancellation cannot spawn replacement workers early."""
        import threading
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        gate = tile_http.OperaTileView(
            FakeHass(),
            registry_lookup=lambda product,stamp:self.registration,
            is_permitted=lambda user,product:True,
            is_enabled=lambda:True,frame_cache=self.cache,
            max_active=1,wait_seconds=0.02,render_seconds=1.0,
        )
        def blocked_render(**kwargs):
            started.set()
            try:
                if not release.wait(timeout=3.0):
                    raise AssertionError("native_worker_test_not_released")
                return b"PNG dummy"
            finally:
                finished.set()

        async def exercise():
            first = asyncio.create_task(gate.get(
                self.req,"DBZH",self.stamp,"6","33","19"))
            self.assertTrue(await asyncio.to_thread(started.wait,1.0))
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertFalse(finished.is_set())
            with self.assertRaises(web.HTTPServiceUnavailable):
                await gate.get(self.req,"DBZH",self.stamp,"6","33","19")
            self.assertFalse(finished.is_set())
            release.set()
            self.assertTrue(await asyncio.to_thread(finished.wait,1.0))
            await asyncio.wait_for(gate._limit.acquire(),timeout=1.0)
            gate._limit.release()

        with patch.object(tile_http,"render_verified_cog",side_effect=blocked_render):
            try:
                asyncio.run(exercise())
            finally:
                release.set()

    def test_waiting_queue_limit_and_cancel_cleanup(self):
        """At most one waiter may compete for a busy native GDAL slot."""
        import threading
        started = threading.Event()
        release = threading.Event()
        worker_calls = []

        def blocked_render(**kwargs):
            worker_calls.append(kwargs["z"])
            started.set()
            if not release.wait(timeout=3.0):
                raise AssertionError("worker_release_timeout")
            return b"PNG dummy"

        gate = tile_http.OperaTileView(
            FakeHass(),
            registry_lookup=lambda product, stamp:self.registration,
            is_permitted=lambda user,product:True,
            is_enabled=lambda:True,frame_cache=self.cache,
            max_active=1, max_waiting=1,
            wait_seconds=0.5, render_seconds=1.0,
        )

        async def exercise():
            first = asyncio.create_task(gate.get(
                self.req,"DBZH",self.stamp,"6","33","19"))
            self.assertTrue(await asyncio.to_thread(started.wait,1.0))
            second = asyncio.create_task(gate.get(
                self.req,"DBZH",self.stamp,"6","33","19"))
            for _ in range(100):
                if gate._waiting == 1:
                    break
                await asyncio.sleep(0.005)
            self.assertEqual(gate._waiting,1,"second_request_not_waiting")
            with self.assertRaises(web.HTTPServiceUnavailable):
                await gate.get(self.req,"DBZH",self.stamp,"6","33","19")
            self.assertEqual(len(worker_calls),1)
            self.assertEqual(gate._waiting,1)
            second.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await second
            self.assertEqual(gate._waiting,0,
                             "cancelled_waiter_leaked_a_queue_slot")
            release.set()
            self.assertEqual((await first).content_type,"image/png")
            self.assertEqual((await gate.get(
                self.req,"DBZH",self.stamp,"6","33","19"
            )).content_type,"image/png")
            self.assertEqual(gate._waiting,0)
            self.assertEqual(len(worker_calls),2)

        with patch.object(tile_http,"render_verified_cog",side_effect=blocked_render):
            try:
                asyncio.run(exercise())
            finally:
                release.set()

    def test_wait_timeout_restores_queue_budget(self):
        """An expired waiter frees admission space without freeing worker."""
        import threading
        started = threading.Event()
        release = threading.Event()

        def blocked_render(**kwargs):
            started.set()
            if not release.wait(timeout=3.0):
                raise AssertionError("worker_release_timeout")
            return b"PNG dummy"

        gate = tile_http.OperaTileView(
            FakeHass(),
            registry_lookup=lambda product,stamp:self.registration,
            is_permitted=lambda user,product:True,
            is_enabled=lambda:True,frame_cache=self.cache,
            max_active=1,max_waiting=1,wait_seconds=0.03,
            render_seconds=1.0,
        )
        async def exercise():
            first = asyncio.create_task(gate.get(
                self.req,"DBZH",self.stamp,"6","33","19"))
            self.assertTrue(await asyncio.to_thread(started.wait,1.0))
            for _ in range(2):
                with self.assertRaises(web.HTTPServiceUnavailable):
                    await gate.get(self.req,"DBZH",self.stamp,"6","33","19")
                self.assertEqual(gate._waiting,0)
            release.set()
            self.assertEqual((await first).content_type,"image/png")
            self.assertEqual((await gate.get(
                self.req,"DBZH",self.stamp,"6","33","19"
            )).content_type,"image/png")

        with patch.object(tile_http,"render_verified_cog",side_effect=blocked_render):
            try:
                asyncio.run(exercise())
            finally:
                release.set()

    def test_utc_expiry_during_actual_async_render_is_denied(self):
        """The final authorization rejects pixels after a UTC deadline passes."""
        start = self.t + timedelta(seconds=899)
        expired = self.t + timedelta(seconds=901)
        import threading
        rendering_started = threading.Event()
        allow_finish = threading.Event()
        class FrozenClock:
            value = start
            @classmethod
            def now(cls, tz=None):
                return cls.value
        def blocking_render(**kwargs):
            rendering_started.set()
            if not allow_finish.wait(timeout=3):
                raise AssertionError("test_worker_not_released")
            return b"PNG dummy"
        async def exercise():
            pending = asyncio.create_task(self.view().get(
                self.req, "DBZH", self.stamp, "6", "33", "19"))
            self.assertTrue(await asyncio.to_thread(rendering_started.wait, 1))
            FrozenClock.value = expired
            allow_finish.set()
            with self.assertRaises(web.HTTPForbidden):
                await pending
        with patch.object(tile_http, "render_verified_cog", side_effect=blocking_render), \
             patch.object(tile_http, "datetime", FrozenClock):
            try:
                asyncio.run(exercise())
            finally:
                allow_finish.set()

    def test_http_executor_keeps_evicted_frame_until_worker_finished(self):
        """Run the actual HTTP get path with a real cache lease under eviction."""
        import threading
        started = threading.Event()
        release = threading.Event()
        old_frame = self.registration.frame
        old_path = old_frame.path

        def blocked_render(**kwargs):
            self.assertEqual(kwargs["trusted_path"], old_path)
            started.set()
            if not release.wait(timeout=3):
                raise AssertionError("blocked_http_worker_not_released")
            self.assertTrue(old_path.is_file())
            return b"PNG dummy"

        async def exercise():
            request_task = asyncio.create_task(
                self.view().get(self.req, "DBZH", self.stamp, "6", "33", "19"))
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            # The public cache has max_frames=3 by default. Fourth distinct
            # generation evicts the first from the catalog, but not disk.
            for n in range(4):
                source = Path(self.tmp.name) / ("generation-" + str(n) + ".tiff")
                source.write_bytes(("synthetic-generation-" + str(n)).encode())
                digest = sha256(source.read_bytes()).hexdigest()
                self.cache.admit(source_path=source, product="DBZH",
                                 valid_at=self.t, expected_sha256=digest)
            self.assertIsNone(self.cache.get(product="DBZH",
                                            valid_at=old_frame.valid_at,
                                            digest=old_frame.digest))
            self.assertTrue(old_path.is_file(), "eviction deleted active HTTP reader")
            release.set()
            response = await request_task
            self.assertEqual(response.content_type, "image/png")
            # Done-callback is responsible for final lease release.
            await asyncio.sleep(0)
            self.assertFalse(old_path.exists(), "evicted file not released")

        with patch.object(tile_http, "render_verified_cog", side_effect=blocked_render):
            try:
                asyncio.run(exercise())
            finally:
                release.set()

    def test_invalid_waiting_queue_configuration_fails_closed(self):
        """Prevent accidental unbounded or boolean waiting budgets."""
        for invalid in (0, -1, 65, True, 3.0, "4", None):
            with self.assertRaises(ValueError):
                tile_http.OperaTileView(
                    FakeHass(),registry_lookup=lambda p,s:self.registration,
                    is_permitted=lambda u,p:True,max_waiting=invalid)

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
