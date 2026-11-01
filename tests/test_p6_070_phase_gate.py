"""P6-070: verify privacy-safe phase documentation gate against current core."""
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
class P6070DocumentationGate(unittest.TestCase):
    def test_manifest_matches_shipped_contract_and_html(self):
        m=json.loads((ROOT/"docs/p6_070_phase_gate.v1.json").read_text(encoding="utf-8"))
        c=json.loads((ROOT/"custom_components/weather_router/consumer_capability_map.json").read_text(encoding="utf-8"))
        h=(ROOT/"custom_components/weather_router/frontend/weather-router-help.html").read_text(encoding="utf-8")
        self.assertEqual(m["schema"],"weather_router.p6_070_phase_gate.v1")
        self.assertEqual(m["core"]["providers"],len(c["providers"]))
        self.assertEqual(m["core"]["internal"],sum(len(v) for v in c["providers"].values()))
        self.assertEqual(m["core"]["public"],len(c["public_capabilities"]))
        self.assertEqual(m["core"]["edges"],sum(len(ids) for p in c["providers"].values() for ids in p.values()))
        self.assertEqual(m["core"]["aggregate_intents"],sum(1 for v in c["public_capabilities"].values() if v.get("strategy")=="aggregate"))
        self.assertEqual(m["core"]["public"],227)
        self.assertIn("227 Public-Capabilities",h)
        self.assertIn("P6-070",h)
        self.assertGreaterEqual(len(m["private_sources_reviewed"]),8)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}",v) for v in m["private_sources_reviewed"].values()))
        self.assertEqual(m["proposed_transition"],{"P6-070":"DONE","P6-080":"ACTIVE","P7":"OPEN"})
        self.assertTrue(any("not a CI validation" in note for note in m["caveats"]))
if __name__=="__main__":
    unittest.main()
