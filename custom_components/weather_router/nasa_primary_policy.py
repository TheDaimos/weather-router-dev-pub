"""Pure NASA complement decision when WR OPERA V2 has no admitted frame.

Do not infer geographic absence for DWD timeouts or for indeterminate active
OPERA states. A stale reservation envelope is not proof of a displayed frame.
"""
from __future__ import annotations

OPERA = "opera/opera_rate_raster"
ABSENT_REASONS = frozenset((
    "no_admitted_current_frame", "frame_expired",
    "rate_disabled_or_route_inactive", "consumer_not_authorized",
    "profile_semantics_filtered", "provider_or_profile_disabled",
))


def reconcile_opera_reservation(decision, coverage_memory, unknown, sources,
                                *, nasa_enabled, opera_allowed):
    """Return a secret-free reason; modify only OPERA reservation state."""
    if not nasa_enabled:
        return None
    status = decision.get("result")
    if status in ABSENT_REASONS:
        coverage_memory.pop(OPERA, None)
        unknown[:] = [sid for sid in unknown if sid != OPERA]
        return ("opera_no_admitted_frame" if status == "no_admitted_current_frame"
                else "opera_frame_expired" if status == "frame_expired"
                else "opera_not_eligible")
    if status == "admitted_for_planning":
        return None
    if opera_allowed and not any(row.get("source_id") == OPERA for row in sources):
        previous = coverage_memory.get(OPERA)
        if previous is not None:
            sources.append({"source_id": OPERA, "eligible": False,
                            "machine_coverage": previous})
        elif OPERA not in unknown:
            unknown.append(OPERA)
    return None
