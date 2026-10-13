"""Persistent, restrictive Consumer API profiles for WeatherRouter.

Profiles are an optional policy layer above normal router eligibility. They may only
narrow what a consumer can see. They never enable a globally disabled provider/domain
and never express provider preference or priority.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
PUBLIC_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")

PROFILE_LIST_FIELDS = (
    "allowed_domains",
    "allowed_families",
    "allowed_phenomena",
    "allowed_capabilities",
    "allowed_hazard_types",
    "allowed_severities",
    "excluded_providers",
    "excluded_data_origins",
    "excluded_measurement_methods",
    "excluded_observation_kinds",
)
PROFILE_FIELDS = {
    "name",
    "description",
    "enabled",
    "revision",
    *PROFILE_LIST_FIELDS,
}
PROFILE_INPUT_FIELDS = PROFILE_FIELDS - {"revision"}
KNOWN_SEVERITIES = {"unknown", "minor", "moderate", "severe", "extreme"}


def _string_list(value: Any, field: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if not allow_empty and not value:
        raise ValueError(f"{field} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must contain non-empty strings")
    normalized = [item.strip() for item in value]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def validate_consumer_profiles(value: Any) -> None:
    """Validate persisted profile structure without depending on the live registry."""
    if not isinstance(value, dict):
        raise ValueError("consumer_profiles must be an object")
    for profile_id, profile in value.items():
        if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
            raise ValueError(f"invalid consumer profile id: {profile_id!r}")
        if not isinstance(profile, dict):
            raise ValueError(f"consumer profile {profile_id} must be an object")
        unknown = set(profile) - PROFILE_FIELDS
        if unknown:
            raise ValueError(
                f"consumer profile {profile_id} has unsupported fields: {sorted(unknown)}"
            )
        name = profile.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError(f"consumer profile {profile_id} needs a valid name")
        description = profile.get("description")
        if description is not None and (
            not isinstance(description, str) or len(description.strip()) > 500
        ):
            raise ValueError(f"consumer profile {profile_id} has invalid description")
        if not isinstance(profile.get("enabled"), bool):
            raise ValueError(f"consumer profile {profile_id} enabled must be boolean")
        revision = profile.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError(f"consumer profile {profile_id} has invalid revision")
        for field in PROFILE_LIST_FIELDS:
            if field not in profile:
                continue
            _string_list(
                profile[field],
                field,
                allow_empty=field.startswith("excluded_"),
            )
        if any(
            not PUBLIC_CAPABILITY_RE.fullmatch(item)
            for item in profile.get("allowed_capabilities", [])
        ):
            raise ValueError(
                f"consumer profile {profile_id} contains invalid public capability ids"
            )
        severities = set(profile.get("allowed_severities", []))
        if not severities.issubset(KNOWN_SEVERITIES):
            raise ValueError(
                f"consumer profile {profile_id} contains unknown severities"
            )


def normalize_consumer_profile(
    profile_id: str,
    raw: Mapping[str, Any],
    *,
    current_revision: int = 0,
    known_domains: set[str] | None = None,
    known_providers: set[str] | None = None,
) -> dict[str, Any]:
    """Normalize one complete admin profile replacement."""
    if not PROFILE_ID_RE.fullmatch(profile_id):
        raise ValueError("profile_id must match ^[a-z][a-z0-9_-]{0,63}$")
    if not isinstance(raw, Mapping):
        raise ValueError("profile must be an object")
    unknown = set(raw) - PROFILE_INPUT_FIELDS
    if unknown:
        raise ValueError(f"unsupported profile fields: {sorted(unknown)}")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValueError("profile name must be 1..80 characters")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("profile enabled must be boolean")

    profile: dict[str, Any] = {
        "name": name.strip(),
        "enabled": enabled,
        "revision": max(0, int(current_revision)) + 1,
    }
    if "description" in raw:
        description = raw["description"]
        if not isinstance(description, str) or len(description.strip()) > 500:
            raise ValueError("profile description must be at most 500 characters")
        profile["description"] = description.strip()

    for field in PROFILE_LIST_FIELDS:
        if field not in raw:
            continue
        profile[field] = _string_list(
            raw[field],
            field,
            allow_empty=field.startswith("excluded_"),
        )

    if known_domains is not None:
        unknown_domains = set(profile.get("allowed_domains", [])) - known_domains
        if unknown_domains:
            raise ValueError(f"unknown allowed_domains: {sorted(unknown_domains)}")
    if known_providers is not None:
        unknown_providers = set(profile.get("excluded_providers", [])) - known_providers
        if unknown_providers:
            raise ValueError(f"unknown excluded_providers: {sorted(unknown_providers)}")
    if any(
        not PUBLIC_CAPABILITY_RE.fullmatch(item)
        for item in profile.get("allowed_capabilities", [])
    ):
        raise ValueError("allowed_capabilities contains invalid public capability ids")
    severities = set(profile.get("allowed_severities", []))
    if not severities.issubset(KNOWN_SEVERITIES):
        raise ValueError(
            f"unknown allowed_severities: {sorted(severities - KNOWN_SEVERITIES)}"
        )

    validate_consumer_profiles({profile_id: profile})
    return profile


def profile_reference(profile_id: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return profile identity safe for public Consumer API responses."""
    return {
        "id": profile_id,
        "name": str(profile["name"]),
        "revision": int(profile["revision"]),
        "applied": True,
    }


