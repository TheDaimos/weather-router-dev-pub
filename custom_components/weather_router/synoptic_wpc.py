"""NOAA/WPC authoritative North-American coded surface H/L bulletins.

WPC is *regional*. This adapter never manufactures global coverage and never
mislabels encoded analysis points as pressure forecast contours.
Source: https://www.wpc.ncep.noaa.gov/html/read_coded_bull_hr.shtml
Publication index: https://ftp-wpc.ncep.noaa.gov/coded_sfc/
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
from time import monotonic
import re
from urllib.parse import urljoin, urlsplit
from typing import Any

CAPABILITY = "weather.synoptic.pressure_centers"
ROOT = "https://ftp-wpc.ncep.noaa.gov/coded_sfc/"
MAX_INDEX_BYTES = 140_000
MAX_BULLETIN_BYTES = 150_000
COVERAGE = {"type": "bbox", "crs": "EPSG:4326",
            "west": -180., "east": -30., "south": 0., "north": 85.}
_ALLOWED_SUFFIXES = (".txt", ".dat", ".html", ".text", ".sfc")
_STOP = frozenset(("HIGHS", "LOWS", "COLD", "WARM", "STNRY", "OCFNT",
                   "TROF", "TROUGH", "FRONT", "DISS", "OUTFLOW",
                   "VALID", "ANALYSIS", "ISOBAR", "RIDGE"))


class WpcUnavailable(ValueError):
    """Stable provider-level reason, safe to show in diagnostics."""


class Listing(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if isinstance(href, str):
                self.links.append(href)


def candidates(index: bytes, base: str) -> list[str]:
    """Return bounded same-origin text bulletins from an official day directory."""
    if len(index) > MAX_INDEX_BYTES:
        raise WpcUnavailable("synoptic_wpc_index_budget")
    page = Listing()
    try:
        page.feed(index.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise WpcUnavailable("synoptic_wpc_index_invalid") from error
    picked = []
    for href in page.links:
        url = urljoin(base, href)
        parsed = urlsplit(url)
        name = parsed.path.rsplit("/", 1)[-1]
        if (parsed.scheme == "https" and parsed.netloc == "ftp-wpc.ncep.noaa.gov"
                and parsed.path.startswith(urlsplit(base).path)
                and not parsed.query and not parsed.fragment
                and name and "." not in name[:1]
                and any(name.lower().endswith(suffix) for suffix in _ALLOWED_SUFFIXES)
                and re.fullmatch(r"[a-zA-Z0-9_.-]{3,85}", name)):
            picked.append(url)
    # Prefer high-resolution coded bulletins when the publisher lists both.
    picked.sort(key=lambda url: (not bool(re.search(r"high|hires|hr", url, re.I)), url), reverse=False)
    return picked[:24]


def _datetime(token: str, now: datetime) -> datetime:
    if not re.fullmatch(r"\d{6}", token):
        raise WpcUnavailable("synoptic_wpc_invalid_time")
    month, day, hour = int(token[:2]), int(token[2:4]), int(token[4:6])
    possible = []
    for year in (now.year - 1, now.year, now.year + 1):
        try:
            possible.append(datetime(year, month, day, hour, tzinfo=timezone.utc))
        except ValueError:
            continue
    if not possible:
        raise WpcUnavailable("synoptic_wpc_invalid_time")
    valid = min(possible, key=lambda value: abs((value - now).total_seconds()))
    if not -timedelta(minutes=15) <= now - valid <= timedelta(hours=13):
        raise WpcUnavailable("synoptic_wpc_stale")
    return valid


def decode(data: bytes, now: datetime | None = None) -> dict:
    """Decode NOAA-issued pressure centres, not unrelated bulletin numbers."""
    now = now or datetime.now(timezone.utc)
    if not data or len(data) > MAX_BULLETIN_BYTES:
        raise WpcUnavailable("synoptic_wpc_transport_budget")
    try:
        s = data.decode("ascii", errors="strict").upper()
    except UnicodeError as error:
        raise WpcUnavailable("synoptic_wpc_bad_encoding") from error
    time_match = re.search(r"\bVALID\s+(\d{6})Z\b", s)
    if not time_match:
        raise WpcUnavailable("synoptic_wpc_missing_validity")
    valid = _datetime(time_match.group(1), now)
    # Isolate exclusively HIGHS/LOWS sections, never parse front coordinates.
    tokens = re.findall(r"\b[A-Z][A-Z0-9_-]*\b|\b\d{1,7}\b", s[time_match.end():])
    features, category, ix = [], None, 0
    while ix < len(tokens):
        word = tokens[ix]
        if word in ("HIGHS", "LOWS"):
            category = "H" if word == "HIGHS" else "L"
            ix += 1
            continue
        if word in _STOP:
            category = None
            ix += 1
            continue
        if category and word.isdecimal() and ix + 1 < len(tokens):
            coord = tokens[ix + 1]
            pressure = int(word)
            if coord.isdecimal() and 870 <= pressure <= 1090:
                if len(coord) in (4, 5):
                    lat = int(coord[:2])
                    lon = int(coord[2:])
                elif len(coord) == 7:
                    lat = int(coord[:3]) / 10
                    lon = int(coord[3:]) / 10
                else:
                    ix += 1
                    continue
                if 0 <= lat <= 85 and 0 <= lon <= 180:
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-lon, lat]},
                        "properties": {"kind": category, "pressure_hpa": pressure}
                    })
                    ix += 2
                    continue
        ix += 1
    if not 1 <= len(features) <= 700:
        raise WpcUnavailable("synoptic_wpc_no_centers")
    expires = min(now + timedelta(minutes=25), valid + timedelta(hours=13))
    if expires <= now:
        raise WpcUnavailable("synoptic_wpc_stale")
    iso = lambda t: t.isoformat().replace("+00:00", "Z")
    return {
        "capability": CAPABILITY,
        "id": hashlib.sha256(data).hexdigest()[:24],
        "model": "NOAA WPC human surface analysis",
        "kind": "surface_analysis", "unit": "hPa",
        "model_run": iso(valid), "valid_at": iso(valid), "valid_until": iso(expires),
        "refresh_after_seconds": 600,
        "coverage": dict(COVERAGE),
        "geometry": {"type": "FeatureCollection", "features": features},
        "provenance": {
            "provider_id": "noaa_nws",
            "model": "WPC Surface Analysis",
            "source": "NOAA/NWS WPC coded surface analysis bulletin",
            "attribution": "NOAA / NWS Weather Prediction Center",
            "data_origin": "human_analysis",
            "measurement_method": "official_encoded_pressure_centers",
        },
    }


def subset(frame: dict, bbox: dict) -> dict:
    from .spatial_coverage import point_in_bbox
    features = [
        f for f in frame["geometry"]["features"]
        if point_in_bbox(f["geometry"]["coordinates"][1],
                         f["geometry"]["coordinates"][0], bbox)
    ]
    return {**frame, "geometry": {"type": "FeatureCollection", "features": features}}


async def _fetch(hass, url: str, budget: int) -> bytes:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .const import DOMAIN
    import aiohttp
    parsed = urlsplit(url)
    if (parsed.scheme != "https"
            or parsed.netloc != "ftp-wpc.ncep.noaa.gov"
            or not parsed.path.startswith("/coded_sfc/")
            or parsed.query or parsed.fragment):
        raise WpcUnavailable("synoptic_wpc_untrusted_url")
    async with asyncio.timeout(12):
        async with async_get_clientsession(hass).get(
            url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False,
            headers={"User-Agent": "WeatherRouter/0.10 (public NOAA surface analysis)"}
        ) as response:
            if response.status != 200:
                raise WpcUnavailable("synoptic_wpc_http_unavailable")
            if response.content_length and response.content_length > budget:
                raise WpcUnavailable("synoptic_wpc_transport_budget")
            raw = await response.content.read(budget + 1)
            if len(raw) > budget:
                raise WpcUnavailable("synoptic_wpc_transport_budget")
            return raw


async def async_fetch_centers(hass: Any, bbox: dict) -> dict:
    """Lazy coalesced regional retrieval, no unbounded listing crawler."""
    from .const import DOMAIN
    from .spatial_coverage import bbox_contains, normalize_bbox
    request = normalize_bbox(bbox)
    if request is None or not bbox_contains(COVERAGE, request):
        raise WpcUnavailable("synoptic_wpc_outside_region")
    state = hass.data.setdefault(DOMAIN, {}).setdefault(
        "synoptic_wpc_state", {"lock": asyncio.Lock(), "frame": None,
                               "checked": 0., "cooldown": 0.})
    now = datetime.now(timezone.utc)
    cached = state["frame"]
    if cached and state["checked"] + 600 > monotonic():
        return subset(cached, request)
    async with state["lock"]:
        now = datetime.now(timezone.utc)
        cached = state["frame"]
        if cached and state["checked"] + 600 > monotonic():
            return subset(cached, request)
        if state["cooldown"] > monotonic():
            if cached and datetime.fromisoformat(
                    cached["valid_until"].replace("Z", "+00:00")) > now:
                return subset(cached, request)
            raise WpcUnavailable("synoptic_wpc_cooldown")
        for day in (now.date(), (now-timedelta(days=1)).date()):
            base = ROOT + day.strftime("%Y%m%d") + "/"
            try:
                choices = candidates(await _fetch(hass, base, MAX_INDEX_BYTES), base)
            except (WpcUnavailable, TimeoutError, OSError):
                continue
            for url in choices[:8]:
                try:
                    raw = await _fetch(hass, url, MAX_BULLETIN_BYTES)
                    frame = await hass.async_add_executor_job(decode, raw, now)
                    if cached is None or frame["valid_at"] >= cached["valid_at"]:
                        state.update(frame=frame, checked=monotonic(), cooldown=0.)
                    return subset(state["frame"], request)
                except (WpcUnavailable, TimeoutError, OSError):
                    continue
        state["cooldown"] = monotonic() + 180
        if cached and datetime.fromisoformat(
                cached["valid_until"].replace("Z", "+00:00")) > now:
            return subset(cached, request)
        raise WpcUnavailable("synoptic_wpc_no_verified_bulletin")
