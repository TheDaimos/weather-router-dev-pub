"""Static contract tests for the provider-neutral router topic taxonomy."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
WEBSOCKET_PATH = ROOT / "custom_components" / "weather_router" / "websocket_api.py"
FRONTEND_PATH = (
    ROOT
    / "custom_components"
    / "weather_router"
    / "frontend"
    / "weather-router-lab-routing.js"
)
CAPABILITY_MAP_PATH = (
    ROOT
    / "custom_components"
    / "weather_router"
    / "consumer_capability_map.json"
)

REQUIRED_TOPICS = {
    "precipitation",
    "wind",
    "clouds",
    "thunderstorm",
    "lightning_observation",
    "snow_ice",
    "temperature",
    "uv",
    "visibility_fog",
    "tornado",
    "hail",
    "severe_wind",
    "supercell",
    "flood",
    "heavy_rain_flash_flood",
    "tsunami",
    "earthquake",
    "volcanism",
    "tropical_systems",
    "pollen",
    "space_weather",
    "aviation",
    "civil_protection",
    "security",
    "biological_hazards",
}


def _literal_assignment(name: str):
    """Read one literal assignment from const.py without importing Home Assistant."""
    tree = ast.parse(CONST_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {CONST_PATH}")


class TopicTaxonomyContractTest(unittest.TestCase):
    """P1-010 taxonomy must be complete and transported generically to the UI."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.domains = _literal_assignment("ROUTER_DOMAINS")
        cls.groups = _literal_assignment("ROUTER_TOPIC_GROUPS")
        cls.flattened = {
            topic_id: {
                "name": topic_name,
                "group": group_id,
                "group_name": group["name"],
                "domain": group["domain"],
            }
            for group_id, group in cls.groups.items()
            for topic_id, topic_name in group["topics"].items()
        }

    def test_required_topic_taxonomy_is_complete(self) -> None:
        self.assertTrue(
            REQUIRED_TOPICS <= set(self.flattened),
            REQUIRED_TOPICS - set(self.flattened),
        )

    def test_topic_ids_are_unique_and_domains_are_valid(self) -> None:
        topic_ids = [
            topic_id
            for group in self.groups.values()
            for topic_id in group["topics"]
        ]
        self.assertEqual(len(topic_ids), len(set(topic_ids)))
        for group_id, group in self.groups.items():
            self.assertIn(group["domain"], self.domains, group_id)
            self.assertTrue(group["topics"], group_id)

    def test_flat_topic_metadata_matches_group_contract(self) -> None:
        for group_id, group in self.groups.items():
            for topic_id, name in group["topics"].items():
                self.assertEqual(
                    self.flattened[topic_id],
                    {
                        "name": name,
                        "group": group_id,
                        "group_name": group["name"],
                        "domain": group["domain"],
                    },
                )


    def test_every_internal_capability_has_valid_topic_assignment(self) -> None:
        payload = json.loads(CAPABILITY_MAP_PATH.read_text(encoding="utf-8"))
        providers = payload["providers"]
        assignment_contract = payload["capability_topic_assignments"]
        assignments = assignment_contract["providers"]
        allowed_exceptions = set(assignment_contract["allowed_exceptions"])

        self.assertEqual(set(assignments), set(providers))

        mapped = 0
        exceptions = 0
        for provider_id, capabilities in providers.items():
            self.assertEqual(
                set(assignments[provider_id]),
                set(capabilities),
                provider_id,
            )
            for capability_id in capabilities:
                assignment = assignments[provider_id][capability_id]
                classification = assignment["classification"]
                topics = assignment["topics"]
                if classification == "topic_mapped":
                    self.assertTrue(topics, f"{provider_id}/{capability_id}")
                    self.assertTrue(
                        set(topics) <= set(self.flattened),
                        f"{provider_id}/{capability_id}: {topics}",
                    )
                    mapped += 1
                else:
                    self.assertIn(classification, allowed_exceptions)
                    self.assertFalse(topics)
                    self.assertTrue(assignment.get("reason"))
                    exceptions += 1

        self.assertEqual(mapped, 280)
        self.assertEqual(exceptions, 0)

    def test_reference_capability_topic_assignments_are_semantically_explicit(self) -> None:
        payload = json.loads(CAPABILITY_MAP_PATH.read_text(encoding="utf-8"))
        assignments = payload["capability_topic_assignments"]["providers"]

        self.assertEqual(
            assignments["dwd"]["radar_precipitation_quality_checked"]["topics"],
            ["precipitation"],
        )
        self.assertEqual(
            assignments["nasa_gibs"]["satellite_precipitation_imerg_30min"]["topics"],
            ["precipitation", "satellite_imagery"],
        )
        self.assertEqual(
            assignments["fmi_lightning"]["lightning_strikes_observed"]["topics"],
            ["lightning_observation"],
        )
        self.assertEqual(
            assignments["open_meteo_pollen"]["grass_pollen"]["topics"],
            ["pollen"],
        )
        self.assertEqual(
            assignments["gbif_biodiversity"]["occurrence_density_lion"]["topics"],
            ["biological_hazards"],
        )

    def test_websocket_exposes_taxonomy_without_duplicate_shadow_list(self) -> None:
        source = WEBSOCKET_PATH.read_text(encoding="utf-8")
        self.assertIn("ROUTER_TOPIC_GROUPS", source)
        self.assertIn('"topic_groups": [', source)
        self.assertIn("for group_id, metadata in ROUTER_TOPIC_GROUPS.items()", source)

    def test_frontend_consumes_server_topic_groups_generically(self) -> None:
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn("settings.topic_groups", source)
        self.assertIn("for (const group of topicGroups)", source)
        self.assertNotIn("const ROUTER_TOPIC_GROUPS", source)


if __name__ == "__main__":
    unittest.main()
