"""Server-side preview freshness option; never changes approved radar tile age."""
from collections.abc import Mapping
DEFAULT_PREVIEW_MAX_AGE_SECONDS = 1650
MIN_PREVIEW_MAX_AGE_SECONDS = 900
MAX_PREVIEW_MAX_AGE_SECONDS = 3600
OPTION_PREVIEW_MAX_AGE_SECONDS = "opera_dev_preview_max_age_seconds"


def validated_preview_age(value):
    """Fail closed for invalid/untrusted values, excluding bool (an int subtype)."""
    if type(value) is not int or not MIN_PREVIEW_MAX_AGE_SECONDS <= value <= MAX_PREVIEW_MAX_AGE_SECONDS:
        raise ValueError("invalid_opera_preview_max_age_seconds")
    return value


def preview_age_from_entries(entries):
    """Return the canonical persisted WR age limit, including legacy migration."""
    from .opera_config import read_config
    options = getattr(entries[0], "options", {}) if entries else {}
    return read_config(options)["max_age_seconds"]


OPTION_PREVIEW_STALE_AFTER_SECONDS = "opera_dev_preview_stale_after_seconds"
OPTION_PREVIEW_SERVE_STALE = "opera_dev_preview_serve_stale"
MAX_HISTORICAL_PREVIEW_AGE_SECONDS = 3600


def preview_continuity_from_entries(entries):
    """All preview and operational consumers share one WR-owned time policy."""
    from .opera_config import read_config
    options = getattr(entries[0], "options", {}) if entries else {}
    current = read_config(options)
    freshness = current["max_age_seconds"]
    stale_after = current["stale_after_seconds"]
    serve_stale = current["serve_stale"]
    delivery_limit = max(freshness, current["max_stale_age_seconds"]) if serve_stale else freshness
    return {"freshness_seconds": freshness, "stale_after_seconds": stale_after,
            "serve_stale": serve_stale, "delivery_limit_seconds": delivery_limit}
