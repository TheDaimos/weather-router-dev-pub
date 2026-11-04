"""Inspect the ACTUAL public OPERA HTTP handler's lease ownership.

No HA server required: tests parse the production handler, not a reference
implementation, and validate safety-critical ordering and error paths.
Runtime HTTP/HA integration still requires separate real tests.
"""
import ast
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] /
          "custom_components/weather_router/opera_tile_http.py")


class HttpLeaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.module = ast.parse(cls.source)
        cls.view = next(node for node in cls.module.body
                        if isinstance(node, ast.ClassDef) and node.name == "OperaTileView")
        cls.handler = next(node for node in cls.view.body
                           if isinstance(node, ast.AsyncFunctionDef) and node.name == "get")

    def test_lease_is_acquired_before_render_schedule(self):
        body = ast.get_source_segment(self.source, self.handler)
        self.assertLess(body.index("lease.__enter__()"),
                        body.index("self.hass.async_add_executor_job(work)"))
        self.assertIn("self._frame_cache.lease(", body)

    def test_worker_completion_owns_lease_release(self):
        body = ast.get_source_segment(self.source, self.handler)
        self.assertIn("task.add_done_callback(_worker_done)", body)
        callback = next(node for node in ast.walk(self.handler)
                        if isinstance(node, ast.FunctionDef) and node.name == "_worker_done")
        self.assertIn("lease.__exit__", ast.get_source_segment(self.source, callback))
        self.assertIn("self._limit.release()", ast.get_source_segment(self.source, callback))

    def test_http_timeout_does_not_release_reader(self):
        handler = ast.get_source_segment(self.source, self.handler)
        timeout_part = handler.split("except asyncio.TimeoutError as exc:", 2)[-1]
        self.assertNotIn("lease.__exit__", timeout_part)

    def test_no_cache_fails_closed(self):
        body = ast.get_source_segment(self.source, self.handler)
        self.assertIn("if self._frame_cache is None:", body)
        self.assertIn("raise web.HTTPServiceUnavailable()", body)

    def test_render_worker_reads_pinned_file(self):
        body = ast.get_source_segment(self.source, self.handler)
        self.assertIn("trusted_path=pinned.path", body)
        self.assertIn("verified_frame=pinned", body)


if __name__ == "__main__":
    unittest.main()
