"""Generic local extension loader for WeatherRouter.

Concrete local providers live outside the standard integration package below
/config/.weather-router/extensions. The core only implements this generic,
fail-closed manifest and lifecycle contract.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
EXTENSION_ROOT = Path("/config/.weather-router/extensions")
EXTENSION_MANIFEST = "extension.json"
EXTENSION_SCHEMA = "weather_router.extension.v1"
_EXTENSION_STATE_KEY = "weather_router_extension_modules"
_MAX_MANIFEST_BYTES = 128 * 1024
_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_SAFE_CLASS = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,127}$")
_SAFE_DOMAIN = re.compile(r"^[a-z][a-z0-9_]*$")
_SAFE_INTERNAL = re.compile(r"^[a-z][a-z0-9_]*$")
_SAFE_PUBLIC = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")


@dataclass(frozen=True, slots=True)
class _DedicatedBufferPolicyManifest(Exception):
    """Not a provider extension; parsed by the opt-in E-078 loader."""


class ExtensionSpec:
    extension_id: str
    root: Path
    provider_id: str
    provider_class: str
    domains: tuple[str, ...]
    default_enabled: bool
    provider_capabilities: dict[str, list[str]]
    public_capabilities: dict[str, dict[str, Any]]


def _extension_spec(directory: Path) -> ExtensionSpec:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("extension directory must be a real directory")
    manifest = directory / EXTENSION_MANIFEST
    init_file = directory / "__init__.py"
    if not manifest.is_file() or not init_file.is_file() or manifest.is_symlink():
        raise ValueError("extension requires real extension.json and __init__.py")
    if manifest.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("extension manifest exceeds size limit")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if (isinstance(payload, dict)
            and payload.get("schema") == "weather_router.extension.v2"
            and payload.get("kind") == "buffer_policy"):
        raise _DedicatedBufferPolicyManifest()
    if not isinstance(payload, dict) or payload.get("schema") != EXTENSION_SCHEMA:
        raise ValueError("unsupported extension manifest")
    extension_id = payload.get("id")
    if not isinstance(extension_id, str) or not _SAFE_ID.fullmatch(extension_id) or extension_id != directory.name:
        raise ValueError("invalid extension id")

    provider = payload.get("provider")
    if not isinstance(provider, dict):
        raise ValueError("provider metadata missing")
    provider_id = provider.get("id")
    provider_class = provider.get("class")
    domains = provider.get("domains")
    default_enabled = provider.get("default_enabled", False)
    if (
        not isinstance(provider_id, str) or not _SAFE_ID.fullmatch(provider_id)
        or not isinstance(provider_class, str) or not _SAFE_CLASS.fullmatch(provider_class)
        or not isinstance(domains, list) or not domains
        or any(not isinstance(item, str) or not _SAFE_DOMAIN.fullmatch(item) for item in domains)
        or len(set(domains)) != len(domains)
        or not isinstance(default_enabled, bool)
    ):
        raise ValueError("invalid provider metadata")

    consumer = payload.get("consumer")
    if not isinstance(consumer, dict):
        raise ValueError("consumer metadata missing")
    provider_map = consumer.get("provider_capabilities")
    public_map = consumer.get("public_capabilities", {})
    if not isinstance(provider_map, dict) or not provider_map or not isinstance(public_map, dict):
        raise ValueError("invalid consumer mapping")

    normalized_provider: dict[str, list[str]] = {}
    for internal_id, public_ids in provider_map.items():
        if (
            not isinstance(internal_id, str) or not _SAFE_INTERNAL.fullmatch(internal_id)
            or not isinstance(public_ids, list) or not public_ids
            or any(not isinstance(public_id, str) or not _SAFE_PUBLIC.fullmatch(public_id) for public_id in public_ids)
        ):
            raise ValueError("invalid capability mapping")
        normalized_provider[internal_id] = list(dict.fromkeys(public_ids))

    normalized_public: dict[str, dict[str, Any]] = {}
    for public_id, metadata in public_map.items():
        if not isinstance(public_id, str) or not _SAFE_PUBLIC.fullmatch(public_id) or not isinstance(metadata, dict):
            raise ValueError("invalid public capability metadata")
        normalized_public[public_id] = deepcopy(metadata)

    return ExtensionSpec(
        extension_id, directory, provider_id, provider_class, tuple(domains),
        default_enabled, normalized_provider, normalized_public
    )


def extension_specs() -> tuple[ExtensionSpec, ...]:
    if not EXTENSION_ROOT.is_dir():
        return ()
    result: list[ExtensionSpec] = []
    for directory in sorted(EXTENSION_ROOT.iterdir(), key=lambda item: item.name):
        if directory.name.startswith("."):
            continue
        try:
            result.append(_extension_spec(directory))
        except _DedicatedBufferPolicyManifest:
            continue
        except (OSError, json.JSONDecodeError, ValueError) as err:
            _LOGGER.error("WeatherRouter extension %s rejected: %s", directory.name, err)
    return tuple(result)


def _load_package(spec: ExtensionSpec) -> Any:
    module_name = f"_weather_router_extension_{spec.extension_id}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    loader_spec = spec_from_file_location(
        module_name,
        spec.root / "__init__.py",
        submodule_search_locations=[str(spec.root)],
    )
    if loader_spec is None or loader_spec.loader is None:
        raise ImportError("extension package loader unavailable")
    module = module_from_spec(loader_spec)
    sys.modules[module_name] = module
    try:
        loader_spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _extension_provider(spec: ExtensionSpec, module: Any) -> Any:
    provider = getattr(module, spec.provider_class)()
    if getattr(provider, "id", None) != spec.provider_id:
        raise ValueError("extension provider id does not match manifest")
    setattr(provider, "router_domains", spec.domains)
    setattr(provider, "router_default_enabled", spec.default_enabled)
    setattr(provider, "weather_router_extension_id", spec.extension_id)
    if not getattr(provider, "router_topics", None):
        setattr(provider, "router_topics", ())

    # Generic UI classification only: an extension whose entire public
    # capability mapping lives below weather.lightning.* is a dedicated
    # lightning provider and may be grouped under "Gewitter". This avoids
    # source-specific knowledge in the WeatherRouter core and keeps old
    # extension packages compatible even if they do not yet declare a
    # router_display_group attribute themselves.
    if not getattr(provider, "router_display_group", None):
        public_ids = {
            public_id
            for values in spec.provider_capabilities.values()
            for public_id in values
        }
        if public_ids and all(item.startswith("weather.lightning.") for item in public_ids):
            setattr(provider, "router_display_group", "thunderstorm")

    return provider


def _provider_is_visible(provider: Any) -> bool:
    visibility = getattr(provider, "is_visible", None)
    return not callable(visibility) or bool(visibility())


def extension_provider_catalog(*, include_hidden: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for spec in extension_specs():
        try:
            module = _load_package(spec)
            provider = _extension_provider(spec, module)
            if spec.provider_id in result:
                raise ValueError("duplicate extension provider id")
            if not include_hidden and not _provider_is_visible(provider):
                continue
            result[spec.provider_id] = provider
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("WeatherRouter extension %s provider load failed: %s", spec.extension_id, err)
    return result


def merge_extension_capability_map(payload: dict[str, Any]) -> dict[str, Any]:
    providers = payload.get("providers")
    public_capabilities = payload.get("public_capabilities")
    if not isinstance(providers, dict) or not isinstance(public_capabilities, dict):
        raise ValueError("base consumer capability map is malformed")
    for spec in extension_specs():
        try:
            module = _load_package(spec)
            provider = _extension_provider(spec, module)
            if not _provider_is_visible(provider):
                continue
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "WeatherRouter extension %s capability merge skipped: %s",
                spec.extension_id,
                err,
            )
            continue
        if spec.provider_id in providers:
            raise ValueError(f"extension provider collides with base mapping: {spec.provider_id}")
        providers[spec.provider_id] = deepcopy(spec.provider_capabilities)
        for public_id, metadata in spec.public_capabilities.items():
            existing = public_capabilities.get(public_id)
            if existing is not None and existing != metadata:
                raise ValueError(f"extension public capability metadata conflict: {public_id}")
            public_capabilities.setdefault(public_id, deepcopy(metadata))
        referenced = {item for values in spec.provider_capabilities.values() for item in values}
        missing = sorted(referenced - set(public_capabilities))
        if missing:
            raise ValueError(f"extension mapping lacks public metadata: {missing}")
    return payload


def _loaded_modules_sync() -> tuple[tuple[ExtensionSpec, Any], ...]:
    loaded: list[tuple[ExtensionSpec, Any]] = []
    for spec in extension_specs():
        try:
            module = _load_package(spec)
            provider = _extension_provider(spec, module)
            if not _provider_is_visible(provider):
                continue
            loaded.append((spec, module))
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("WeatherRouter extension %s import failed: %s", spec.extension_id, err)
    return tuple(loaded)


async def async_setup_extensions(hass: HomeAssistant, entry: ConfigEntry[Any]) -> None:
    loaded = await hass.async_add_executor_job(_loaded_modules_sync)
    state = hass.data.setdefault(_EXTENSION_STATE_KEY, {})
    for spec, module in loaded:
        try:
            hook = getattr(module, "async_setup_extension", None)
            if callable(hook):
                await hook(hass, entry)
            state[spec.extension_id] = module
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("WeatherRouter extension %s setup failed: %s", spec.extension_id, err)


async def async_notify_routing_changed(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    options: dict[str, Any],
) -> None:
    for extension_id, module in tuple(hass.data.get(_EXTENSION_STATE_KEY, {}).items()):
        try:
            hook = getattr(module, "async_routing_changed", None)
            if callable(hook):
                await hook(hass, entry, options)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("WeatherRouter extension %s routing hook failed: %s", extension_id, err)


async def async_unload_extensions(hass: HomeAssistant, entry: ConfigEntry[Any]) -> None:
    state = hass.data.get(_EXTENSION_STATE_KEY, {})
    for extension_id, module in reversed(tuple(state.items())):
        try:
            hook = getattr(module, "async_unload_extension", None)
            if callable(hook):
                await hook(hass, entry)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("WeatherRouter extension %s unload failed: %s", extension_id, err)
    hass.data.pop(_EXTENSION_STATE_KEY, None)
