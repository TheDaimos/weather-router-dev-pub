"""P6-040: restrictive metadata filters must fail closed for missing metadata."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/weather_router/consumer_profiles.py"
spec = importlib.util.spec_from_file_location("p6040_missing_meta", PATH)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

class P6040MissingMetadata(unittest.TestCase):
    def setUp(self):
        self.id = "weather.point.synthetic"
        self.mapping = {"public_capabilities": {self.id: {"family": "point"}}}

    def test_restricted_phenomenon_without_metadata_denied(self):
        self.assertEqual(
            policy.profile_allows_capability(
                {"enabled": True, "allowed_phenomena": ["precipitation"]}, self.mapping, self.id),
            (False, "profile_phenomenon_filtered"),
        )

    def test_restricted_hazard_without_metadata_denied(self):
        self.assertEqual(
            policy.profile_allows_capability(
                {"enabled": True, "allowed_hazard_types": ["flood"]}, self.mapping, self.id),
            (False, "profile_hazard_filtered"),
        )

    def test_unrestricted_missing_metadata_permitted(self):
        self.assertEqual(
            policy.profile_allows_capability({"enabled": True}, self.mapping, self.id),
            (True, None),
        )

if __name__ == "__main__":
    unittest.main()
