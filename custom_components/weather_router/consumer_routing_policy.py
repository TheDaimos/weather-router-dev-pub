"""Pure candidate semantics and scoring for WeatherRouter Consumer routing."""

from __future__ import annotations

from typing import Any, Mapping


def normalized_candidate_semantics(
    mapping: Mapping[str, Any],
    public_id: str,
    provider_id: str,
    capability_id: str,
    *,
    source_class: str | None,
    unit: str | None,
) -> dict[str, Any]:
    """Return normalized, provider-independent semantics for one candidate."""
    raw_all = mapping.get("candidate_semantics", {})
    raw = (
        raw_all.get(f"{provider_id}/{capability_id}", {})
        if isinstance(raw_all, Mapping)
        else {}
    )
    if not isinstance(raw, Mapping):
        raw = {}

    source_all = mapping.get("capability_source_semantics", {})
    source_providers = (
        source_all.get("providers", {})
        if isinstance(source_all, Mapping)
        else {}
    )
    source_provider = (
        source_providers.get(provider_id, {})
        if isinstance(source_providers, Mapping)
        else {}
    )
    source_semantics = (
        source_provider.get(capability_id, {})
        if isinstance(source_provider, Mapping)
        else {}
    )
    if not isinstance(source_semantics, Mapping):
        source_semantics = {}

    observation_all = mapping.get("capability_observation_semantics", {})
    observation_providers = (
        observation_all.get("providers", {})
        if isinstance(observation_all, Mapping)
        else {}
    )
    observation_provider = (
        observation_providers.get(provider_id, {})
        if isinstance(observation_providers, Mapping)
        else {}
    )
    observation_semantics = (
        observation_provider.get(capability_id, {})
        if isinstance(observation_provider, Mapping)
        else {}
    )
    if not isinstance(observation_semantics, Mapping):
        observation_semantics = {}

    coverage_all = mapping.get("capability_coverage_semantics", {})
    coverage_providers = (
        coverage_all.get("providers", {})
        if isinstance(coverage_all, Mapping)
        else {}
    )
    coverage_provider = (
        coverage_providers.get(provider_id, {})
        if isinstance(coverage_providers, Mapping)
        else {}
    )
    coverage_semantics = (
        coverage_provider.get(capability_id, {})
        if isinstance(coverage_provider, Mapping)
        else {}
    )
    if not isinstance(coverage_semantics, Mapping):
        coverage_semantics = {}

    time_all = mapping.get("capability_time_semantics", {})
    time_providers = (
        time_all.get("providers", {})
        if isinstance(time_all, Mapping)
        else {}
    )
    time_provider = (
        time_providers.get(provider_id, {})
        if isinstance(time_providers, Mapping)
        else {}
    )
    time_semantics = (
        time_provider.get(capability_id, {})
        if isinstance(time_provider, Mapping)
        else {}
    )
    if not isinstance(time_semantics, Mapping):
        time_semantics = {}

    physical_all = mapping.get("capability_physical_semantics", {})
    physical_providers = (
        physical_all.get("providers", {})
        if isinstance(physical_all, Mapping)
        else {}
    )
    physical_provider = (
        physical_providers.get(provider_id, {})
        if isinstance(physical_providers, Mapping)
        else {}
    )
    physical = (
        physical_provider.get(capability_id, {})
        if isinstance(physical_provider, Mapping)
        else {}
    )
    if not isinstance(physical, Mapping):
        physical = {}

    public_all = mapping.get("public_capabilities", {})
    public_meta = (
        public_all.get(public_id, {})
        if isinstance(public_all, Mapping)
        else {}
    )
    if not isinstance(public_meta, Mapping):
        public_meta = {}
    family = str(public_meta.get("family") or "")

    data_origin = raw.get("data_origin")
    if not isinstance(data_origin, str) or not data_origin:
        source_origin = source_semantics.get("data_origin")
        data_origin = (
            source_origin
            if isinstance(source_origin, str) and source_origin
            else family if family in {"radar", "satellite", "model", "nowcast"}
            else "unspecified"
        )

    observation_kind = raw.get("observation_kind")
    if not isinstance(observation_kind, str) or not observation_kind:
        normalized_kind = observation_semantics.get("observation_kind")
        if isinstance(normalized_kind, str) and normalized_kind:
            observation_kind = normalized_kind
        elif family == "nowcast":
            observation_kind = "nowcast"
        elif family == "model":
            observation_kind = "model"
        elif source_class and "observation_forecast" in source_class:
            observation_kind = "observation_forecast"
        elif source_class and "observation" in source_class:
            observation_kind = "observation"
        elif source_class and ("forecast" in source_class or "model" in source_class):
            observation_kind = "forecast"
        else:
            observation_kind = "unspecified"

    quantity = raw.get("quantity")
    if not isinstance(quantity, str) or not quantity:
        physical_quantity = physical.get("quantity")
        quantity = (
            physical_quantity
            if isinstance(physical_quantity, str) and physical_quantity
            else "not_applicable"
        )

    unit_source = physical.get("unit_source")
    if unit_source == "not_applicable":
        raw_unit = None
    else:
        raw_unit = raw.get("unit", unit)

    result = {
        "data_origin": data_origin,
        "measurement_method": str(
            raw.get("measurement_method")
            or source_semantics.get("measurement_method")
            or "unspecified"
        ),
        "observation_kind": observation_kind,
        "quantity": quantity,
        "unit": raw_unit if raw_unit is None or isinstance(raw_unit, str) else str(raw_unit),
        "time_semantics": dict(time_semantics) if time_semantics else None,
        "coverage_semantics": dict(coverage_semantics) if coverage_semantics else None,
    }
    routing_note = raw.get("routing_note")
    if isinstance(routing_note, str) and routing_note:
        result["routing_note"] = routing_note
    return result


def candidate_score(
    mapping: Mapping[str, Any],
    public_id: str,
    semantics: Mapping[str, Any],
) -> tuple[int, int, int]:
    """Return a provider-neutral score tuple from normalized semantics only."""
    public_all = mapping.get("public_capabilities", {})
    public_meta = (
        public_all.get(public_id, {})
        if isinstance(public_all, Mapping)
        else {}
    )
    if not isinstance(public_meta, Mapping):
        public_meta = {}
    preferences = public_meta.get("routing_preferences", {})
    if not isinstance(preferences, Mapping):
        preferences = {}

    def rank(preference_key: str, semantic_key: str) -> int:
        values = preferences.get(preference_key, [])
        if not isinstance(values, list) or not values:
            return 0
        value = semantics.get(semantic_key)
        try:
            return values.index(value)
        except ValueError:
            return len(values) + 1

    return (
        rank("observation_kinds", "observation_kind"),
        rank("quantities", "quantity"),
        rank("data_origins", "data_origin"),
    )
