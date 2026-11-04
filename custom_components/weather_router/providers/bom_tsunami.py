"""Australian Bureau of Meteorology / JATWC tsunami warning RSS provider."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import tsunami_semantics

_PROVIDER_REVISION = "wr-0.10.129-tsunami-semantics-1"
_STATUS_URL = "https://www.bom.gov.au/tsunami/national.shtml"
_BOM_HEADERS = {
    "Accept": "application/rss+xml,application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
        "Gecko/20100101 Firefox/128.0"
    ),
}

_RSS_FEEDS = (
    ("NSW/ACT", "https://www.bom.gov.au/fwo/IDZ00054.warnings_nsw.xml"),
    ("Victoria", "https://www.bom.gov.au/fwo/IDZ00059.warnings_vic.xml"),
    ("Queensland", "https://www.bom.gov.au/fwo/IDZ00056.warnings_qld.xml"),
    ("Western Australia", "https://www.bom.gov.au/fwo/IDZ00060.warnings_wa.xml"),
    ("South Australia", "https://www.bom.gov.au/fwo/IDZ00057.warnings_sa.xml"),
    ("Tasmania", "https://www.bom.gov.au/fwo/IDZ00058.warnings_tas.xml"),
    ("Northern Territory", "https://www.bom.gov.au/fwo/IDZ00055.warnings_nt.xml"),
)

_CAPABILITIES = (
    CapabilityInfo(
        id="official_tsunami_warnings_australia",
        name="Amtliche Tsunamiwarnungen · Australien / JATWC",
        unit=None,
        source_class="warning",
        render_mode="hazard_feed",
        description=(
            "Aktuelle australische Tsunamiwarnungen aus den offiziellen BoM-"
            "Warnungs-RSS-Feeds."
        ),
        coverage="Australien und australische Offshore-Gebiete",
        temporal_resolution="ereignisgesteuert",
        strengths=(
            "amtliche Bureau-of-Meteorology-/JATWC-Quelle",
            "National/State Tsunami Watch und Warning",
            "Marine- und Land-Inundation-Threats werden als Quelltext erhalten",
        ),
        limitations=(
            "RSS ist laut BoM ein alternativer Warninformationsweg und nicht als einzige "
            "Warnquelle während eines Ereignisses vorgesehen",
            "RSS enthält nicht zwingend die vollständige CAP-/GIS-Geometrie",
        ),
        documentation_url="https://www.bom.gov.au/rss/",
    ),
)


class _HtmlTextExtractor(HTMLParser):
    """Collect visible-ish text from the simple Bureau status page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)

    def text(self) -> str:
        return " ".join(self.parts)


def _status_page_confirms_no_warning(payload: bytes) -> bool:
    """Return True only for explicit Bureau no-current-tsunami wording."""
    parser = _HtmlTextExtractor()
    parser.feed(payload.decode("utf-8", errors="replace"))
    text = parser.text().casefold()
    return (
        "no tsunami currently affecting australia" in text
        and "no tsunami warnings current" in text
    )


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = (element.text or "").strip()
    return value or None


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in element if item.tag.rsplit("}", 1)[-1] == name), None)


def _child_text(element: ET.Element, name: str) -> str | None:
    return _text(_child(element, name))


def _safe_bom_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "www.bom.gov.au",
        "bom.gov.au",
    }:
        return None
    if parsed.scheme == "http":
        return value.replace("http://", "https://", 1)
    return value


def _alert_level(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values).casefold()
    if "cancellation" in text or "cancelled" in text:
        return "canceled"
    if "no threat" in text:
        return "no_threat"
    if "land" in text and "warning" in text:
        return "land_inundation_warning"
    if "marine" in text and "warning" in text:
        return "marine_warning"
    if "warning" in text:
        return "warning"
    if "watch" in text:
        return "watch"
    return "information"


def _severity(level: str) -> str:
    return {
        "land_inundation_warning": "extreme",
        "marine_warning": "severe",
        "warning": "severe",
        "watch": "moderate",
        "information": "minor",
        "no_threat": "minor",
        "canceled": "minor",
    }.get(level, "unknown")


