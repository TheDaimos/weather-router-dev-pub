#!/usr/bin/env python3
"""Fail-closed structural checks for the WeatherRouter V0.10 TEST source tree."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "weather_router"
FRONTEND = INTEGRATION / "frontend"
PROVIDERS = INTEGRATION / "providers"
CONSUMER_V1 = ROOT / "contracts" / "consumer_v1"
DIAGNOSTICS_CONTRACT = ROOT / "contracts" / "diagnostics"

REQUIRED_FILES = (
    INTEGRATION / "__init__.py",
    INTEGRATION / "config_flow.py",
    INTEGRATION / "const.py",
    INTEGRATION / "diagnostics.py",
    INTEGRATION / "routing_diagnostic_core.py",
    INTEGRATION / "routing_diagnostics.py",
    INTEGRATION / "manifest.json",
    INTEGRATION / "select.py",
    INTEGRATION / "strings.json",
    INTEGRATION / "websocket_api.py",
    INTEGRATION / "consumer_api.py",
    INTEGRATION / "consumer_profiles.py",
    INTEGRATION / "spatial_coverage.py",
    INTEGRATION / "consumer_capability_map.json",
    INTEGRATION / "provider_time_contracts.v1.json",
    INTEGRATION / "consumer_hazard_event_types.json",
    PROVIDERS / "__init__.py",
    INTEGRATION / "extensions.py",
    PROVIDERS / "registry.json",
    PROVIDERS / "open_meteo.py",
    PROVIDERS / "open_meteo_pollen.py",
    PROVIDERS / "rainviewer.py",
    PROVIDERS / "dwd.py",
    PROVIDERS / "wms_satellite.py",
    PROVIDERS / "nasa_gibs.py",
    PROVIDERS / "eumetview.py",
    PROVIDERS / "met_norway.py",
    PROVIDERS / "noaa_nws.py",
    PROVIDERS / "noaa_swpc.py",
    PROVIDERS / "nasa_iss.py",
    PROVIDERS / "nasa_moon.py",
    PROVIDERS / "met_norway_astronomy.py",
    PROVIDERS / "fmi.py",
    PROVIDERS / "smhi.py",
    PROVIDERS / "eccc_geomet.py",
    PROVIDERS / "jma.py",
    PROVIDERS / "ecmwf_open_data.py",
    PROVIDERS / "hazard_common.py",
    PROVIDERS / "nhc_tropical_cyclones.py",
    PROVIDERS / "noaa_tsunami.py",
    PROVIDERS / "bmkg_tsunami.py",
    PROVIDERS / "bom_tsunami.py",
    PROVIDERS / "usgs_earthquakes.py",
    PROVIDERS / "smithsonian_volcanoes.py",
    PROVIDERS / "usgs_volcanoes.py",
    PROVIDERS / "bbk_warning_common.py",
    PROVIDERS / "bbk_mowas.py",
    PROVIDERS / "bbk_police.py",
    PROVIDERS / "nina_supplementary.py",
    PROVIDERS / "gdacs.py",
    PROVIDERS / "glofas.py",
    PROVIDERS / "gbif_biodiversity.py",
    PROVIDERS / "eccc_lightning.py",
    PROVIDERS / "noaa_goes_glm.py",
    PROVIDERS / "eumetsat_mtg_li.py",
    PROVIDERS / "fmi_lightning.py",
    PROVIDERS / "biological_taxa.json",
    PROVIDERS / "usgs_seismic_events.py",
    PROVIDERS / "aviation_weather.py",
    FRONTEND / "weather-router-lab.js",
    FRONTEND / "weather-router-lab-map-workspace.js",
    FRONTEND / "weather-router-lab-log-export.js",
    FRONTEND / "weather-router-lab-timeline.js",
    FRONTEND / "weather-router-lab-raster-stability.js",
    FRONTEND / "weather-router-lab-frame-buffer.js",
    FRONTEND / "weather-router-lab-legends.js",
    FRONTEND / "weather-router-lab-diagnostics.js",
    FRONTEND / "weather-router-lab-hazards.js",
    FRONTEND / "weather-router-lab-routing.js",
    FRONTEND / "weather-router-lab-consumer-api.js",
    FRONTEND / "weather-router-lab-routing-diagnostics.js",
    FRONTEND / "weather-router-lab-biological.js",
    FRONTEND / "weather-router-lab-dev-loader.js",
    INTEGRATION / "translations" / "de.json",
    INTEGRATION / "translations" / "en.json",
    ROOT / "docs" / "CONSUMER_API_V1.md",
    ROOT / "docs" / "CONSUMER_PROFILES_V1.md",
    CONSUMER_V1 / "README.md",
    CONSUMER_V1 / "discovery.response.schema.json",
    CONSUMER_V1 / "capabilities.request.schema.json",
    CONSUMER_V1 / "capabilities.response.schema.json",
    CONSUMER_V1 / "resolve.request.schema.json",
    CONSUMER_V1 / "resolve.response.schema.json",
    CONSUMER_V1 / "capability-map.draft.json",
    CONSUMER_V1 / "hazard-event-types.v1.json",
    CONSUMER_V1 / "consumer-profile.schema.json",
    CONSUMER_V1 / "resources" / "value.schema.json",
    CONSUMER_V1 / "resources" / "raster_tile.schema.json",
    CONSUMER_V1 / "resources" / "hazard_feed.schema.json",
    CONSUMER_V1 / "resources" / "event_feed.schema.json",
    CONSUMER_V1 / "resources" / "image_sequence.schema.json",
    CONSUMER_V1 / "resources" / "live_stream.schema.json",
    CONSUMER_V1 / "resources" / "planetary_tile.schema.json",
    CONSUMER_V1 / "resources" / "data_file.schema.json",
    ROOT / "tests" / "test_spatial_coverage.py",
    ROOT / "tests" / "test_routing_diagnostic_core.py",
    DIAGNOSTICS_CONTRACT / "README.md",
    DIAGNOSTICS_CONTRACT / "routing_diagnostic.v1.schema.json",
    DIAGNOSTICS_CONTRACT / "routing_diagnostics.request.schema.json",
    DIAGNOSTICS_CONTRACT / "routing_diagnostics.index.v1.schema.json",
    DIAGNOSTICS_CONTRACT / "routing_diagnostics_clear.request.schema.json",
    DIAGNOSTICS_CONTRACT / "routing_diagnostics_clear.response.schema.json",
    DIAGNOSTICS_CONTRACT / "routing_diagnostics_subscribe.request.schema.json",
    DIAGNOSTICS_CONTRACT / "routing_diagnostic.event.v1.schema.json",
    ROOT / "docs" / "DIAGNOSTICS.md",
)


def main() -> None:
    """Validate the current source tree without importing Home Assistant."""
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing required files: {', '.join(missing)}")

    for path in INTEGRATION.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    consumer_api_source = (INTEGRATION / "consumer_api.py").read_text(encoding="utf-8")
    for marker in (
        "_generic_hazard_type_for_public_id",
        "provider_hazard_type",
        "hazard_type_fallback",
    ):
        if marker not in consumer_api_source:
            raise SystemExit(f"Consumer unknown-hazard fallback missing marker: {marker}")

    for marker in (
        "weather_router/consumer/discovery",
        "weather_router/consumer/capabilities",
        "weather_router/consumer/resolve",
        "CONSUMER_CONTRACT_VERSION",
        "CandidateUnavailable",
        'vol.Required("capability")',
        "_candidate_enabled",
        "_validate_mapping_against_providers",
        "_resolve_aggregate_hazard",
        "aggregate_eligible_sources",
        "_catalog_filter",
        "_catalog_row_matches",
        "filter_options",
        "phenomena",
        "event_filter",
        "_filter_hazard_payload",
        "_validate_hazard_mapping",
        "profile_id",
        "profile_filtered",
        "profile_allows_provider",
        "consumer_capability_map.json",
        "consumer_hazard_event_types.json",
        'payload["legend"]',
        "normalized_legend",
    ):
        if marker not in consumer_api_source:
            raise SystemExit(f"Consumer API missing marker: {marker}")

    runtime_capability_map = json.loads(
        (INTEGRATION / "consumer_capability_map.json").read_text(encoding="utf-8")
    )
    draft_capability_map = json.loads(
        (CONSUMER_V1 / "capability-map.draft.json").read_text(encoding="utf-8")
    )
    if runtime_capability_map != draft_capability_map:
        raise SystemExit(
            "runtime consumer capability map differs from contract draft"
        )

    runtime_hazard_taxonomy = json.loads(
        (INTEGRATION / "consumer_hazard_event_types.json").read_text(encoding="utf-8")
    )
    draft_hazard_taxonomy = json.loads(
        (CONSUMER_V1 / "hazard-event-types.v1.json").read_text(encoding="utf-8")
    )
    if runtime_hazard_taxonomy != draft_hazard_taxonomy:
        raise SystemExit(
            "runtime consumer hazard taxonomy differs from contract draft"
        )
    if runtime_hazard_taxonomy.get("schema") != "weather_router.consumer.hazard_event_types.v1":
        raise SystemExit("consumer hazard taxonomy: unexpected schema")
    hazard_types = runtime_hazard_taxonomy.get("hazard_types")
    if not isinstance(hazard_types, dict):
        raise SystemExit("consumer hazard taxonomy: hazard_types must be an object")
    for expected_type in (
        "severe_thunderstorm",
        "windstorm",
        "heavy_rain",
        "snow_ice",
        "hail",
        "tornado",
        "downburst",
        "supercell",
        "lightning",
        "flood",
        "surface_water_flood",
        "debris_flow",
        "levee_failure",
        "dam_failure",
        "glacial_lake_outburst_flood",
        "ice_jam_flood",
        "tsunami",
        "earthquake",
        "volcanic_activity",
        "public_safety",
        "civil_protection",
        "aviation_warning",
    ):
        if expected_type not in hazard_types:
            raise SystemExit(
                f"consumer hazard taxonomy missing expected type: {expected_type}"
            )

    consumer_doc = (ROOT / "docs" / "CONSUMER_API_V1.md").read_text(encoding="utf-8")
    for marker in (
        "PRESENT",
        "COMPATIBLE",
        "READY",
        "CAPABLE",
        "weather_router/consumer/discovery",
        "weather_router/consumer/capabilities",
        "weather_router/consumer/resolve",
        "weather.radar.precipitation",
        '"status": "unavailable"',
        "Provider-Credentials",
    ):
        if marker not in consumer_doc:
            raise SystemExit(f"Consumer API V1 draft missing marker: {marker}")

    consumer_schema_expectations = {
        "discovery.response.schema.json": "weather_router.consumer.discovery.v1",
        "capabilities.request.schema.json": "weather_router.consumer.capabilities.request.v1",
        "capabilities.response.schema.json": "weather_router.consumer.capabilities.v1",
        "resolve.request.schema.json": "weather_router.consumer.resolve.request.v1",
        "resolve.response.schema.json": "weather_router.consumer.resolution.v1",
        "consumer-profile.schema.json": "weather_router.consumer.profile.v1",
    }
    for filename, schema_id in consumer_schema_expectations.items():
        path = CONSUMER_V1 / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("$id") != schema_id:
            raise SystemExit(f"{filename}: unexpected $id")
        if payload.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise SystemExit(f"{filename}: expected JSON Schema draft 2020-12")

    resolve_request = json.loads(
        (CONSUMER_V1 / "resolve.request.schema.json").read_text(encoding="utf-8")
    )
    if "provider" in resolve_request.get("properties", {}):
        raise SystemExit("Consumer resolve request must remain provider-neutral")
    if "profile_id" not in resolve_request.get("properties", {}):
        raise SystemExit("Consumer resolve request missing optional profile_id")
    capabilities_request = json.loads(
        (CONSUMER_V1 / "capabilities.request.schema.json").read_text(encoding="utf-8")
    )
    if "profile_id" not in capabilities_request.get("properties", {}):
        raise SystemExit("Consumer capabilities request missing optional profile_id")

    event_filter = resolve_request.get("properties", {}).get("event_filter")
    if not isinstance(event_filter, dict):
        raise SystemExit("Consumer resolve request missing event_filter contract")
    event_filter_properties = event_filter.get("properties", {})
    for field in ("hazard_types", "severities"):
        if field not in event_filter_properties:
            raise SystemExit(
                f"Consumer resolve event_filter missing {field}"
            )

    resolve_response = json.loads(
        (CONSUMER_V1 / "resolve.response.schema.json").read_text(encoding="utf-8")
    )
    capability_response = json.loads(
        (CONSUMER_V1 / "capabilities.response.schema.json").read_text(encoding="utf-8")
    )
    capability_item_properties = (
        capability_response
        .get("properties", {})
        .get("capabilities", {})
        .get("items", {})
        .get("properties", {})
    )
    if "event_filter_options" not in capability_item_properties:
        raise SystemExit("Consumer capability response missing event_filter_options")

    hazard_resource = json.loads(
        (CONSUMER_V1 / "resources" / "hazard_feed.schema.json").read_text(encoding="utf-8")
    )
    hazard_resource_properties = hazard_resource.get("properties", {})
    for field in (
        "event_count",
        "unfiltered_event_count",
        "event_filter",
        "filtered",
        "source_count",
        "matched_source_count",
    ):
        if field not in hazard_resource_properties:
            raise SystemExit(
                f"Consumer hazard resource missing filter field: {field}"
            )

    response_properties = resolve_response.get("properties", {})
    if "profile" not in response_properties:
        raise SystemExit("Consumer resolve response missing profile metadata")
    if "profile" not in capability_response.get("properties", {}):
        raise SystemExit("Consumer capability response missing profile metadata")
    unavailable_codes = set(
        response_properties.get("unavailable", {})
        .get("properties", {})
        .get("code", {})
        .get("enum", [])
    )
    for expected_code in ("profile_not_available", "profile_filtered"):
        if expected_code not in unavailable_codes:
            raise SystemExit(f"Consumer resolve response missing {expected_code}")
    for required_property in ("resource", "provenance", "routing", "unavailable"):
        if required_property not in response_properties:
            raise SystemExit(
                f"Consumer resolve response missing {required_property}"
            )

    resource_schema_ids = {
        "value.schema.json": "weather_router.consumer.resource.value.v1",
        "raster_tile.schema.json": "weather_router.consumer.resource.raster_tile.v1",
        "hazard_feed.schema.json": "weather_router.consumer.resource.hazard_feed.v1",
        "image_sequence.schema.json": "weather_router.consumer.resource.image_sequence.v1",
        "live_stream.schema.json": "weather_router.consumer.resource.live_stream.v1",
        "planetary_tile.schema.json": "weather_router.consumer.resource.planetary_tile.v1",
        "data_file.schema.json": "weather_router.consumer.resource.data_file.v1",
    }
    for filename, schema_id in resource_schema_ids.items():
        payload = json.loads(
            (CONSUMER_V1 / "resources" / filename).read_text(encoding="utf-8")
        )
        if payload.get("$id") != schema_id:
            raise SystemExit(f"{filename}: unexpected resource $id")

    response_text = json.dumps(resolve_response, ensure_ascii=False)
    for resource_file in resource_schema_ids:
        expected_ref = f"resources/{resource_file}"
        if expected_ref not in response_text:
            raise SystemExit(
                f"resolve response missing resource schema reference: {expected_ref}"
            )

    const_source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "0.10.0":
        raise SystemExit("manifest version must remain the accepted 0.10.0 integration baseline")
    if 'INTEGRATION_VERSION: Final = "0.10.0"' not in const_source:
        raise SystemExit("const.py integration version differs from manifest baseline")

    dev_build_match = re.search(
        r'DEV_BUILD_VERSION: Final = "([^"]+)"',
        const_source,
    )
    dev_loader_match = re.search(
        r'DEV_LOADER_REV: Final = "([^"]+)"',
        const_source,
    )
    if dev_build_match is None or dev_loader_match is None:
        raise SystemExit("const.py missing DEV build/loader revision")
    expected_dev_build = dev_build_match.group(1)
    expected_dev_loader = dev_loader_match.group(1)

    expected = {
        "domain": "weather_router",
        "name": "WeatherRouter",
        "config_flow": True,
        "integration_type": "service",
        "single_config_entry": True,
        "version": "0.10.0",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise SystemExit(f"manifest.json: expected {key}={value!r}")

    required_dependencies = {"frontend", "http", "websocket_api"}
    if set(manifest.get("dependencies", [])) != required_dependencies:
        raise SystemExit("manifest.json: unexpected V0.10 dependencies")

    if '"pollen": "Pollen"' not in const_source:
        raise SystemExit("const.py: dedicated pollen router domain missing")
    if '"biological_hazards": "Biologische Gefahren & Wildtiere"' not in const_source:
        raise SystemExit("const.py: biological hazards router domain missing")
    for marker in (
        "ROUTER_TOPIC_GROUPS",
        "ROUTER_TOPICS",
        '"convective_hazards"',
        '"thunderstorm": "Gewitter"',
        '"tornado": "Tornado / Windhose"',
        '"hail": "Hagel"',
        '"severe_wind": "Starkwind / Downburst"',
        '"supercell": "Superzelle"',
    ):
        if marker not in const_source:
            raise SystemExit(f"const.py: convective topic taxonomy missing marker: {marker}")

    for marker in (
        "API_CONTRACT_VERSION",
        "CONF_ROUTER_ENABLED",
        "CONF_ENABLED_DOMAINS",
        "CONF_ENABLED_PROVIDERS",
        "ROUTER_DOMAINS",
        "DEFAULT_ENABLED_PROVIDER_IDS",
        "DEFAULT_ENABLED_DOMAINS",
        "INTEGRATION_VERSION",
        "CONSUMER_CONTRACT_NAME",
        "CONSUMER_CONTRACT_VERSION",
    ):
        if marker not in const_source:
            raise SystemExit(f"const.py: missing router marker: {marker}")

    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    if "config" not in strings or "entity" not in strings:
        raise SystemExit("strings.json: missing config/entity sections")

    for language in ("de", "en"):
        path = INTEGRATION / "translations" / f"{language}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "config" not in payload or "entity" not in payload:
            raise SystemExit(f"{path}: missing config/entity translation sections")

    biological_catalog = json.loads(
        (PROVIDERS / "biological_taxa.json").read_text(encoding="utf-8")
    )
    if biological_catalog.get("schema_version") != 1:
        raise SystemExit("biological taxon catalog: unexpected schema")
    biological_taxa = biological_catalog.get("taxa")
    if not isinstance(biological_taxa, list) or len(biological_taxa) != 88:
        raise SystemExit("biological taxon catalog: expected 88 taxa")
    biological_ids = [item.get("id") for item in biological_taxa if isinstance(item, dict)]
    biological_names = [
        item.get("scientific_name") for item in biological_taxa if isinstance(item, dict)
    ]
    if len(set(biological_ids)) != 88 or None in biological_ids:
        raise SystemExit("biological taxon catalog: ids must be unique")
    if len(set(biological_names)) != 88 or None in biological_names:
        raise SystemExit("biological taxon catalog: scientific names must be unique")
    plant_homonyms = {
        item.get("id"): (
            item.get("match_rank"),
            item.get("match_kingdom"),
            item.get("match_authorship"),
        )
        for item in biological_taxa
        if isinstance(item, dict) and item.get("id") in {"foxglove", "yew"}
    }
    if plant_homonyms != {
        "foxglove": ("GENUS", "Plantae", "L."),
        "yew": ("GENUS", "Plantae", "L."),
    }:
        raise SystemExit("biological taxon catalog: plant homonym hints missing")
    expected_biological_groups = {
        "predator",
        "large_wildlife",
        "crocodilian",
        "marine",
        "marine_venomous",
        "snake",
        "venomous_snake",
        "venomous_arthropod",
        "poisonous_amphibian",
        "toxic_plant",
        "toxic_fungus",
        "vector",
    }
    if {
        item.get("group") for item in biological_taxa if isinstance(item, dict)
    } - expected_biological_groups:
        raise SystemExit("biological taxon catalog: unknown group")

    gbif_source = (PROVIDERS / "gbif_biodiversity.py").read_text(encoding="utf-8")
    for marker in (
        "https://api.gbif.org/v2/species/match",
        "7ddf754f-d193-4cc9-b351-99906754a03b",
        "https://api.gbif.org/v2/map/occurrence/adhoc",
        "occurrence_density",
        "Catalogue of Life Extended Release",
        "wr-0.10.73-gbif-bio-3",
        "\"kingdom\"",
        "\"taxonRank\"",
        "\"scientificNameAuthorship\"",
        '"population_density": False',
        '"risk_probability": False',
        "async_get_taxon_layer",
        "hasGeospatialIssue",
    ):
        if marker not in gbif_source:
            raise SystemExit(f"GBIF biodiversity provider missing marker: {marker}")

    extension_loader_source = (INTEGRATION / "extensions.py").read_text(encoding="utf-8")
    for marker in (
        'EXTENSION_ROOT = Path("/config/.weather-router/extensions")',
        'EXTENSION_SCHEMA = "weather_router.extension.v1"',
        "extension_provider_catalog",
        "merge_extension_capability_map",
        "async_setup_extensions",
        "async_notify_routing_changed",
        "async_unload_extensions",
        "extension provider collides with base mapping",
        "_provider_is_visible",
        "if not _provider_is_visible(provider):",
    ):
        if marker not in extension_loader_source:
            raise SystemExit(f"generic extension loader missing marker: {marker}")

    dwd_source = (PROVIDERS / "dwd.py").read_text(encoding="utf-8")
    for marker in (
        "async def async_get_coverage",
        "wms_layer_geographic_coverage",
        "machine_coverage",
        "_async_layer_specific_coverage",
        "layer_specific_wms",
    ):
        if marker not in dwd_source:
            raise SystemExit(f"DWD raster coverage contract missing marker: {marker}")

    spatial_source = (INTEGRATION / "spatial_coverage.py").read_text(encoding="utf-8")
    for marker in (
        "coverage_matches_context",
        "bbox_intersects",
        "_longitude_segments",
        "wms_layer_geographic_coverage",
        'crs != "CRS:84"',
    ):
        if marker not in spatial_source:
            raise SystemExit(f"spatial coverage helper missing marker: {marker}")

    for marker in (
        "_raster_machine_coverage",
        'getattr(candidate.provider, "async_get_coverage", None)',
        '"outside_coverage"',
        'result["machine_coverage"] = machine_coverage',
        '"spatial_coverage"',
    ):
        if marker not in consumer_api_source:
            raise SystemExit(f"Consumer raster coverage routing missing marker: {marker}")

    official_lightning_sources = {
        "fmi_lightning.py": (
            "fmi::observations::lightning::multipointcoverage",
            "opendata.fmi.fi",
            "event_feed",
            "peak_current",
            "cloud_indicator",
        ),
        "eumetsat_mtg_li.py": (
            "view.eumetsat.int",
            "MTG Lightning Imager",
            "EO:EUM:DAT:0686",
            "EO:EUM:DAT:0691",
            "ground_strike_confirmation",
        ),
        "noaa_goes_glm.py": (
            "GLM-L2-LCFA",
            "noaa-goes19",
            "noaa-goes18",
            "async_get_data_file",
            "ground_strike_confirmation",
        ),
        "eccc_lightning.py": (
            "Lightning_2.5km_Density",
            "geo.weather.gc.ca",
            "observed_flash_density",
            "includes_cloud_to_ground",
            "includes_intra_cloud",
        ),
    }
    for filename, markers in official_lightning_sources.items():
        source = (PROVIDERS / filename).read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                raise SystemExit(
                    f"official lightning provider {filename} missing marker: {marker}"
                )

    registry = json.loads((PROVIDERS / "registry.json").read_text(encoding="utf-8"))
    if registry.get("schema_version") != 1:
        raise SystemExit("provider registry: expected schema_version=1")
    registered = {
        (item.get("module"), item.get("class"))
        for item in registry.get("providers", [])
        if isinstance(item, dict)
    }
    for expected_provider in (
        ("open_meteo", "OpenMeteoProvider"),
        ("open_meteo_pollen", "OpenMeteoPollenProvider"),
        ("rainviewer", "RainViewerProvider"),
        ("dwd", "DwdProvider"),
        ("nasa_gibs", "NasaGibsProvider"),
        ("eumetview", "EumetViewProvider"),
        ("met_norway", "MetNorwayProvider"),
        ("noaa_nws", "NoaaNwsProvider"),
        ("noaa_swpc", "NoaaSwpcProvider"),
        ("nasa_iss", "NasaIssProvider"),
        ("nasa_moon", "NasaMoonProvider"),
        ("met_norway_astronomy", "MetNorwayAstronomyProvider"),
        ("fmi", "FmiProvider"),
        ("smhi", "SmhiProvider"),
        ("eccc_geomet", "EcccGeometProvider"),
        ("jma", "JmaProvider"),
        ("ecmwf_open_data", "EcmwfOpenDataProvider"),
        ("nhc_tropical_cyclones", "NhcTropicalCycloneProvider"),
        ("noaa_tsunami", "NoaaTsunamiProvider"),
        ("bmkg_tsunami", "BmkgTsunamiProvider"),
        ("bom_tsunami", "BomTsunamiProvider"),
        ("usgs_earthquakes", "UsgsEarthquakeProvider"),
        ("smithsonian_volcanoes", "SmithsonianVolcanoProvider"),
        ("usgs_volcanoes", "UsgsVolcanoProvider"),
        ("gdacs", "GdacsProvider"),
        ("glofas", "GlofasProvider"),
        ("gbif_biodiversity", "GbifBiodiversityProvider"),
        ("usgs_seismic_events", "UsgsSeismicEventsProvider"),
        ("bbk_mowas", "BbkMowasProvider"),
        ("bbk_police", "BbkPoliceProvider"),
        ("aviation_weather", "AviationWeatherProvider"),
        ("nina_supplementary", "NinaFloodProvider"),
        ("nina_supplementary", "NinaKatwarnProvider"),
        ("nina_supplementary", "NinaBiwappProvider"),
        ("fmi_lightning", "FmiLightningProvider"),
        ("eumetsat_mtg_li", "EumetsatMtgLiProvider"),
        ("noaa_goes_glm", "NoaaGoesGlmProvider"),
        ("eccc_lightning", "EcccLightningProvider"),
    ):
        if expected_provider not in registered:
            raise SystemExit(f"provider registry missing {expected_provider}")

    provider_entries = registry.get("providers", [])
    if len(provider_entries) != 38:
        raise SystemExit(f"provider registry: expected 38 providers, got {len(provider_entries)}")

    registry_by_module_for_topics = {
        item.get("module"): item
        for item in provider_entries
        if isinstance(item, dict)
    }
    expected_convective_topics = {
        "thunderstorm",
        "tornado",
        "hail",
        "severe_wind",
    }
    for provider_id in ("dwd", "noaa_nws"):
        if set(registry_by_module_for_topics.get(provider_id, {}).get("topics", [])) != expected_convective_topics:
            raise SystemExit(
                f"provider registry: {provider_id} convective topic metadata incomplete"
            )
    for provider_id in (
        "fmi_lightning",
        "eumetsat_mtg_li",
        "noaa_goes_glm",
        "eccc_lightning",
    ):
        if registry_by_module_for_topics.get(provider_id, {}).get("topics"):
            raise SystemExit(
                f"provider registry: {provider_id} observation provider must not inherit hazard topics"
            )

    capability_map = json.loads(
        (CONSUMER_V1 / "capability-map.draft.json").read_text(encoding="utf-8")
    )
    if capability_map.get("schema") != "weather_router.consumer.capability_map.draft.v1":
        raise SystemExit("consumer capability map: unexpected schema")
    mapped_providers = capability_map.get("providers")
    if not isinstance(mapped_providers, dict):
        raise SystemExit("consumer capability map: providers must be an object")
    phenomena = capability_map.get("phenomena")
    expected_phenomena = {
        "temperature",
        "dew_point",
        "humidity",
        "pressure",
        "rain",
        "precipitation",
        "snow",
        "wind",
        "clouds",
        "visibility",
        "fog",
        "thunderstorm",
        "lightning",
        "uv",
        "pollen",
        "aurora",
        "weather_condition",
        "vector",
        "toxic_fungus",
        "toxic_plant",
        "toxic",
        "snake",
        "venomous",
        "marine",
        "crocodilian",
        "predator",
        "wildlife",
    }
    if not isinstance(phenomena, dict) or set(phenomena) != expected_phenomena:
        raise SystemExit("consumer capability map: unexpected weather phenomena taxonomy")
    public_capabilities = capability_map.get("public_capabilities")
    if not isinstance(public_capabilities, dict):
        raise SystemExit("consumer capability map: public_capabilities must be an object")
    if len(public_capabilities) != 227:
        raise SystemExit(
            f"consumer capability map: expected 227 public capabilities, got {len(public_capabilities)}"
        )
    expected_lightning_capabilities = {
        "weather.lightning.density",
        "weather.lightning.observed.events",
        "weather.lightning.observed.nearest_distance",
        "weather.lightning.observed.nearest_azimuth",
        "weather.lightning.observed.density",
        "weather.lightning.satellite.mtg_li.accumulated_flashes",
        "weather.lightning.satellite.glm_east.lcfa",
        "weather.lightning.satellite.glm_west.lcfa",
    }
    lightning_capabilities = {
        public_id
        for public_id in public_capabilities
        if public_id.startswith("weather.lightning.")
    }
    if lightning_capabilities != expected_lightning_capabilities:
        raise SystemExit(
            f"consumer capability map: lightning observation mismatch {sorted(lightning_capabilities)}"
        )
    biological_capabilities = {
        public_id
        for public_id in public_capabilities
        if public_id.startswith("biological_hazards.")
    }
    if len(biological_capabilities) != 88:
        raise SystemExit(
            f"consumer capability map: expected 88 biological capabilities, got {len(biological_capabilities)}"
        )
    expected_pollen_capabilities = {
        "pollen.alder",
        "pollen.birch",
        "pollen.grass",
        "pollen.mugwort",
        "pollen.olive",
        "pollen.ragweed",
    }
    pollen_capabilities = {
        public_id
        for public_id in public_capabilities
        if public_id.startswith("pollen.") or public_id.startswith("weather.pollen.")
    }
    if pollen_capabilities != expected_pollen_capabilities:
        raise SystemExit(
            "consumer capability map: dedicated pollen namespace mismatch"
        )
    new_provider_reachability = {
        "open_meteo_pollen": ("pollen", 6),
        "met_norway_astronomy": ("space", 24),
        "glofas": ("natural_hazards", 9),
        "gbif_biodiversity": ("biological_hazards", 88),
        "fmi_lightning": ("weather", 3),
        "eumetsat_mtg_li": ("weather", 1),
        "noaa_goes_glm": ("weather", 2),
        "eccc_lightning": ("weather", 1),
    }
    registry_by_module = {
        item.get("module"): item
        for item in provider_entries
        if isinstance(item, dict) and item.get("module")
    }
    for provider_id, (expected_domain, expected_count) in new_provider_reachability.items():
        registry_item = registry_by_module.get(provider_id)
        if registry_item is None:
            raise SystemExit(f"new provider reachability: registry missing {provider_id}")
        if registry_item.get("domains") != [expected_domain]:
            raise SystemExit(
                f"new provider reachability: {provider_id} must route through {expected_domain}"
            )
        mapped_rows = mapped_providers.get(provider_id)
        if not isinstance(mapped_rows, dict) or len(mapped_rows) != expected_count:
            raise SystemExit(
                f"new provider reachability: {provider_id} expected {expected_count} mapped capabilities"
            )
        public_ids = {
            public_id
            for values in mapped_rows.values()
            if isinstance(values, list)
            for public_id in values
            if isinstance(public_id, str)
        }
        if len(public_ids) != expected_count:
            raise SystemExit(
                f"new provider reachability: {provider_id} public capability count mismatch"
            )
        if any(public_id.split(".", 1)[0] != expected_domain for public_id in public_ids):
            raise SystemExit(
                f"new provider reachability: {provider_id} capability outside {expected_domain}"
            )

    expected_uv_capabilities = {
        "weather.point.uv_index",
        "weather.point.uv_index_clear_sky",
        "weather.point.uv_index_max_today",
        "weather.point.uv_index_clear_sky_max_today",
    }
    if not expected_uv_capabilities.issubset(public_capabilities):
        raise SystemExit("consumer capability map: UV capability expansion incomplete")

    expected_glofas_capabilities = {
        "natural_hazards.flood.reporting_points.layer",
        "natural_hazards.flood.probability_5y.layer",
        "natural_hazards.flood.probability_20y.layer",
        "natural_hazards.flood.summary_1_3d.layer",
        "natural_hazards.flood.summary_4_10d.layer",
        "natural_hazards.flood.summary_11_30d.layer",
        "natural_hazards.flood.rapid_mapping.layer",
        "natural_hazards.flood.rapid_impact.layer",
        "natural_hazards.flood.hazard_100y.layer",
    }
    if not expected_glofas_capabilities.issubset(public_capabilities):
        raise SystemExit("consumer capability map: GloFAS capability set incomplete")

    astronomy_public_ids = {
        public_id
        for values in mapped_providers["met_norway_astronomy"].values()
        if isinstance(values, list)
        for public_id in values
        if isinstance(public_id, str)
    }
    if len(astronomy_public_ids) != 24:
        raise SystemExit("consumer capability map: MET Norway sun/moon capability set incomplete")
    if any(
        not (public_id.startswith("space.sun.") or public_id.startswith("space.moon."))
        for public_id in astronomy_public_ids
    ):
        raise SystemExit("consumer capability map: MET Norway astronomy namespace mismatch")

    new_hydrology_types = {
        "dam_failure",
        "debris_flow",
        "glacial_lake_outburst_flood",
        "ice_jam_flood",
        "levee_failure",
        "surface_water_flood",
    }
    if not new_hydrology_types.issubset(hazard_types):
        raise SystemExit("hazard taxonomy: new hydrology types incomplete")
    for hazard_type in new_hydrology_types:
        if not any(
            hazard_type in metadata.get("hazard_types", [])
            for metadata in public_capabilities.values()
            if isinstance(metadata, dict)
        ):
            raise SystemExit(
                f"hazard taxonomy: {hazard_type} is declared but unreachable from public capabilities"
            )
    for public_id, metadata in public_capabilities.items():
        if not isinstance(metadata, dict) or not metadata.get("family"):
            raise SystemExit(
                f"consumer capability map: {public_id} missing family metadata"
            )
        tagged = metadata.get("phenomena")
        if not isinstance(tagged, list) or any(item not in expected_phenomena for item in tagged):
            raise SystemExit(
                f"consumer capability map: {public_id} has invalid phenomena metadata"
            )
        declared_hazards = metadata.get("hazard_types", [])
        if not isinstance(declared_hazards, list):
            raise SystemExit(
                f"consumer capability map: {public_id} hazard_types must be a list"
            )
        if any(item not in hazard_types for item in declared_hazards):
            raise SystemExit(
                f"consumer capability map: {public_id} has unknown hazard type metadata"
            )
    registered_provider_ids = set()
    for item in provider_entries:
        module_name = item.get("module")
        class_name = item.get("class")
        # Map provider ids are runtime ids, so validate exact known set below from
        # the current provider registry contract rather than deriving ids from class names.
        if not module_name or not class_name:
            raise SystemExit("provider registry contains incomplete provider metadata")
    expected_mapped_provider_ids = {
        "open_meteo", "open_meteo_pollen", "rainviewer", "dwd", "nasa_gibs", "eumetview",
        "met_norway", "noaa_nws", "noaa_swpc", "nasa_iss", "nasa_moon",
        "met_norway_astronomy",
        "fmi", "smhi", "eccc_geomet", "jma", "ecmwf_open_data",
        "nhc_tropical_cyclones", "noaa_tsunami", "bmkg_tsunami",
        "bom_tsunami", "usgs_earthquakes", "smithsonian_volcanoes",
        "usgs_volcanoes", "gdacs", "glofas", "usgs_seismic_events", "bbk_mowas",
        "bbk_police", "aviation_weather", "nina_flood", "nina_katwarn",
        "nina_biwapp", "gbif_biodiversity",
        "fmi_lightning", "eumetsat_mtg_li", "noaa_goes_glm", "eccc_lightning"
    }
    if set(mapped_providers) != expected_mapped_provider_ids:
        missing = sorted(expected_mapped_provider_ids - set(mapped_providers))
        extra = sorted(set(mapped_providers) - expected_mapped_provider_ids)
        raise SystemExit(
            f"consumer capability map provider mismatch: missing={missing}, extra={extra}"
        )
    for provider_id, capability_rows in mapped_providers.items():
        if not isinstance(capability_rows, dict) or not capability_rows:
            raise SystemExit(
                f"consumer capability map: {provider_id} has no capability mappings"
            )
        for internal_id, public_ids in capability_rows.items():
            if not isinstance(internal_id, str) or not internal_id:
                raise SystemExit(
                    f"consumer capability map: invalid internal id for {provider_id}"
                )
            if not isinstance(public_ids, list) or not public_ids:
                raise SystemExit(
                    f"consumer capability map: {provider_id}/{internal_id} needs public ids"
                )
            for public_id in public_ids:
                if (
                    not isinstance(public_id, str)
                    or "." not in public_id
                    or public_id.startswith(".")
                    or public_id.endswith(".")
                    or " " in public_id
                ):
                    raise SystemExit(
                        f"consumer capability map: invalid public capability {public_id!r}"
                    )
    for item in provider_entries:
        if not isinstance(item, dict) or not item.get("domains"):
            raise SystemExit("provider registry: every provider needs router domains")
        if not isinstance(item.get("default_enabled"), bool):
            raise SystemExit("provider registry: every provider needs default_enabled")

    pollen_registry = next(
        (item for item in provider_entries if item.get("module") == "open_meteo_pollen"),
        None,
    )
    if pollen_registry is None or pollen_registry.get("domains") != ["pollen"]:
        raise SystemExit(
            "provider registry: open_meteo_pollen must use dedicated pollen domain"
        )

    opt_in_modules = {
        "gdacs",
        "glofas",
        "open_meteo_pollen",
        "met_norway_astronomy",
        "usgs_seismic_events",
        "bbk_mowas",
        "bbk_police",
        "aviation_weather",
        "nina_supplementary",
    }
    for item in provider_entries:
        if item.get("module") in opt_in_modules and item.get("default_enabled") is not False:
            raise SystemExit(f"new safety provider must be opt-in: {item}")

    provider_contract = (PROVIDERS / "__init__.py").read_text(encoding="utf-8")
    for needle in (
        "registry.json",
        "invalidate_caches",
        "import_module",
        "NetworkTargetInfo",
        "network_targets",
        "router_domains",
        "router_default_enabled",
        "_SAFE_DOMAIN",
    ):
        if needle not in provider_contract:
            raise SystemExit(f"provider registry contract missing marker: {needle}")

    websocket = (INTEGRATION / "websocket_api.py").read_text(encoding="utf-8")
    for needle in (
        "weather_router/providers",
        "weather_router/diagnostic_query",
        "weather_router/map_layer",
        "weather_router/hazard_feed",
        "weather_router/provider_diagnostics",
        "weather_router/all_provider_diagnostics",
        'vol.Optional("provider"): str',
        "provider_filter = msg.get",
        "weather_router/routing_settings",
        "weather_router/routing_settings_update",
        "_routing_settings_payload",
        "_provider_policy",
        "_capability_policy",
        "domain_partially_disabled",
        "providers_skipped",
        "_async_aggregate_provider_report",
        "_descriptor_diagnostic_summary",
        "_exception_report",
        "_redact_text",
        "require_admin",
        "API_CONTRACT_VERSION",
        "network_targets",
        "async_add_executor_job",
        "_async_provider_catalog",
        '"revision": getattr(provider, "revision", None)',
    ):
        if needle not in websocket:
            raise SystemExit(f"WeatherRouter WebSocket API missing required marker: {needle}")

    open_meteo = (PROVIDERS / "open_meteo.py").read_text(encoding="utf-8")
    for needle in (
        "api.open-meteo.com",
        "NetworkTargetInfo",
        "point_weather_api",
        '"uv_index"',
        '"uv_index_clear_sky"',
        '"uv_index_max_today"',
        '"uv_index_clear_sky_max_today"',
        "hourly_nearest",
    ):
        if needle not in open_meteo:
            raise SystemExit(f"Open-Meteo provider missing required marker: {needle}")

    rainviewer = (PROVIDERS / "rainviewer.py").read_text(encoding="utf-8")
    for needle in (
        "api.rainviewer.com/public/weather-maps.json",
        "radar_reflectivity",
        "Niederschlagsradar",
        "tile_url",
        "max_zoom",
        "timeline",
        "frames",
        "NetworkTargetInfo",
        "weather_map_metadata",
    ):
        if needle not in rainviewer:
            raise SystemExit(f"RainViewer provider missing required marker: {needle}")

    dwd = (PROVIDERS / "dwd.py").read_text(encoding="utf-8")
    for needle in (
        "maps.dwd.de",
        "brz-maps.dwd.de",
        "Niederschlagsradar",
        "RADOLAN-RY",
        "Satellite_meteosat",
        "Blitzdichte",
        "Gewitterzellen",
        "Icon-eu_reg00625_fd_sl_TOTPREC01H",
        "Icon_reg025_fd_sl_T2M",
        "Icon_reg025_fd_sl_UV10M",
        "{bbox-epsg-3857}",
        "GetCapabilities",
        "default_index",
        "current_index",
        "NetworkTargetInfo",
        "async_diagnostics",
        "available_layers",
        "attempts",
        "_layer_style_metadata",
        "GetLegendGraphic",
        '"legend"',
        "official_weather_warnings",
        "_DWD_CAP_WARNINGS_URL",
        "COMMUNEUNION_CELLS_STAT",
        "_parse_dwd_cap_zip",
        "_filter_dwd_cap_events",
        "point_in_geometry",
        "geometry_intersects_bbox_strict",
        "async_get_hazard_feed",
    ):
        if needle not in dwd:
            raise SystemExit(f"DWD provider missing required marker: {needle}")
    if re.search(
        r'_DWD_PROVIDER_REVISION = "wr-0\.10\.\d+-[a-z0-9-]+-semantics-1"',
        dwd,
    ) is None:
        raise SystemExit("DWD provider missing versioned semantics revision")

    satellite_wms = (PROVIDERS / "wms_satellite.py").read_text(encoding="utf-8")
    for marker in (
        "EPSG:3857",
        "{bbox-epsg-3857}",
        "parse_time_axis",
        "current",
        "async_capabilities",
        "layer_time_dimension",
        "tile_url",
    ):
        if marker not in satellite_wms:
            raise SystemExit(f"Shared satellite WMS helper missing marker: {marker}")

    nasa_gibs = (PROVIDERS / "nasa_gibs.py").read_text(encoding="utf-8")
    for marker in (
        "gibs.earthdata.nasa.gov",
        "MODIS_Terra_CorrectedReflectance_TrueColor",
        "satellite_imagery_true_color",
        "NasaGibsProvider",
        "async_diagnostics",
        "_times_for_spec",
        "GOES-East_ABI_GeoColor",
        "GOES-West_ABI_GeoColor",
        "GOES-East_ABI_Band13_Clean_Infrared",
        "Himawari_AHI_Air_Mass",
        "IMERG_Precipitation_Rate_30min",
        "satellite_precipitation_imerg_30min",
        "latest_policy",
        "exclude_incomplete_daily_composite",
        "timeline",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in nasa_gibs:
            raise SystemExit(f"NASA GIBS provider missing marker: {marker}")

    met_norway = (PROVIDERS / "met_norway.py").read_text(encoding="utf-8")
    for marker in (
        "api.met.no",
        "MetNorwayProvider",
        "Locationforecast",
        "_USER_AGENT",
        "User-Agent",
        "temperature",
        "cloud_cover",
        "precipitation",
        "wind_speed",
        "ProviderInfo",
        "Geosatellite 1.4",
        "Nowcast 2.0",
        "Radar 2.0",
        "Nowcast 2.0",
        "_NOWCAST_URL",
        "nowcast_temperature",
        "nowcast_precipitation_rate",
        "nowcast_wind_speed",
    ):
        if marker not in met_norway:
            raise SystemExit(f"MET Norway provider missing marker: {marker}")

    astronomy = (PROVIDERS / "met_norway_astronomy.py").read_text(encoding="utf-8")
    for marker in (
        "sunrise/3.0",
        "MetNorwayAstronomyProvider",
        "moon_phase_angle",
        "moon_illumination",
        "moonrise_time",
        "high_moon_elevation",
        "sunrise_time",
        "solar_noon_elevation",
        "_phase_name",
        "_SYNODIC_MONTH_DAYS",
    ):
        if marker not in astronomy:
            raise SystemExit(f"MET Norway astronomy provider missing marker: {marker}")

    pollen = (PROVIDERS / "open_meteo_pollen.py").read_text(encoding="utf-8")
    for marker in (
        "air-quality-api.open-meteo.com",
        "OpenMeteoPollenProvider",
        "alder_pollen",
        "birch_pollen",
        "grass_pollen",
        "mugwort_pollen",
        "olive_pollen",
        "ragweed_pollen",
        "cams_europe",
        "Grains/m³",
    ):
        if marker not in pollen:
            raise SystemExit(f"Open-Meteo pollen provider missing marker: {marker}")

    eumetview = (PROVIDERS / "eumetview.py").read_text(encoding="utf-8")
    for marker in (
        "view.eumetsat.int",
        "msg_fes:rgb_eview",
        "satellite_clouds",
        "EumetViewProvider",
        "async_diagnostics",
        "timeline",
        "NetworkTargetInfo",
    ):
        if marker not in eumetview:
            raise SystemExit(f"EUMETView provider missing marker: {marker}")

    noaa_nws = (PROVIDERS / "noaa_nws.py").read_text(encoding="utf-8")
    for marker in (
        "api.weather.gov",
        "NoaaNwsProvider",
        "forecastHourly",
        "User-Agent",
        "outside_coverage",
        "precipitation_probability",
        "official_weather_alerts",
        "hazard_feed",
        "async_get_hazard_feed",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in noaa_nws:
            raise SystemExit(f"NOAA NWS provider missing marker: {marker}")

    noaa_swpc = (PROVIDERS / "noaa_swpc.py").read_text(encoding="utf-8")
    for marker in (
        "services.swpc.noaa.gov",
        "NoaaSwpcProvider",
        "image_sequence",
        "products/animations",
        'for kind in ("primary", "secondary")',
        "solar_suvi_094",
        "solar_suvi_304",
        "_safe_frame_url",
        "timeline",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in noaa_swpc:
            raise SystemExit(f"NOAA SWPC provider missing marker: {marker}")

    nasa_iss = (PROVIDERS / "nasa_iss.py").read_text(encoding="utf-8")
    for marker in (
        "eol.jsc.nasa.gov",
        "NasaIssProvider",
        "live_stream",
        "youtube-nocookie.com",
        "_YOUTUBE_EMBED_RE",
        "iss_earth_live",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in nasa_iss:
            raise SystemExit(f"NASA ISS provider missing marker: {marker}")

    nasa_moon = (PROVIDERS / "nasa_moon.py").read_text(encoding="utf-8")
    for marker in (
        "trek.nasa.gov",
        "NasaMoonProvider",
        "planetary_tile",
        "LRO_WAC_Mosaic_Global_303ppd_v02",
        "WMTSCapabilities.xml",
        "columns_at_zoom0",
        "rows_at_zoom0",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in nasa_moon:
            raise SystemExit(f"NASA Moon provider missing marker: {marker}")

    fmi = (PROVIDERS / "fmi.py").read_text(encoding="utf-8")
    for marker in (
        "opendata.fmi.fi",
        "FmiProvider",
        "harmonie_scandinavia_surface",
        "_TIMESERIES_URL",
        "latlon",
        "timesteps",
        "Temperature",
        "WindSpeedMS",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in fmi:
            raise SystemExit(f"FMI provider missing marker: {marker}")

    smhi = (PROVIDERS / "smhi.py").read_text(encoding="utf-8")
    for marker in (
        "opendata-download-metfcst.smhi.se",
        "SmhiProvider",
        "snow1g",
        "air_temperature",
        "probability_of_precipitation",
        "symbol_code",
        'params={"timeseries": "1", "parameters": params}',
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in smhi:
            raise SystemExit(f"SMHI provider missing marker: {marker}")

    eccc = (PROVIDERS / "eccc_geomet.py").read_text(encoding="utf-8")
    for marker in (
        "api.weather.gc.ca",
        "geo.weather.gc.ca",
        "EcccGeometProvider",
        "swob-realtime",
        "air_temp",
        "rel_hum",
        "mslp",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in eccc:
            raise SystemExit(f"ECCC provider missing marker: {marker}")

    jma = (PROVIDERS / "jma.py").read_text(encoding="utf-8")
    for marker in (
        "www.jma.go.jp",
        "JmaProvider",
        "forecast_area.json",
        "amedastable.json",
        "weather_summary",
        "precipitation_probability",
        "official_tsunami_warnings_japan",
        "tsunami_observations_japan",
        "eqvol.xml",
        "eqvol_l.xml",
        "_parse_jma_warning_report",
        "_parse_jma_observation_report",
        "async_get_hazard_feed",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in jma:
            raise SystemExit(f"JMA provider missing marker: {marker}")

    nhc = (PROVIDERS / "nhc_tropical_cyclones.py").read_text(encoding="utf-8")
    for marker in (
        "www.nhc.noaa.gov",
        "CurrentStorms.json",
        "NhcTropicalCycloneProvider",
        "active_tropical_cyclones",
        "hazard_feed",
        "forecastTrack",
        "trackCone",
        "windWatchesWarnings",
        "stormSurgeWatchWarningGIS",
        "async_get_hazard_feed",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in nhc:
            raise SystemExit(f"NHC provider missing marker: {marker}")

    noaa_tsunami = (PROVIDERS / "noaa_tsunami.py").read_text(encoding="utf-8")
    for marker in (
        "PAAQCAP.xml",
        "PHEBCAP.xml",
        "PAAQAtom.xml",
        "PHEBAtom.xml",
        "NoaaTsunamiProvider",
        "official_tsunami_alerts",
        "CAP-TSU",
        "_polygon_geometry",
        "active_threat",
        "async_get_hazard_feed",
    ):
        if marker not in noaa_tsunami:
            raise SystemExit(f"NOAA tsunami provider missing marker: {marker}")

    bmkg_tsunami = (PROVIDERS / "bmkg_tsunami.py").read_text(encoding="utf-8")
    for marker in (
        "autogempa.json",
        "BmkgTsunamiProvider",
        "tsunami_potential_earthquake",
        "tsunami_potential",
        "_has_tsunami_potential",
        "semantic_boundary",
        "async_get_hazard_feed",
    ):
        if marker not in bmkg_tsunami:
            raise SystemExit(f"BMKG tsunami provider missing marker: {marker}")

    bom_tsunami = (PROVIDERS / "bom_tsunami.py").read_text(encoding="utf-8")
    for marker in (
        "warnings_nsw.xml",
        "warnings_vic.xml",
        "warnings_qld.xml",
        "warnings_wa.xml",
        "warnings_sa.xml",
        "warnings_tas.xml",
        "warnings_nt.xml",
        "BomTsunamiProvider",
        "official_tsunami_warnings_australia",
        "_BOM_HEADERS",
        "Firefox/128.0",
        "_STATUS_URL",
        "_status_page_confirms_no_warning",
        "official_status_page_no_current_warning",
        "async_get_hazard_feed",
    ):
        if marker not in bom_tsunami:
            raise SystemExit(f"BoM tsunami provider missing marker: {marker}")
    if re.search(
        r'_PROVIDER_REVISION = "wr-0\.10\.\d+-[a-z0-9-]+-\d+"',
        bom_tsunami,
    ) is None:
        raise SystemExit("BoM tsunami provider missing versioned provider revision")

    usgs_earthquakes = (PROVIDERS / "usgs_earthquakes.py").read_text(encoding="utf-8")
    for marker in (
        "earthquake.usgs.gov",
        "UsgsEarthquakeProvider",
        "earthquakes_past_day",
        "significant_earthquakes_past_month",
        "all_day.geojson",
        "hazard_type",
        "earthquake",
        "async_get_hazard_feed",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in usgs_earthquakes:
            raise SystemExit(f"USGS earthquake provider missing marker: {marker}")

    smithsonian_volcanoes = (PROVIDERS / "smithsonian_volcanoes.py").read_text(encoding="utf-8")
    for marker in (
        "volcano.si.edu",
        "SmithsonianVolcanoProvider",
        "WeeklyVolcanoRSS.xml",
        "weekly_volcanic_activity",
        "volcanic_activity",
        "GeoRSS",
        "async_get_hazard_feed",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in smithsonian_volcanoes:
            raise SystemExit(f"Smithsonian volcano provider missing marker: {marker}")

    usgs_volcanoes = (PROVIDERS / "usgs_volcanoes.py").read_text(encoding="utf-8")
    for marker in (
        "volcanoes.usgs.gov",
        "UsgsVolcanoProvider",
        "getElevatedVolcanoes",
        "getUSVolcanoes",
        "elevated_us_volcanoes",
        "volcanic_activity",
        "async_get_hazard_feed",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in usgs_volcanoes:
            raise SystemExit(f"USGS volcano provider missing marker: {marker}")

    hazard_common = (PROVIDERS / "hazard_common.py").read_text(encoding="utf-8")
    for marker in (
        "normalize_hazard_type",
        "waterspout",
        "tornado",
        "downburst",
        "supercell",
        "severe_thunderstorm",
        "tropical_cyclone",
        "tsunami",
        "tsunami_potential",
        "earthquake",
        "volcanic_activity",
        "storm_surge",
        "surface_water_flood",
        "debris_flow",
        "levee_failure",
        "dam_failure",
        "glacial_lake_outburst_flood",
        "ice_jam_flood",
        "flash_flood",
        "windstorm",
    ):
        if marker not in hazard_common:
            raise SystemExit(f"Hazard normalizer missing marker: {marker}")

    ecmwf = (PROVIDERS / "ecmwf_open_data.py").read_text(encoding="utf-8")
    for marker in (
        "data.ecmwf.int",
        "EcmwfOpenDataProvider",
        "ifs_open_grib",
        "aifs_open_grib",
        "aifs-single",
        "/forecasts/",
        "_probe_model",
        "_RETRYABLE_HTTP_STATUS",
        "transient_rate_limit_seen",
        "wr-0.10.78-data-file-resolver-2",
        "grib_signature",
        "data_file",
        "GRIB2",
        "point_decoder_available",
        "ProviderInfo",
        "NetworkTargetInfo",
    ):
        if marker not in ecmwf:
            raise SystemExit(f"ECMWF provider missing marker: {marker}")

    bbk_common = (PROVIDERS / "bbk_warning_common.py").read_text(encoding="utf-8")
    for marker in (
        "warnung.bund.de/api31",
        "/warnings/{quote(identifier, safe='')}.geojson",
        "source_channel",
        "official_warning",
        "geometry_errors",
    ):
        if marker not in bbk_common:
            raise SystemExit(f"BBK warning helper missing marker: {marker}")

    bbk_mowas = (PROVIDERS / "bbk_mowas.py").read_text(encoding="utf-8")
    for marker in (
        "/mowas/mapData.json",
        "civil_protection_warnings_germany",
        "wr-0.10.48-bbk-mowas-1",
    ):
        if marker not in bbk_mowas:
            raise SystemExit(f"BBK MoWaS provider missing marker: {marker}")

    bbk_police = (PROVIDERS / "bbk_police.py").read_text(encoding="utf-8")
    for marker in (
        "/police/mapData.json",
        "police_public_safety_warnings_germany",
        "keine automatische Interpretation als Anschlag",
        "wr-0.10.48-bbk-police-1",
    ):
        if marker not in bbk_police:
            raise SystemExit(f"BBK police provider missing marker: {marker}")

    gdacs = (PROVIDERS / "gdacs.py").read_text(encoding="utf-8")
    for marker in (
        "data.gdacs.org/xml/rss_7d.xml",
        "global_disaster_alerts_7d",
        "disaster_awareness_alert",
        "primary_warning_authority",
        "_PROVIDER_REVISION",
    ):
        if marker not in gdacs:
            raise SystemExit(f"GDACS provider missing marker: {marker}")
    if re.search(
        r'_PROVIDER_REVISION = "wr-0\.10\.\d+-[a-z0-9-]+-1"',
        gdacs,
    ) is None:
        raise SystemExit("GDACS provider missing versioned provider revision")

    glofas = (PROVIDERS / "glofas.py").read_text(encoding="utf-8")
    for marker in (
        "ows.globalfloods.eu/glofas-ows/ows.py",
        "flood_reporting_points",
        "flood_probability_5y",
        "flood_probability_20y",
        "flood_summary_1_3d",
        "rapid_flood_mapping",
        "rapid_impact_assessment",
        "FloodHazard100y",
        "modellbasierte Frühwarnquelle",
    ):
        if marker not in glofas:
            raise SystemExit(f"GloFAS provider missing marker: {marker}")

    seismic_events = (PROVIDERS / "usgs_seismic_events.py").read_text(encoding="utf-8")
    for marker in (
        "type != earthquake",
        "seismic_explosion",
        "classification_only",
        "does not infer",
        "_PROVIDER_REVISION",
    ):
        if marker not in seismic_events:
            raise SystemExit(f"USGS seismic events provider missing marker: {marker}")

    if re.search(r'_PROVIDER_REVISION = "wr-0\.10\.\d+-[^"]+"', seismic_events) is None:
        raise SystemExit("USGS seismic events provider has no versioned provider revision")

    aviation = (PROVIDERS / "aviation_weather.py").read_text(encoding="utf-8")
    for marker in (
        "aviationweather.gov/api/data/isigmet",
        "aviationweather.gov/api/data/airsigmet",
        "aviationweather.gov/api/data/gairmet",
        "us_gairmet_current",
        "official_aviation_warning",
        "volcanic_ash",
        "_PROVIDER_REVISION",
    ):
        if marker not in aviation:
            raise SystemExit(f"Aviation Weather provider missing marker: {marker}")
    if re.search(
        r'_PROVIDER_REVISION = "wr-0\.10\.\d+-[a-z0-9-]+-1"',
        aviation,
    ) is None:
        raise SystemExit("Aviation Weather provider missing versioned provider revision")

    nina_supplementary = (PROVIDERS / "nina_supplementary.py").read_text(encoding="utf-8")
    for marker in (
        "/lhp/mapData.json",
        "/katwarn/mapData.json",
        "/biwapp/mapData.json",
        "NinaFloodProvider",
        "NinaKatwarnProvider",
        "NinaBiwappProvider",
    ):
        if marker not in nina_supplementary:
            raise SystemExit(f"NINA supplementary provider missing marker: {marker}")

    lab = (FRONTEND / "weather-router-lab.js").read_text(encoding="utf-8")
    for needle in (
        "weather_router/providers",
        "weather_router/diagnostic_query",
        "weather_router/map_layer",
        "4 · Punktwerte",
        "2 · Kartenebenen",
        "MET Norway · Sonne & Mond",
        "Copernicus GloFAS",
        "MapLibre",
        "OpenFreeMap",
        "Dark · kontrastarm",
        "Lokaler Hintergrund · ohne Basiskarte",
        "basemap-provider",
        "basemap-style",
        "engine-status",
        "raster-opacity",
        "weather-provider-filter",
        "weather-capability-filter",
        "Nur aktive",
        "weather-provider-group",
        "weather-provider-info",
        "provider-info-window",
        "provider-info-directory",
        "#d4af37",
        "_providerInfoOpen",
        "Sonne & Weltraum",
        "image_sequence",
        "_syncMediaSequenceStates",
        "_loadMediaSequence",
        "_startMediaPlayback",
        "_stopAllMediaPlayback",
        "_stopMediaSequencePlayback",
        "media-sequence-region",
        "live_stream",
        "_syncLiveStreamStates",
        "_loadLiveStream",
        "_stopLiveStream",
        "live-stream-wrap",
        "planetary_tile",
        "_syncPlanetaryTileStates",
        "_loadPlanetaryTile",
        "DIAGNOSTIC_TEST_LOCATIONS",
        "diagnostic-test-location",
        "_diagnosticPoint",
        "MET Nowcast · Oslo (Norwegen)",
        "FMI · Helsinki (Finnland)",
        "SMHI · Stockholm (Schweden)",
        "ECCC/MSC · Toronto (Kanada)",
        "JMA · Tokio (Japan)",
        "_renderPlanetaryVisibleTiles",
        "_stopPlanetaryView",
        "planetary-view",
        "overscroll-behavior:contain",
        "scrollbar-gutter:stable",
        ".map-wrap { position:relative; min-width:0; min-height:0; height:100%; overflow:hidden",
    ):
        if needle not in lab:
            raise SystemExit(f"WeatherRouter Lab missing required marker: {needle}")

    for needle in (
        "LAB_MENU_STATE_KEY",
        'data-lab-menu-key="basemap"',
        'data-lab-menu-key="reference"',
        'data-lab-menu-key="weather-layers"',
        'data-lab-menu-key="solar-media"',
        'data-lab-menu-key="diagnostic-matrix"',
        'data-lab-menu-key="results"',
        'data-lab-menu-key="raw-diagnostics"',
    ):
        if needle not in lab:
            raise SystemExit(f"WeatherRouter collapsible menu marker missing: {needle}")

    if "tile.openstreetmap.org" in lab:
        raise SystemExit("WeatherRouter Lab must not use OpenStreetMap standard tiles directly")
    if "api.rainviewer.com" in lab or "tilecache.rainviewer.com" in lab:
        raise SystemExit("RainViewer provider metadata must stay behind the WeatherRouter backend")
    if "maps.dwd.de" in lab or "brz-maps.dwd.de" in lab:
        raise SystemExit("DWD provider endpoints must stay behind the WeatherRouter backend")
    if (
        "gibs.earthdata.nasa.gov" in lab
        or "view.eumetsat.int" in lab
        or "api.met.no" in lab
        or "api.weather.gov" in lab
        or "services.swpc.noaa.gov" in lab
        or "trek.nasa.gov" in lab
    ):
        raise SystemExit("Provider endpoints must stay behind the WeatherRouter backend")

    timeline = (FRONTEND / "weather-router-lab-timeline.js").read_text(encoding="utf-8")
    for needle in (
        "PLAYBACK_INTERVAL_MS",
        "timeline?.frames",
        "Neueste",
        "Jetzt",
        "Vorhersage",
        "Beobachtung",
        "default_index",
        "current_index",
        "Verlauf",
        "_timelineApplyFrame",
        "_timelineNearestIndex",
        "_timelineTimeGranularity",
        "_timelineDailyDateText",
        "_timelineDailyAgeText",
    ):
        if needle not in timeline:
            raise SystemExit(f"WeatherRouter timeline module missing required marker: {needle}")

    stability = (FRONTEND / "weather-router-lab-raster-stability.js").read_text(encoding="utf-8")
    for needle in (
        "setTiles",
        "FRAME_FADE_MS",
        "_handleWeatherTileError",
        "_timelineApplyFrame",
        "Keine Basiskarte · nur Wetterlayer",
    ):
        if needle not in stability:
            raise SystemExit(f"WeatherRouter raster stability module missing required marker: {needle}")

    frame_buffer = (FRONTEND / "weather-router-lab-frame-buffer.js").read_text(encoding="utf-8")
    for needle in (
        "BUFFER_DEFAULT_TARGET",
        "BUFFER_MAX_TARGET",
        "BUFFER_TILE_CONCURRENCY",
        "_timelinePrimeBuffer",
        "_timelineEnsureBuffered",
        "_timelinePrimeMapStage",
        "_timelineSwapToFrame",
        "timelineStagedIndex",
        "buffer-b",
        "Puffer",
        "Kacheln",
        "double buffer",
        "BUFFER_RENDER_SETTLE_TIMEOUT_MS",
        "BUFFER_STAGE_OPACITY",
        "_timelineWaitForRenderCycles",
        "_timelineWaitForSpecificSource",
        "sourceIsLoaded",
        "timelineStageFailureReason",
        "timelineStageSourceWaitDetail",
        "source_timeout",
        "render_timeout",
        'event?.sourceDataType === "idle"',
        "_timelineStageWarningText",
        "_timelineResetViewportBuffer",
        "timelineResumeAfterViewport",
        "timelineViewportSuspended",
        "timelineViewportRecoveryPromise",
        "previousApplyBasemap",
        "_timelineWaitForMapStable",
        "timelineStyleRecoveryActive",
        "timelineStyleRecoveryToken",
        "Kartenstil: Wetterlayer/Kartenpuffer konnte nach dem Stilwechsel",
        "prebuffer -> hidden MapLibre stage -> release the existing playback loop",
        'this._map.on("moveend", reprimeForViewport)',
        "render-settled MapLibre double buffer",
        "BUFFER_SETTINGS_KEY",
        "BUFFER_MANUAL_MAX_TARGET",
        "_timelineBufferSettings",
        "_timelineWaitForStartBuffer",
        "Wiedergabepuffer",
        "Parallele Kacheln",
        "Wiedergabe starten ab",
        "localStorage",
    ):
        if needle not in frame_buffer:
            raise SystemExit(f"WeatherRouter frame buffer missing marker: {needle}")

    if 'this._map.on("zoomend"' in frame_buffer:
        raise SystemExit("WeatherRouter frame buffer must use one canonical moveend viewport reset, not a duplicate zoomend hook")

    legends = (FRONTEND / "weather-router-lab-legends.js").read_text(encoding="utf-8")
    for needle in (
        "weather-legends",
        "descriptor?.legend?.url",
        "Legenden",
        "weather-legend-image",
        "generic WMS legend overlay",
    ):
        if needle not in legends:
            raise SystemExit(f"WeatherRouter legend frontend missing marker: {needle}")

    log_export = (FRONTEND / "weather-router-lab-log-export.js").read_text(encoding="utf-8")
    for needle in (
        "weather_router/log_git_status",
        "weather_router/log_git_configure",
        "weather_router/log_git_export",
        "Snapshot aktualisieren",
        "wr-log-refresh",
        "Menü war beim Start bereits geöffnet",
        "_wrGeneratedLog",
        "im Snapshot",
        "revision: provider.revision || null",
    ):
        if needle not in log_export:
            raise SystemExit(f"WeatherRouter log export frontend missing marker: {needle}")

    event_log = (FRONTEND / "weather-router-lab-event-log.js").read_text(encoding="utf-8")
    for needle in (
        "weather_router.event_log.v1",
        'mode: this._mapMode || "docked"',
        "EVENT_LOG_LIMIT",
        "_wrLog",
        "_wrEventLogSnapshot",
        "Ereignislog",
        "Log kopieren",
        "navigator.clipboard?.writeText",
        "document.execCommand",
        "<redacted>",
        "browser_error",
        "unhandled_rejection",
    ):
        if needle not in event_log:
            raise SystemExit(f"WeatherRouter event log frontend missing marker: {needle}")

    diagnostics_frontend = (FRONTEND / "weather-router-lab-diagnostics.js").read_text(encoding="utf-8")
    for needle in (
        "weather_router/provider_diagnostics",
        "Provider-Diagnose",
        "Alle Provider prüfen",
        "weather_router/all_provider_diagnostics",
        "JSON kopieren",
        "JSON teilen / speichern",
        "diagnostic-git",
        "Nach Git übertragen",
        "_diagnosticGitExport",
        "Fachbereich teilweise deaktiviert",
        "eligibleCapabilities",
        "navigator.clipboard?.writeText",
        "document.execCommand",
        "navigator.share",
        "provider_diagnostics.v1",
        "all_provider_diagnostics.v1",
        "Gefahrenfeed",
        "_diagnosticSetProgress",
        "_diagnosticAggregateReports",
        "_diagnosticTransportFailureReport",
        "Provider-Gesamtdiagnose läuft",
        "Provider ${safeCurrent}/${safeTotal}",
        "wr-diagnostic-spinner",
        "wr-diagnostic-progress-bar",
        'provider: provider.id',
    ):
        if needle not in diagnostics_frontend:
            raise SystemExit(f"WeatherRouter provider diagnostics frontend missing marker: {needle}")

    hazards_frontend = (FRONTEND / "weather-router-lab-hazards.js").read_text(encoding="utf-8")
    for needle in (
        "weather_router/hazard_feed",
        "Gefahren & Warnungen",
        "hazard_feed_loaded",
        "hazard-feed-events",
        "_hazardApplyToMap",
        "_hazardIcon",
        "tsunami_potential",
        "earthquake",
        "volcanic_activity",
        "🌊",
        "🌋",
        "FeatureCollection",
        "_hazardBindEvents",
        "data-hazard-toggle",
        "limit: 1000",
        "unabhängig vom aktuellen",
        "Karte enthält alle",
        "_hazardFocusEvent",
        "_hazardGeometryPoints",
        "data-hazard-focus",
        "hazard_event_focus",
        "Ereignis auf der Karte anzeigen",
        "fitBounds",
        "easeTo",
        "HAZARD_PROXIMITY_KEY",
        "HAZARD_PROXIMITY_DEFAULT_KM",
        "_hazardDistanceKm",
        "_hazardEventGeoMeta",
        "_hazardDisplayEvents",
        "_hazardNearbySummary",
        "Koordinaten ·",
        "Entfernung ·",
        "Nähehinweis",
        "Rein informativer WeatherRouter-Hinweis",
        "HAZARD_TARGET_SYMBOL_URL",
        "gewitterradar_target_symbol.svg",
        "hazard-event-focus img",
    ):
        if needle not in hazards_frontend:
            raise SystemExit(f"WeatherRouter hazard frontend missing marker: {needle}")

    target_svg = (FRONTEND / "gewitterradar_target_symbol.svg").read_text(encoding="utf-8")
    for marker in (
        'viewBox="0 0 64 64"',
        'stop-color="#E7C16A"',
        'stop-color="#8C5D17"',
        'stop-color="#F0CF75"',
        'stroke="#62B9FF"',
        'r="9.2"',
    ):
        if marker not in target_svg:
            raise SystemExit(f"WeatherRouter target SVG missing Gewitterradar marker: {marker}")

    for forbidden in (
        "_hazardCurrentBbox",
        "request.bbox",
    ):
        if forbidden in hazards_frontend:
            raise SystemExit(
                f"WeatherRouter hazard frontend must stay provider-scoped, not viewport-scoped: {forbidden}"
            )

    consumer_frontend = (FRONTEND / "weather-router-lab-consumer-api.js").read_text(encoding="utf-8")
    for needle in (
        "Consumer API V1 · Schnittstellentest",
        "weather_router/consumer/discovery",
        "weather_router/consumer/capabilities",
        "weather_router/consumer/resolve",
        "PRESENT",
        "COMPATIBLE",
        "READY",
        "_consumerApiContext",
        "Alle Themen",
        "consumer-api-phenomenon",
        "consumer-api-family",
        "consumer-api-hazard-type",
        "consumer-api-severity",
        "Ereignisfilter wirken erst nach dem Abruf",
    ):
        if needle not in consumer_frontend:
            raise SystemExit(f"WeatherRouter Consumer API Lab module missing marker: {needle}")

    for needle in (
        "weather_router/consumer_profiles",
        "weather_router/consumer_profile_upsert",
        "weather_router/consumer_profile_delete",
        "consumer-api-profile",
        "consumer-profile-template-storm",
        "consumer-profile-template-aurora",
        "data-profile-excluded-provider",
        "profile_id",
    ):
        if needle not in consumer_frontend:
            raise SystemExit(
                f"WeatherRouter consumer profile frontend missing marker: {needle}"
            )

    biological_frontend = (FRONTEND / "weather-router-lab-biological.js").read_text(encoding="utf-8")
    for needle in (
        "2a · Biologische Taxonsuche",
        "weather_router/biological_taxon_layer",
        "occurrence_density",
        "keine Populationsdichte",
        "_biologicalSearchTaxon",
        "_biologicalClearDynamicLayers",
        "gbif_biodiversity",
    ):
        if needle not in biological_frontend:
            raise SystemExit(f"WeatherRouter biological frontend missing marker: {needle}")

    routing_frontend = (FRONTEND / "weather-router-lab-routing.js").read_text(encoding="utf-8")
    for needle in (
        "weather_router/routing_settings",
        "weather_router/routing_settings_update",
        "0 · Router-Steuerung",
        "WeatherRouter aktiv",
        "Fachbereiche",
        "Dienste / Provider",
        'pollen: "Pollen"',
        'biological_hazards: "Biologische Gefahren & Wildtiere"',
        "keine Datenabrufe",
        "default_enabled",
        "enabled_by_user",
        "eligible_provider_count",
        "snapshot.routing",
    ):
        if needle not in routing_frontend:
            raise SystemExit(f"WeatherRouter routing frontend missing marker: {needle}")

    legends_frontend = (FRONTEND / "weather-router-lab-legends.js").read_text(encoding="utf-8")
    for needle in (
        "_mapWorkspaceElement",
        'mapWrap.querySelector("#weather-legends")',
    ):
        if needle not in legends_frontend:
            raise SystemExit(f"WeatherRouter legends detached-window support missing marker: {needle}")

    map_workspace = (FRONTEND / "weather-router-lab-map-workspace.js").read_text(encoding="utf-8")
    for needle in (
        'weather_router_lab_map_mode_v1',
        'DOCKED: "docked"',
        'POPOUT: "popout"',
        'HIDDEN: "hidden"',
        "_mapModeLoad",
        "_mapModePersist",
        "_captureMapViewState",
        "_restoreMapViewState",
        "_setMapMode",
        "_applyMapMode",
        "map-mode-hidden",
        "map-mode-popout",
        'window.open(',
        'MAP_WINDOW_NAME',
        '"popup=yes,width=1400,height=900,resizable=yes,scrollbars=no"',
        'popup.document.adoptNode(workspace)',
        'addEventListener("beforeunload"',
        '"map_window_opened"',
        "main_window_preserved:",
        '"map_window_closed"',
        '"map_window_blocked"',
        "map-dock-anchor",
        "map-workspace",
        'querySelector(\'[data-lab-menu-key="basemap"]\')',
        "sidebar.insertBefore(control, basemapMenu)",
        "In eigenem Fenster öffnen",
        "Andocken",
        "Karte ausblenden",
        "Karte anzeigen",
        "Kartenfenster anzeigen",
        "WeatherRouter bleibt im Hauptfenster vollständig nutzbar",
        "dockAnchor.after(workspace)",
        "map_mode_changed",
        "expectedMap.resize()",
    ):
        if needle not in map_workspace:
            raise SystemExit(f"WeatherRouter map workspace missing marker: {needle}")

    diagnostics_doc = (ROOT / "docs" / "DIAGNOSTICS.md").read_text(encoding="utf-8")
    for marker in (
        "weather_router.routing_diagnostic.v1",
        "50 Traces",
        "Diagnose beobachtet und erklärt Routing",
        "Aktuellen Kartenausschnitt testen",
        "ConfigEntry Diagnostics V2",
        "bbox_source",
    ):
        if marker not in diagnostics_doc:
            raise SystemExit(f"routing diagnostics documentation missing marker: {marker}")

    routing_diagnostic_core = (INTEGRATION / "routing_diagnostic_core.py").read_text(encoding="utf-8")
    for marker in (
        "weather_router.routing_diagnostic.v1",
        "ROUTING_DIAGNOSTIC_LIMIT = 50",
        "class RoutingTraceBuilder",
        "safe_url_summary",
        "resource_summary",
        "diagnostic_value",
    ):
        if marker not in routing_diagnostic_core:
            raise SystemExit(f"routing diagnostic core missing marker: {marker}")

    routing_diagnostics = (INTEGRATION / "routing_diagnostics.py").read_text(encoding="utf-8")
    for marker in (
        "weather_router/routing_diagnostics",
        "weather_router/routing_diagnostics_clear",
        "weather_router/routing_diagnostics_subscribe",
        "provider_runtime_summary",
        "routing_diagnostic_summary",
        "deque(maxlen=ROUTING_DIAGNOSTIC_LIMIT)",
    ):
        if marker not in routing_diagnostics:
            raise SystemExit(f"routing diagnostics runtime missing marker: {marker}")

    consumer_trace_markers = (
        "begin_routing_trace",
        "candidate_check",
        "candidate_coverage",
        "candidate_attempt",
        "trace.set_resource",
        "trace.set_freshness",
        "trace.set_decision",
        "trace.finish",
    )
    for marker in consumer_trace_markers:
        if marker not in consumer_api_source:
            raise SystemExit(f"Consumer routing trace missing marker: {marker}")

    routing_diagnostic_ui = (FRONTEND / "weather-router-lab-routing-diagnostics.js").read_text(encoding="utf-8")
    for marker in (
        "Routing & Consumer-Diagnose",
        "Live Routing beobachten",
        "Aktuellen Kartenausschnitt testen",
        "Puntland / Somalia",
        "Antimeridian",
        "Kandidatenmatrix",
        "Vergleichsmodus",
        "Routingreport herunterladen",
        "weather_router/routing_diagnostics_subscribe",
        "_wrGitExportSnapshot",
        "wr-rd-export-status",
        "Letzten Git-Export öffnen",
    ):
        if marker not in routing_diagnostic_ui:
            raise SystemExit(f"routing diagnostic UI missing marker: {marker}")

    log_export_ui = (FRONTEND / "weather-router-lab-log-export.js").read_text(encoding="utf-8")
    for marker in (
        "_wrGitExportSnapshot",
        "_wrGitPendingExport",
    ):
        if marker not in log_export_ui:
            raise SystemExit(f"shared Git export flow missing marker: {marker}")

    git_export_source = (INTEGRATION / "log_git_export.py").read_text(encoding="utf-8")
    for marker in (
        'schema == "weather_router.routing_diagnostic.v1"',
        'routing-diagnostic-',
        'meta.get("completed_at")',
    ):
        if marker not in git_export_source:
            raise SystemExit(f"routing Git export path missing marker: {marker}")

    dwd_source = (PROVIDERS / "dwd.py").read_text(encoding="utf-8")
    for marker in (
        "_async_layer_specific_coverage",
        "_layer_capabilities_endpoint",
        "wms_layer_get_capabilities",
        "layer_specific_wms",
        "aggregate_coverage_missing",
        "_DWD_PROVIDER_REVISION",
    ):
        if marker not in dwd_source:
            raise SystemExit(f"DWD layer coverage fallback missing marker: {marker}")

    hazard_common_source = (PROVIDERS / "hazard_common.py").read_text(encoding="utf-8")
    for marker in (
        "tornado_semantic_class",
        "tornado_hazard_match_scope",
        "normalize_alert_stage",
        "official_tornado_alert_event",
        "official_waterspout_alert_event",
        "wind_hazard_semantic_class",
        "wind_hazard_match_scope",
        "official_wind_alert_event",
        "official_downburst_alert_event",
        "explicit_event",
        "contextual_text",
    ):
        if marker not in hazard_common_source:
            raise SystemExit(f"Tornado hazard normalization missing marker: {marker}")

    nws_source = (PROVIDERS / "noaa_nws.py").read_text(encoding="utf-8")
    for marker in (
        "normalize_alert_stage",
        "tornado_hazard_match_scope",
        "tornado_semantic_class",
        "wind_hazard_match_scope",
        "wind_hazard_semantic_class",
    ):
        if marker not in nws_source:
            raise SystemExit(f"NWS Tornado semantics missing marker: {marker}")

    for marker in (
        "alert_stages",
        "hazard_match_scopes",
        "tornado_semantic_classes",
        "hail_match_scopes",
        "hail_semantic_classes",
        "wind_hazard_match_scopes",
        "wind_hazard_semantic_classes",
        'for semantic_key in (',
        'event[semantic_key] = raw.get(semantic_key)',
    ):
        if marker not in consumer_api_source:
            raise SystemExit(f"Consumer Tornado semantics missing marker: {marker}")

    diagnostic_source = (INTEGRATION / "routing_diagnostic_core.py").read_text(encoding="utf-8")
    for marker in (
        '"alert_stages"',
        '"tornado_semantic_classes"',
        '"hazard_match_scopes"',
        '"hail_semantic_classes"',
        '"hail_match_scopes"',
        '"wind_hazard_semantic_classes"',
        '"wind_hazard_match_scopes"',
    ):
        if marker not in diagnostic_source:
            raise SystemExit(f"Tornado routing diagnostics missing marker: {marker}")

    if '"error_message": error_message' not in consumer_api_source:
        raise SystemExit("Consumer coverage trace must preserve redacted coverage errors")

    config_diagnostics = (INTEGRATION / "diagnostics.py").read_text(encoding="utf-8")
    for marker in (
        "weather_router.config_entry_diagnostics.v2",
        "weather_router_build",
        "public_capability_count",
        "routing_trace_ring",
        "error_classes",
        "extension_count",
    ):
        if marker not in config_diagnostics:
            raise SystemExit(f"ConfigEntry diagnostics missing marker: {marker}")

    diagnostic_schema_expectations = {
        "routing_diagnostic.v1.schema.json": (
            ("properties", "schema", "const"),
            "weather_router.routing_diagnostic.v1",
        ),
        "routing_diagnostics.request.schema.json": (
            ("properties", "type", "const"),
            "weather_router/routing_diagnostics",
        ),
        "routing_diagnostics.index.v1.schema.json": (
            ("properties", "schema", "const"),
            "weather_router.routing_diagnostics.index.v1",
        ),
        "routing_diagnostics_clear.request.schema.json": (
            ("properties", "type", "const"),
            "weather_router/routing_diagnostics_clear",
        ),
        "routing_diagnostics_clear.response.schema.json": (
            ("properties", "schema", "const"),
            "weather_router.routing_diagnostics.index.v1",
        ),
        "routing_diagnostics_subscribe.request.schema.json": (
            ("properties", "type", "const"),
            "weather_router/routing_diagnostics_subscribe",
        ),
        "routing_diagnostic.event.v1.schema.json": (
            ("properties", "schema", "const"),
            "weather_router.routing_diagnostic.v1",
        ),
    }
    for file_name, (path_parts, expected) in diagnostic_schema_expectations.items():
        payload = json.loads(
            (DIAGNOSTICS_CONTRACT / file_name).read_text(encoding="utf-8")
        )
        current = payload
        for part in path_parts:
            current = current.get(part, {}) if isinstance(current, dict) else {}
        if current != expected:
            raise SystemExit(
                f"diagnostic schema mismatch: {file_name} expected {expected!r}, got {current!r}"
            )

    diagnostics_contract_readme = (
        DIAGNOSTICS_CONTRACT / "README.md"
    ).read_text(encoding="utf-8")
    for marker in (
        "weather_router/routing_diagnostics",
        "weather_router/routing_diagnostics_clear",
        "weather_router/routing_diagnostics_subscribe",
        "kein Bestandteil von Consumer API V1",
    ):
        if marker not in diagnostics_contract_readme:
            raise SystemExit(f"diagnostics contract README missing marker: {marker}")

    if f'WR_LAB_BUILD_VERSION = "{expected_dev_build}"' not in lab:
        raise SystemExit(
            f"WeatherRouter Lab: expected WR {expected_dev_build} from const.py"
        )

    routing_ui = (FRONTEND / "weather-router-lab-routing.js").read_text(encoding="utf-8")
    for marker in (
        "router-fold",
        "router-provider-group",
        "router-topic-section-title",
        "router-topic-pill",
        "hazardGroups.map",
        "group.name",
        "router-fold-count",
        "data-router-fold-key",
        "repeat(auto-fit,minmax(145px,1fr))",
    ):
        if marker not in routing_ui:
            raise SystemExit(f"WeatherRouter compact routing UI missing marker: {marker}")

    consumer_ui = (FRONTEND / "weather-router-lab-consumer-api.js").read_text(encoding="utf-8")
    for marker in (
        "consumer-api-fold",
        "consumer-api-profile-sections",
        "Provider-Ausschlüsse",
        "Filter & Auflösung",
        "Antwort / Diagnose",
        "Schnittstellenstatus",
        "Profil & Richtlinien",
        "data-consumer-section",
        "consumer-api-policy-grid",
        "data-profile-policy-toggle",
        "data-profile-policy-value",
        "baseCapabilities",
        "Erweiterte Capability-Positivliste",
    ):
        if marker not in consumer_ui:
            raise SystemExit(f"WeatherRouter compact Consumer API UI missing marker: {marker}")


    for marker in (
        "weather-provider-grid",
        "grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))",
        "weather-provider-group[open] { grid-column:1 / -1; }",
        "weather-provider-group-body",
    ):
        if marker not in lab:
            raise SystemExit(f"WeatherRouter adaptive weather-layer layout missing marker: {marker}")

    hazards_ui = (FRONTEND / "weather-router-lab-hazards.js").read_text(encoding="utf-8")
    for marker in (
        "hazard-overview",
        "hazard-filter-controls",
        "hazard-group-list",
        "hazard-group-body",
        "hazard-feed-expand",
        "hazard-feed-summary-meta",
        "Nur Feeds mit Ereignissen",
        "Tropische Systeme",
        "Tsunami & Küste",
        "Erdbeben & Vulkanismus",
        "repeat(auto-fit,minmax(min(100%,380px),1fr))",
    ):
        if marker not in hazards_ui:
            raise SystemExit(f"WeatherRouter compact hazards UI missing marker: {marker}")

    loader = (FRONTEND / "weather-router-lab-dev-loader.js").read_text(encoding="utf-8")
    if f'WR_LAB_BUILD_VERSION = "{expected_dev_build}"' not in loader:
        raise SystemExit(
            f"WeatherRouter loader: expected WR {expected_dev_build} from const.py"
        )
    if f'LOADER_REV = "{expected_dev_loader}"' not in loader:
        raise SystemExit(
            f"WeatherRouter loader: expected {expected_dev_loader} from const.py"
        )
    consumer_api_text = (INTEGRATION / "consumer_api.py").read_text(encoding="utf-8")
    for marker in (
        "_DIAGNOSTIC_FAULT_MODES",
        "resource_temporarily_unavailable",
        "rate_limited",
        "source_stale",
        "websocket_routing_diagnostic_fault_arm",
        "_consume_diagnostic_fault",
        "_fault_matches_candidate",
        "Admin-Diagnose simuliert nach realem Resource-Abruf eine veraltete Quelle.",
    ):
        if marker not in consumer_api_text:
            raise SystemExit(f"P0-070 diagnostic fault injection missing marker: {marker}")

    for marker in (
        "_public_intent_contract",
        "_validate_intent_resource_contract",
        '"intent_contract"',
        '"legend"',
        '"attribution"',
        '"numeric_interchangeable"',
        '"render_interchangeable"',
        'frame.get("kind")',
        '"default_index"',
        '"current_index"',
    ):
        if marker not in consumer_api_text and marker not in routing_core_text:
            raise SystemExit(f"P0-080 precipitation intent contract missing marker: {marker}")

    precipitation_meta = runtime_capability_map.get("public_capabilities", {}).get(
        "weather.precipitation.layer", {}
    )
    precipitation_contract = precipitation_meta.get("intent_contract", {})
    if precipitation_meta.get("name") != "Niederschlag · beste verfügbare Flächenebene":
        raise SystemExit("P0-080 precipitation intent public name is not provider-neutral")
    if precipitation_contract.get("resource_type") != "raster_tile":
        raise SystemExit("P0-080 precipitation intent must guarantee raster_tile")
    if precipitation_contract.get("render_interchangeable") is not True:
        raise SystemExit("P0-080 precipitation intent must be render-interchangeable")
    if precipitation_contract.get("numeric_interchangeable") is not False:
        raise SystemExit("P0-080 precipitation intent must not claim numeric interchangeability")
    if precipitation_contract.get("legend") != "required":
        raise SystemExit("P0-080 precipitation intent must require a legend")
    if precipitation_contract.get("attribution") != "required":
        raise SystemExit("P0-080 precipitation intent must require attribution")


    capability_map_text = (INTEGRATION / "consumer_capability_map.json").read_text(encoding="utf-8")
    nasa_gibs_text = (PROVIDERS / "nasa_gibs.py").read_text(encoding="utf-8")
    rainviewer_text = (PROVIDERS / "rainviewer.py").read_text(encoding="utf-8")
    if '"kind": (' not in nasa_gibs_text or '"estimate"' not in nasa_gibs_text:
        raise SystemExit("P0-080 IMERG timeline must preserve estimate frame semantics")
    if '"kind": "observation"' not in rainviewer_text:
        raise SystemExit("P0-080 RainViewer timeline must preserve observation frame semantics")
    for marker in (
        "_coverage_contract_allows",
        "machine_coverage_required",
        "coverage_declared",
    ):
        if marker not in consumer_api_text:
            raise SystemExit(f"Shared raster coverage policy missing marker: {marker}")
    if '"coverage_policy": "required"' not in capability_map_text:
        raise SystemExit("weather.precipitation.layer must require machine-readable coverage")
    for marker in (
        "async_get_coverage",
        "wms_layer_geographic_coverage",
        "NASA GIBS WMS GetCapabilities",
    ):
        if marker not in nasa_gibs_text:
            raise SystemExit(f"NASA GIBS machine coverage missing marker: {marker}")

    routing_runtime_text = (INTEGRATION / "routing_diagnostics.py").read_text(encoding="utf-8")
    routing_core_text = (INTEGRATION / "routing_diagnostic_core.py").read_text(encoding="utf-8")
    routing_schema_text = (DIAGNOSTICS_CONTRACT / "routing_diagnostic.v1.schema.json").read_text(encoding="utf-8")
    for marker in ("DEV_BUILD_VERSION", "DEV_LOADER_REV", "build_version", "loader_revision"):
        if marker not in routing_runtime_text and marker not in routing_core_text:
            raise SystemExit(f"Routing diagnostic build metadata missing marker: {marker}")
    for marker in ('"unit": None', '"unit": unit'):
        if marker not in routing_core_text:
            raise SystemExit(f"Routing diagnostic candidate unit missing marker: {marker}")
    for marker in ('"build_version"', '"loader_revision"'):
        if marker not in routing_schema_text:
            raise SystemExit(f"Routing diagnostic schema missing build metadata marker: {marker}")

    routing_diag_ui = (FRONTEND / "weather-router-lab-routing-diagnostics.js").read_text(encoding="utf-8")
    for marker in (
        "Capability suchen",
        "Kontext aus Trace übernehmen",
        "weather_router/consumer_profiles",
        "P0-060-Testprofile anlegen / aktualisieren",
        "P0-070 Fehlerprobe + Resolve starten",
        "weather_router/routing_diagnostic_fault_arm",
        "wr-rd-candidate-cards",
        "100dvh",
        "wr-rd-head-git",
        "wr-rd-head-status",
        "wr-diagnostic-hub",
        "_rdCaptureManual",
        "uiNumber",
    ):
        if marker not in routing_diag_ui:
            raise SystemExit(f"WeatherRouter routing diagnostic UX missing marker: {marker}")

    for needle in (
        "weather-router-lab.js",
        "weather-router-lab-map-workspace.js",
        "weather-router-lab-event-log.js",
        "weather-router-lab-log-export.js",
        "weather-router-lab-timeline.js",
        "weather-router-lab-raster-stability.js",
        "weather-router-lab-frame-buffer.js",
        "weather-router-lab-legends.js",
        "weather-router-lab-diagnostics.js",
        "weather-router-lab-hazards.js",
        "weather-router-lab-routing.js",
        "weather-router-lab-consumer-api.js",
        "weather-router-lab-biological.js",
        "weather-router-lab-dev-loader",
        "import.meta.url",
    ):
        if needle not in loader:
            raise SystemExit(f"WeatherRouter Lab dev loader missing required marker: {needle}")

    consumer_source = (INTEGRATION / "consumer_api.py").read_text(encoding="utf-8")
    provider_contract_source = (PROVIDERS / "__init__.py").read_text(encoding="utf-8")
    websocket_source = (INTEGRATION / "websocket_api.py").read_text(encoding="utf-8")
    if "class DataFileProvider" not in provider_contract_source:
        raise SystemExit("provider contract missing DataFileProvider")
    for marker in (
        '"event_feed"',
        "async_get_event_feed",
        "_normalize_event_feed",
        "_normalize_data_file",
        "async_get_data_file",
    ):
        if marker not in consumer_source:
            raise SystemExit(f"Consumer event_feed support missing marker: {marker}")
    for marker in (
        "weather_router/event_feed",
        "websocket_event_feed",
        "_event_feed_diagnostic_summary",
        "_data_file_diagnostic_summary",
        "data_file_resolved",
    ):
        if marker not in websocket_source:
            raise SystemExit(f"WeatherRouter event_feed websocket missing marker: {marker}")

    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    if "async_register_consumer_api" not in init_source:
        raise SystemExit("Consumer API is not registered by the integration")
    profile_source = (INTEGRATION / "consumer_profiles.py").read_text(encoding="utf-8")
    for marker in (
        "validate_consumer_profiles",
        "normalize_consumer_profile",
        "profile_allows_capability",
        "profile_allows_provider",
        "apply_profile_event_filter",
        "excluded_providers",
    ):
        if marker not in profile_source:
            raise SystemExit(f"Consumer profile policy missing marker: {marker}")
    websocket_source = (INTEGRATION / "websocket_api.py").read_text(encoding="utf-8")
    for marker in (
        "weather_router/biological_taxon_layer",
        "websocket_biological_taxon_layer",
        "async_get_taxon_layer",
        "gbif_biodiversity",
    ):
        if marker not in websocket_source:
            raise SystemExit(f"biological taxon admin API missing marker: {marker}")
    for marker in (
        "weather_router/consumer_profiles",
        "weather_router/consumer_profile_upsert",
        "weather_router/consumer_profile_delete",
    ):
        if marker not in websocket_source:
            raise SystemExit(f"Consumer profile admin API missing marker: {marker}")
    profile_path = INTEGRATION / "consumer_profiles.py"
    profile_spec = importlib.util.spec_from_file_location(
        "weather_router_consumer_profiles_verifier",
        profile_path,
    )
    if profile_spec is None or profile_spec.loader is None:
        raise SystemExit("Consumer profile policy could not be loaded for verification")
    profile_module = importlib.util.module_from_spec(profile_spec)
    profile_spec.loader.exec_module(profile_module)

    test_profile = profile_module.normalize_consumer_profile(
        "aurora_test",
        {
            "name": "Aurora Test",
            "enabled": True,
            "allowed_domains": ["weather", "space"],
            "allowed_families": ["point", "solar"],
            "allowed_phenomena": ["clouds", "visibility"],
            "allowed_hazard_types": ["severe_thunderstorm", "hail"],
            "excluded_providers": ["provider_bad"],
        },
        known_domains={"weather", "space"},
        known_providers={"provider_good", "provider_bad"},
    )
    if profile_module.profile_allows_provider(test_profile, "provider_bad"):
        raise SystemExit("Consumer profile deny-only provider exclusion regressed")
    if not profile_module.profile_allows_provider(test_profile, "provider_good"):
        raise SystemExit("Consumer profile unexpectedly excludes allowed provider")

    profile_mapping = {
        "public_capabilities": {
            "weather.point.cloud_cover": {
                "family": "point",
                "phenomena": ["clouds"],
                "hazard_types": [],
            },
            "natural_hazards.earthquake.events": {
                "family": "earthquake",
                "phenomena": [],
                "hazard_types": ["earthquake"],
            },
        }
    }
    allowed, _reason = profile_module.profile_allows_capability(
        test_profile,
        profile_mapping,
        "weather.point.cloud_cover",
    )
    if not allowed:
        raise SystemExit("Consumer profile incorrectly filters allowed cloud capability")
    allowed, _reason = profile_module.profile_allows_capability(
        test_profile,
        profile_mapping,
        "natural_hazards.earthquake.events",
    )
    if allowed:
        raise SystemExit("Consumer profile domain allow-list failed to filter earthquake")

    merged_filter, conflict = profile_module.apply_profile_event_filter(
        test_profile,
        {
            "hazard_types": {"severe_thunderstorm", "heavy_rain"},
            "severities": {"severe"},
        },
    )
    if conflict or merged_filter.get("hazard_types") != {"severe_thunderstorm"}:
        raise SystemExit("Consumer profile/request hazard intersection regressed")

    _merged_filter, conflict = profile_module.apply_profile_event_filter(
        test_profile,
        {"hazard_types": {"earthquake"}},
    )
    if not conflict:
        raise SystemExit("Consumer profile empty hazard intersection must conflict")

    try:
        profile_module.normalize_consumer_profile(
            "invalid_priority",
            {
                "name": "Invalid",
                "enabled": True,
                "preferred_providers": ["provider_good"],
            },
        )
    except ValueError:
        pass
    else:
        raise SystemExit("Consumer profiles must reject provider priority fields")

    profile_schema = json.loads(
        (CONSUMER_V1 / "consumer-profile.schema.json").read_text(encoding="utf-8")
    )
    capability_pattern = (
        profile_schema
        .get("properties", {})
        .get("allowed_capabilities", {})
        .get("items", {})
        .get("pattern")
    )
    if not isinstance(capability_pattern, str):
        raise SystemExit("Consumer profile schema missing allowed_capabilities pattern")
    if re.fullmatch(capability_pattern, "weather.point.cloud_cover") is None:
        raise SystemExit("Consumer profile schema rejects valid public capability id")
    if re.fullmatch(capability_pattern, r"weather\\point") is not None:
        raise SystemExit("Consumer profile schema accepts invalid capability id")
    if "weather-router-lab-dev-loader.js" not in init_source:
        raise SystemExit("WeatherRouter panel is not routed through the development loader")

    print("WeatherRouter provider structure: OK")


if __name__ == "__main__":
    main()
