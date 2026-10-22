"""Provider-neutral machine-readable spatial coverage helpers.

This module intentionally has no Home Assistant imports. Consumer routing and provider
adapters share the same bbox/antimeridian rules, and the geometry can be unit-tested
without loading Home Assistant.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any
from xml.etree import ElementTree as ET


class CoverageTemporarilyUnavailable(RuntimeError):
    """Temporarily missing coverage metadata; never geographic non-coverage."""



def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: Any, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(result) or not minimum <= result <= maximum:
        return None
    return result


def normalize_bbox(value: Any) -> dict[str, float] | None:
    """Return one validated lon/lat bbox; west > east intentionally wraps."""
    if not isinstance(value, dict):
        return None
    west = _number(value.get("west"), -180.0, 180.0)
    south = _number(value.get("south"), -90.0, 90.0)
    east = _number(value.get("east"), -180.0, 180.0)
    north = _number(value.get("north"), -90.0, 90.0)
    if west is None or south is None or east is None or north is None or south > north:
        return None
    return {"west": west, "south": south, "east": east, "north": north}


def _longitude_segments(
    west: float,
    east: float,
) -> tuple[tuple[float, float], ...]:
    if west <= east:
        return ((west, east),)
    return ((west, 180.0), (-180.0, east))


def bbox_intersects(
    first: dict[str, float],
    second: dict[str, float],
) -> bool:
    """Return bbox overlap, including antimeridian-wrapping bboxes."""
    if first["north"] < second["south"] or second["north"] < first["south"]:
        return False
    return any(
        first_west <= second_east and second_west <= first_east
        for first_west, first_east in _longitude_segments(first["west"], first["east"])
        for second_west, second_east in _longitude_segments(second["west"], second["east"])
    )


def point_in_bbox(
    latitude: float,
    longitude: float,
    bbox: dict[str, float],
) -> bool:
    """Return whether one point lies in a geographic bbox."""
    if not bbox["south"] <= latitude <= bbox["north"]:
        return False
    return any(
        west <= longitude <= east
        for west, east in _longitude_segments(bbox["west"], bbox["east"])
    )


def normalize_coverage(value: Any) -> dict[str, Any] | None:
    """Normalize provider machine coverage without reading display text."""
    if not isinstance(value, dict):
        return None
    scope = value.get("scope")
    if scope == "global":
        result = deepcopy(value)
        result["scope"] = "global"
        result.pop("bbox", None)
        return result
    if scope != "bbox":
        return None
    bbox = normalize_bbox(value.get("bbox"))
    if bbox is None:
        return None
    result = deepcopy(value)
    result["scope"] = "bbox"
    result["bbox"] = bbox
    return result


def coverage_matches_context(
    coverage: dict[str, Any],
    context: dict[str, Any],
) -> bool:
    """Evaluate machine coverage against global/point/bbox request context."""
    normalized = normalize_coverage(coverage)
    if normalized is None:
        raise ValueError("invalid machine-readable coverage")

    if normalized["scope"] == "global":
        return True

    bbox = normalized["bbox"]
    kind = context.get("type")
    if kind == "global":
        return False
    if kind == "point":
        latitude = _number(context.get("latitude"), -90.0, 90.0)
        longitude = _number(context.get("longitude"), -180.0, 180.0)
        if latitude is None or longitude is None:
            raise ValueError("invalid point context")
        return point_in_bbox(latitude, longitude, bbox)
    if kind == "bbox":
        request_bbox = normalize_bbox(context)
        if request_bbox is None:
            raise ValueError("invalid bbox context")
        return bbox_intersects(bbox, request_bbox)
    raise ValueError("unsupported spatial context")


def _find_named_layer(root: ET.Element, layer_name: str) -> ET.Element | None:
    """Find one named WMS layer, tolerating an unambiguous workspace prefix."""
    qualified_matches: list[ET.Element] = []
    for element in root.iter():
        if _local_name(element.tag) != "Layer":
            continue
        for child in element:
            if _local_name(child.tag) != "Name":
                continue
            candidate = (child.text or "").strip()
            if candidate == layer_name:
                return element
            if candidate.rsplit(":", 1)[-1] == layer_name:
                qualified_matches.append(element)
            break
    return qualified_matches[0] if len(qualified_matches) == 1 else None


def _ex_geographic_bbox(layer: ET.Element) -> dict[str, float] | None:
    for child in layer:
        if _local_name(child.tag) != "EX_GeographicBoundingBox":
            continue
        values: dict[str, Any] = {}
        names = {
            "westBoundLongitude": "west",
            "eastBoundLongitude": "east",
            "southBoundLatitude": "south",
            "northBoundLatitude": "north",
        }
        for item in child:
            key = names.get(_local_name(item.tag))
            if key is not None:
                values[key] = (item.text or "").strip()
        bbox = normalize_bbox(values)
        if bbox is not None:
            return bbox
    return None


def _crs84_bbox(layer: ET.Element) -> dict[str, float] | None:
    for child in layer:
        if _local_name(child.tag) != "BoundingBox":
            continue
        crs = str(child.attrib.get("CRS") or child.attrib.get("SRS") or "").upper()
        if crs != "CRS:84":
            continue
        bbox = normalize_bbox(
            {
                "west": child.attrib.get("minx"),
                "south": child.attrib.get("miny"),
                "east": child.attrib.get("maxx"),
                "north": child.attrib.get("maxy"),
            }
        )
        if bbox is not None:
            return bbox
    return None


def _epsg4326_bbox(
    root: ET.Element,
    layer: ET.Element,
) -> dict[str, float] | None:
    """Parse EPSG:4326 BoundingBox with explicit WMS-version axis order."""
    version = str(root.attrib.get("version") or "")
    for child in layer:
        if _local_name(child.tag) != "BoundingBox":
            continue
        crs = str(child.attrib.get("CRS") or child.attrib.get("SRS") or "").upper()
        if crs != "EPSG:4326":
            continue
        if version.startswith("1.3"):
            values = {
                "west": child.attrib.get("miny"),
                "south": child.attrib.get("minx"),
                "east": child.attrib.get("maxy"),
                "north": child.attrib.get("maxx"),
            }
        elif version.startswith("1.1"):
            values = {
                "west": child.attrib.get("minx"),
                "south": child.attrib.get("miny"),
                "east": child.attrib.get("maxx"),
                "north": child.attrib.get("maxy"),
            }
        else:
            continue
        bbox = normalize_bbox(values)
        if bbox is not None:
            return bbox
    return None


def _legacy_latlon_bbox(layer: ET.Element) -> dict[str, float] | None:
    for child in layer:
        if _local_name(child.tag) != "LatLonBoundingBox":
            continue
        bbox = normalize_bbox(
            {
                "west": child.attrib.get("minx"),
                "south": child.attrib.get("miny"),
                "east": child.attrib.get("maxx"),
                "north": child.attrib.get("maxy"),
            }
        )
        if bbox is not None:
            return bbox
    return None



def bbox_longitude_width(bbox: dict[str, float]) -> float:
    """Return bbox width in longitude degrees, respecting antimeridian wrapping."""
    west = bbox["west"]
    east = bbox["east"]
    return east - west if west <= east else (180.0 - west) + (east + 180.0)


def bbox_center(bbox: dict[str, float]) -> dict[str, float]:
    """Return geographic bbox center with correct antimeridian handling."""
    longitude = bbox["west"] + (bbox_longitude_width(bbox) / 2.0)
    if longitude > 180.0:
        longitude -= 360.0
    return {
        "latitude": (bbox["south"] + bbox["north"]) / 2.0,
        "longitude": longitude,
    }


def bbox_contains(outer: dict[str, float], inner: dict[str, float]) -> bool:
    """Return whether outer fully contains inner, including wrapped longitudes."""
    if outer["south"] > inner["south"] or outer["north"] < inner["north"]:
        return False
    outer_segments = _longitude_segments(outer["west"], outer["east"])
    inner_segments = _longitude_segments(inner["west"], inner["east"])
    return all(
        any(outer_west <= inner_west and inner_east <= outer_east
            for outer_west, outer_east in outer_segments)
        for inner_west, inner_east in inner_segments
    )


def _longitude_intersection_width(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    width = 0.0
    for first_west, first_east in _longitude_segments(first["west"], first["east"]):
        for second_west, second_east in _longitude_segments(second["west"], second["east"]):
            width += max(0.0, min(first_east, second_east) - max(first_west, second_west))
    return min(360.0, width)


def bbox_overlap_percent(
    coverage_bbox: dict[str, float],
    request_bbox: dict[str, float],
) -> float:
    """Return approximate share of the request bbox overlapped by coverage."""
    request_width = bbox_longitude_width(request_bbox)
    request_height = max(0.0, request_bbox["north"] - request_bbox["south"])
    request_area = request_width * request_height
    if request_area <= 0.0:
        center = bbox_center(request_bbox)
        return 100.0 if point_in_bbox(center["latitude"], center["longitude"], coverage_bbox) else 0.0
    intersection_width = _longitude_intersection_width(coverage_bbox, request_bbox)
    intersection_height = max(
        0.0,
        min(coverage_bbox["north"], request_bbox["north"])
        - max(coverage_bbox["south"], request_bbox["south"]),
    )
    return round(min(100.0, max(0.0, (intersection_width * intersection_height / request_area) * 100.0)), 3)


def context_diagnostics(context: dict[str, Any]) -> dict[str, Any]:
    """Return derived spatial diagnostics without changing routing semantics."""
    kind = context.get("type")
    if kind == "global":
        return {
            "type": "global",
            "global": True,
            "routing_uses": "global",
        }
    if kind == "point":
        return {
            "type": "point",
            "latitude": context.get("latitude"),
            "longitude": context.get("longitude"),
            "routing_uses": "consumer_point",
        }
    if kind != "bbox":
        return {"type": str(kind or "unknown"), "routing_uses": "unknown"}

    bbox = normalize_bbox(context)
    if bbox is None:
        return {"type": "bbox", "valid": False, "routing_uses": "consumer_bbox"}
    center = bbox_center(bbox)
    longitude_width = bbox_longitude_width(bbox)
    latitude_height = bbox["north"] - bbox["south"]
    from math import cos, radians
    width_km = abs(longitude_width * 111.32 * cos(radians(center["latitude"])))
    height_km = abs(latitude_height * 110.574)
    return {
        "type": "bbox",
        **bbox,
        "center": center,
        "longitude_width_deg": round(longitude_width, 6),
        "latitude_height_deg": round(latitude_height, 6),
        "crosses_antimeridian": bbox["west"] > bbox["east"],
        "approximate_extent_km": {
            "width": round(width_km, 1),
            "height": round(height_km, 1),
        },
        "routing_uses": "consumer_bbox",
    }


def coverage_diagnostics(
    coverage: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Explain a coverage decision while preserving coverage_matches_context semantics."""
    normalized = normalize_coverage(coverage)
    if normalized is None:
        return {
            "machine_coverage": False,
            "valid": False,
            "routing_match": None,
            "final_status": "invalid_coverage",
        }

    result: dict[str, Any] = {
        "machine_coverage": True,
        "valid": True,
        "scope": normalized["scope"],
        "source": normalized.get("source"),
        "provider_metadata_source": normalized.get("provider_metadata_source"),
        "coverage_metadata_scope": normalized.get("coverage_metadata_scope"),
        "aggregate_coverage_missing": normalized.get("aggregate_coverage_missing"),
        "endpoint_host": normalized.get("endpoint_host"),
        "bbox_source": normalized.get("bbox_source"),
        "layer": normalized.get("layer"),
        "crs": normalized.get("crs"),
        "wms_get_capabilities": normalized.get("source") == "wms_get_capabilities",
        "ex_geographic_bbox": normalized.get("bbox_source") == "EX_GeographicBoundingBox",
        "crs84_fallback": normalized.get("bbox_source") == "BoundingBox/CRS:84",
        "latlon_bbox_fallback": normalized.get("bbox_source") == "LatLonBoundingBox",
        "routing_match": coverage_matches_context(normalized, context),
        "final_status": "eligible" if coverage_matches_context(normalized, context) else "outside_coverage",
    }
    if isinstance(normalized.get("cache"), dict):
        result["cache"] = deepcopy(normalized["cache"])

    if normalized["scope"] == "global":
        result.update(
            {
                "bbox": None,
                "center_inside": True,
                "bbox_intersects": True,
                "overlap_percent": 100.0,
                "consumer_fully_inside": True,
                "provider_fully_inside_consumer": False,
                "antimeridian_handling": "not_required",
            }
        )
        return result

    provider_bbox = normalized["bbox"]
    result["bbox"] = provider_bbox
    result["provider_crosses_antimeridian"] = provider_bbox["west"] > provider_bbox["east"]
    kind = context.get("type")
    if kind == "point":
        latitude = _number(context.get("latitude"), -90.0, 90.0)
        longitude = _number(context.get("longitude"), -180.0, 180.0)
        center_inside = (
            latitude is not None
            and longitude is not None
            and point_in_bbox(latitude, longitude, provider_bbox)
        )
        result.update(
            {
                "center_inside": center_inside,
                "bbox_intersects": None,
                "overlap_percent": 100.0 if center_inside else 0.0,
                "consumer_fully_inside": center_inside,
                "provider_fully_inside_consumer": False,
                "antimeridian_handling": "provider_segments" if result["provider_crosses_antimeridian"] else "normal",
            }
        )
        return result

    if kind == "bbox":
        request_bbox = normalize_bbox(context)
        if request_bbox is None:
            result["valid"] = False
            return result
        center = bbox_center(request_bbox)
        result.update(
            {
                "consumer_bbox": request_bbox,
                "consumer_center": center,
                "consumer_crosses_antimeridian": request_bbox["west"] > request_bbox["east"],
                "center_inside": point_in_bbox(center["latitude"], center["longitude"], provider_bbox),
                "bbox_intersects": bbox_intersects(provider_bbox, request_bbox),
                "overlap_percent": bbox_overlap_percent(provider_bbox, request_bbox),
                "consumer_fully_inside": bbox_contains(provider_bbox, request_bbox),
                "provider_fully_inside_consumer": bbox_contains(request_bbox, provider_bbox),
                "antimeridian_handling": "split_longitude_segments"
                if provider_bbox["west"] > provider_bbox["east"] or request_bbox["west"] > request_bbox["east"]
                else "normal",
            }
        )
        return result

    result.update(
        {
            "center_inside": False,
            "bbox_intersects": False,
            "overlap_percent": 0.0,
            "consumer_fully_inside": False,
            "provider_fully_inside_consumer": False,
            "antimeridian_handling": "not_applicable",
        }
    )
    return result