class BomTsunamiProvider:
    """Australian official tsunami warnings from BoM state warning RSS feeds."""

    id = "bom_tsunami"
    name = "BoM / JATWC · Australia Tsunami"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Der Joint Australian Tsunami Warning Centre wird von Bureau of "
                "Meteorology und Geoscience Australia betrieben. WeatherRouter nutzt "
                "die offiziellen staatlichen BoM-Warnungs-RSS-Feeds, die Tsunamiwarnungen "
                "einschließen."
            ),
            coverage="Australien und australische Offshore-Gebiete",
            strengths=(
                "amtliche australische Warnquelle",
                "Watch/Warning/Cancellation",
                "Marine- und Land-Inundation-Bedrohung",
            ),
            limitations=(
                "RSS darf laut BoM nicht als alleinige Warnquelle während eines "
                "Warnereignisses verwendet werden",
                "BoM-RSS-Nutzungsbedingungen und Attribution sind bei öffentlicher "
                "Weiterverwendung zu beachten",
            ),
            documentation_url="https://www.bom.gov.au/rss/",
            attribution="Australian Bureau of Meteorology / JATWC",
            services=(
                {
                    "name": "BoM State Warning RSS",
                    "status": "integriert",
                    "note": "Tsunamiwarnungen aus sieben staatlichen/territorialen Feeds",
                },
                {
                    "name": "JATWC CAP/GIS products",
                    "status": "katalogisiert",
                    "note": "späterer Geometrieausbau ohne instabiles Scraping",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="official_tsunami_warnings",
                scheme="https",
                host="www.bom.gov.au",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=("official_tsunami_warnings_australia",),
                note=(
                    "Official BoM state warning RSS feeds; tsunami is an included warning "
                    "type. National tsunami status page is used only as a fail-closed "
                    "no-warning fallback when every RSS endpoint is blocked."
                ),
            ),
        )

    async def async_get_hazard_feed(
        self,
        hass: HomeAssistant,
        capability_id: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        del latitude, longitude, bbox
        if capability_id != "official_tsunami_warnings_australia":
            raise ValueError(f"Unsupported BoM tsunami capability: {capability_id}")

        session = async_get_clientsession(hass)
        events: list[dict[str, Any]] = []
        errors: list[str] = []
        maximum = max(1, min(int(limit), 500))
        seen: set[str] = set()

        for region, feed_url in _RSS_FEEDS:
            try:
                async with session.get(
                    feed_url,
                    headers=_BOM_HEADERS,
                    timeout=20,
                ) as response:
                    response.raise_for_status()
                    payload = await response.read()
                root = ET.fromstring(payload)
            except Exception as err:  # noqa: BLE001 - isolate one state feed
                errors.append(f"{region}:{type(err).__name__}:{err}")
                continue

            for item in (
                element for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "item"
            ):
                title = _child_text(item, "title")
                description = _child_text(item, "description")
                if "tsunami" not in f"{title or ''} {description or ''}".casefold():
                    continue

                link = _safe_bom_url(_child_text(item, "link"))
                guid = _child_text(item, "guid")
                event_id = guid or link or f"{region}:{title}:{_child_text(item, 'pubDate')}"
                if event_id in seen:
                    continue
                seen.add(event_id)

                level = _alert_level(title, description)
                events.append(
                    {
                        "id": event_id,
                        "hazard_type": "tsunami",
                        "tsunami_semantics": tsunami_semantics(
                            "official_tsunami_warning_event",
                            alert_stage=level,
                            source_alert_level=title,
                            active_threat=level in {
                                "warning", "watch", "marine_warning",
                                "land_inundation_warning",
                            },
                            wave_evidence="none",
                        ),
                        "event": title or "Tsunami Warning",
                        "headline": title or "Australian Tsunami Warning",
                        "severity": _severity(level),
                        "urgency": "immediate"
                        if "warning" in level
                        else "expected",
                        "certainty": "likely"
                        if level not in {"no_threat", "canceled"}
                        else "observed",
                        "status": "actual",
                        "message_type": "cancel"
                        if level == "canceled"
                        else "alert",
                        "sent": _child_text(item, "pubDate"),
                        "effective": None,  # RSS pubDate ist Veröffentlichung, nicht Warnbeginn.
                        "onset": None,
                        "expires": None,
                        "ends": None,
                        "area_desc": region,
                        "geometry": None,
                        "description": description,
                        "instruction": None,
                        "sender_name": "Australian Bureau of Meteorology / JATWC",
                        "response": "monitor",
                        "affected_zones": [region],
                        "parameters": {
                            "alert_level": level,
                            "rss_region": region,
                            "rss_guid": guid,
                            "source_feed": feed_url,
                        },
                        "web_url": link or "https://www.bom.gov.au/tsunami/",
                    }
                )
                if len(events) >= maximum:
                    break
            if len(events) >= maximum:
                break

        fallback_status = None
        if not events and len(errors) == len(_RSS_FEEDS):
            try:
                async with session.get(
                    _STATUS_URL,
                    headers=_BOM_HEADERS,
                    timeout=20,
                ) as response:
                    response.raise_for_status()
                    status_payload = await response.read()
                if _status_page_confirms_no_warning(status_payload):
                    fallback_status = "official_status_page_no_current_warning"
                else:
                    raise ValueError(
                        "BoM national tsunami status page did not explicitly confirm "
                        "a no-warning state"
                    )
            except Exception as err:  # noqa: BLE001 - preserve fail-closed warning semantics
                raise ValueError(
                    "All BoM warning RSS feeds failed and official tsunami status "
                    "fallback was inconclusive"
                    + (f" ({type(err).__name__}:{err})" if err else "")
                ) from err

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "warning",
            "render_mode": "hazard_feed",
            "coverage_status": "regional",
            "events": events,
            "event_count": len(events),
            "provider_metadata": {
                "state_feed_count": len(_RSS_FEEDS),
                "feed_errors": errors,
                "fallback_status": fallback_status,
                "request_profile": "browser_compatible_public_feed",
                "rss_usage_note": (
                    "BoM states RSS is an alternate warning information path and "
                    "must retain attribution/link to the full warning."
                ),
            },
            "attribution": "Australian Bureau of Meteorology / JATWC",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, "official_tsunami_warnings_australia"}:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }
        feed = await self.async_get_hazard_feed(
            hass,
            "official_tsunami_warnings_australia",
            limit=25,
        )
        return {
            "ok": True,
            "stage": (
                "bom_national_status_no_warning_fallback"
                if (feed.get("provider_metadata") or {}).get("fallback_status")
                else "bom_state_warning_rss"
            ),
            "provider_revision": _PROVIDER_REVISION,
            "event_count": feed.get("event_count", 0),
            "feed_errors": (feed.get("provider_metadata") or {}).get(
                "feed_errors",
                [],
            ),
        }
