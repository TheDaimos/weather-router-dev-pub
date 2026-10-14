"""P7-010: fail-closed audit of the Gewitterradar provider-neutral intent matrix."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/p7_010_gewitterradar_intent_matrix.v1.json"
CAPABILITIES = ROOT / "custom_components/weather_router/consumer_capability_map.json"


class P7010GewitterradarIntentMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_map = CAPABILITIES.read_bytes()
        cls.mapping = json.loads(cls.raw_map)
        cls.matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        cls.rows = cls.matrix["intents"]

    def test_actual_core_map_and_snapshot_are_consistent(self):
        self.assertEqual(self.matrix["schema"], "weather_router.p7_010.gewitterradar_intent_matrix.v1")
        self.assertEqual(self.matrix["weather_router"]["consumer_api_contract"], 1)
        self.assertEqual(self.mapping["contract_version"], 1)
        self.assertEqual(len(self.mapping["public_capabilities"]), 227)
        self.assertEqual(self.matrix["weather_router"]["public_capabilities"], 227)
        actual_sha = hashlib.sha1(
            f"blob {len(self.raw_map)}\0".encode("ascii") + self.raw_map
        ).hexdigest()
        self.assertEqual(actual_sha, self.matrix["weather_router"]["source_capability_map_sha"])

    def test_all_rows_resolve_to_contract_resources(self):
        self.assertEqual(len(self.rows), 45)
        ids = [row["id"] for row in self.rows]
        self.assertEqual(len(set(ids)), len(ids))
        for row in self.rows:
            with self.subTest(intent=row["id"]):
                record = self.mapping["public_capabilities"].get(row["capability"])
                self.assertIsNotNone(record, row["capability"])
                self.assertIn(row["resource"], record["resource_types"])
                self.assertIn(row["context"], {"point", "bbox", "global"})
                self.assertTrue(row["label"])
                self.assertTrue(row["reason"])
                self.assertIn(
                    row["status"],
                    {"implemented", "prepared_only", "migration_pending",
                     "expert_only", "deferred_adapter"},
                )
                if "event_filter" in row:
                    self.assertEqual(row["resource"], "hazard_feed")
                    self.assertEqual(row["capability"], "weather.warning.official")
                    types = row["event_filter"]["hazard_types"]
                    self.assertTrue(types)
                    self.assertTrue(set(types) <= set(record["hazard_types"]))

    def test_current_consumer_implementation_is_not_overstated(self):
        c = self.matrix["consumer"]
        self.assertEqual(c["version"], "4.11.74 DEV")
        self.assertEqual(c["module_count"], 33)
        self.assertEqual(sum(c["module_groups"].values()), 33)
        self.assertEqual(c["weather_module_count"], 5)
        self.assertEqual(
            set(c["current_explicit_capabilities"]),
            {
                "weather.precipitation.layer",
                "weather.lightning.observed.events",
                "weather.lightning.observed.density",
                "weather.warning.official",
            },
        )
        self.assertEqual(
            c["actual_resolve_implemented"],
            ["weather.precipitation.layer"],
        )
        self.assertEqual(
            c["frontend_renderer_capabilities"],
            ["weather.precipitation.layer"],
        )
        implemented = [r for r in self.rows if r["status"] == "implemented"]
        self.assertEqual(len(implemented), 1)
        self.assertEqual(implemented[0]["capability"], "weather.precipitation.layer")
        for capability in c["current_explicit_capabilities"][1:]:
            self.assertTrue(
                any(r["capability"] == capability and r["status"] != "implemented"
                    for r in self.rows)
            )

    def test_event_semantics_are_not_falsely_interchangeable(self):
        for id_, typ in (
            ("observed_lightning_events", "event_feed"),
            ("observed_lightning_density", "raster_tile"),
            ("lightning_distance", "value"),
            ("satellite_lightning_raster", "raster_tile"),
            ("satellite_lightning_files_east", "data_file"),
            ("thunder_probability", "value"),
            ("thunderstorm_cells", "raster_tile"),
            ("official_thunder_warnings", "hazard_feed"),
        ):
            record = next((r for r in self.rows if r["id"] == id_), None)
            self.assertIsNotNone(record, id_)
            self.assertEqual(record["resource"], typ)
        policy = self.matrix["policy"]
        self.assertFalse(policy["consumer_provider_selection"])
        self.assertFalse(policy["consumer_scoring"])
        self.assertFalse(policy["consumer_auto_coverage_decision"])
        self.assertTrue(policy["profile_can_only_restrict"])
        self.assertTrue(policy["router_optional"])
        self.assertTrue(policy["resource_type_must_match"])
        self.assertTrue(policy["local_data_independent"])
        self.assertFalse(self.matrix["migration_approved"])

    def test_local_functions_remain_outside_weather_routing(self):
        local = self.matrix["local_only"]
        self.assertEqual(len(local), 10)
        self.assertEqual(len({x["id"] for x in local}), len(local))
        self.assertIn("local_lightning_markers", {x["id"] for x in local})
        self.assertIn("tracking_and_radius", {x["id"] for x in local})
        self.assertIn("compass_and_medallion", {x["id"] for x in local})
        for item in local:
            self.assertNotIn("capability", item)
            self.assertTrue(item["reason"])

    def test_p7_remains_unreleased_for_consumer_migration(self):
        self.assertEqual(self.matrix["phase"], "P7-010")
        self.assertEqual(self.matrix["phase_status"], "ACTIVE")
        gates = {x["id"]: x["status"] for x in self.matrix["gates"]}
        self.assertEqual(gates["P7-010-INVENTORY"], "PASS")
        self.assertEqual(gates["P7-010-MATRIX"], "PASS")
        self.assertEqual(gates["P7-010-STATIC"], "OPEN")
        self.assertEqual(gates["P7-010-CONSUMER-ADAPTER"], "OPEN")
        self.assertEqual(gates["P7-010-HA"], "OPEN")


if __name__ == "__main__":
    unittest.main()