def profile_allows_provider(profile: Mapping[str, Any] | None, provider_id: str) -> bool:
    """Return whether a globally eligible provider survives profile exclusions."""
    if profile is None:
        return True
    return provider_id not in set(profile.get("excluded_providers", []))


def profile_allows_candidate(
    profile: Mapping[str, Any] | None,
    semantics: Mapping[str, Any],
) -> tuple[bool, str | None]:
    """Apply deny-only policy to normalized candidate properties."""
    if profile is None:
        return True, None

    checks = (
        ("excluded_data_origins", "data_origin", "profile_data_origin_filtered"),
        (
            "excluded_measurement_methods",
            "measurement_method",
            "profile_measurement_method_filtered",
        ),
        (
            "excluded_observation_kinds",
            "observation_kind",
            "profile_observation_kind_filtered",
        ),
    )
    for profile_field, semantic_field, reason in checks:
        denied = set(profile.get(profile_field, []))
        value = semantics.get(semantic_field)
        if denied and isinstance(value, str) and value in denied:
            return False, reason
    return True, None


def profile_allows_capability(
    profile: Mapping[str, Any] | None,
    mapping: Mapping[str, Any],
    public_id: str,
) -> tuple[bool, str | None]:
    """Apply allow-list profile policy to one public capability."""
    if profile is None:
        return True, None
    if not profile.get("enabled", False):
        return False, "profile_disabled"

    metadata = mapping.get("public_capabilities", {}).get(public_id, {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    domain = public_id.split(".", 1)[0]
    family = str(metadata.get("family") or "")
    phenomena = set(metadata.get("phenomena", []) or [])
    hazard_types = set(metadata.get("hazard_types", []) or [])

    allowed_domains = set(profile.get("allowed_domains", []))
    if allowed_domains and domain not in allowed_domains:
        return False, "profile_domain_filtered"

    allowed_capabilities = set(profile.get("allowed_capabilities", []))
    if allowed_capabilities and public_id not in allowed_capabilities:
        return False, "profile_capability_filtered"

    allowed_families = set(profile.get("allowed_families", []))
    if allowed_families and family not in allowed_families:
        return False, "profile_family_filtered"

    allowed_phenomena = set(profile.get("allowed_phenomena", []))
    if allowed_phenomena and phenomena and not phenomena.intersection(allowed_phenomena):
        return False, "profile_phenomenon_filtered"

    allowed_hazards = set(profile.get("allowed_hazard_types", []))
    if allowed_hazards and hazard_types and not hazard_types.intersection(allowed_hazards):
        return False, "profile_hazard_filtered"

    return True, None


def apply_profile_event_filter(
    profile: Mapping[str, Any] | None,
    request_filter: dict[str, set[str]],
) -> tuple[dict[str, set[str]], bool]:
    """Intersect request hazard/severity filters with profile allow lists."""
    if profile is None:
        return request_filter, False

    merged = {key: set(values) for key, values in request_filter.items()}
    for field, profile_field in (
        ("hazard_types", "allowed_hazard_types"),
        ("severities", "allowed_severities"),
    ):
        allowed = set(profile.get(profile_field, []))
        if not allowed:
            continue
        if field in merged:
            intersection = merged[field].intersection(allowed)
            if not intersection:
                return merged, True
            merged[field] = intersection
        else:
            merged[field] = allowed
    return merged, False
