"""Independent, network-free lunar ephemeris for terrestrial observers."""
from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

PHASES = ("new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous",
          "full_moon", "waning_gibbous", "last_quarter", "waning_crescent")
UTC = timezone.utc


def resolve_timezone(latitude: float, longitude: float) -> str:
    """Offline geographic IANA lookup; UTC if the lookup cannot be resolved."""
    try:
        return _timezone_finder().timezone_at(lat=latitude, lng=longitude) or "UTC"
    except (ImportError, ValueError, RuntimeError, OSError):
        return "UTC"


from functools import lru_cache


@lru_cache(maxsize=1)
def _timezone_finder():
    from timezonefinder import TimezoneFinder
    return TimezoneFinder(in_memory=False)


def calculate_moon(latitude: float, longitude: float, at: datetime,
                   timezone_name: str | None = None) -> dict:
    """Return geocentric phase and local civil-day horizon events (sea level)."""
    if not (isfinite(latitude) and -90 <= latitude <= 90 and
            isfinite(longitude) and -180 <= longitude <= 180):
        raise ValueError("Invalid terrestrial coordinates")
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Timestamp must include UTC offset")
    at = at.astimezone(UTC)
    if not 1901 <= at.year <= 2099:
        raise ValueError("Supported years: 1901–2099")
    timezone_name = timezone_name or resolve_timezone(latitude, longitude)
    zone = ZoneInfo(timezone_name)
    local_day = at.astimezone(zone).date()
    start = datetime.combine(local_day, datetime.min.time(), zone).astimezone(UTC)
    end = datetime.combine(local_day + timedelta(days=1), datetime.min.time(), zone).astimezone(UTC)
    # Lazy import: no lunar computation or library import in weather provider paths.
    import astronomy as astro

    def instant(dt):
        return astro.Time.Parse(dt.isoformat(timespec="microseconds").replace("+00:00", "Z"))

    def utc(t):
        return datetime.fromisoformat(str(t).replace("Z", "+00:00"))

    def event(t):
        if t is None:
            return None
        dt = utc(t)
        return {"utc": dt.isoformat(), "local": dt.astimezone(zone).isoformat()}

    now = instant(at)
    angle = astro.MoonPhase(now)
    previous = astro.SearchMoonPhase(0, now, -35)
    following = astro.SearchMoonPhase(0, now, 35)
    if previous is None or following is None:
        raise RuntimeError("Lunar cycle not resolved")
    age = (now.ut - previous.ut)
    cycle = following.ut - previous.ut
    quarter = astro.SearchMoonQuarter(now)
    if quarter.time.ut <= now.ut:
        quarter = astro.NextMoonQuarter(quarter)
    observer = astro.Observer(latitude, longitude, 0)
    # Apparent topocentric observer-to-Moon-center range, sea-level observer.
    # The public numeric value is quantized to 1 km, not a precision claim.
    distance_km = round(astro.Equator(astro.Body.Moon, now, observer, True, True).dist * astro.KM_PER_AU)
    duration = (end - start).total_seconds() / 86400

    def horizon(direction):
        t = astro.SearchRiseSet(astro.Body.Moon, observer, direction, instant(start), duration)
        return event(t) if t is not None and start <= utc(t) < end else None

    return {
        "schema": "weather_router.moon.v1", "status": "ready",
        "latitude": latitude, "longitude": longitude,
        "distance_km": distance_km,
        "distance_kind": "topocentric_observer_to_moon_center",
        "observer_height_m": 0, "distance_resolution_km": 1,
        "timestamp_utc": at.isoformat(), "timezone": timezone_name,
        "local_date": local_day.isoformat(),
        "phase": PHASES[int((angle + 22.5) // 45) % 8],
        "phase_angle_deg": angle, "moon_age_days": age,
        "cycle_days": cycle, "cycle_fraction": max(0.0, min(1.0, age / cycle)),
        "illumination_percent": 100 * astro.Illumination(astro.Body.Moon, now).phase_fraction,
        "next_major_phase": {"phase": PHASES[quarter.quarter * 2], **event(quarter.time)},
        "moonrise": horizon(astro.Direction.Rise),
        "moonset": horizon(astro.Direction.Set),
        "model": "astronomy-engine/2.1.19",
    }
