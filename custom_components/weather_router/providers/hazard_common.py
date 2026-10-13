"""Shared hazard-feed normalization helpers for WeatherRouter."""

from __future__ import annotations

from math import isfinite
from typing import Any, Iterable


_HAZARD_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "tsunami_potential",
        (
            "tsunami potential",
            "potential tsunami",
            "berpotensi tsunami",
            "potensi tsunami",
            "tsunamigefährd",
        ),
    ),
    (
        "tsunami",
        (
            "tsunami warning",
            "tsunami advisory",
            "tsunami watch",
            "tsunami threat",
            "tsunami",
            "津波警報",
            "大津波警報",
            "津波注意報",
        ),
    ),
    ("earthquake", ("earthquake", "erdbeben", "seismic event", "seismisches ereignis")),
    (
        "volcanic_activity",
        ("volcanic activity", "volcano", "eruption", "vulkanaktivität", "vulkanausbruch"),
    ),
    ("waterspout", ("waterspout", "wasserhose")),
    ("tornado", ("tornado", "windhose")),
    (
        "supercell",
        (
            "supercell",
            "superzelle",
        ),
    ),
    (
        "downburst",
        (
            "downburst",
            "microburst",
            "macroburst",
            "fallböe",
            "fallboe",
        ),
    ),
    (
        "tropical_cyclone",
        (
            "hurricane",
            "tropical cyclone",
            "tropical storm",
            "typhoon",
            "tropischer wirbelsturm",
            "tropensturm",
            "hurrikan",
        ),
    ),
    (
        "severe_thunderstorm",
        (
            "severe thunderstorm",
            "strong thunderstorm",
            "schweres gewitter",
            "starkes gewitter",
            "gewit",
        ),
    ),
    ("hail", ("hail", "hagel")),
    ("storm_surge", ("storm surge", "sturmflut")),
    (
        "levee_failure",
        (
            "levee failure", "levee breach", "dike breach", "dyke breach",
            "dike failure", "dyke failure", "deichbruch", "deichversagen",
        ),
    ),
    (
        "dam_failure",
        (
            "dam failure", "dam break", "dam breach", "reservoir failure",
            "dammbruch", "talsperrenbruch", "talsperrenversagen",
        ),
    ),
    (
        "glacial_lake_outburst_flood",
        (
            "glacial lake outburst flood", "glof", "gletscherseeausbruch",
            "gletschersee-ausbruch",
        ),
    ),
    (
        "ice_jam_flood",
        (
            "ice jam flood", "ice jam", "eisstau-hochwasser", "eisstau",
        ),
    ),
    (
        "debris_flow",
        (
            "debris flow", "mudflow", "mud flow", "mudslide", "mud slide",
            "mure", "schlammlawine", "schlammstrom", "geröllstrom",
        ),
    ),
    (
        "surface_water_flood",
        (
            "surface water flood", "pluvial flood", "urban flooding", "urban flood",
            "oberflächenüberflutung", "oberflaechenueberflutung",
            "pluviales hochwasser", "straßenüberflutung", "strassenueberflutung",
        ),
    ),
    ("flash_flood", ("flash flood", "sturzflut", "plötzliche überschwemm")),
    ("flood", ("flood", "hochwasser", "überschwemm")),
    ("landslide", ("landslide", "rock slide", "rockslide", "erdrutsch", "felsrutsch")),
    (
        "heavy_rain",
        ("heavy rain", "excessive rainfall", "starkregen", "dauerregen", "extreme rain"),
    ),
    (
        "windstorm",
        (
            "high wind",
            "wind warning",
            "wind advisory",
            "gale",
            "storm warning",
            "hurricane force wind",
            "sturm",
            "orkan",
            "windbö",
            "stürmische",
        ),
    ),
    ("lightning", ("lightning", "blitz")),
    ("snow_ice", ("snow", "ice", "blizzard", "freezing rain", "schnee", "glätte", "eis")),
    ("heat", ("heat", "hitze")),
    ("cold", ("cold", "frost", "kälte")),
    ("fog", ("fog", "nebel")),
    ("wildfire", ("fire weather", "red flag", "wildfire", "waldbrand")),
    ("avalanche", ("avalanche", "lawine")),
    ("coastal_event", ("coastal flood", "high surf", "coastal event", "küsten")),
)


