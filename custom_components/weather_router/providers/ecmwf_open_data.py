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


def _run_paths(model: str, run: datetime) -> tuple[str, str, str]:
    """Return relative index/GRIB paths and display run identifier."""
    date_text = run.strftime("%Y%m%d")
    hour_text = run.strftime("%H")
    stem = f"{date_text}{hour_text}0000-0h-oper-fc"
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


class EcmwfOpenDataProvider:
    """Expose ECMWF Open Data as a truthful data-file capability."""

    id = "ecmwf_open_data"
    name = "ECMWF Open Data"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

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
        result = await _probe_model(
            async_get_clientsession(hass),
            model,
            datetime.now(timezone.utc),
        )
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
            "data_time": data_time,
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

        session = async_get_clientsession(hass)
        now = datetime.now(timezone.utc)
        results: dict[str, dict[str, Any]] = {}
        for item in requested:
            results[item] = await _probe_model(
                session,
                _MODEL_BY_CAPABILITY[item],
                now,
            )

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
