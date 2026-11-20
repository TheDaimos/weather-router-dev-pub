"""Bounded MeteoGate ORD RATE object discovery; never scientific authorization.

Only explicit OPERA ODIM-HDF5 objects from documented MeteoGate links are
eligible. No redirects, arbitrary hosts, bucket guesses or anonymous proxies.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode, urlsplit, unquote

from .providers.opera import validate_key

API = ("https://api.meteogate.eu/eu-eumetnet-weather-radar/"
       "collections/observations/locations/0-20010-0-OPERA")
HOST_PREFIXES = {
    "s3.waw3-1.cloudferro.com": "/openradar-24h/",
    "object-store.os-api.cci1.ecmwf.int": "/openradar-24h-backup/",
}
MAX_JSON_BYTES = 256 * 1024
MAX_LINK_NODES = 256


def validated_rate_link(url, expected_slots):
    """Return (nominal timestamp, canonical HTTPS URL) or None."""
    if type(url) is not str or len(url) > 1024:
        return None
    try:
        part = urlsplit(url)
        if (part.scheme != "https" or part.hostname not in HOST_PREFIXES
                or part.username is not None or part.password is not None
                or part.port not in (None, 443) or part.query or part.fragment
                or part.netloc != part.hostname):
            return None
        prefix = HOST_PREFIXES[part.hostname]
        if not part.path.startswith(prefix) or "%" in part.path:
            return None
        key = unquote(part.path[len(prefix):])
        parsed = validate_key(key)
        if (parsed is None or parsed[0] != "RATE" or parsed[2] != "h5"
                or parsed[1] not in expected_slots
                or parsed[1].minute % 15 != 0):
            return None
        return parsed[1], url
    except (ValueError, TypeError):
        return None


def extract_rate_links(payload, expected_slots):
    """Collect only rel=items ODIM links; fail closed for ambiguous slots."""
    if not isinstance(payload, (dict, list)):
        raise ValueError("meteo_gate_invalid_json")
    found = {}
    node_count = 0
    stack = [(payload, 0)]
    while stack:
        node, depth = stack.pop()
        node_count += 1
        if node_count > MAX_LINK_NODES or depth > 8:
            raise ValueError("meteo_gate_response_limit")
        if isinstance(node, dict):
            if node.get("rel") in ("items", "item"):
                checked = validated_rate_link(node.get("href"), expected_slots)
                if checked:
                    stamp, url = checked
                    found.setdefault(stamp, set()).add(url)
            for key, value in node.items():
                if isinstance(value, (list, dict)):
                    stack.append((value, depth + 1))
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (list, dict)):
                    stack.append((value, depth + 1))
    # Multiple independent object links for the same nominal stamp are
    # ambiguous, even when they advertise the same product.
    return {stamp: next(iter(urls)) for stamp, urls in found.items()
            if len(urls) == 1}


async def discover_rate_links(session, now):
    """One bounded ORD query per monitor cycle, using documented API filters."""
    current = now.astimezone(timezone.utc)
    window_end = current.replace(second=0, microsecond=0)
    window_start = window_end - timedelta(hours=2)
    valid_slots = frozenset(
        window_end.replace(minute=(window_end.minute // 15) * 15)
        - timedelta(minutes=15 * n) for n in range(8))
    fmt = lambda value: value.strftime("%Y-%m-%dT%H:%MZ")
    params = urlencode({
        "datetime": fmt(window_start) + "/" + fmt(window_end),
        "f": "CoverageJSON", "standard_name": "RATE",
        "format": "ODIM", "method": "comp",
    })
    async with asyncio.timeout(12):
        async with session.get(API + "?" + params, allow_redirects=False,
                               ssl=True, headers={"Accept": "application/prs.coverage+json"}) as response:
            if response.status == 204:
                return {}
            if response.status != 200:
                raise ValueError("meteo_gate_failed")
            if (response.content_length is not None
                    and response.content_length > MAX_JSON_BYTES):
                raise ValueError("meteo_gate_response_limit")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in ("application/prs.coverage+json", "application/json"):
                raise ValueError("meteo_gate_invalid_content_type")
            raw = await response.content.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("meteo_gate_response_limit")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("meteo_gate_invalid_json") from exc
    return extract_rate_links(payload, valid_slots)
