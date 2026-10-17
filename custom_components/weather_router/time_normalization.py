"""Explicit, pure UTC normalization for WeatherRouter provider data.

No naive local timestamp is interpreted as UTC. Numeric epochs require a
source-declared unit. Calendar dates and durations are not observations.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("unknown_time_zone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def iso_instant(value: Any) -> str | None:
    """Parse timezone-aware ISO/RFC3339 instants only."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return utc_iso(parsed)
    except (ValueError, OverflowError, TypeError):
        return None


def epoch_instant(value: Any, *, unit: str) -> str | None:
    """Never guess seconds vs milliseconds. Provider must declare unit."""
    if unit not in ("seconds", "milliseconds"):
        raise ValueError("undeclared_epoch_unit")
    if type(value) not in (int, float) or not isfinite(value):
        return None
    try:
        instant = datetime.fromtimestamp(
            value / (1000 if unit == "milliseconds" else 1), tz=UTC)
        return utc_iso(instant)
    except (ValueError, OverflowError, OSError):
        return None


def provider_local_instant(value: Any, *, iana_zone: str) -> str | None:
    """Convert proven IANA-local datetime; reject gaps and ambiguous times."""
    if not isinstance(value, str) or not isinstance(iana_zone, str):
        return None
    try:
        naive = datetime.fromisoformat(value.strip())
        if naive.tzinfo is not None:
            return utc_iso(naive)
        zone = ZoneInfo(iana_zone)
        a = naive.replace(tzinfo=zone, fold=0)
        b = naive.replace(tzinfo=zone, fold=1)
        # Both DST folds are allowed only if they resolve to one UTC instant.
        if a.utcoffset() != b.utcoffset():
            return None
        utc = a.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) != naive:
            return None
        return utc_iso(utc)
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return None