def _wms_bbox_from_layer_element(
    root: ET.Element,
    layer: ET.Element,
) -> tuple[dict[str, float], str, str] | None:
    """Return one geographic bbox explicitly declared on one WMS Layer element."""
    bbox = _ex_geographic_bbox(layer)
    if bbox is not None:
        return bbox, "EX_GeographicBoundingBox", "EPSG:4326"

    bbox = _crs84_bbox(layer)
    if bbox is not None:
        return bbox, "BoundingBox/CRS:84", "CRS:84"

    bbox = _epsg4326_bbox(root, layer)
    if bbox is not None:
        return bbox, "BoundingBox/EPSG:4326", "EPSG:4326"

    bbox = _legacy_latlon_bbox(layer)
    if bbox is not None:
        return bbox, "LatLonBoundingBox", "EPSG:4326"

    return None


def _wms_layer_label(layer: ET.Element) -> str | None:
    """Return a stable diagnostic label for one WMS layer/group."""
    title: str | None = None
    for child in layer:
        name = _local_name(child.tag)
        value = (child.text or "").strip()
        if name == "Name" and value:
            return value
        if name == "Title" and value:
            title = value
    return title


def wms_layer_geographic_coverage(
    root: ET.Element,
    layer_name: str,
) -> dict[str, Any] | None:
    """Return machine-readable geographic coverage for one named WMS layer.

    Direct layer metadata is preferred. WMS 1.3 permits geographic/bounding-box
    metadata to be inherited from parent Layer elements, so the nearest real
    parent layer/group is used when the concrete layer omits its own bbox.

    The top-level service root Layer is intentionally excluded from inheritance:
    GeoServer commonly advertises a broad/world root extent that describes the
    service container rather than one concrete product.
    """
    layer = _find_named_layer(root, layer_name)
    if layer is None:
        return None

    parsed = _wms_bbox_from_layer_element(root, layer)
    inherited_from: str | None = None

    if parsed is None:
        parent_map = {
            child: parent
            for parent in root.iter()
            for child in parent
        }
        ancestors: list[ET.Element] = []
        parent = parent_map.get(layer)
        while parent is not None:
            if _local_name(parent.tag) == "Layer":
                ancestors.append(parent)
            parent = parent_map.get(parent)

        # The outermost Layer is the service root/container. Never use that as
        # product coverage; only inherit from actual intermediate layer groups.
        candidates = ancestors[:-1] if ancestors else []
        for ancestor in candidates:
            parsed = _wms_bbox_from_layer_element(root, ancestor)
            if parsed is not None:
                inherited_from = _wms_layer_label(ancestor)
                break

    if parsed is None:
        return None

    bbox, bbox_source, crs = parsed
    return {
        "scope": "bbox",
        "bbox": bbox,
        "source": "wms_get_capabilities",
        "provider_metadata_source": "WMS GetCapabilities",
        "bbox_source": bbox_source,
        "bbox_inherited": inherited_from is not None,
        "bbox_inherited_from": inherited_from,
        "layer": layer_name,
        "crs": crs,
    }