def normalize_hazard_type(*values: Any) -> str:
    """Map provider event text to a stable WeatherRouter hazard type."""
    text = " ".join(str(value or "") for value in values).casefold()
    for hazard_type, needles in _HAZARD_PATTERNS:
        if any(needle in text for needle in needles):
            return hazard_type
    return "weather_warning"


_TORNADO_HAZARD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tornado": ("tornado", "windhose"),
    "waterspout": ("waterspout", "wasserhose"),
}


def tornado_semantic_class(hazard_type: Any) -> str | None:
    """Return the broad official Tornado/Waterspout alert class."""
    normalized = str(hazard_type or "").strip().casefold()
    if normalized == "tornado":
        return "official_tornado_alert_event"
    if normalized == "waterspout":
        return "official_waterspout_alert_event"
    return None


def tornado_hazard_match_scope(
    hazard_type: Any,
    *,
    event: Any = None,
    headline: Any = None,
    description: Any = None,
    instruction: Any = None,
) -> str | None:
    """Explain whether Tornado/Waterspout matching was explicit or contextual."""
    normalized = str(hazard_type or "").strip().casefold()
    needles = _TORNADO_HAZARD_KEYWORDS.get(normalized)
    if not needles:
        return None

    explicit_text = " ".join(
        str(value or "") for value in (event, headline)
    ).casefold()
    if any(needle in explicit_text for needle in needles):
        return "explicit_event"

    contextual_text = " ".join(
        str(value or "") for value in (description, instruction)
    ).casefold()
    if any(needle in contextual_text for needle in needles):
        return "contextual_text"
    return None


_HAIL_HAZARD_KEYWORDS: tuple[str, ...] = ("hail", "hagel")


def hail_semantic_class(*values: Any) -> str | None:
    """Return the broad official Hail alert class from real provider text."""
    text = " ".join(str(value or "") for value in values).casefold()
    if any(needle in text for needle in _HAIL_HAZARD_KEYWORDS):
        return "official_hail_alert_event"
    return None


def hail_hazard_match_scope(
    *,
    event: Any = None,
    headline: Any = None,
    description: Any = None,
    instruction: Any = None,
) -> str | None:
    """Explain whether Hail matching was explicit or only contextual."""
    explicit_text = " ".join(
        str(value or "") for value in (event, headline)
    ).casefold()
    if any(needle in explicit_text for needle in _HAIL_HAZARD_KEYWORDS):
        return "explicit_event"

    contextual_text = " ".join(
        str(value or "") for value in (description, instruction)
    ).casefold()
    if any(needle in contextual_text for needle in _HAIL_HAZARD_KEYWORDS):
        return "contextual_text"
    return None


_SUPERCELL_HAZARD_KEYWORDS: tuple[str, ...] = (
    "supercell",
    "superzelle",
)


def supercell_semantic_class(*values: Any) -> str | None:
    """Return broad official Supercell alert semantics from real provider text."""
    text = " ".join(str(value or "") for value in values).casefold()
    if any(needle in text for needle in _SUPERCELL_HAZARD_KEYWORDS):
        return "official_supercell_alert_event"
    return None


def supercell_hazard_match_scope(
    *,
    event: Any = None,
    headline: Any = None,
    description: Any = None,
    instruction: Any = None,
) -> str | None:
    """Explain whether Supercell evidence is explicit or contextual."""
    explicit_text = " ".join(
        str(value or "") for value in (event, headline)
    ).casefold()
    if any(needle in explicit_text for needle in _SUPERCELL_HAZARD_KEYWORDS):
        return "explicit_event"

    contextual_text = " ".join(
        str(value or "") for value in (description, instruction)
    ).casefold()
    if any(needle in contextual_text for needle in _SUPERCELL_HAZARD_KEYWORDS):
        return "contextual_text"
    return None


