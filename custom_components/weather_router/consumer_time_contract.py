"""Pure validation for Consumer API time-semantics contracts."""

from __future__ import annotations

from typing import Any


_ALLOWED_FIELD_STATES = {
    "optional_runtime",
    "not_applicable",
    "derived_from_data_time_and_runtime_interval",
}
_ALLOWED_FRESHNESS = {"consumer_max_age_optional", "not_applicable"}
_ALLOWED_TIME_MODES = {"latest"}
_RUNTIME_ACCUMULATION_STATES = {"not_applicable", "provider_runtime_interval"}


def validate_time_semantics_contract(
    payload: dict[str, Any],
    providers: dict[str, Any],
) -> None:
    """Validate the shipped time-semantics block used by Consumer API V1."""
    time_contract = payload.get("capability_time_semantics")
    if not isinstance(time_contract, dict):
        raise ValueError("consumer capability map needs capability_time_semantics")
    if time_contract.get("schema") != "weather_router.consumer.capability_time_semantics.v1":
        raise ValueError("consumer capability time semantics have unexpected schema")

    time_providers = time_contract.get("providers")
    if not isinstance(time_providers, dict):
        raise ValueError("consumer capability time semantics providers must be an object")
    if not set(time_providers).issubset(set(providers)):
        raise ValueError("consumer capability time semantics reference unknown providers")

    allowed_field_states = set(time_contract.get("field_states", []))
    allowed_freshness = set(time_contract.get("freshness_policies", []))
    allowed_time_modes = set(time_contract.get("request_time_modes", []))

    if allowed_field_states != _ALLOWED_FIELD_STATES:
        raise ValueError("consumer capability time semantics have invalid field states")
    if allowed_freshness != _ALLOWED_FRESHNESS:
        raise ValueError("consumer capability time semantics have invalid freshness policies")
    if allowed_time_modes != _ALLOWED_TIME_MODES:
        raise ValueError("consumer capability time semantics have invalid request modes")

    for provider_id, time_map in time_providers.items():
        provider_map = providers.get(provider_id)
        if not isinstance(provider_map, dict) or not isinstance(time_map, dict):
            raise ValueError("consumer capability time semantics provider map is invalid")
        if set(time_map) != set(provider_map):
            raise ValueError(
                f"consumer capability time semantics coverage mismatch for {provider_id}"
            )

        for internal_id, metadata in time_map.items():
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"consumer capability time semantics invalid for {provider_id}/{internal_id}"
                )
            if metadata.get("request_time_mode") != "latest":
                raise ValueError(
                    f"consumer capability request time mode invalid for {provider_id}/{internal_id}"
                )

            for field in (
                "data_time",
                "valid_time",
                "forecast_reference_time",
                "interval_start",
                "interval_end",
                "frame_cadence",
            ):
                if metadata.get(field) not in allowed_field_states:
                    raise ValueError(
                        f"consumer capability time field {field} invalid for {provider_id}/{internal_id}"
                    )

            accumulation = metadata.get("accumulation_period")
            if accumulation not in _RUNTIME_ACCUMULATION_STATES and (
                not isinstance(accumulation, str) or not accumulation.startswith("P")
            ):
                raise ValueError(
                    f"consumer capability accumulation period invalid for {provider_id}/{internal_id}"
                )

            if metadata.get("freshness_policy") not in allowed_freshness:
                raise ValueError(
                    f"consumer capability freshness policy invalid for {provider_id}/{internal_id}"
                )
