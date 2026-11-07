"""Public boundary examples, not private runtime execution or HA/device acceptance."""
import json,math,unittest
from pathlib import Path
DATA=json.loads((Path(__file__).parent/'synthetic-v2.json').read_text())
class Contract(unittest.TestCase):
 def test_public_fixture_has_only_explicit_synthetic_frames(self):
  self.assertTrue(DATA['synthetic']);self.assertFalse(DATA['contains_native_or_instance_data'])
  for r in DATA['cases'].values():
   self.assertEqual(r['contract_version'],2);self.assertEqual(r['schema'],'weather_router.consumer.temperature_field.v2');f=r['frame'];self.assertEqual(f['unit'],'K');self.assertEqual(f['height_m'],2);self.assertEqual(f['kind'],'model_forecast');g=f['grid'];self.assertLessEqual(len(g['values']),16000);self.assertEqual(len(g['values']),len(g['valid_mask']))
   a=f['advection'];self.assertEqual(a['unit'],'K/h');self.assertEqual(a['level'],{'type':'isobaric','value':850,'unit':'hPa'});self.assertEqual(a['model_run'],f['model_run']);self.assertEqual(a['valid_at'],f['valid_at']);self.assertLessEqual(a['valid_until'],f['valid_until'])
 def test_metric_negative_dot_product_outputs_and_no_data_stencils(self):
  cold=DATA['cases']['cold']['frame']['advection'];g=cold['grid'];lat=g['latitudes'][2];expected=-10*.2/(6371229*math.cos(math.radians(lat))*math.pi/180)*3600
  self.assertAlmostEqual(g['rate'][12],expected,places=4);self.assertGreater(DATA['cases']['warm']['frame']['advection']['grid']['rate'][12],0)
  for k in ['hole','terrain']:
   mask=DATA['cases'][k]['frame']['advection']['grid']['valid_mask'];self.assertEqual(mask[12],0);self.assertEqual(mask[11],0)
 def test_absolute_units_do_not_change_source_values(self):
  values=DATA['cases']['cold']['frame']['grid']['values'];before=values[:]
  for kelvin in values:
   c=kelvin-273.15;f=c*1.8+32;self.assertAlmostEqual((f-32)/1.8+273.15,kelvin)
  self.assertEqual(values,before)
if __name__=='__main__':unittest.main()