_FLOOD_SEMANTIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "official_levee_failure_alert_event",
        (
            "levee failure", "levee breach", "dike breach", "dyke breach",
            "dike failure", "dyke failure", "deichbruch", "deichversagen",
        ),
    ),
    (
        "official_dam_failure_alert_event",
        (
            "dam failure", "dam break", "dam breach", "reservoir failure",
            "dammbruch", "talsperrenbruch", "talsperrenversagen",
        ),
    ),
    (
        "official_glof_alert_event",
        (
            "glacial lake outburst flood", "glof", "gletscherseeausbruch",
            "gletschersee-ausbruch",
        ),
    ),
    (
        "official_ice_jam_flood_alert_event",
        (
            "ice jam flood", "ice jam", "eisstau-hochwasser", "eisstau",
        ),
    ),
    (
        "official_debris_flow_alert_event",
        (
            "debris flow", "mudflow", "mud flow", "mudslide", "mud slide",
            "mure", "schlammlawine", "schlammstrom", "geröllstrom",
        ),
    ),
    (
        "official_surface_water_flood_alert_event",
        (
            "surface water flood", "pluvial flood", "urban flooding", "urban flood",
            "oberflächenüberflutung", "oberflaechenueberflutung",
            "pluviales hochwasser", "straßenüberflutung", "strassenueberflutung",
        ),
    ),
    (
        "official_flash_flood_alert_event",
        ("flash flood", "sturzflut", "plötzliche überschwemm"),
    ),
)

_FLOOD_GENERIC_KEYWORDS: tuple[str, ...] = (
    "flood",
    "hochwasser",
    "überschwemm",
    "überflutung",
)

_FLOOD_GENERIC_EXCLUSIONS: tuple[str, ...] = (
    "coastal flood",
    "coastal flooding",
)


def _generic_flood_evidence(text: str) -> bool:
    """Match independent generic flood evidence without compound false positives."""
    cleaned = text
    for _semantic_class, needles in _FLOOD_SEMANTIC_KEYWORDS:
        for needle in needles:
            cleaned = cleaned.replace(needle, " ")
    for needle in _FLOOD_GENERIC_EXCLUSIONS:
        cleaned = cleaned.replace(needle, " ")
    return any(needle in cleaned for needle in _FLOOD_GENERIC_KEYWORDS)


def _flood_semantics_for_text(text: str, scope: str) -> list[dict[str, str]]:
    """Return all flood classes explicitly supported by one text scope."""
    result: list[dict[str, str]] = []
    for semantic_class, needles in _FLOOD_SEMANTIC_KEYWORDS:
        if any(needle in text for needle in needles):
            result.append(
                {
                    "semantic_class": semantic_class,
                    "match_scope": scope,
                }
            )
    if _generic_flood_evidence(text):
        result.append(
            {
                "semantic_class": "official_flood_alert_event",
                "match_scope": scope,
            }
        )
    return result


def flood_semantics(
    *,
    event: Any = None,
    headline: Any = None,
    description: Any = None,
    instruction: Any = None,
) -> list[dict[str, str]]:
    """Return paired multi-valued official flood semantics from real source text."""
    explicit_text = " ".join(
        str(value or "") for value in (event, headline)
    ).casefold()
    contextual_text = " ".join(
        str(value or "") for value in (description, instruction)
    ).casefold()

    result = _flood_semantics_for_text(explicit_text, "explicit_event")
    explicit_classes = {item["semantic_class"] for item in result}
    for item in _flood_semantics_for_text(contextual_text, "contextual_text"):
        if item["semantic_class"] not in explicit_classes:
            result.append(item)
    return result


_DOWNBURST_HAZARD_KEYWORDS: tuple[str, ...] = (
    "downburst",
    "microburst",
    "macroburst",
    "fallböe",
    "fallboe",
)

