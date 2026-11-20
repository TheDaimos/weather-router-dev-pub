"""Persistent, admin-only OPERA service preferences; scientific admission is separate."""
from __future__ import annotations
from math import isfinite

PRODUCTS = ("RATE", "DBZH", "ACRR")
DEFAULTS = {"RATE": False, "DBZH": False, "ACRR": False}
MIN_AGE, MAX_AGE = 900, 3600

def read_config(options):
    raw = options.get("opera_services", {})
    if not isinstance(raw, dict):
        raw = {}
    services = {p: raw.get(p) is True for p in PRODUCTS}
    def age(key, old, default):
        value = options.get(key, options.get(old, default))
        return value if type(value) is int and MIN_AGE <= value <= MAX_AGE else default
    freshness = age("opera_max_age_seconds", "opera_dev_preview_max_age_seconds", 1500)
    stale = age("opera_stale_after_seconds", "opera_dev_preview_stale_after_seconds", freshness)
    return {
        "services": services,
        "max_age_seconds": freshness,
        "stale_after_seconds": stale,
        "max_stale_age_seconds": age("opera_max_stale_age_seconds", "opera_max_stale_age_seconds", MAX_AGE),
        "serve_stale": options.get("opera_serve_stale", options.get("opera_dev_preview_serve_stale", False)) is True,
        "scientific_status": {p: "UNVERIFIED" for p in PRODUCTS},
    }

def update_config(options, request):
    """Validate first, then return a new options mapping without enabling the provider."""
    if not isinstance(request, dict) or set(request) - {"services", "max_age_seconds", "stale_after_seconds", "serve_stale", "max_stale_age_seconds"}:
        raise ValueError("unknown_opera_setting")
    updated = dict(options)
    current = read_config(options)
    for field in ("max_age_seconds", "stale_after_seconds", "serve_stale"):
        updated["opera_" + field] = current[field]
        updated.pop("opera_dev_preview_" + field, None)
    if "services" in request:
        raw = request["services"]
        if not isinstance(raw, dict) or set(raw) != set(PRODUCTS) or any(type(v) is not bool for v in raw.values()):
            raise ValueError("invalid_opera_services")
        updated["opera_services"] = dict(raw)
    for public, stored in (("max_age_seconds", "opera_max_age_seconds"),
                           ("stale_after_seconds", "opera_stale_after_seconds"),
                           ("max_stale_age_seconds", "opera_max_stale_age_seconds")):
        if public in request:
            value = request[public]
            if type(value) is not int or not MIN_AGE <= value <= MAX_AGE:
                raise ValueError("invalid_opera_age")
            updated[stored] = value
            legacy = "opera_dev_preview_" + public
            updated.pop(legacy, None)
    if "serve_stale" in request:
        if type(request["serve_stale"]) is not bool:
            raise ValueError("invalid_opera_stale_flag")
        updated["opera_serve_stale"] = request["serve_stale"]
        updated.pop("opera_dev_preview_serve_stale", None)
    return updated

def frame_status(age_seconds, settings):
    """Classify a diagnostic frame without ever granting scientific approval."""
    if type(age_seconds) not in (int, float) or not isfinite(age_seconds) or age_seconds < 0:
        return "UNAVAILABLE"
    stale = settings["stale_after_seconds"]
    maximum = settings["max_age_seconds"]
    delivery = max(maximum, settings.get("max_stale_age_seconds", MAX_AGE)) if settings["serve_stale"] else maximum
    if age_seconds > delivery:
        return "UNAVAILABLE"
    if age_seconds > stale or age_seconds > maximum:
        return "STALE"
    return "CURRENT"


def service_allowed(options, product):
    """Independent opt-in, never enough for scientific approval."""
    return product in PRODUCTS and read_config(options)["services"][product] is True
