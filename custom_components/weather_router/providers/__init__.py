"""WeatherRouter provider registry.

Provider implementations stay behind this small project-local contract. Shared provider
knowledge remains canonical in home-assistant-dev-toolkit/knowledge/weather/.

The provider module list is deliberately data-driven. The small JSON registry is read on
catalog access so newly copied provider modules can be discovered during development
without changing this already-imported module or restarting Home Assistant. Existing
Python modules are not force-reloaded; edits to already imported provider code still
require a controlled Home Assistant restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module, invalidate_caches
import json
import logging
from pathlib import Path
import re
from typing import Any, Protocol

from homeassistant.core import HomeAssistant

from ..extensions import extension_provider_catalog

_LOGGER = logging.getLogger(__name__)
_REGISTRY_PATH = Path(__file__).with_name("registry.json")
_SAFE_MODULE = re.compile(r"^[a-z][a-z0-9_]*$")
_SAFE_CLASS = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SAFE_DOMAIN = re.compile(r"^[a-z][a-z0-9_]*$")
_SAFE_TOPIC = re.compile(r"^[a-z][a-z0-9_]*$")
_REGISTRY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CapabilityInfo:
    """One provider capability exposed to the diagnostic/router layer."""

    id: str
    name: str
    unit: str | None
    source_class: str
    render_mode: str = "value"
    description: str | None = None
    coverage: str | None = None
    temporal_resolution: str | None = None
    typical_latency: str | None = None
    strengths: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    documentation_url: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Human-readable, secret-free provider information for generic UIs."""

    summary: str
    coverage: str | None = None
    strengths: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    documentation_url: str | None = None
    attribution: str | None = None
    services: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class NetworkTargetInfo:
    """One documented provider network destination.

    These records are intentionally secret-free and FQDN-oriented. They are the future
    source for the WeatherRouter firewall/network view; provider-specific runtime
    descriptors may additionally report resolved dynamic tile hosts.
    """

    purpose: str
    scheme: str
    host: str
    port: int
    target_type: str
    required: bool = True
    capabilities: tuple[str, ...] = ()
    note: str | None = None


class Provider(Protocol):
    """Minimal common provider contract used by the V0.10 diagnostic lab."""

    id: str
    name: str

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        """Return capabilities currently implemented by this provider."""

    def provider_info(self) -> ProviderInfo:
        """Return structured explanatory metadata for generic UIs."""

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        """Return secret-free documented network targets used by this provider."""


class PointProvider(Provider, Protocol):
    """Provider contract for point-value data."""

    async def async_fetch_point(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        capability_ids: list[str],
    ) -> dict[str, Any]:
        """Fetch point data for the requested capabilities."""


class MapLayerProvider(Provider, Protocol):
    """Provider contract for map-layer descriptors."""

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return one renderable map-layer descriptor."""


class RasterCoverageProvider(Provider, Protocol):
    """Optional machine-readable spatial coverage contract for raster providers."""

    async def async_get_coverage(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return machine-readable geographic coverage for one raster capability."""


class DataFileProvider(Provider, Protocol):
    """Provider contract for directly resolvable data-file resources."""

    async def async_get_data_file(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return one provider data-file descriptor."""


class EventFeedProvider(Provider, Protocol):
    """Provider contract for normalized observation/event feeds."""

    async def async_get_event_feed(
        self,
        hass: HomeAssistant,
        capability_id: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Return one normalized non-warning event feed."""


class HazardFeedProvider(Provider, Protocol):
    """Provider contract for normalized warning/event feeds."""

    async def async_get_hazard_feed(
        self,
        hass: HomeAssistant,
        capability_id: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        """Return one normalized WeatherRouter hazard feed."""


def _registry_entries() -> tuple[dict[str, str], ...]:
    """Read and validate the small development-time provider registry."""
    payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != _REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported provider registry schema_version")

    raw_entries = payload.get("providers")
    if not isinstance(raw_entries, list):
        raise ValueError("provider registry providers must be a list")

    entries: list[dict[str, str]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("provider registry entry must be an object")
        module = raw.get("module")
        class_name = raw.get("class")
        domains = raw.get("domains", ["weather"])
        topics = raw.get("topics", [])
        default_enabled = raw.get("default_enabled", True)
        if (
            not isinstance(module, str)
            or not _SAFE_MODULE.fullmatch(module)
            or not isinstance(class_name, str)
            or not _SAFE_CLASS.fullmatch(class_name)
            or not isinstance(domains, list)
            or not domains
            or any(
                not isinstance(domain, str) or not _SAFE_DOMAIN.fullmatch(domain)
                for domain in domains
            )
            or len(set(domains)) != len(domains)
            or not isinstance(topics, list)
            or any(
                not isinstance(topic, str) or not _SAFE_TOPIC.fullmatch(topic)
                for topic in topics
            )
            or len(set(topics)) != len(topics)
            or not isinstance(default_enabled, bool)
        ):
            raise ValueError("provider registry contains invalid module/class/domain/topic metadata")
        entries.append(
            {
                "module": module,
                "class": class_name,
                "domains": tuple(domains),
                "topics": tuple(topics),
                "default_enabled": default_enabled,
            }
        )

    return tuple(entries)


def provider_catalog(*, include_hidden: bool = False) -> dict[str, Provider]:
    """Return provider instances from the reloadable module registry.

    The registry file itself is read on every access. Newly added module names therefore
    become importable without restarting Home Assistant. Python deliberately keeps an
    already imported module cached; modifying an existing provider implementation still
    requires a restart and is not hidden behind unsafe runtime module reloading.
    """
    invalidate_caches()
    providers: dict[str, Provider] = {}

    try:
        entries = _registry_entries()
    except (OSError, json.JSONDecodeError, ValueError) as err:
        _LOGGER.error("WeatherRouter provider registry could not be loaded: %s", err)
        return providers

    for entry in entries:
        module_name = entry["module"]
        class_name = entry["class"]
        try:
            module = import_module(f"{__package__}.{module_name}")
            provider_class = getattr(module, class_name)
            provider = provider_class()
            provider_id = provider.id
            if not isinstance(provider_id, str) or not provider_id:
                raise ValueError("provider id must be a non-empty string")
            if provider_id in providers:
                raise ValueError(f"duplicate provider id: {provider_id}")
            # Registry routing metadata is deliberately attached at discovery time.
            # Provider implementations stay focused on source semantics and do not
            # need to know about user eligibility/policy.
            setattr(provider, "router_domains", tuple(entry["domains"]))
            setattr(provider, "router_topics", tuple(entry.get("topics", ())))
            setattr(provider, "router_default_enabled", bool(entry["default_enabled"]))
            visibility = getattr(provider, "is_visible", None)
            if not include_hidden and callable(visibility) and not bool(visibility()):
                continue
            providers[provider_id] = provider
        except Exception as err:  # noqa: BLE001 - isolate one broken dev provider
            _LOGGER.error(
                "WeatherRouter provider %s.%s could not be loaded: %s",
                module_name,
                class_name,
                err,
            )

    for provider_id, provider in extension_provider_catalog(
        include_hidden=include_hidden
    ).items():
        if provider_id in providers:
            _LOGGER.error(
                "WeatherRouter extension provider id collides with built-in provider: %s",
                provider_id,
            )
            continue
        providers[provider_id] = provider

    return providers