_BROAD_WIND_HAZARD_KEYWORDS: tuple[str, ...] = (
    "high wind",
    "wind warning",
    "wind advisory",
    "damaging wind",
    "destructive wind",
    "severe wind",
    "strong wind",
    "wind gust",
    "gale",
    "storm warning",
    "hurricane force wind",
    "orkan",
    "windbö",
    "sturmbö",
    "stürmische bö",
)


def _broad_wind_keyword_matches(text: str, needle: str) -> bool:
    """Match broad wind phrases without treating thunderstorm as storm."""
    if needle == "storm warning":
        normalized = " ".join(text.split())
        return " storm warning " in f" {normalized} "
    return needle in text


def wind_hazard_semantic_class(*values: Any) -> str | None:
    """Return specific Downburst or broad official wind-alert semantics."""
    text = " ".join(str(value or "") for value in values).casefold()
    if any(needle in text for needle in _DOWNBURST_HAZARD_KEYWORDS):
        return "official_downburst_alert_event"
    if any(
        _broad_wind_keyword_matches(text, needle)
        for needle in _BROAD_WIND_HAZARD_KEYWORDS
    ):
        return "official_wind_alert_event"
    return None


def wind_hazard_match_scope(
    *,
    event: Any = None,
    headline: Any = None,
    description: Any = None,
    instruction: Any = None,
) -> str | None:
    """Explain whether wind-hazard evidence is explicit or contextual."""
    semantic_class = wind_hazard_semantic_class(
        event,
        headline,
        description,
        instruction,
    )
    if semantic_class == "official_downburst_alert_event":
        needles = _DOWNBURST_HAZARD_KEYWORDS
        matcher = lambda text, needle: needle in text
    elif semantic_class == "official_wind_alert_event":
        needles = _BROAD_WIND_HAZARD_KEYWORDS
        matcher = _broad_wind_keyword_matches
    else:
        return None

    explicit_text = " ".join(
        str(value or "") for value in (event, headline)
    ).casefold()
    if any(matcher(explicit_text, needle) for needle in needles):
        return "explicit_event"

    contextual_text = " ".join(
        str(value or "") for value in (description, instruction)
    ).casefold()
    if any(matcher(contextual_text, needle) for needle in needles):
        return "contextual_text"
    return None


_TROPICAL_ALERT_WORDS = (
    " warning",
    " watch",
    " advisory",
    " outlook",
    " forecast",
)

# NOAA/NHC CurrentStorms.json uses compact classification codes rather than
# necessarily spelling out the lifecycle in full. Keep this mapping exact so
# short codes are never matched as arbitrary substrings in free text.
_TROPICAL_CLASSIFICATION_CODE_MAP: dict[str, tuple[str, str | None]] = {
    "PC": ("potential_tropical_cyclone", None),
    "TD": ("tropical_depression", None),
    "TS": ("tropical_storm", None),
    "HU": ("hurricane_strength_tropical_cyclone", "hurricane"),
    "MH": ("hurricane_strength_tropical_cyclone", "hurricane"),
    "STD": ("subtropical_cyclone", None),
    "STS": ("subtropical_cyclone", None),
    "SD": ("subtropical_cyclone", None),
    "SS": ("subtropical_cyclone", None),
    "PTC": ("post_tropical_cyclone", None),
    "TY": ("hurricane_strength_tropical_cyclone", "typhoon"),
}


