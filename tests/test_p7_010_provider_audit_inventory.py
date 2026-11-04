"""Reject incomplete provider/capability inventories without fabricating PASS."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "custom_components/weather_router/consumer_capability_map.json"
MATRIX = ROOT / "docs/P7_010_PROVIDER_UTC_AUDIT_MATRIX_2026-10-16.json"


class ProviderTimeAuditInventoryTests(unittest.TestCase):
    def test_exact_registry_coverage_and_evidence(self):
        mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
        audit = json.loads(MATRIX.read_text(encoding="utf-8"))
        target = {(name, cap) for name, entries in mapping["providers"].items()
                  for cap in entries}
        actual = [(row["provider"], row["capability"]) for row in audit["entries"]]
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual(set(actual), target)
        self.assertEqual(audit["providers"], len(mapping["providers"]))
        self.assertEqual(audit["capabilities"], len(target))
        for row in audit["entries"]:
            self.assertTrue(row["raw_field"] and row["raw_format"])
            self.assertTrue(row["source_timezone"] and row["utc_conversion"])
            self.assertTrue(row["evidence"])
            self.assertIn(row["test_status"], {
                "STATIC_CODE_REVIEW__RUNTIME_UNTESTED",
                "RUNTIME_SOURCE_FORMAT_UNVERIFIED",
            })

    def test_time_roles_agree_with_contract(self):
        mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
        audit = json.loads(MATRIX.read_text(encoding="utf-8"))
        for row in audit["entries"]:
            roles = mapping["capability_time_semantics"]["providers"][
                row["provider"]][row["capability"]]
            self.assertEqual(row["declared_time_roles"]["data_time"], roles["data_time"])
            self.assertEqual(row["declared_time_roles"]["valid_time"], roles["valid_time"])
            self.assertEqual(row["interval_semantics"]["accumulation"],
                             roles["accumulation_period"])


if __name__ == "__main__":
    unittest.main()
