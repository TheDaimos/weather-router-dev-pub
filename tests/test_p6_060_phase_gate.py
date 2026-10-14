"""P6-060 public phase gate: check evidence scope, not private log contents."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "docs/p6_060_phase_gate.v1.json"

class P6060PhaseGate(unittest.TestCase):
    def test_public_safe_report_is_conservative(self):
        record = json.loads(FILE.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], "weather_router.p6_060_phase_gate.v1")
        self.assertEqual(record["source_version"], "0.10.146")
        self.assertEqual(record["loader_revision"], "0.10-loader-149")
        observation = record["catalog_ha_observation"]
        self.assertEqual(observation["manually_triggered_requests"], 3)
        self.assertEqual(observation["successful_catalog_responses"], 3)
        self.assertEqual(observation["available_count"], observation["capability_count"])
        self.assertEqual(observation["capability_count"], 227)
        self.assertIs(observation["router_ready"], True)
        self.assertIs(observation["perceived_system_disruption"], False)
        self.assertIs(observation["cpu_ram_measurements_available"], False)
        self.assertIs(observation["timing_measurements_available"], False)
        self.assertEqual(record["source_ci"]["conclusion"], "success")
        self.assertEqual(record["proposed_transition"], {
            "P6_060": "DONE", "P6_070": "ACTIVE", "P6_080": "OPEN", "P7": "OPEN"
        })
        self.assertEqual(record["diagnostic_followups"]["unclassified_browser_rejections"], 2)
        self.assertEqual(record["diagnostic_followups"]["catalog_causality"], "not_established")
        self.assertGreaterEqual(len(record["limitations"]), 3)

if __name__ == "__main__":
    unittest.main()
