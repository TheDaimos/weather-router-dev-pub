"""Focused additive v1 distance contract; no HA/network/provider dependency."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest
import astronomy as astro

spec=importlib.util.spec_from_file_location('moon_engine',Path(__file__).resolve().parents[1]/'custom_components/weather_router/moon_engine.py')
moon=importlib.util.module_from_spec(spec);spec.loader.exec_module(moon)
class DistanceTest(unittest.TestCase):
    def test_topocentric_range_and_location(self):
        at=datetime(2026,11,24,12,tzinfo=timezone.utc);t=astro.Time.Parse('2026-11-24T12:00:00Z')
        values=[]
        for lat,lon in [(52.52,13.405),(-52.52,-166.595)]:
            reply=moon.calculate_moon(lat,lon,at,'UTC');d=reply['distance_km'];values.append(d)
            self.assertTrue(300000<d<420000)
            self.assertEqual(reply['distance_kind'],'topocentric_observer_to_moon_center')
            self.assertEqual(reply['observer_height_m'],0)
            # Independent vector subtraction verifies the observer baseline.
            geo=astro.GeoVector(astro.Body.Moon,t,True);obs=astro.ObserverVector(t,astro.Observer(lat,lon,0),False)
            expected=((geo.x-obs.x)**2+(geo.y-obs.y)**2+(geo.z-obs.z)**2)**.5*astro.KM_PER_AU
            self.assertLessEqual(abs(d-expected),.50001)
            self.assertEqual(reply['schema'],'weather_router.moon.v1')
        self.assertNotEqual(*values)
if __name__=='__main__':unittest.main()