def tropical_system_from_classification(
    value: Any,
    *,
    classification_source: str = "structured_provider_field",
    fallback_unspecified: bool = False,
) -> dict[str, str] | None:
    """Normalize source-reported tropical-system lifecycle without inventing intensity."""
    raw = str(value or "").strip()
    if not raw:
        return None
    text = raw.casefold()

    system_class: str | None = None
    regional_term: str | None = None

    code_match = _TROPICAL_CLASSIFICATION_CODE_MAP.get(raw.upper())
    if code_match is not None:
        system_class, regional_term = code_match
    elif "potential tropical cyclone" in text:
        system_class = "potential_tropical_cyclone"
    elif (
        "post-tropical" in text
        or "post tropical" in text
        or "remnant low" in text
        or "remnants" in text
    ):
        system_class = "post_tropical_cyclone"
    elif "subtropical" in text:
        system_class = "subtropical_cyclone"
    elif "tropical depression" in text:
        system_class = "tropical_depression"
    elif "tropical storm" in text:
        system_class = "tropical_storm"
    elif "hurricane" in text:
        system_class = "hurricane_strength_tropical_cyclone"
        regional_term = "hurricane"
    elif "typhoon" in text:
        system_class = "hurricane_strength_tropical_cyclone"
        regional_term = "typhoon"
    elif "severe tropical cyclone" in text:
        system_class = "hurricane_strength_tropical_cyclone"
        regional_term = "severe_tropical_cyclone"
    elif "tropical cyclone" in text:
        system_class = "tropical_cyclone_unspecified"
    elif fallback_unspecified:
        system_class = "tropical_cyclone_unspecified"

    if system_class is None:
        return None

    result = {
        "system_class": system_class,
        "source_classification": raw,
        "classification_source": classification_source,
    }
    if regional_term is not None:
        result["regional_term"] = regional_term
    return result


def tropical_system_from_explicit_text(
    event: Any = None,
    headline: Any = None,
) -> dict[str, str] | None:
    """Classify current tropical-system state only from explicit non-alert text."""
    text = " ".join(str(value or "").strip() for value in (event, headline)).strip()
    folded = f" {text.casefold()} "
    if not text or any(marker in folded for marker in _TROPICAL_ALERT_WORDS):
        return None
    return tropical_system_from_classification(
        text,
        classification_source="explicit_event_text",
        fallback_unspecified=False,
    )


def normalize_alert_stage(*values: Any) -> str:
    """Normalize broad official alert stages without inventing specificity."""
    text = " ".join(str(value or "") for value in values).casefold()
    if "warning" in text:
        return "warning"
    if "watch" in text:
        return "watch"
    if "outlook" in text:
        return "outlook"
    if "statement" in text or "update" in text:
        return "statement"
    return "unspecified"



_EARTHQUAKE_SEMANTIC_CLASSES = frozenset(
    {"seismic_catalog_earthquake_event", "disaster_awareness_earthquake_event"}
)
_EARTHQUAKE_CATALOG_SELECTIONS = frozenset({"all_day", "significant_month"})


