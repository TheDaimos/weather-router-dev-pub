"""P6-040: metadata restrictions are scoped to applicable public capabilities.

The profile's hazard and phenomenon restrictions must not silently hide unrelated
capabilities without those metadata tags. For tagged capabilities, an explicit
non-matching restriction must deny access.
"""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/weather_router/consumer_profiles.py"
spec = importlib.util.spec_from_file_location("p6040_metadata_scope", PATH)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class P6040ScopedMetadata(unittest.TestCase):
    def setUp(self):
        self.id = "weather.point.synthetic"
        self.mapping = {"public_capabilities": {self.id: {"family": "point"}}}

    def test_phenomenon_filter_does_not_hide_untagged_capability(self):
        self.assertEqual(
            policy.profile_allows_capability(
                {"enabled": True, "allowed_phenomena": ["precipitation"]}, self.mapping, self.id),
            (True, None),
        )

    def test_hazard_filter_does_not_hide_unrelated_nonhazard_capability(self):
        self.assertEqual(
            policy.profile_allows_capability(
                {"enabled": True, "allowed_hazard_types": ["flood"]}, self.mapping, self.id),
            (True, None),
        )

    def test_explicit_tagged_phenomenon_mismatch_denied(self):
        mapping = {"public_capabilities": {self.id: {"family": "point", "phenomena": ["fog"]}}}
        self.assertEqual(
            policy.profile_allows_capability(
                {"enabled": True, "allowed_phenomena": ["precipitation"]}, mapping, self.id),
            (False, "profile_phenomenon_filtered"),
        )

    def test_explicit_tagged_hazard_mismatch_denied(self):
        mapping = {"public_capabilities": {self.id: {"family": "warning", "hazard_types": ["flood"]}}}
        self.assertEqual(
            policy.profile_allows_capability(
                {"enabled": True, "allowed_hazard_types": ["hail"]}, mapping, self.id),
            (False, "profile_hazard_filtered"),
        )

    def test_matching_restrictions_and_unrestricted_profile_allow(self):
        mapping = {"public_capabilities": {self.id: {"family": "warning", "phenomena": ["rain"], "hazard_types": ["flood"]}}}
        self.assertEqual(
            policy.profile_allows_capability(
                {"enabled": True, "allowed_phenomena": ["rain"], "allowed_hazard_types": ["flood"]},
                mapping, self.id),
            (True, None),
        )
        self.assertEqual(
            policy.profile_allows_capability({"enabled": True}, self.mapping, self.id),
            (True, None),
        )

if __name__ == "__main__":
    unittest.main()
