"""Offline synthetic tests; no Metaculus requests."""
import sys,pathlib,math,unittest
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]))
from score_core import *
from collector import matching_question,get_history
class AuditTests(unittest.TestCase):
 def test_binary_yes(self):
  self.assertAlmostEqual(binary_metrics([.2,.8],1)['binary_brier'],.04)
 def test_binary_no(self):
  self.assertAlmostEqual(binary_metrics([.2,.8],0)['binary_brier'],.64)
 def test_binary_direction(self):
  self.assertAlmostEqual(binary_metrics([.2,.8],1)['binary_log_loss'],-math.log(.8))
 def test_choice(self):
  self.assertAlmostEqual(choice_metrics([.1,.2,.7],2)['multiclass_brier'],.14)
 def test_exact_options(self):
  self.assertEqual(resolve_choice('C',['A','B','C']),2)
  with self.assertRaises(ValueError):resolve_choice('C',['a','b','c'])
 def test_numeric(self):
  c=[i/200 for i in range(201)]
  self.assertTrue(vector_valid(c,'NumericQuestion'))
  self.assertGreater(numeric_crps(c,5,0,10),0)
  with self.assertRaises(ValueError):numeric_crps(c,11,0,10)
 def test_invalid_cdf(self):
  c=[i/200 for i in range(201)];c[30]=.9
  self.assertFalse(vector_valid(c,'NumericQuestion'))
 def test_pending_and_canceled(self):
  self.assertEqual(norm_resolution('closed','yes')[0],'PENDING_RESOLUTION')
  self.assertEqual(norm_resolution('resolved','annulled')[0],'CANCELED')
  self.assertEqual(norm_resolution('resolved','below_lower_bound')[0],'OUT_OF_BOUNDS')
 def test_truth(self):
  self.assertEqual(norm_resolution('resolved','no')[0],'RESOLVED_VALID')
 def test_exact_question_id(self):
  post={'question':{'id':3,'my_forecasts':{}},'other':{'id':4,'resolution':'yes'}}
  self.assertEqual(matching_question(post,4)['resolution'],'yes')
  with self.assertRaises(ValueError):matching_question(post,5)
 def test_last_before_close(self):
  hist=[{'start_time':'2026-11-17T10:00:00Z','forecast_values':[.5,.5]},
        {'start_time':'2026-11-17T11:00:00Z','forecast_values':[.2,.8]}]
  self.assertEqual(choose_last_before_close(hist,'2026-11-17T10:30:00Z')[0]['forecast_values'],[.5,.5])
  self.assertEqual(choose_last_before_close([{'forecast_values':[.1,.9]}],'2026-11-17T10:30:00Z')[1],'HISTORY_TIMESTAMP_MISSING')
 def test_never_replace_history_with_latest(self):
  self.assertIsNone(get_history({'my_forecasts':{'latest':{'forecast_values':[.3,.7]}}}))
if __name__=='__main__':unittest.main()
