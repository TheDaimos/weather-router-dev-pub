"""Official NOAA GOES-R Geostationary Lightning Mapper data files via NODD."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any
from urllib.parse import quote
import xml.etree.ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_PROVIDER_REVISION = "wr-0.10.76-noaa-glm-1"
_PRODUCT_PREFIX = "GLM-L2-LCFA"
_KEY_TIME_RE = re.compile(r"_s(?P<year>\d{4})(?P<doy>\d{3})(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})")
_SATELLITES = {
    "glm_east_lcfa": {
        "name": "NOAA GOES-19 GLM · East · LCFA",
        "bucket": "noaa-goes19",
        "satellite": "GOES-19",
        "coverage": "Americas / Atlantic / adjacent oceans · GOES-East",
    },
    "glm_west_lcfa": {
        "name": "NOAA GOES-18 GLM · West · LCFA",
        "bucket": "noaa-goes18",
        "satellite": "GOES-18",
        "coverage": "Americas / Pacific / adjacent oceans · GOES-West",
    },
}

_CAPABILITIES = tuple(
    CapabilityInfo(
        id=capability_id,
        name=metadata["name"],
        unit=None,
        source_class="satellite_observation",
        render_mode="data_file",
        description=(
            "Latest official NOAA GOES-R GLM Level-2 LCFA NetCDF file containing "
            "lightning events, groups and flashes."
        ),
        coverage=metadata["coverage"],
        temporal_resolution="20-second Level-2 product files; NODD updated as data become available",
        strengths=(
            "official NOAA/NESDIS source",
            "public NODD S3 access without AWS credentials",
            "events, groups and flashes in one Level-2 product",
            "total lightning over large ocean and land areas",
        ),
        limitations=(
            "optical satellite detection, not a ground-strike-only network",
            "NetCDF file resource; event decoding is intentionally separate",
            "coverage roughly limited to GOES GLM field of view",
        ),
        documentation_url="https://www.ncei.noaa.gov/products/goes-terrestrial-weather-abi-glm",
    )
    for capability_id, metadata in _SATELLITES.items()
)
_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _data_time_from_key(key: str) -> str | None:
    match = _KEY_TIME_RE.search(key)
    if not match:
        return None
    try:
        base = datetime(
            int(match.group("year")),
            1,
            1,
            tzinfo=timezone.utc,
        ) + timedelta(
            days=int(match.group("doy")) - 1,
            hours=int(match.group("hour")),
            minutes=int(match.group("minute")),
            seconds=int(match.group("second")),
        )
    except ValueError:
        return None
    return base.isoformat().replace("+00:00", "Z")


def _list_entries(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    entries: list[dict[str, Any]] = []
    for element in root.iter():
        if _local(element.tag) != "Contents":
            continue
        item: dict[str, Any] = {}
        for child in element:
            name = _local(child.tag)
            if name == "Key":
                item["key"] = (child.text or "").strip()
            elif name == "LastModified":
                item["last_modified"] = (child.text or "").strip() or None
            elif name == "Size":
                try:
                    item["size"] = int((child.text or "0").strip())
                except ValueError:
                    item["size"] = None
        key = item.get("key")
        if isinstance(key, str) and key.endswith(".nc"):
            entries.append(item)
    return entries


class NoaaGoesGlmProvider:
    """Latest NOAA GOES-18/19 GLM LCFA products via public NODD buckets."""

    id = "noaa_goes_glm"
    name = "NOAA · GOES Geostationary Lightning Mapper"
    router_display_group = "thunderstorm"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Official GOES-R Geostationary Lightning Mapper Level-2 lightning "
                "detection data from NOAA's Open Data Dissemination program."
            ),
            coverage="Western Hemisphere · GOES-East and GOES-West GLM fields of view",
            strengths=(
                "official NOAA/NESDIS satellite source",
                "continuous total-lightning monitoring",
                "public S3 access without AWS account",
                "Level-2 hierarchy of events, groups and flashes",
            ),
            limitations=(
                "satellite optical total lightning rather than ground-strike confirmation",
                "WeatherRouter currently exposes the latest LCFA NetCDF as data_file",
                "direct event decoding is a later parser layer, not fabricated from metadata",
            ),
            documentation_url="https://www.ncei.noaa.gov/products/goes-terrestrial-weather-abi-glm",
            attribution="NOAA / NESDIS / GOES-R Program · NOAA Open Data Dissemination",
            services=(
                {
                    "name": "GOES-19 GLM · East",
                    "status": "integriert",
                    "note": "NODD S3 · GLM-L2-LCFA · NetCDF",
                },
                {
                    "name": "GOES-18 GLM · West",
                    "status": "integriert",
                    "note": "NODD S3 · GLM-L2-LCFA · NetCDF",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        targets: list[NetworkTargetInfo] = []
        for capability_id, metadata in _SATELLITES.items():
            targets.append(
                NetworkTargetInfo(
                    purpose="official_goes_glm_lightning_data",
                    scheme="https",
                    host=f"{metadata['bucket']}.s3.amazonaws.com",
                    port=443,
                    target_type="public_s3",
                    required=True,
                    capabilities=(capability_id,),
                    note="NOAA NODD public GOES GLM Level-2 LCFA products.",
                )
            )
        return tuple(targets)

    async def _latest_file(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        metadata = _SATELLITES.get(capability_id)
        if metadata is None:
            raise ValueError(f"Unsupported NOAA GLM capability: {capability_id}")

        bucket = metadata["bucket"]
        endpoint = f"https://{bucket}.s3.amazonaws.com/"
        session = async_get_clientsession(hass)
        now = datetime.now(timezone.utc)

        latest: dict[str, Any] | None = None
        for hours_back in range(0, 4):
            value = now - timedelta(hours=hours_back)
            prefix = (
                f"{_PRODUCT_PREFIX}/"
                f"{value.year:04d}/{value.timetuple().tm_yday:03d}/{value.hour:02d}/"
            )
            async with session.get(
                endpoint,
                params={
                    "list-type": "2",
                    "prefix": prefix,
                    "max-keys": "1000",
                },
                headers={
                    "Accept": "application/xml,text/xml",
                    "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)",
                },
                timeout=20,
            ) as response:
                response.raise_for_status()
                payload = await response.text()

            entries = _list_entries(payload)
            if entries:
                entries.sort(key=lambda item: item.get("key") or "")
                latest = entries[-1]
                break

        if latest is None:
            raise ValueError(f"NOAA NODD has no recent {_PRODUCT_PREFIX} file for {metadata['satellite']}")

        key = str(latest["key"])
        data_time = _data_time_from_key(key) or latest.get("last_modified")
        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "satellite_observation",
            "render_mode": "data_file",
            "format": "netcdf4",
            "content_type": "application/x-netcdf",
            "transport": "direct",
            "url": f"https://{bucket}.s3.amazonaws.com/{quote(key, safe='/._-')}",
            "size_bytes": latest.get("size"),
            "data_time": data_time,
            "satellite": metadata["satellite"],
            "product": _PRODUCT_PREFIX,
            "coverage": metadata["coverage"],
            "attribution": "NOAA / NESDIS / GOES-R Program",
            "metadata_url": "https://www.ncei.noaa.gov/products/goes-terrestrial-weather-abi-glm",
            "provider_metadata": {
                "bucket": bucket,
                "key": key,
                "measurement": "satellite_total_lightning",
                "contains": ["events", "groups", "flashes"],
                "ground_strike_confirmation": False,
                "official_source": True,
                "license": "NOAA public data / attribution requested",
            },
        }

    async def async_get_data_file(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        return await self._latest_file(hass, capability_id)

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        capability_ids = (
            [capability_id]
            if capability_id in _CAPABILITY_MAP
            else list(_CAPABILITY_MAP)
            if capability_id is None
            else []
        )
        if not capability_ids:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }

        files: list[dict[str, Any]] = []
        try:
            for item in capability_ids:
                descriptor = await self._latest_file(hass, item)
                files.append(
                    {
                        "capability": item,
                        "satellite": descriptor.get("satellite"),
                        "product": descriptor.get("product"),
                        "data_time": descriptor.get("data_time"),
                        "size_bytes": descriptor.get("size_bytes"),
                        "host": f"{_SATELLITES[item]['bucket']}.s3.amazonaws.com",
                    }
                )
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "stage": "nodd_glm_listing",
                "provider_revision": _PROVIDER_REVISION,
                "files": files,
                "error": {"type": type(err).__name__, "message": str(err)},
            }

        return {
            "ok": True,
            "stage": "nodd_glm_listing",
            "provider_revision": _PROVIDER_REVISION,
            "files": files,
            "official_source": True,
            "ground_strike_confirmation": False,
        }