def _earthquake_number(value: Any) -> float | int | None:
    """Return a finite source number without treating booleans as measurements."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    if isinstance(value, int):
        return value
    return number


def earthquake_semantics(
    semantic_class: str,
    *,
    catalog_selection: Any = None,
    magnitude: Any = None,
    magnitude_type: Any = None,
    depth_km: Any = None,
    felt_reports: Any = None,
    community_intensity_cdi: Any = None,
    instrumental_intensity_mmi: Any = None,
    pager_alert: Any = None,
    significance: Any = None,
    tsunami_flag: bool | None = None,
    source_status: Any = None,
    catalog_updated: Any = None,
    legacy_magnitude_display_band: Any = None,
) -> dict[str, Any]:
    """Build validated additive earthquake semantics without changing generic severity."""
    if semantic_class not in _EARTHQUAKE_SEMANTIC_CLASSES:
        raise ValueError(f"Unsupported earthquake semantic class: {semantic_class}")
    result: dict[str, Any] = {"semantic_class": semantic_class}
    if catalog_selection is not None:
        selection = str(catalog_selection).strip().casefold()
        if selection not in _EARTHQUAKE_CATALOG_SELECTIONS:
            raise ValueError(f"Unsupported earthquake catalog selection: {catalog_selection}")
        result["catalog_selection"] = selection
    for key, value in (
        ("magnitude", magnitude),
        ("depth_km", depth_km),
        ("felt_reports", felt_reports),
        ("community_intensity_cdi", community_intensity_cdi),
        ("instrumental_intensity_mmi", instrumental_intensity_mmi),
        ("significance", significance),
    ):
        number = _earthquake_number(value)
        if number is not None:
            result[key] = number
    for key, value in (
        ("magnitude_type", magnitude_type),
        ("pager_alert", pager_alert),
        ("source_status", source_status),
        ("catalog_updated", catalog_updated),
        ("legacy_magnitude_display_band", legacy_magnitude_display_band),
    ):
        text_value = str(value or "").strip()
        if text_value:
            result[key] = text_value.casefold() if key == "pager_alert" else text_value
    if tsunami_flag is not None:
        if not isinstance(tsunami_flag, bool):
            raise ValueError("earthquake tsunami_flag must be boolean or None")
        result["tsunami_flag"] = tsunami_flag
    return result


_VOLCANO_SEMANTIC_CLASSES = frozenset(
    {
        "weekly_volcanic_activity_report_event",
        "official_volcano_status_event",
        "disaster_awareness_volcanic_event",
        "seismic_catalog_volcanic_event",
    }
)


def volcano_semantics(
    semantic_class: str,
    *,
    report_type: Any = None,
    report_categories: Any = None,
    aviation_color_code: Any = None,
    volcano_alert_level: Any = None,
    smithsonian_vnum: Any = None,
    volcano_code: Any = None,
    observatory: Any = None,
    region: Any = None,
    nvews_threat: Any = None,
    notice_type: Any = None,
    source_event_type: Any = None,
    legacy_severity_band: Any = None,
) -> dict[str, Any]:
    """Build validated additive volcano semantics without collapsing source dimensions."""
    if semantic_class not in _VOLCANO_SEMANTIC_CLASSES:
        raise ValueError(f"Unsupported volcano semantic class: {semantic_class}")
    result: dict[str, Any] = {"semantic_class": semantic_class}
    for key, value in (
        ("report_type", report_type),
        ("aviation_color_code", aviation_color_code),
        ("volcano_alert_level", volcano_alert_level),
        ("smithsonian_vnum", smithsonian_vnum),
        ("volcano_code", volcano_code),
        ("observatory", observatory),
        ("region", region),
        ("nvews_threat", nvews_threat),
        ("notice_type", notice_type),
        ("source_event_type", source_event_type),
        ("legacy_severity_band", legacy_severity_band),
    ):
        text_value = str(value or "").strip()
        if text_value:
            result[key] = text_value
    if isinstance(report_categories, (list, tuple, set)):
        categories: list[str] = []
        for value in report_categories:
            text_value = str(value or "").strip()
            if text_value and text_value not in categories:
                categories.append(text_value)
        if categories:
            result["report_categories"] = categories
    return result


_TSUNAMI_SEMANTIC_CLASSES = frozenset(
    {
        "official_tsunami_warning_event",
        "tsunami_observation_event",
        "tsunami_potential_indicator_event",
        "disaster_awareness_tsunami_event",
    }
)
_TSUNAMI_ALERT_STAGES = frozenset(
    {
        "warning", "advisory", "watch", "threat", "marine_warning",
        "land_inundation_warning", "information", "no_threat", "canceled",
    }
)
_TSUNAMI_WAVE_EVIDENCE = frozenset({"expected", "observed", "mixed", "none"})


def tsunami_semantics(
    semantic_class: str,
    *,
    alert_stage: Any = None,
    source_alert_level: Any = None,
    active_threat: bool | None = None,
    wave_evidence: str | None = None,
) -> dict[str, Any]:
    """Build validated additive Tsunami semantics without changing generic alerts."""
    if semantic_class not in _TSUNAMI_SEMANTIC_CLASSES:
        raise ValueError(f"Unsupported tsunami semantic class: {semantic_class}")
    result: dict[str, Any] = {"semantic_class": semantic_class}
    if alert_stage is not None:
        stage = str(alert_stage).strip().casefold()
        if stage not in _TSUNAMI_ALERT_STAGES:
            raise ValueError(f"Unsupported tsunami alert stage: {alert_stage}")
        result["alert_stage"] = stage
    source_level = str(source_alert_level or "").strip()
    if source_level:
        result["source_alert_level"] = source_level
    if active_threat is not None:
        if not isinstance(active_threat, bool):
            raise ValueError("tsunami active_threat must be boolean or None")
        result["active_threat"] = active_threat
    if wave_evidence is not None:
        evidence = str(wave_evidence).strip().casefold()
        if evidence not in _TSUNAMI_WAVE_EVIDENCE:
            raise ValueError(f"Unsupported tsunami wave evidence: {wave_evidence}")
        result["wave_evidence"] = evidence
    return result


def normalize_severity(value: Any) -> str:
    """Normalize common warning severities without inventing precision."""
    text = str(value or "").strip().casefold()
    mapping = {
        "extreme": "extreme",
        "severe": "severe",
        "moderate": "moderate",
        "minor": "minor",
        "unknown": "unknown",
    }
    return mapping.get(text, "unknown")


def dwd_level_severity(value: Any) -> str:
    """Map documented DWD WarnWetter level integers to generic severity."""
    try:
        level = int(value)
    except (TypeError, ValueError):
        return "unknown"
    return {
        1: "minor",
        2: "moderate",
        3: "severe",
        4: "extreme",
    }.get(level, "unknown")


def _geometry_points(value: Any) -> Iterable[tuple[float, float]]:
    """Yield longitude/latitude coordinate pairs from nested GeoJSON coordinates."""
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _geometry_points(item)


def _point_in_ring(
    longitude: float,
    latitude: float,
    ring: list[Any] | tuple[Any, ...],
) -> bool:
    """Return whether one point lies inside one GeoJSON linear ring."""
    points = [
        (float(item[0]), float(item[1]))
        for item in ring
        if (
            isinstance(item, (list, tuple))
            and len(item) >= 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], (int, float))
        )
    ]
    if len(points) < 3:
        return False

    inside = False
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current

        # Treat a point on the polygon boundary as inside.
        cross = (longitude - x1) * (y2 - y1) - (latitude - y1) * (x2 - x1)
        if (
            abs(cross) <= 1e-10
            and min(x1, x2) - 1e-10 <= longitude <= max(x1, x2) + 1e-10
            and min(y1, y2) - 1e-10 <= latitude <= max(y1, y2) + 1e-10
        ):
            return True

        if (y1 > latitude) != (y2 > latitude):
            intersect_x = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < intersect_x:
                inside = not inside
        previous = current
    return inside


def point_in_geometry(
    geometry: dict[str, Any] | None,
    longitude: float,
    latitude: float,
) -> bool:
    """Return whether a point is contained in a Polygon/MultiPolygon geometry."""
    if not isinstance(geometry, dict):
        return False
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if geometry_type == "Polygon" and isinstance(coordinates, list):
        polygons = [coordinates]
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        polygons = coordinates
    else:
        return False

    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            continue
        outer = polygon[0]
        if not isinstance(outer, list) or not _point_in_ring(longitude, latitude, outer):
            continue
        holes = polygon[1:]
        if any(
            isinstance(hole, list) and _point_in_ring(longitude, latitude, hole)
            for hole in holes
        ):
            continue
        return True
    return False


def _longitude_inside_bbox(longitude: float, west: float, east: float) -> bool:
    """Return whether longitude lies in a normal or antimeridian-crossing bbox."""
    return (
        west <= longitude <= east
        if west <= east
        else longitude >= west or longitude <= east
    )


def _point_inside_bbox(
    longitude: float,
    latitude: float,
    bbox: tuple[float, float, float, float],
) -> bool:
    west, south, east, north = bbox
    return _longitude_inside_bbox(longitude, west, east) and south <= latitude <= north


def _geometry_rings(geometry: dict[str, Any]) -> Iterable[list[tuple[float, float]]]:
    """Yield validated rings from Polygon/MultiPolygon geometries."""
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, list):
        polygons = [coordinates]
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        polygons = coordinates
    else:
        return
    for polygon in polygons:
        if not isinstance(polygon, list):
            continue
        for ring in polygon:
            if not isinstance(ring, list):
                continue
            points = [
                (float(item[0]), float(item[1]))
                for item in ring
                if (
                    isinstance(item, (list, tuple))
                    and len(item) >= 2
                    and isinstance(item[0], (int, float))
                    and isinstance(item[1], (int, float))
                )
            ]
            if len(points) >= 2:
                yield points


def _segments_intersect(
    first_a: tuple[float, float],
    first_b: tuple[float, float],
    second_a: tuple[float, float],
    second_b: tuple[float, float],
) -> bool:
    """Return whether two closed two-dimensional line segments intersect."""
    def orientation(
        a: tuple[float, float],
        b: tuple[float, float],
        c: tuple[float, float],
    ) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(
        a: tuple[float, float],
        b: tuple[float, float],
        point: tuple[float, float],
    ) -> bool:
        return (
            min(a[0], b[0]) - 1e-10 <= point[0] <= max(a[0], b[0]) + 1e-10
            and min(a[1], b[1]) - 1e-10 <= point[1] <= max(a[1], b[1]) + 1e-10
            and abs(orientation(a, b, point)) <= 1e-10
        )

    o1 = orientation(first_a, first_b, second_a)
    o2 = orientation(first_a, first_b, second_b)
    o3 = orientation(second_a, second_b, first_a)
    o4 = orientation(second_a, second_b, first_b)

    if ((o1 > 0 > o2) or (o1 < 0 < o2)) and ((o3 > 0 > o4) or (o3 < 0 < o4)):
        return True
    return (
        on_segment(first_a, first_b, second_a)
        or on_segment(first_a, first_b, second_b)
        or on_segment(second_a, second_b, first_a)
        or on_segment(second_a, second_b, first_b)
    )


def geometry_intersects_bbox_strict(
    geometry: dict[str, Any] | None,
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    """Return a fail-closed Polygon/MultiPolygon intersection with a consumer bbox.

    Missing geometry is never treated as spatial evidence.  The implementation is
    intentionally dependency-free: it checks polygon vertices, consumer-bbox
    corners contained by the polygon and exact polygon-edge/rectangle-edge
    intersections.
    """
    if bbox is None:
        return True
    if not isinstance(geometry, dict):
        return False
    coordinates = geometry.get("coordinates")
    if coordinates is None:
        return False

    if any(_point_inside_bbox(lon, lat, bbox) for lon, lat in _geometry_points(coordinates)):
        return True

    west, south, east, north = bbox
    # Point-in-polygon corner checks are valid for normal bboxes.  Split an
    # antimeridian bbox into two normal bboxes before checking.
    boxes = (
        [(west, south, east, north)]
        if west <= east
        else [(west, south, 180.0, north), (-180.0, south, east, north)]
    )
    for part in boxes:
        pwest, psouth, peast, pnorth = part
        for lon, lat in (
            (pwest, psouth),
            (pwest, pnorth),
            (peast, psouth),
            (peast, pnorth),
        ):
            if point_in_geometry(geometry, lon, lat):
                return True

        rectangle_edges = (
            ((pwest, psouth), (peast, psouth)),
            ((peast, psouth), (peast, pnorth)),
            ((peast, pnorth), (pwest, pnorth)),
            ((pwest, pnorth), (pwest, psouth)),
        )
        for ring in _geometry_rings(geometry):
            previous = ring[-1]
            for current in ring:
                if any(
                    _segments_intersect(previous, current, edge_start, edge_end)
                    for edge_start, edge_end in rectangle_edges
                ):
                    return True
                previous = current
    return False


def geometry_intersects_bbox(
    geometry: dict[str, Any] | None,
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    """Backward-compatible conservative geometry/bbox check.

    Existing non-P3 callers historically keep events with missing geometry. New
    warning-routing code that needs spatial proof must use
    :func:`geometry_intersects_bbox_strict`.
    """
    if bbox is None or not isinstance(geometry, dict):
        return True
    coordinates = geometry.get("coordinates")
    if coordinates is None:
        return True
    return geometry_intersects_bbox_strict(geometry, bbox)
