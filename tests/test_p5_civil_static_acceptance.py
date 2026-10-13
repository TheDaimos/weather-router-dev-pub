"""Independent static acceptance for P5-CIVIL-50."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAPPING = json.loads(
    (ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json").read_text(encoding="utf-8")
)
DRAFT = json.loads(
    (ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json").read_text(encoding="utf-8")
)
DESIGN = json.loads(
    (ROOT / "docs" / "p5_civil_intent_design.v1.json").read_text(encoding="utf-8")
)
SEMANTICS = json.loads(
    (ROOT / "docs" / "p5_civil_semantics.v1.json").read_text(encoding="utf-8")
)
REGISTRY = json.loads(
    (ROOT / "custom_components" / "weather_router" / "providers" / "registry.json").read_text(encoding="utf-8")
)["providers"]
CONSUMER = (
    ROOT / "custom_components" / "weather_router" / "consumer_api.py"
).read_text(encoding="utf-8")
CONST = (
    ROOT / "custom_components" / "weather_router" / "const.py"
).read_text(encoding="utf-8")
LAB = (
    ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
).read_text(encoding="utf-8")
LOADER = (
    ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"
).read_text(encoding="utf-8")


from wr_public_version_contract import assert_current_version_surfaces

class P5CivilStaticAcceptanceTest(unittest.TestCase):
    def test_01_exact_public_catalog_shape(self) -> None:
        self.assertEqual(len(MAPPING["public_capabilities"]), 227)
        ids = sorted(
            item for item in MAPPING["public_capabilities"]
            if item.startswith("civil_protection.")
        )
        self.assertEqual(ids, ["civil_protection.warning.official"])
        public = MAPPING["public_capabilities"]["civil_protection.warning.official"]
        self.assertEqual(public["strategy"], "aggregate")
        self.assertEqual(public["resource_types"], ["hazard_feed"])

    def test_02_exact_four_candidates_remain(self) -> None:
        expected = {
            "bbk_mowas/civil_protection_warnings_germany",
            "nina_flood/flood_information_germany",
            "nina_katwarn/katwarn_public_warnings",
            "nina_biwapp/biwapp_public_warnings",
        }
        found = set()
        for provider_id, capabilities in MAPPING["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "civil_protection.warning.official" in public_ids:
                    found.add(f"{provider_id}/{capability_id}")
        self.assertEqual(found, expected)

    def test_03_all_civil_sources_remain_default_disabled(self) -> None:
        classes = {
            "BbkMowasProvider",
            "NinaFloodProvider",
            "NinaKatwarnProvider",
            "NinaBiwappProvider",
        }
        rows = [item for item in REGISTRY if item["class"] in classes]
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertFalse(row["default_enabled"])

    def test_04_nina_flood_remains_cross_domain(self) -> None:
        row = next(item for item in REGISTRY if item["class"] == "NinaFloodProvider")
        self.assertEqual(
            row["domains"],
            ["natural_hazards", "civil_protection"],
        )

    def test_05_context_supported_rejects_civil_point(self) -> None:
        start = CONSUMER.index("def _context_supported")
        end = CONSUMER.index("def _requirements_match", start)
        block = CONSUMER[start:end]
        self.assertIn(
            "candidate.public_id in _CIVIL_PROTECTION_PUBLIC_IDS",
            block,
        )
        self.assertIn('context["type"] == "point"', block)
        self.assertIn("return False", block)

    def test_06_public_point_guard_precedes_aggregate_resolution(self) -> None:
        guard = CONSUMER.index("Civil-Point-Abfragen benötigen")
        aggregate = CONSUMER.index(
            "payload, provider_result, provenance, degraded = await _resolve_aggregate_hazard",
            guard,
        )
        self.assertLess(guard, aggregate)
        block = CONSUMER[max(0, guard - 1400):guard + 900]
        self.assertIn('"requirements_not_met"', block)
        self.assertIn("retryable=False", block)
        self.assertIn('result="rejected"', block)
        self.assertIn('reason="requirements_not_met"', block)
        self.assertNotIn("candidate_attempt(", block)
        self.assertNotIn("candidate_provider_contact(", block)

    def test_07_global_and_bbox_contracts_are_preserved(self) -> None:
        contract = DESIGN["context_contract"]
        self.assertEqual(contract["global"], "allowed")
        self.assertEqual(contract["bbox"], "allowed_event_geometry_filter")
        self.assertEqual(contract["nearby"], "not_implicit")
        self.assertIn('kwargs["bbox"] = (', CONSUMER)

    def test_08_aggregate_provenance_and_source_counters_remain(self) -> None:
        for token in (
            'event["source_event_id"] = source_event_id',
            'event["source_ref"] = candidate.provider.id',
            'event["id"] = f"{candidate.provider.id}:{source_event_id}"',
            '"source_count": len(sources)',
            '"matched_source_count": matched_source_count',
            "degraded = bool(failures)",
        ):
            self.assertIn(token, CONSUMER)

    def test_09_no_cross_channel_dedup_is_introduced(self) -> None:
        self.assertFalse(
            SEMANTICS["aggregation_semantics"]["cross_channel_deduplication"]
        )
        self.assertFalse(
            DESIGN["preserved"]["cross_channel_deduplication"]
        )

    def test_10_empty_source_and_partial_failure_semantics_remain(self) -> None:
        agg = SEMANTICS["aggregation_semantics"]
        self.assertFalse(agg["successful_empty_source_is_error"])
        self.assertTrue(agg["partial_failure_can_be_degraded"])
        self.assertTrue(
            agg["successful_empty_aggregate_is_allowed_when_source_count_gt_zero"]
        )

    def test_11_runtime_and_draft_maps_are_identical(self) -> None:
        self.assertEqual(MAPPING, DRAFT)

    def test_12_version_surfaces_are_010140_loader143(self) -> None:
        assert_current_version_surfaces(self, CONST, LAB, LOADER)


if __name__ == "__main__":
    unittest.main()
