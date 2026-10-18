"""Constants for WeatherRouter."""

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "weather_router"
NAME: Final = "WeatherRouter"
INTEGRATION_VERSION: Final = "0.10.0"
DEV_BUILD_VERSION: Final = "0.10.158"
DEV_LOADER_REV: Final = "0.10-loader-161"

# Internal Lab/diagnostic API contract.
API_CONTRACT_VERSION: Final = 1

# Separate public Consumer API contract.
CONSUMER_CONTRACT_NAME: Final = "weather_router.consumer"
CONSUMER_CONTRACT_VERSION: Final = 1

CONF_LOG_GIT_TOKEN: Final = "log_git_token"
CONF_LOG_GIT_BRANCH: Final = "log_git_branch"
LOG_GIT_REPOSITORY: Final = "TheDaimos/weather-router-dev"
LOG_GIT_ROOT: Final = ".weather-router/logs"

CONF_REFERENCE_LOCATION: Final = "reference_location"
DEFAULT_REFERENCE_LOCATION: Final = "zone.home"

CONF_ROUTER_ENABLED: Final = "router_enabled"
CONF_ENABLED_DOMAINS: Final = "enabled_domains"
CONF_ENABLED_PROVIDERS: Final = "enabled_providers"
CONF_CONSUMER_PROFILES: Final = "consumer_profiles"

ROUTER_DOMAINS: Final = {
    "weather": "Wetter",
    "pollen": "Pollen",
    "natural_hazards": "Naturgefahren",
    "civil_protection": "Bevölkerungsschutz",
    "security": "Öffentliche Sicherheit",
    "aviation": "Luftfahrtwarnungen",
    "space": "Sonne & Weltraum",
    "biological_hazards": "Biologische Gefahren & Wildtiere",
}

# Provider-neutral topic taxonomy below the coarse router domains. Topics are
# deliberately not new router domains: they describe what a provider/feed covers
# without multiplying global policy boundaries or breaking Consumer API V1.
ROUTER_TOPIC_GROUPS: Final = {
    "weather": {
        "name": "Wetter",
        "domain": "weather",
        "topics": {
            "precipitation": "Niederschlag",
            "wind": "Wind",
            "clouds": "Wolken",
            "snow_ice": "Schnee / Eis",
            "temperature": "Temperatur",
            "uv": "UV",
            "visibility_fog": "Sicht / Nebel",
            "humidity": "Luftfeuchte",
            "air_pressure": "Luftdruck",
            "dew_point": "Taupunkt",
            "weather_condition": "Wetterzustand",
            "weather_warning": "Wetterwarnungen",
            "satellite_imagery": "Satellitenbilder",
            "weather_model_data": "Wettermodelldaten",
            "lightning_observation": "Blitzbeobachtung",
        },
    },
    "convective_hazards": {
        "name": "Unwetter / Konvektive Gefahren",
        "domain": "natural_hazards",
        "topics": {
            "thunderstorm": "Gewitter",
            "tornado": "Tornado / Windhose",
            "hail": "Hagel",
            "severe_wind": "Starkwind / Downburst",
            "supercell": "Superzelle",
        },
    },
    "hydrology": {
        "name": "Hochwasser & Hydrologie",
        "domain": "natural_hazards",
        "topics": {
            "flood": "Hochwasser",
            "heavy_rain_flash_flood": "Starkregen / Sturzflut",
        },
    },
    "geophysical": {
        "name": "Geophysikalische Gefahren",
        "domain": "natural_hazards",
        "topics": {
            "tsunami": "Tsunami",
            "earthquake": "Erdbeben",
            "volcanism": "Vulkanismus",
            "seismic_activity": "Weitere seismische Aktivität",
        },
    },
    "general_hazards": {
        "name": "Weitere Naturgefahren",
        "domain": "natural_hazards",
        "topics": {
            "disaster_awareness": "Globale Gefahrenlage",
        },
    },
    "tropical_systems": {
        "name": "Tropische Systeme",
        "domain": "natural_hazards",
        "topics": {
            "tropical_systems": "Tropische Systeme",
        },
    },
    "pollen": {
        "name": "Pollen",
        "domain": "pollen",
        "topics": {
            "pollen": "Pollen",
        },
    },
    "space_weather": {
        "name": "Weltraum & Astronomie",
        "domain": "space",
        "topics": {
            "space_weather": "Weltraumwetter",
            "astronomy": "Astronomie",
            "earth_observation": "Erdbeobachtung aus dem All",
        },
    },
    "aviation": {
        "name": "Luftfahrt",
        "domain": "aviation",
        "topics": {
            "aviation": "Luftfahrt",
        },
    },
    "civil_protection": {
        "name": "Bevölkerungsschutz",
        "domain": "civil_protection",
        "topics": {
            "civil_protection": "Bevölkerungsschutz",
        },
    },
    "security": {
        "name": "Sicherheit",
        "domain": "security",
        "topics": {
            "security": "Sicherheit",
        },
    },
    "biological_hazards": {
        "name": "Biologische Gefahren",
        "domain": "biological_hazards",
        "topics": {
            "biological_hazards": "Biologische Gefahren",
        },
    },
}

ROUTER_TOPICS: Final = {
    topic_id: {
        "name": topic_name,
        "group": group_id,
        "group_name": group["name"],
        "domain": group["domain"],
    }
    for group_id, group in ROUTER_TOPIC_GROUPS.items()
    for topic_id, topic_name in group["topics"].items()
}

# Preserve the previously accepted provider set on upgrades. Providers introduced
# after this checkpoint are deliberately opt-in and therefore do not create new
# network traffic merely because WeatherRouter was updated.
DEFAULT_ENABLED_PROVIDER_IDS: Final = (
    "open_meteo",
    "rainviewer",
    "dwd",
    "nasa_gibs",
    "eumetview",
    "met_norway",
    "noaa_nws",
    "noaa_swpc",
    "nasa_iss",
    "nasa_moon",
    "fmi",
    "smhi",
    "eccc_geomet",
    "jma",
    "ecmwf_open_data",
    "nhc_tropical_cyclones",
    "noaa_tsunami",
    "bmkg_tsunami",
    "bom_tsunami",
    "usgs_earthquakes",
    "smithsonian_volcanoes",
    "usgs_volcanoes",
)

# Existing accepted functional areas stay active by default. Newer Pollen,
# civil-protection/security/aviation and biological-hazards routing is opt-in.
DEFAULT_ENABLED_DOMAINS: Final = (
    "weather",
    "natural_hazards",
    "space",
)

# Initial discovery is deliberately restricted to Home Assistant people and zones.
# Arbitrary device_trackers are not listed automatically because many installations
# contain a large number of technical trackers. Explicit coordinate/profile support
# can be added later without changing this baseline contract.
LOCATION_DISCOVERY_DOMAINS: Final = ("person", "zone")
LOCATION_DOMAINS: Final = LOCATION_DISCOVERY_DOMAINS

DEFAULT_OPTIONS: Final = {
    CONF_REFERENCE_LOCATION: DEFAULT_REFERENCE_LOCATION,
    CONF_ROUTER_ENABLED: True,
    CONF_ENABLED_DOMAINS: list(DEFAULT_ENABLED_DOMAINS),
    CONF_ENABLED_PROVIDERS: list(DEFAULT_ENABLED_PROVIDER_IDS),
    CONF_CONSUMER_PROFILES: {},
}

PLATFORMS: Final = (Platform.SELECT,)
