"""Static contract test for the P4-TROPICAL-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_tropical_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"


class P4TropicalIntentDesignContractTest(unittest.TestCase):
    """Protect tropical-system lifecycle design without public-contract sprawl."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    def test_no_new_public_capability_is_designed(self) -> None:
        self.assertEqual(self.design["public_capabilities_added"], 0)
        self.assertEqual(
            self.design["public_capability_count_before"],
            self.design["public_capability_count_after"],
        )
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_tropical_system_is_structured_event_semantics(self) -> None:
        semantics = self.design["event_semantics"]
        self.assertEqual(semantics["field"], "tropical_system")
        self.assertEqual(semantics["shape"], "object")
        self.assertEqual(semantics["required_fields"], ["system_class"])
        self.assertIn("source_classification", semantics["optional_fields"])

    def test_potential_and_post_tropical_are_explicit_classes(self) -> None:
        classes = set(self.design["event_semantics"]["system_classes"])
        self.assertIn("potential_tropical_cyclone", classes)
        self.assertIn("post_tropical_cyclone", classes)
        self.assertIn("tropical_cyclone_unspecified", classes)

    def test_primary_hazard_type_is_only_compatibility_label(self) -> None:
        primary = self.design["primary_hazard_type"]
        self.assertTrue(primary["remains_for_compatibility"])
        self.assertFalse(primary["sufficient_proof_of_current_lifecycle"])

    def test_nhc_uses_structured_source_classification(self) -> None:
        nhc = self.design["nhc_design"]
        self.assertEqual(nhc["source_field"], "classification")
        self.assertTrue(nhc["preserve_raw_source_classification"])
        self.assertEqual(nhc["structured_source"], "structured_provider_field")
        self.assertEqual(nhc["fallback"], "tropical_cyclone_unspecified")

    def test_general_warning_does_not_use_context_only_for_current_lifecycle(self) -> None:
        warning = self.design["general_weather_warning_design"]
        self.assertTrue(warning["attach_from_explicit_event_or_headline_only"])
        self.assertFalse(warning["description_or_instruction_only"])
        self.assertTrue(warning["do_not_promote_future_forecast_language"])

    def test_gdacs_and_aviation_only_get_unspecified_without_finer_evidence(self) -> None:
        self.assertEqual(
            self.design["gdacs_design"]["tc_event_class"],
            "tropical_cyclone_unspecified",
        )
        self.assertFalse(self.design["gdacs_design"]["infer_finer_intensity"])
        self.assertEqual(
            self.design["aviation_design"]["tc_event_class"],
            "tropical_cyclone_unspecified",
        )
        self.assertFalse(self.design["aviation_design"]["infer_finer_intensity"])

    def test_track_cone_and_surge_do_not_create_new_contracts(self) -> None:
        forecast = self.design["forecast_resources"]
        self.assertFalse(forecast["new_public_capability"])
        self.assertFalse(forecast["new_resource_type"])
        self.assertFalse(forecast["track_is_event_geometry"])
        self.assertFalse(forecast["cone_is_hazard_area"])
        self.assertFalse(
            self.design["storm_surge"]["auto_event_from_nhc_resource_link"]
        )

    def test_filter_is_explicitly_gated(self) -> None:
        filt = self.design["event_filter_additions"]
        self.assertEqual(filt["filter_path"], "tropical_system.system_class")
        self.assertFalse(filt["regional_term_filter_added"])
        self.assertEqual(len(filt["compatible_public_capabilities"]), 6)

    def test_versions_are_planned_for_runtime_change(self) -> None:
        versions = self.design["versions"]
        self.assertEqual(versions["planned_build_version"], "0.10.127")
        self.assertEqual(versions["planned_loader_revision"], "0.10-loader-130")

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.design["invariants"])
        self.assertIn("No new public capability.", invariants)
        self.assertIn(
            "Potential tropical cyclone is not promoted to confirmed tropical cyclone.",
            invariants,
        )
        self.assertIn("Storm surge remains distinct.", invariants)
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