def rss_instant(value: Any) -> str | None:
    """RFC2822 timestamps require a concrete numeric/named zone."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return utc_iso(parsed)
    except (ValueError, TypeError, OverflowError, IndexError):
        return None


def wms_time_values(raw: Any, *, max_values: int = 256) -> list[str]:
    """Expand bounded explicit ISO instants or ISO start/end/PTnH/PTnM.

    Unspecified zone, daily date-only, and unbounded/invalid intervals fail
    closed; no point-in-time freshness is inferred from a day product.
    """
    if not isinstance(raw, str) or not raw.strip():
        return []
    output: list[str] = []
    for item in raw.split(","):
        parts = item.strip().split("/")
        if len(parts) == 1:
            instant = iso_instant(parts[0])
            if instant is None:
                return []
            output.append(instant)
        elif len(parts) == 3:
            first, last = iso_instant(parts[0]), iso_instant(parts[1])
            cadence = parts[2]
            import re
            match = re.fullmatch(r"PT([1-9][0-9]*)(M|H)", cadence)
            if not first or not last or not match:
                return []
            count = int(match.group(1))
            step = timedelta(minutes=count) if match.group(2) == "M" else timedelta(hours=count)
            a = datetime.fromisoformat(first.replace("Z", "+00:00"))
            b = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if a > b:
                return []
            while a <= b:
                if len(output) >= max_values:
                    return []
                output.append(utc_iso(a))
                a += step
        else:
            return []
        if len(output) > max_values:
            return []
    return output


def calendar_day_interval(value: Any, *, iana_zone: str) -> tuple[str, str] | None:
    """UTC bounds of a local calendar day; never fabricate observation time."""
    if not isinstance(value, str):
        return None
    try:
        selected = date.fromisoformat(value)
        zone = ZoneInfo(iana_zone)
        start = datetime(selected.year, selected.month, selected.day, tzinfo=zone)
        next_day = selected + timedelta(days=1)
        end = datetime(next_day.year, next_day.month, next_day.day, tzinfo=zone)
        return utc_iso(start), utc_iso(end)
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return None


# UNUMSTOESSLICHER WEATHERROUTER-ZEITVERTRAG:
# Keine unnormalisierten Providerzeiten ausserhalb dieser Grenze; keine
# Einheit raten; fehlende Beobachtungszeit ist NIEMALS die Abrufzeit.
# Format, UTC-Basis und Zeitrolle sind PRO QUELLE UND ROHFELD deklariert.
# Neue Provider/Capabilities muessen im Vertrag registriert sein.
from typing import NamedTuple
from functools import lru_cache
import json
from pathlib import Path


class ProviderTimeResult(NamedTuple):
    utc: datetime | None
    role: str | None
    source_format: str | None
    timezone_basis: str | None
    status: str
    reason: str | None = None

    @property
    def iso(self) -> str | None:
        return utc_iso(self.utc) if self.utc is not None else None


@lru_cache(maxsize=1)
def provider_time_contracts() -> dict[str, Any]:
    """Load the authoritative, declarative provider/capability/field registry."""
    path = Path(__file__).with_name("provider_time_contracts.v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "weather_router.provider_time_contracts.v1":
        raise ValueError("invalid_provider_time_contract_schema")
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("invalid_provider_time_contract_providers")
    for provider, capabilities in providers.items():
        if not isinstance(provider, str) or not isinstance(capabilities, dict):
            raise ValueError("invalid_provider_time_contract_provider")
        for capability, contract in capabilities.items():
            if not isinstance(capability, str) or not isinstance(contract, dict):
                raise ValueError("invalid_provider_time_contract_capability")
            if contract.get("status") not in ("unverified", "static_code_evidence", "runtime_verified"):
                raise ValueError("invalid_provider_time_contract_status")
            fields = contract.get("fields")
            if not isinstance(fields, dict):
                raise ValueError("invalid_provider_time_contract_fields")
            for field, rule in fields.items():
                if not isinstance(field, str) or not isinstance(rule, dict):
                    raise ValueError("invalid_provider_time_field")
                if rule.get("format") not in (
                    "rfc3339", "unix_seconds", "unix_milliseconds",
                    "rfc2822", "iana_local", "calendar_day"
                ):
                    raise ValueError("invalid_provider_time_format")
                if rule.get("role") not in (
                    "observed_at", "data_time", "valid_at", "issued_at",
                    "published_at", "updated_at", "retrieved_at",
                    "forecast_reference_time", "valid_from", "valid_until",
                    "started_at", "ended_at", "resolved_at", "occurred_at",
                    "interval_start", "interval_end"
                ):
                    raise ValueError("invalid_provider_time_role")
                if not isinstance(rule.get("evidence"), str) or not rule["evidence"]:
                    raise ValueError("provider_time_evidence_missing")
                if rule["format"] in ("unix_seconds", "unix_milliseconds") and rule.get("timezone") != "UTC":
                    raise ValueError("invalid_provider_epoch_time_basis")
    return payload


def normalize_provider_time(
    provider_id: str, capability_id: str, field_path: str, raw_value: Any,
    *, provider_metadata: dict[str, Any] | None = None,
) -> ProviderTimeResult:
    """Single declared ingress for absolute provider times, never heuristic."""
    contract = provider_time_contracts().get("providers", {}).get(provider_id, {}).get(capability_id)
    if not isinstance(contract, dict):
        return ProviderTimeResult(None, None, None, None, "rejected", "unregistered_capability")
    rule = contract.get("fields", {}).get(field_path)
    if not isinstance(rule, dict) or contract.get("status") == "unverified":
        return ProviderTimeResult(None, None, None, None, "rejected", "unverified_source_time_contract")
    fmt, role = rule["format"], rule["role"]
    basis = rule.get("timezone")
    if raw_value is None:
        return ProviderTimeResult(None, role, fmt, basis, "unknown", "missing_source_time")
    try:
        if fmt == "rfc3339":
            iso = iso_instant(raw_value)
        elif fmt == "unix_seconds":
            iso = epoch_instant(raw_value, unit="seconds")
        elif fmt == "unix_milliseconds":
            iso = epoch_instant(raw_value, unit="milliseconds")
        elif fmt == "rfc2822":
            iso = rss_instant(raw_value)
        elif fmt == "iana_local":
            zone = basis
            if rule.get("timezone_metadata_field"):
                zone = (provider_metadata or {}).get(rule["timezone_metadata_field"])
            if not isinstance(zone, str) or not zone:
                return ProviderTimeResult(None, role, fmt, None, "rejected", "unknown_time_zone")
            iso = provider_local_instant(raw_value, iana_zone=zone)
            basis = zone
        elif fmt == "calendar_day":
            zone = basis
            if not isinstance(zone, str) or not zone:
                return ProviderTimeResult(None, role, fmt, None, "rejected", "unknown_time_zone")
            interval = calendar_day_interval(raw_value, iana_zone=zone)
            # A calendar day has no single observational instant.
            return ProviderTimeResult(None, role, fmt, zone, "interval" if interval else "rejected",
                                      "calendar_interval_not_instant" if interval else "invalid_interval")
        else:
            iso = None
        if iso is None:
            return ProviderTimeResult(None, role, fmt, basis, "rejected", "invalid_timestamp")
        parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return ProviderTimeResult(parsed, role, fmt, basis, "normalized")
    except (TypeError, ValueError, OverflowError):
        return ProviderTimeResult(None, role, fmt, basis, "rejected", "invalid_timestamp")



def validate_provider_time_registry_coverage(
    mapped_providers: dict[str, Any],
) -> None:
    """Sperre die Consumer-Grenze, sobald Provider/Capability ohne Vertrag auftaucht."""
    declared = provider_time_contracts()["providers"]
    if set(declared) != set(mapped_providers):
        raise ValueError("provider_time_contract_provider_inventory_drift")
    for provider, capabilities in mapped_providers.items():
        if not isinstance(capabilities, dict) or set(declared[provider]) != set(capabilities):
            raise ValueError("provider_time_contract_capability_inventory_drift")
