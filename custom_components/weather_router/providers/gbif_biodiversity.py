"""GBIF biodiversity occurrence-density layers for biological hazards and wildlife.

The provider deliberately exposes *occurrence density*, never population density or a
probability of harm. GBIF aggregates occurrence records from many underlying datasets;
their individual licences and attribution requirements remain applicable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_PROVIDER_REVISION = "wr-0.10.73-gbif-bio-3"
_CATALOG_PATH = Path(__file__).with_name("biological_taxa.json")
_MATCH_URL = "https://api.gbif.org/v2/species/match"
_COL_XR_CHECKLIST_KEY = "7ddf754f-d193-4cc9-b351-99906754a03b"
_MAP_BASE = "https://api.gbif.org/v2/map/occurrence/adhoc"
_DOC_URL = "https://techdocs.gbif.org/openapi/v2-maps.json"
_TERMS_URL = "https://www.gbif.org/terms/data-user"


@dataclass(frozen=True, slots=True)
class _TaxonLayer:
    capability_id: str
    name: str
    scientific_name: str
    group: str
    match_rank: str | None = None
    match_kingdom: str | None = None
    match_authorship: str | None = None


_GROUP_LABELS = {
    "predator": "Prädatoren",
    "large_wildlife": "Große Wildtiere",
    "crocodilian": "Krokodilartige",
    "marine": "Marine Großtiere",
    "marine_venomous": "Marine Gifttiere",
    "snake": "Schlangen",
    "venomous_snake": "Giftschlangen",
    "venomous_arthropod": "Giftige Gliederfüßer",
    "poisonous_amphibian": "Giftige Amphibien",
    "toxic_plant": "Giftige / stark reizende Pflanzen",
    "toxic_fungus": "Giftpilze",
    "vector": "Biologische Vektoren",
}


@lru_cache(maxsize=1)
def _catalog() -> tuple[int, tuple[_TaxonLayer, ...]]:
    payload = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported biological taxon catalog schema")
    from_year = int(payload.get("from_year", 2000))
    if from_year < 1800 or from_year > datetime.now(timezone.utc).year:
        raise ValueError("invalid biological taxon catalog from_year")

    raw_taxa = payload.get("taxa")
    if not isinstance(raw_taxa, list) or not raw_taxa:
        raise ValueError("biological taxon catalog needs taxa")

    layers: list[_TaxonLayer] = []
    seen: set[str] = set()
    for raw in raw_taxa:
        if not isinstance(raw, dict):
            raise ValueError("biological taxon catalog entry must be an object")
        taxon_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        scientific_name = str(raw.get("scientific_name") or "").strip()
        group = str(raw.get("group") or "").strip()
        match_rank = str(raw.get("match_rank") or "").strip() or None
        match_kingdom = str(raw.get("match_kingdom") or "").strip() or None
        match_authorship = str(raw.get("match_authorship") or "").strip() or None
        if not taxon_id or not name or not scientific_name or group not in _GROUP_LABELS:
            raise ValueError(f"invalid biological taxon catalog entry: {raw!r}")
        if taxon_id in seen:
            raise ValueError(f"duplicate biological taxon id: {taxon_id}")
        seen.add(taxon_id)
        layers.append(
            _TaxonLayer(
                capability_id=f"occurrence_density_{taxon_id}",
                name=name,
                scientific_name=scientific_name,
                group=group,
                match_rank=match_rank,
                match_kingdom=match_kingdom,
                match_authorship=match_authorship,
            )
        )
    return from_year, tuple(layers)


def _layers() -> tuple[_TaxonLayer, ...]:
    return _catalog()[1]


def _capabilities() -> tuple[CapabilityInfo, ...]:
    from_year, layers = _catalog()
    return tuple(
        CapabilityInfo(
            id=item.capability_id,
            name=f"GBIF · Vorkommensdichte · {item.name}",
            unit="Vorkommensnachweise pro Rasterzelle",
            source_class="biodiversity_occurrence",
            render_mode="raster_tile",
            description=(
                f"Rasterisierte Dichte von GBIF-vermittelten Vorkommensnachweisen für "
                f"{item.name} ({item.scientific_name}) seit {from_year}. "
                "Dies ist ausdrücklich keine Populationsdichte und keine Gefahrenwahrscheinlichkeit."
            ),
            coverage="Global · abhängig von veröffentlichten GBIF-Nachweisen",
            temporal_resolution=f"Vorkommensnachweise {from_year}–heute",
            strengths=(
                "globale Biodiversitätsdaten aus vielen wissenschaftlichen und behördlichen Datensätzen",
                "taxonomisch normalisierte GBIF-Nachweise",
                "direkt als globale Dichtekarte darstellbar",
            ),
            limitations=(
                "Vorkommensdichte ist keine Populationsdichte",
                "Beobachtungsaufwand ist räumlich und zeitlich ungleich verteilt",
                "fehlende Nachweise bedeuten nicht, dass eine Art fehlt",
                "ein Nachweis ist keine aktuelle Warnung oder Aussage zur Angriffswahrscheinlichkeit",
                "Lizenzen und Attribution der zugrunde liegenden Datensätze bleiben maßgeblich",
            ),
            documentation_url=_DOC_URL,
        )
        for item in layers
    )


_LAYER_BY_CAPABILITY = {item.capability_id: item for item in _layers()}


class GbifBiodiversityProvider:
    """Expose GBIF occurrence-density maps for selected biological hazard taxa."""

    id = "gbif_biodiversity"
    name = "GBIF · Biologische Vorkommen"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _capabilities()

    def provider_info(self) -> ProviderInfo:
        from_year, layers = _catalog()
        groups = sorted({_GROUP_LABELS[item.group] for item in layers})
        return ProviderInfo(
            summary=(
                "GBIF vermittelt weltweit Biodiversitäts-Vorkommensdaten aus vielen "
                "wissenschaftlichen, behördlichen und Community-Datensätzen. WeatherRouter "
                "nutzt die offizielle GBIF-Map-API für rasterisierte Vorkommensdichten."
            ),
            coverage="Global · datenabhängig",
            strengths=(
                f"{len(layers)} vorbereitete Taxa/Artengruppen",
                "Prädatoren, Krokodilartige, Haie, Giftschlangen, Gifttiere, Giftpflanzen, Giftpilze und Vektoren",
                "keine Zugangsdaten erforderlich",
                "datengetriebener Katalog lässt sich ohne Provider-Sonderlogik erweitern",
            ),
            limitations=(
                "keine echte Populationsdichte",
                "keine automatische Risikobewertung",
                "keine amtliche Warnquelle",
                "Beobachtungs-/Publikationsbias möglich",
                "unterliegende Datensatzlizenzen und Attribution beachten",
            ),
            documentation_url=_DOC_URL,
            attribution="GBIF.org · GBIF-mediated occurrence data",
            services=(
                {
                    "name": "GBIF Species Match API v2 · COL XR",
                    "status": "integriert",
                    "note": "taxonomische Auflösung über Catalogue of Life Extended Release",
                },
                {
                    "name": "GBIF Maps API · occurrence density",
                    "status": "integriert",
                    "note": f"Rasterisierte Vorkommensdichte {from_year}–heute",
                },
                {
                    "name": "Abgedeckte Gruppen",
                    "status": "integriert",
                    "note": ", ".join(groups),
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="biodiversity_taxon_match_and_occurrence_density",
                scheme="https",
                host="api.gbif.org",
                port=443,
                target_type="https_api_and_raster_tiles",
                required=True,
                capabilities=tuple(item.capability_id for item in _layers()),
                note=(
                    "GBIF Species Match API v2 + COL XR + Maps API. "
                    "Vorkommensdichte, nicht Populationsdichte oder Gefahrenwahrscheinlichkeit."
                ),
            ),
        )

    async def _async_taxon_match(
        self,
        hass: HomeAssistant,
        item: _TaxonLayer,
    ) -> dict[str, Any]:
        session = async_get_clientsession(hass)
        match_params = {
            "scientificName": item.scientific_name,
            "checklistKey": _COL_XR_CHECKLIST_KEY,
        }
        if item.match_rank:
            match_params["taxonRank"] = item.match_rank
        if item.match_kingdom:
            match_params["kingdom"] = item.match_kingdom
        if item.match_authorship:
            match_params["scientificNameAuthorship"] = item.match_authorship

        async with session.get(
            _MATCH_URL,
            params=match_params,
            headers={
                "Accept": "application/json",
                "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)",
            },
            timeout=20,
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        accepted_usage = (
            payload.get("acceptedUsage")
            if isinstance(payload.get("acceptedUsage"), dict)
            else {}
        )
        diagnostics = (
            payload.get("diagnostics")
            if isinstance(payload.get("diagnostics"), dict)
            else {}
        )
        key = usage.get("key") or accepted_usage.get("key")
        taxon_key = str(key).strip() if key is not None else ""
        if not taxon_key:
            raise ValueError(
                f"GBIF COL XR konnte {item.scientific_name!r} keinem Taxon zuordnen"
            )

        return {
            "taxon_key": taxon_key,
            "scientific_name": (
                usage.get("name")
                or accepted_usage.get("name")
                or item.scientific_name
            ),
            "canonical_name": (
                usage.get("canonicalName")
                or accepted_usage.get("canonicalName")
                or item.scientific_name
            ),
            "rank": usage.get("rank") or accepted_usage.get("rank"),
            "status": (
                usage.get("status")
                or accepted_usage.get("status")
                or payload.get("taxonomicStatus")
            ),
            "match_type": diagnostics.get("matchType"),
            "confidence": diagnostics.get("confidence"),
            "taxonomy": "Catalogue of Life Extended Release",
            "checklist_key": _COL_XR_CHECKLIST_KEY,
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        item = _LAYER_BY_CAPABILITY.get(capability_id)
        if item is None:
            raise ValueError(f"Unsupported GBIF biodiversity capability: {capability_id}")

        match = await self._async_taxon_match(hass, item)
        from_year, _ = _catalog()
        current_year = datetime.now(timezone.utc).year
        query = urlencode(
            {
                "srs": "EPSG:3857",
                "taxonKey": str(match["taxon_key"]),
                "checklistKey": _COL_XR_CHECKLIST_KEY,
                "year": f"{from_year},{current_year}",
                "hasGeospatialIssue": "false",
                "bin": "hex",
                "hexPerTile": "64",
                "style": "purpleYellow-noborder.poly",
            }
        )
        tile_url = f"{_MAP_BASE}/{{z}}/{{x}}/{{y}}@1x.png?{query}"

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "biodiversity_occurrence",
            "render_mode": "raster_tile",
            "frame_time": None,
            "tile_url": tile_url,
            "tile_size": 256,
            "max_zoom": 10,
            "default_opacity": 0.78,
            "attribution": (
                'Biodiversity occurrence data: <a href="https://www.gbif.org/" '
                'target="_blank" rel="noopener noreferrer">GBIF.org</a> · '
                'underlying dataset licences apply'
            ),
            "network_hosts": ["api.gbif.org"],
            "provider_metadata": {
                "service": "GBIF Maps API v2",
                "taxonomy": "Catalogue of Life Extended Release",
                "checklist_key": _COL_XR_CHECKLIST_KEY,
                "match_rank_hint": item.match_rank,
                "match_kingdom_hint": item.match_kingdom,
                "match_authorship_hint": item.match_authorship,
                "semantics": "occurrence_density",
                "population_density": False,
                "risk_probability": False,
                "scientific_name_requested": item.scientific_name,
                "scientific_name_matched": match["scientific_name"],
                "taxon_key": match["taxon_key"],
                "taxon_rank": match["rank"],
                "taxon_status": match["status"],
                "match_type": match["match_type"],
                "match_confidence": match["confidence"],
                "group": item.group,
                "group_name": _GROUP_LABELS[item.group],
                "from_year": from_year,
                "to_year": current_year,
                "quality_filter": "hasGeospatialIssue=false",
                "warning": (
                    "Diese Ebene zeigt die Dichte veröffentlichter Vorkommensnachweise. "
                    "Sie ist weder Populationsdichte noch aktuelle Anwesenheits- oder Gefahrenprognose."
                ),
                "data_user_agreement": _TERMS_URL,
            },
        }

    async def async_get_taxon_layer(
        self,
        hass: HomeAssistant,
        scientific_name: str,
    ) -> dict[str, Any]:
        """Resolve an arbitrary GBIF taxon into an admin-Lab occurrence-density layer."""
        name = str(scientific_name or "").strip()
        if len(name) < 2 or len(name) > 200:
            raise ValueError("Taxonname muss zwischen 2 und 200 Zeichen lang sein")

        dynamic = _TaxonLayer(
            capability_id="dynamic_taxon_search",
            name=name,
            scientific_name=name,
            group="dynamic",
        )
        match = await self._async_taxon_match(hass, dynamic)
        from_year, _ = _catalog()
        current_year = datetime.now(timezone.utc).year
        query = urlencode(
            {
                "srs": "EPSG:3857",
                "taxonKey": str(match["taxon_key"]),
                "checklistKey": _COL_XR_CHECKLIST_KEY,
                "year": f"{from_year},{current_year}",
                "hasGeospatialIssue": "false",
                "bin": "hex",
                "hexPerTile": "64",
                "style": "purpleYellow-noborder.poly",
            }
        )
        tile_url = f"{_MAP_BASE}/{{z}}/{{x}}/{{y}}@1x.png?{query}"
        matched_name = str(match.get("scientific_name") or name)

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": "dynamic_taxon_search",
            "source_class": "biodiversity_occurrence",
            "render_mode": "raster_tile",
            "frame_time": None,
            "tile_url": tile_url,
            "tile_size": 256,
            "max_zoom": 10,
            "default_opacity": 0.78,
            "attribution": (
                'Biodiversity occurrence data: <a href="https://www.gbif.org/" '
                'target="_blank" rel="noopener noreferrer">GBIF.org</a> · '
                'underlying dataset licences apply'
            ),
            "network_hosts": ["api.gbif.org"],
            "provider_metadata": {
                "service": "GBIF Maps API v2",
                "taxonomy": "Catalogue of Life Extended Release",
                "checklist_key": _COL_XR_CHECKLIST_KEY,
                "match_rank_hint": dynamic.match_rank,
                "match_kingdom_hint": dynamic.match_kingdom,
                "match_authorship_hint": dynamic.match_authorship,
                "semantics": "occurrence_density",
                "population_density": False,
                "risk_probability": False,
                "dynamic_taxon_search": True,
                "scientific_name_requested": name,
                "scientific_name_matched": matched_name,
                "canonical_name": match.get("canonical_name"),
                "taxon_key": match["taxon_key"],
                "taxon_rank": match.get("rank"),
                "taxon_status": match.get("status"),
                "match_type": match.get("match_type"),
                "match_confidence": match.get("confidence"),
                "from_year": from_year,
                "to_year": current_year,
                "quality_filter": "hasGeospatialIssue=false",
                "warning": (
                    "Freie GBIF-Taxonsuche: Vorkommensdichte veröffentlichter Nachweise, "
                    "keine Populationsdichte und keine Gefahrenwahrscheinlichkeit."
                ),
                "data_user_agreement": _TERMS_URL,
            },
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id is None:
            item = _LAYER_BY_CAPABILITY.get("occurrence_density_lion")
        else:
            item = _LAYER_BY_CAPABILITY.get(capability_id)
        if item is None:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }

        try:
            match = await self._async_taxon_match(hass, item)
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "stage": "gbif_species_match",
                "provider_revision": _PROVIDER_REVISION,
                "capability": item.capability_id,
                "error": {"type": type(err).__name__, "message": str(err)},
            }

        from_year, layers = _catalog()
        return {
            "ok": True,
            "stage": "gbif_species_match",
            "provider_revision": _PROVIDER_REVISION,
            "capability": item.capability_id,
            "catalog_count": len(layers),
            "from_year": from_year,
            "match": match,
            "semantics": {
                "occurrence_density": True,
                "population_density": False,
                "risk_probability": False,
            },
        }
