"""DWD ICON Global / ICON-EU PMSL GRIB2 discovery and bounded pressure contours.

Uses the new 2026 NWP v1 native-grid tree, never legacy .bz2 lat-lon paths.
The publisher's current run/file directory links are discovered, not guessed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from functools import partial
from time import monotonic
from urllib.parse import urljoin, urlsplit, unquote
from typing import Any
import importlib.util
import re

from .synoptic_grib import GribPressureUnavailable, MAX_GRIB_BYTES
from .wind_field_source import plan_subset, WindFieldUnavailable

BASE = "https://opendata.dwd.de/weather/nwp/v1/m/"
RUN_LIMIT = 4
FILE_LIMIT = 5
INDEX_LIMIT = 350_000
_COORD_CACHE_LIMIT = 2


class DwdPressureUnavailable(ValueError):
    """Stable synoptic source error, no leaked network addresses or tokens."""


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            value = dict(attrs).get("href")
            if isinstance(value, str):
                self.hrefs.append(value)


def catalog_links(raw: bytes, *, base: str, directories: bool) -> list[str]:
    if len(raw) > INDEX_LIMIT:
        raise DwdPressureUnavailable("synoptic_dwd_index_too_large")
    parser = Links()
    try:
        parser.feed(raw.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise DwdPressureUnavailable("synoptic_dwd_invalid_catalog") from error
    output = []
    parsed_base = urlsplit(base)
    for rel in parser.hrefs:
        url = urljoin(base, rel)
        p = urlsplit(url)
        if p.scheme != "https" or p.netloc != "opendata.dwd.de":
            continue
        if p.query or p.fragment or not p.path.startswith(parsed_base.path):
            continue
        name = unquote(p.path.removeprefix(parsed_base.path)).strip("/")
        if "/" in name or not name or name.startswith("."):
            continue
        if directories:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}T(?:00|03|06|09|12|15|18|21):00", name):
                output.append(url.rstrip("/")+"/")
        elif re.fullmatch(r"[a-zA-Z0-9_.+-]{10,200}\.grib2", name, re.I):
            output.append(url)
    return sorted(set(output), reverse=directories)


def run_time(url: str) -> datetime:
    text = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise DwdPressureUnavailable("synoptic_dwd_invalid_run") from error


def candidate_files(files: list[str], run: datetime, now: datetime) -> list[str]:
    """Choose a small set of file candidates without assuming filename layout."""
    preferred = []
    for url in files:
        name = url.rsplit("/", 1)[-1]
        leads = re.findall(r"(?:PT|step|lead|fc)[_-]?(\d{1,3})(?:H|h|_|\.)", name, re.I)
        lead = int(leads[-1]) if leads else None
        # Unannotated native filenames are allowed but must be validated
        # by the GRIB reference/validity times after the download.
        distance = abs(((run+timedelta(hours=lead))-now).total_seconds()) if lead is not None else 86400
        preferred.append((distance, name, url))
    preferred.sort()
    return [url for _, _, url in preferred[:FILE_LIMIT]]


async def bounded_get(hass, url: str, limit: int) -> bytes:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    import aiohttp
    if urlsplit(url).netloc != "opendata.dwd.de" or urlsplit(url).scheme != "https":
        raise DwdPressureUnavailable("synoptic_dwd_invalid_url")
    async with asyncio.timeout(18):
        async with async_get_clientsession(hass).get(
            url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "WeatherRouter/0.10 (DWD open data synoptic MSLP)"}
        ) as response:
            if response.status in (429, 503):
                raise DwdPressureUnavailable("synoptic_dwd_rate_limited")
            if response.status != 200:
                raise DwdPressureUnavailable("synoptic_dwd_source_http_error")
            if response.content_length and response.content_length > limit:
                raise DwdPressureUnavailable("synoptic_dwd_transport_budget")
            data = await response.content.read(limit + 1)
            if len(data) > limit:
                raise DwdPressureUnavailable("synoptic_dwd_transport_budget")
            return data


def _regional_window(bbox: dict) -> bool:
    """Tentative bounds only for candidate order, *not* evidence of coverage."""
    try:
        b = plan_subset(bbox)
    except WindFieldUnavailable:
        return False
    return (-30 <= b["west"] < b["east"] <= 55
            and 20 <= b["south"] < b["north"] <= 85
            and b["east"]-b["west"] <= 75)


async def async_fetch_isobars(hass: Any, bbox: dict) -> dict:
    """Select a verified new-v1 ICON PMSL GRIB and derive real MSL contours."""
    from .const import DOMAIN
    from .synoptic_grib import contours_from_grib
    if importlib.util.find_spec("eccodes") is None:
        raise DwdPressureUnavailable("synoptic_grib_eccodes_not_installed")
    try:
        plan = plan_subset(bbox)
    except WindFieldUnavailable as error:
        raise DwdPressureUnavailable("synoptic_dwd_invalid_bbox") from error
    key = tuple(plan.values())
    state = hass.data.setdefault(DOMAIN, {}).setdefault(
        "synoptic_dwd_pressure", {
            "lock": asyncio.Lock(), "cache": {}, "coordinates": {},
            "cooldown": 0., "requests": 0, "failures": 0,
        })
    now = datetime.now(timezone.utc)
    entry = state["cache"].get(key)
    if (entry and entry[1] > monotonic()
            and datetime.fromisoformat(entry[0]["valid_until"].replace(
                "Z", "+00:00")) > now):
        return entry[0]
    if state["cooldown"] > monotonic():
        raise DwdPressureUnavailable("synoptic_dwd_cooldown")
    async with state["lock"]:
        now = datetime.now(timezone.utc)
        entry = state["cache"].get(key)
        if entry and entry[1] > monotonic():
            return entry[0]
        model_order = ("icon-eu", "icon") if _regional_window(bbox) else ("icon",)
        last_code = "synoptic_dwd_no_verified_model_run"
        for model in model_order:
            root = BASE + model + "/p/PMSL/r/"
            try:
                dirs = catalog_links(await bounded_get(hass, root, INDEX_LIMIT),
                                     base=root, directories=True)
            except (DwdPressureUnavailable, TimeoutError):
                continue
            for folder in dirs[:RUN_LIMIT]:
                run = run_time(folder)
                if run > now or now-run > timedelta(hours=30):
                    continue
                try:
                    # DWD NWP v1 explicitly nests single-level forecast step
                    # files under r/{ISO_RUN}/s/{PTxxxHyyM.grib2}. The
                    # colon in a run name is URL-percent-encoded upstream.
                    step_dir = folder + "s/"
                    urls = candidate_files(
                        catalog_links(await bounded_get(hass, step_dir, INDEX_LIMIT),
                                      base=step_dir, directories=False), run, now)
                    if not urls:
                        continue
                    # Native ICON GRIB2 fields have no geographic vertices.
                    # CLAT/CLON sidecars are required and grid UUID validated
                    # against the actual PMSL message by synoptic_grib.
                    coordinates = state.setdefault("coordinates", {})
                    coord_key = (model, run.isoformat())
                    pair = coordinates.get(coord_key)
                    if pair is None:
                        base_run = folder.removeprefix(root)
                        sidecars = []
                        for name in ("CLAT", "CLON"):
                            coord_url = (
                                BASE + model + "/p/" + name + "/r/"
                                + base_run + "s/PT000H00M.grib2")
                            sidecars.append(await bounded_get(
                                hass, coord_url, MAX_GRIB_BYTES))
                        pair = tuple(sidecars)
                        coordinates[coord_key] = pair
                        while len(coordinates) > _COORD_CACHE_LIMIT:
                            coordinates.pop(next(iter(coordinates)))
                except (DwdPressureUnavailable, TimeoutError):
                    continue
                for url in urls:
                    state["requests"] += 1
                    try:
                        raw = await bounded_get(hass, url, MAX_GRIB_BYTES)
                        task = partial(
                            contours_from_grib, raw, plan,
                            model=model, provider_id="dwd",
                            source="DWD NWP v1 native PMSL GRIB2 / CLAT+CLON",
                            attribution="Deutscher Wetterdienst (DWD) · CC BY 4.0",
                            coordinate_fields=pair)
                        frame = await hass.async_add_executor_job(task)
                        model_run = datetime.fromisoformat(
                            frame["model_run"].replace("Z", "+00:00"))
                        if model_run != run:
                            last_code = "synoptic_dwd_run_mismatch"
                            continue
                        state["cache"][key] = (frame, monotonic()+600)
                        while len(state["cache"]) > 4:
                            state["cache"].pop(next(iter(state["cache"])))
                        state["cooldown"] = 0.
                        return frame
                    except (GribPressureUnavailable, DwdPressureUnavailable, TimeoutError) as error:
                        last_code = str(error)
                        continue
        state["failures"] += 1
        state["cooldown"] = monotonic()+90
        raise DwdPressureUnavailable(last_code)
