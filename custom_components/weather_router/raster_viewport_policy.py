"""Experimental P7-010 viewport suitability for raster candidates.

Not part of active Consumer V1 routing. Do not use this as a provider preference,
a claim of per-pixel composite rendering, or a substitute for coverage validation.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any


def experimental_viewport_rank(
    coverage_diagnostic: Mapping[str, Any],
    semantic_score: tuple[int, int, int],
) -> tuple[int, tuple[int, int, int], float] | None:
    """Provide a *prototype* ordering only after verified machine coverage.

    A tiny out-of-focus intersection is deliberately less suitable than a broad
    valid source. Within the same relevance tier, preserve the provider-neutral
    existing semantic score. This is not wired into live routing.
    """
    if coverage_diagnostic.get("routing_match") is not True:
        return None
    overlap = coverage_diagnostic.get("overlap_percent")
    center = coverage_diagnostic.get("center_inside")
    if isinstance(overlap, bool) or not isinstance(overlap, (float, int)):
        return None
    overlap = float(overlap)
    if not isfinite(overlap) or not 0.0 <= overlap <= 100.0:
        return None
    if center not in (True, False) or not isinstance(center, bool):
        return None
    if len(semantic_score) != 3 or any(
        isinstance(x, bool) or not isinstance(x, int) for x in semantic_score
    ):
        raise TypeError("normalized semantic score expected")

    # EXPERIMENTAL tiers: any possible future thresholds need explicit
    # product decision, screen-space validation, and HA acceptance.
    if center and overlap >= 25.0:
        tier = 0
    elif overlap >= 70.0:
        tier = 0
    elif center and overlap >= 10.0:
        tier = 1
    elif overlap >= 10.0:
        tier = 2
    else:
        tier = 3
    return tier, semantic_score, -overlap
