"""SCI-09: bounded, deterministic tests of installed OPERA production functions.

Synthetic samples are NEVER independent meteorological scientific evidence.
No remote IO, process launch, registrations, secrets or persistent files.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

SUITES = ("decoder", "geometry", "security")
MAX_SECONDS = 7.0


def run_opera_functiontests(suite: str = "all") -> dict:
    if suite not in (*SUITES, "all"):
        raise ValueError("invalid_science_suite")
    started = monotonic()
    checks = []
    selected = SUITES if suite == "all" else (suite,)

    def check(group, name, work):
        t = monotonic()
        if monotonic() - started > MAX_SECONDS:
            checks.append({"group": group, "id": name, "status": "not_executed", "reason": "time_budget"})
            return
        try:
            work()
        except ImportError:
            status, reason = "failed", "dependency_unavailable"
        except AssertionError:
            status, reason = "failed", "assertion_failed"
        except Exception as exc:
            status, reason = "failed", type(exc).__name__[:60]
        else:
            status, reason = "passed", "deterministic_vector"
        checks.append({"group": group, "id": name, "status": status, "reason": reason,
                       "duration_ms": round((monotonic() - t) * 1000, 2)})

    if "decoder" in selected:
        def decoder():
            import numpy as np
            import h5py
            from .opera_odim_pixels import decode_odim_window, OdimWindowError
            with TemporaryDirectory(prefix="wr-opera-sci09-") as temp:
                file = Path(temp) / "synthetic.h5"
                with h5py.File(file, "w") as h:
                    group = h.create_group("dataset1/data1")
                    attrs = group.create_group("what").attrs
                    attrs["quantity"] = "RATE"
                    attrs["gain"] = 0.5
                    attrs["offset"] = -1.
                    attrs["nodata"] = 255.
                    attrs["undetect"] = 254.
                    group.create_dataset("data", data=np.array(
                        [[2., 4., 255.], [254., np.nan, -3.]], dtype=np.float32))
                result = decode_odim_window(
                    file, dataset_path="/dataset1/data1/data", quantity="RATE",
                    x=0, y=0, width=3, height=2)
                assert result.unit == "mm/h" and result.raster_approved is False
                assert result.values[0, 0] == 0 and result.values[0, 1] == 1
                assert result.nodata_mask[0, 2] and result.undetect_mask[1, 0]
                assert result.nan_mask[1, 1] and np.isnan(result.values[1, 1])
                assert result.values[1, 2] < 0
                try:
                    decode_odim_window(file, dataset_path="/dataset1/data1/data",
                                       quantity="RATE", x=0, y=0, width=1025, height=1025)
                except OdimWindowError:
                    pass
                else:
                    raise AssertionError("window_limit_not_enforced")
        check("decoder", "odim_calibration_special_values_bounds_zero", decoder)

    if "geometry" in selected:
        def geometry():
            from .opera_odim_reconstruction import ReconstructedGrid
            from .opera_odim_tile import decode_rate_tile, OperaTileError
            from pyproj import Transformer, CRS
            grid = ReconstructedGrid((-2000., -2000., 2000., 2000.),
                                     (1000., 1000.), 0., 4, 4, True)
            assert grid.center(0, 0) == (-1500., 1500.)
            assert grid.center(3, 3) == (1500., -1500.)
            projection = "+proj=laea +lat_0=0 +lon_0=0 +datum=WGS84 +units=m +no_defs"
            transformer = Transformer.from_crs(CRS.from_epsg(4326),
                                                CRS.from_user_input(projection), always_xy=True)
            x, y = transformer.transform(0., 0.)
            assert abs(x) < 1e-6 and abs(y) < 1e-6
            try:
                decode_rate_tile(Path("/nonexistent"), grid=grid, projection=projection,
                                 dataset_path="/dataset1/data1/data", x=0, y=0, z=0,
                                 orientation_verified=False)
            except OperaTileError as exc:
                assert str(exc) == "orientation_not_approved"
            else:
                raise AssertionError("orientation_gate_missing")
        check("geometry", "laea_pixel_centers_mercator_origin_orientation_gate", geometry)

    if "security" in selected:
        def security():
            from .opera_tile_access import assert_authorized, validated_route, TileAccessDenied
            from .opera_v2_admission import RateAdmission, explicit_rate_response
            instant = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
            assert validated_route(product="RATE", stamp="20261026T100000Z",
                                   z="0", x="0", y="0", query_present=False) == (0, 0, 0)
            for when in (instant - timedelta(seconds=1), instant + timedelta(seconds=901)):
                try:
                    assert_authorized(authenticated_user=True, profile_and_provider_allowed=True,
                                      valid_at=instant, now=when)
                except TileAccessDenied:
                    pass
                else:
                    raise AssertionError("time_gate_missing")
            assert_authorized(authenticated_user=True, profile_and_provider_allowed=True,
                              valid_at=instant, now=instant + timedelta(seconds=900)) is None
            try:
                assert_authorized(authenticated_user=None, profile_and_provider_allowed=True,
                                  valid_at=instant, now=instant)
            except TileAccessDenied:
                pass
            else:
                raise AssertionError("missing_auth_gate")
            assert RateAdmission().ready is False
            reply = explicit_rate_response(
                enabled=True, correlation_id="sci09", capability="weather.radar.precipitation",
                source_request={"provider_id": "opera", "product_id": "RATE"})
            assert reply["raster_approved"] is False
            assert reply["layers"] == [] and reply["tile_urls"] == []
            assert reply["status"] == "active_blocked"
        check("security", "utc_auth_admission_v2_block", security)

    return {
        "schema": "weather_router.opera.functiontests.v1",
        "suite": suite,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "duration_ms": round((monotonic()-started)*1000, 2),
        "checks": checks,
        "status": ("passed" if checks and all(c["status"] == "passed" for c in checks)
                   else "failed"),
        "not_executed": [
            "independent_original_19_pairs", "scientific_quality_channel",
            "reference_rgba_palette", "actual_http_request",
            "consumer_v2_end_to_end", "registration_revocation_race",
            "ha_dev_real_acceptance",
        ],
        "test_vectors": "synthetic_only",
        "scientific_raster_approved": False,
        "dra_candidate_approved": False,
    }
