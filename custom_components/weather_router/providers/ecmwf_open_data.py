"""ECMWF Open Data provider descriptor and lightweight live probe.

ECMWF Open Data is distributed as GRIB2. WeatherRouter deliberately does not invent
point values without an explicit GRIB decoding contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_PORTAL = "https://data.ecmwf.int/forecasts/"
_PROVIDER_REVISION = "wr-0.10.78-data-file-resolver-2"
_MODEL_BY_CAPABILITY = {
    "ifs_open_grib": "ifs",
    "aifs_open_grib": "aifs-single",
}
_PROBE_HOURS = (18, 12, 6, 0)
_MAX_PROBE_RUNS = 10
_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}

_CAPABILITIES = (
    CapabilityInfo(
        id="ifs_open_grib",
        name="IFS Open Data · GRIB2",
        unit=None,
        source_class="model",
        render_mode="data_file",
        description="Offener globaler IFS-Datensatz von ECMWF im GRIB2-Format.",
        coverage="Global",
        temporal_resolution="00/06/12/18 UTC · Forecast-Schritte produktabhängig",
        strengths=("offizielle ECMWF-Quelle", "globales numerisches Vorhersagemodell"),
        limitations=(
            "GRIB2 benötigt einen eigenen Decoder",
            "noch keine direkte Punktdarstellung im WeatherRouter-Lab",
        ),
        documentation_url="https://www.ecmwf.int/en/forecasts/datasets/open-data",
    ),
    CapabilityInfo(
        id="aifs_open_grib",
        name="AIFS Open Data · GRIB2",
        unit=None,
        source_class="model",
        render_mode="data_file",
        description="Offene ECMWF-AIFS-Single-Daten im GRIB2-Format.",
        coverage="Global",
        temporal_resolution="00/06/12/18 UTC · 6-stündliche Forecast-Schritte",
        strengths=("offizielle ECMWF-Quelle", "KI-basiertes globales Forecast-Modell"),
        limitations=(
            "GRIB2 benötigt einen eigenen Decoder",
            "noch keine direkte Punktdarstellung im WeatherRouter-Lab",
        ),
        documentation_url="https://www.ecmwf.int/en/forecasts/datasets/open-data",
    ),

)


def _candidate_runs(now: datetime) -> list[datetime]:
    """Return recent ECMWF cycle candidates newest first."""
    current = now.astimezone(timezone.utc)
    candidates: list[datetime] = []
    for day_offset in range(3):
        day = (current - timedelta(days=day_offset)).date()
        for hour in _PROBE_HOURS:
            candidate = datetime(
                day.year,
                day.month,
                day.day,
                hour,
                tzinfo=timezone.utc,
            )
            if candidate <= current:
                candidates.append(candidate)
    candidates.sort(reverse=True)
    return candidates[:_MAX_PROBE_RUNS]


def _run_paths(model: str, run: datetime, *, step: int = 0) -> tuple[str, str, str]:
    """Return relative index/GRIB paths and display run identifier."""
    date_text = run.strftime("%Y%m%d")
    hour_text = run.strftime("%H")
    if type(step) is not int or step < 0 or step > 144 or step % 3:
        raise ValueError("ecmwf_mslp_invalid_step")
    stem = f"{date_text}{hour_text}0000-{step}h-oper-fc"
    base = f"{date_text}/{hour_text}z/{model}/0p25/oper/{stem}"
    return f"{base}.index", f"{base}.grib2", f"{date_text}T{hour_text}Z"


async def _probe_model(
    session: Any,
    model: str,
    now: datetime,
) -> dict[str, Any]:
    """Find a recent run and verify both its index and GRIB magic bytes."""
    attempted: list[dict[str, Any]] = []

    for run in _candidate_runs(now):
        index_path, grib_path, run_id = _run_paths(model, run)
        index_url = f"{_PORTAL}{index_path}"

        try:
            async with session.get(
                index_url,
                headers={"Accept": "application/x-ndjson,text/plain,*/*"},
                timeout=15,
            ) as response:
                index_status = response.status
                if index_status == 404:
                    attempted.append({"run": run_id, "index_status": 404})
                    continue
                if index_status in _RETRYABLE_HTTP_STATUS:
                    attempted.append(
                        {
                            "run": run_id,
                            "index_status": index_status,
                            "stage": "index_probe",
                            "transient": True,
                        }
                    )
                    continue
                response.raise_for_status()
                first_line = await response.content.readline()
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "stage": "index_probe",
                "model": model,
                "run": run_id,
                "error": {"type": type(err).__name__, "message": str(err)},
                "attempted": attempted,
            }

        try:
            index_record = json.loads(first_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            return {
                "ok": False,
                "stage": "index_parse",
                "model": model,
                "run": run_id,
                "index_status": index_status,
                "error": {"type": type(err).__name__, "message": str(err)},
            }

        if not isinstance(index_record, dict) or not {
            "param",
            "_offset",
            "_length",
        }.issubset(index_record):
            return {
                "ok": False,
                "stage": "index_contract",
                "model": model,
                "run": run_id,
                "index_status": index_status,
                "reason": "ECMWF index first record lacks expected metadata",
            }

        grib_url = f"{_PORTAL}{grib_path}"
        try:
            async with session.get(
                grib_url,
                headers={
                    "Accept": "application/octet-stream",
                    "Range": "bytes=0-15",
                },
                timeout=15,
            ) as response:
                grib_status = response.status
                if grib_status == 404 or grib_status in _RETRYABLE_HTTP_STATUS:
                    attempted.append(
                        {
                            "run": run_id,
                            "index_status": index_status,
                            "grib_status": grib_status,
                            "stage": "grib_probe",
                            "transient": True,
                        }
                    )
                    continue
                response.raise_for_status()
                magic = await response.content.read(4)
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "stage": "grib_probe",
                "model": model,
                "run": run_id,
                "index_status": index_status,
                "error": {"type": type(err).__name__, "message": str(err)},
            }

        if magic != b"GRIB":
            return {
                "ok": False,
                "stage": "grib_signature",
                "model": model,
                "run": run_id,
                "index_status": index_status,
                "grib_status": grib_status,
                "signature": magic.hex(),
            }

        return {
            "ok": True,
            "model": model,
            "run": run_id,
            "index_status": index_status,
            "grib_status": grib_status,
            "index_first_param": index_record.get("param"),
            "index_has_byte_range": True,
            "grib_signature": "GRIB",
            "index_path": index_path,
            "grib_path": grib_path,
        }

    return {
        "ok": False,
        "stage": "recent_run_discovery",
        "model": model,
        "reason": (
            "No recent ECMWF Open Data run could be verified in the probe window"
        ),
        "transient_rate_limit_seen": any(
            item.get("index_status") == 429 or item.get("grib_status") == 429
            for item in attempted
        ),
        "attempted": attempted,
    }



_MSL_INDEX_BUDGET = 2_000_000
_MSL_FIELD_BUDGET = 8_000_000


def _mslp_index_record(payload: bytes, *, step: int = 0) -> dict[str, int]:
    """Select precisely one surface MSL pressure GRIB message, fail closed.

    ECMWF's .index is NDJSON. Offset/length describe a *single* GRIB message
    inside the unmodified official data file, not a separately computed field.
    """
    if not payload or len(payload) > _MSL_INDEX_BUDGET:
        raise ValueError("ecmwf_mslp_index_budget")
    matches = []
    try:
        lines = payload.splitlines()
        if len(lines) > 10000:
            raise ValueError("ecmwf_mslp_index_budget")
        for line in lines:
            if len(line) > 32768:
                raise ValueError("ecmwf_mslp_index_record_budget")
            record = json.loads(line)
            if not isinstance(record, dict) or record.get("param") != "msl":
                continue
            # The IFS surface-pressure reduction must be the published
            # MSL field, not raw surface pressure or an arbitrary level.
            if record.get("levtype") != "sfc":
                continue
            offset, length = record.get("_offset"), record.get("_length")
            if (type(offset) is not int or type(length) is not int
                    or offset < 0 or not 16 <= length <= _MSL_FIELD_BUDGET):
                raise ValueError("ecmwf_mslp_invalid_byte_range")
            if str(record.get("step", "")) not in (str(step), f"{step}.0"):
                continue
            matches.append({"offset": offset, "length": length})
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("ecmwf_mslp_invalid_index") from error
    if len(matches) != 1:
        raise ValueError("ecmwf_mslp_missing_or_ambiguous_field")
    return matches[0]


def _mslp_nearby_steps(run: datetime, now: datetime) -> tuple[int, ...]:
    """Real IFS 3-hour forecast step cadence, nearest valid time first.

    The official 0p25 IFS oper stream publishes step 0..144 at 3h spacing.
    The source may be posted hours after model initialization: step-0 is not
    automatically the currently valid field.
    """
    lead = max(0, min(144, (now - run).total_seconds() / 3600))
    floor_step = min(144, max(0, int(lead // 3) * 3))
    ceil_step = min(144, floor_step + 3)
    steps = sorted({floor_step, ceil_step}, key=lambda x: (abs(x - lead), x))
    return tuple(steps)


async def _probe_mslp_field(session, now: datetime) -> dict[str, Any]:
    """Probe official 0p25 IFS MSLP with bounded index+range verification.

    Published GRIB files are indexed per run and forecast step. A request
    verifies a single indexed field with HTTP 206 and a matching byte range;
    a missing/late run is never represented as a successful source.
    """
    attempted = []
    for run in _candidate_runs(now)[:4]:
        for step in _mslp_nearby_steps(run, now):
            index_path, grib_path, run_id = _run_paths("ifs", run, step=step)
            try:
                async with session.get(
                    _PORTAL + index_path,
                    headers={"Accept": "application/x-ndjson,text/plain,*/*"},
                    timeout=12, allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        attempted.append({"run": run_id, "step": step, "stage": "index",
                                          "http_status": response.status})
                        continue
                    if response.content_length and response.content_length > _MSL_INDEX_BUDGET:
                        attempted.append({"run": run_id, "step": step, "stage": "index_budget"})
                        continue
                    index_data = await response.content.read(_MSL_INDEX_BUDGET + 1)
                field = _mslp_index_record(index_data, step=step)
                start = field["offset"]
                end = start + 15
                async with session.get(
                    _PORTAL + grib_path,
                    headers={"Accept": "application/octet-stream", "Range": f"bytes={start}-{end}"},
                    timeout=12, allow_redirects=False,
                ) as response:
                    if response.status != 206:
                        attempted.append({"run": run_id, "step": step, "stage": "range",
                                          "http_status": response.status})
                        continue
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {start}-{end}/"):
                        attempted.append({"run": run_id, "step": step, "stage": "range_mismatch"})
                        continue
                    sample = await response.content.read(16)
                if len(sample) != 16 or sample[:4] != b"GRIB":
                    attempted.append({"run": run_id, "step": step, "stage": "grib_signature"})
                    continue
                valid_at = run + timedelta(hours=step)
                if valid_at + timedelta(hours=3) <= now:
                    attempted.append({"run": run_id, "step": step, "stage": "forecast_expired"})
                    continue
                return {"ok": True, "model": "ifs", "run": run_id, "step": step,
                        "valid_at": valid_at.isoformat().replace("+00:00", "Z"),
                        "index_path": index_path, "grib_path": grib_path,
                        "parameter": "msl", "level_type": "sfc",
                        "range_start": start, "range_length": field["length"],
                        "grib_signature": "GRIB"}
            except (ValueError, TimeoutError, OSError) as error:
                attempted.append({"run": run_id, "step": step,
                                  "stage": "probe_exception", "type": type(error).__name__})
                continue
    return {"ok": False, "stage": "mslp_source_probe",
            "reason": "no_live_verified_ifs_mslp_byte_range",
            "attempted": attempted[:8]}


class EcmwfOpenDataProvider:
    """Expose ECMWF Open Data as a truthful data-file capability."""

    id = "ecmwf_open_data"
    name = "ECMWF Open Data"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def synoptic_isobars_info(self) -> dict[str, Any]:
        """Independent global ECMWF IFS synoptic MSLP contour source."""
        return {"capability": "weather.synoptic.isobars",
                "coverage": "global", "data_kind": "derived_numeric_grid",
                "synoptic_priority": 25, "model": "ECMWF IFS", "unit": "hPa"}

    async def async_fetch_synoptic_isobars(
        self, hass: HomeAssistant, bbox: dict,
    ) -> dict:
        from ..synoptic_ecmwf import async_fetch_isobars
        return await async_fetch_isobars(hass, bbox)

    def synoptic_pressure_source_info(self) -> dict[str, Any]:
        """Optional V2 global IFS-MSLP file, no numeric decoder claimed."""
        return {"capability": "weather.synoptic.pressure_source",
                "coverage": "global", "data_kind": "indexed_grib2_message"}

    async def async_fetch_synoptic_pressure_source(
        self, hass: HomeAssistant, bbox: dict,
    ) -> dict[str, Any]:
        """Resolve a verified MSL message byte range without fetching GRIB2 fields."""
        from ..wind_field_source import plan_subset
        plan_subset(bbox)
        from ..diagnostic_center import observed_clientsession
        session = observed_clientsession(hass, self.id, async_get_clientsession(hass))
        result = await _probe_mslp_field(session, datetime.now(timezone.utc))
        if result.get("ok") is not True:
            raise ValueError("synoptic_ecmwf_mslp_source_unavailable")
        reference = datetime.strptime(result["run"], "%Y%m%dT%HZ").replace(
            tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        # The index-selected forecast step, not the model run, is valid_at.
        valid = datetime.fromisoformat(result["valid_at"].replace("Z", "+00:00"))
        forecast_end = valid + timedelta(hours=3)
        if valid < reference or forecast_end <= now:
            raise ValueError("synoptic_ecmwf_mslp_stale")
        return {
            "capability": "weather.synoptic.pressure_source",
            "id": f"ifs-msl-{result['run']}-step{result['step']}", "kind": "model_data_file",
            "model": "ECMWF IFS", "unit": "Pa",
            "model_run": reference.isoformat().replace("+00:00", "Z"),
            "valid_at": valid.isoformat().replace("+00:00", "Z"),
            "valid_until": forecast_end.isoformat().replace("+00:00", "Z"),
            "refresh_after_seconds": 240,
            "data_file": {
                "format": "GRIB2", "parameter": "msl", "level_type": "sfc",
                "url": _PORTAL+result["grib_path"],
                "forecast_step_hours": result["step"],
                "byte_offset": result["range_start"],
                "byte_length": result["range_length"],
                "signature_verified": True,
                "decoded": False,
            },
            "coverage": {"type": "global", "crs": "EPSG:4326"},
            "provenance": {"provider_id": self.id, "model": "IFS",
                           "source": "ECMWF Open Data index + GRIB2 range",
                           "attribution": "ECMWF Open Data · CC BY 4.0",
                           "data_origin": "model",
                           "measurement_method": "nwp_indexed_grib2_file"},
        }



    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "ECMWF Open Data stellt einen freien Teil der globalen IFS- und AIFS-"
                "Vorhersagedaten bereit. Die Originaldaten liegen als GRIB2 vor."
            ),
            coverage="Global",
            strengths=(
                "offizielle ECMWF-Quelle",
                "globale IFS-/AIFS-Vorhersagen",
                "CC BY 4.0 Open Data",
            ),
            limitations=(
                "kein Punkt-JSON-Endpunkt",
                "WeatherRouter benötigt vor Punktwerten einen generischen GRIB2-Decodervertrag",
            ),
            documentation_url="https://www.ecmwf.int/en/forecasts/datasets/open-data",
            attribution="ECMWF Open Data · CC BY 4.0",
            services=(
                {
                    "name": "IFS Open Data",
                    "status": "integriert als Datenquelle",
                    "note": "GRIB2 · reale Index-/GRIB-Signaturdiagnose · noch ohne Punktdecoder",
                },
                {
                    "name": "AIFS Single Open Data",
                    "status": "integriert als Datenquelle",
                    "note": "GRIB2 · reale Index-/GRIB-Signaturdiagnose · noch ohne Punktdecoder",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="forecast_data_files",
                scheme="https",
                host="data.ecmwf.int",
                port=443,
                target_type="data_file",
                required=True,
                capabilities=tuple(item.id for item in _CAPABILITIES),
                note="ECMWF Open Data /forecasts · GRIB2 + JSON-lines index files.",
            ),
        )

    async def async_get_data_file(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Resolve the newest verified ECMWF Open Data GRIB2 file."""
        if capability_id not in _MODEL_BY_CAPABILITY:
            raise ValueError(f"Unsupported ECMWF capability: {capability_id}")

        model = _MODEL_BY_CAPABILITY[capability_id]
        from ..diagnostic_center import observed_clientsession
        result = await _probe_model(
            observed_clientsession(hass, self.id, async_get_clientsession(hass)),
            model, datetime.now(timezone.utc))
        if result.get("ok") is not True:
            raise ValueError(
                f"ECMWF Open Data file unavailable for {capability_id}: "
                f"{result.get('stage') or result.get('reason') or 'unknown'}"
            )

        grib_path = result.get("grib_path")
        run_id = result.get("run")
        if not isinstance(grib_path, str) or not grib_path:
            raise ValueError("ECMWF probe returned no GRIB path")

        data_time = None
        if isinstance(run_id, str):
            try:
                data_time = datetime.strptime(
                    run_id,
                    "%Y%m%dT%HZ",
                ).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                data_time = None

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "model",
            "render_mode": "data_file",
            "format": "GRIB2",
            "content_type": "application/octet-stream",
            "transport": "direct",
            "url": f"{_PORTAL}{grib_path}",
            # Modell-Laufzeit ist eine Vorhersage-Referenzzeit und niemals
            # eine aktuelle Beobachtung oder ein Gültigkeitszeitpunkt.
            "data_time": None,
            "forecast_reference_time": data_time,
            "attribution": "ECMWF Open Data · CC BY 4.0",
            "metadata_url": "https://www.ecmwf.int/en/forecasts/datasets/open-data",
            "provider_metadata": {
                "model": model,
                "run": run_id,
                "grib_signature": result.get("grib_signature"),
                "index_path": result.get("index_path"),
                "point_decoder_available": False,
            },
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        requested = (
            [capability_id]
            if capability_id is not None
            else list(_MODEL_BY_CAPABILITY)
        )
        unsupported = [
            item for item in requested if item not in _MODEL_BY_CAPABILITY
        ]
        if unsupported:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
                "unsupported": unsupported,
            }

        from ..diagnostic_center import observed_clientsession
        session = observed_clientsession(hass, "ecmwf_open_data", async_get_clientsession(hass))
        now = datetime.now(timezone.utc)
        results: dict[str, dict[str, Any]] = {}
        for item in requested:
            results[item] = await _probe_model(
                session, _MODEL_BY_CAPABILITY[item], now)

        return {
            "ok": all(result.get("ok") is True for result in results.values()),
            "stage": "open_data_file_probe",
            "provider_revision": _PROVIDER_REVISION,
            "portal": _PORTAL,
            "format": "GRIB2",
            "decoder_status": "not_implemented",
            "results": results,
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        capability = next((item for item in _CAPABILITIES if item.id == capability_id), None)
        if capability is None:
            raise ValueError(f"Unsupported ECMWF capability: {capability_id}")

        model = _MODEL_BY_CAPABILITY[capability_id]
        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "capability_name": capability.name,
            "source_class": "model",
            "render_mode": "data_file",
            "attribution": "ECMWF Open Data · CC BY 4.0",
            "network_hosts": ["data.ecmwf.int"],
            "data_file": {
                "model": model,
                "format": "GRIB2",
                "catalog_url": _PORTAL,
                "point_decoder_available": False,
                "note": (
                    "WeatherRouter exposes the official source without pretending "
                    "to decode GRIB2 until a generic decoder contract exists."
                ),
            },
        }
