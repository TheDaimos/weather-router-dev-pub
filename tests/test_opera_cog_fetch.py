"""Offline bounded OPERA HTTPS fetch tests; never contact real CloudFerro."""
from datetime import datetime, timedelta, timezone
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]/"custom_components/weather_router"
PKG="_wr_opera_fetch_test"
if PKG not in sys.modules:
    obj=types.ModuleType(PKG)
    obj.__path__=[str(ROOT)]
    sys.modules[PKG]=obj

def load(name):
    key=PKG+"."+name
    if key not in sys.modules:
        spec=importlib.util.spec_from_file_location(key,ROOT/(name+".py"))
        mod=importlib.util.module_from_spec(spec)
        sys.modules[key]=mod
        spec.loader.exec_module(mod)
    return sys.modules[key]
load("opera_tile_security")
cachelib=load("opera_frame_cache")
fetcher=load("opera_cog_fetch")

TIFF=b"II*\x00" + b"\x01\x00\x00\x00" + b"not_real_georeferenced_content"

class Content:
    def __init__(self,body):
        self.body=body
    async def iter_chunked(self,n):
        for i in range(0,len(self.body),n):
            yield self.body[i:i+n]

class Response:
    def __init__(self,body=TIFF,status=200,kind="binary/octet-stream",length=None):
        self.status=status
        self.headers={"Content-Type":kind,"Content-Length":str(len(body) if length is None else length)}
        self.content=Content(body)
    async def __aenter__(self):
        return self
    async def __aexit__(self,*args):
        return False

class Session:
    def __init__(self,response):
        self.response=response
        self.requests=[]
    def get(self,url,**kwargs):
        self.requests.append((url,kwargs))
        return self.response

class Hass:
    def async_add_executor_job(self,work):
        return asyncio.get_running_loop().run_in_executor(None,work)

class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.at=datetime(2026,10,19,13,40,tzinfo=timezone.utc)
        self.now=self.at+timedelta(minutes=5)
        self.file="OPERA@20261019T1340@0@DBZH.tiff"
        self.cache=cachelib.ImmutableFrameCache(max_frames=2)
    async def asyncTearDown(self):
        self.cache.close()

    def create(self, response=None, clock=None):
        self.session=Session(response or Response())
        return fetcher.OperaCogFetch(
            hass=Hass(),session=self.session,cache=self.cache,
            clock=clock or (lambda:self.now),
        )

    async def test_fixed_public_host_and_executor_only_admission(self):
        client=self.create()
        frame=await client.fetch(filename=self.file,valid_at=self.at,now=self.now)
        self.assertEqual(frame.product,"DBZH")
        self.assertEqual(frame.path.read_bytes(),TIFF)
        self.assertEqual(self.cache.hash_operations,1)
        url,kwargs=self.session.requests[0]
        self.assertEqual(url,
            "https://s3.waw3-1.cloudferro.com/openradar-24h/2026/10/19/OPERA/COMP/"+self.file)
        self.assertEqual(kwargs["allow_redirects"],False)
        self.assertTrue(kwargs["ssl"])
        self.assertEqual(kwargs["headers"]["Accept-Encoding"],"identity")

    async def test_bad_product_path_age_and_time_rejected_without_network(self):
        for name,clock in (
            ("../../bad.tiff",self.now),
            ("OPERA@20261019T1340@0@ACRR.tiff",self.now),
            (self.file,self.at+timedelta(seconds=901)),
        ):
            client=self.create()
            with self.assertRaises(fetcher.OperaDownloadError):
                await client.fetch(filename=name,valid_at=self.at,now=clock)
            self.assertEqual(self.session.requests,[])

    async def test_bounded_network_fail_closed(self):
        for response in (
            Response(status=302),
            Response(kind="text/html"),
            Response(length=20*1024*1024),
            Response(length=len(TIFF)+1),
            Response(body=b"NOPE"+TIFF),
        ):
            with self.subTest(status=response.status,kind=response.headers["Content-Type"]):
                client=self.create(response=response)
                with self.assertRaises(fetcher.OperaDownloadError):
                    await client.fetch(filename=self.file,valid_at=self.at,now=self.now)
                self.assertEqual(self.cache.hash_operations,0)

    async def test_clock_reevaluated_after_network(self):
        client=self.create(clock=lambda: self.at+timedelta(seconds=901))
        with self.assertRaises(ValueError):
            await client.fetch(filename=self.file,valid_at=self.at,now=self.now)
        self.assertEqual(self.cache.hash_operations,0)

    async def test_rate_is_not_dbzh_and_frame_revision_is_cached(self):
        rate_at=datetime(2026,10,19,13,15,tzinfo=timezone.utc)
        client=self.create(clock=lambda:rate_at+timedelta(minutes=5))
        filename="OPERA@20261019T1315@0@RATE.tiff"
        frame=await client.fetch(filename=filename,valid_at=rate_at,
                                 now=rate_at+timedelta(minutes=5))
        self.assertEqual(frame.product,"RATE")
        self.assertNotEqual(frame.product,"DBZH")

if __name__=="__main__":
    unittest.main()
