import unittest
from practice import core

B={'type':'binary'}
M={'type':'multiple_choice','options':['X','Y','Z']}
N={'type':'numeric','lower_bound':0,'upper_bound':100}
D={'type':'date','lower_bound':'2026-01-01','upper_bound':'2035-01-01'}

def primary(q,p,pre='YELLOW_2',post='YELLOW_1'):
    return core.validate_primary({'pre_complexity':{'level':pre,'reason':'some evidence gaps'},
                                  'prediction':p,'post_complexity':{'level':post,'reason':'new evidence'},
                                  'reasoning':'considered evidence'},q)

class CoreTests(unittest.TestCase):
    def test_binary_agree(self):
        a=primary(B,{'probability':.71});b=primary(B,{'probability':.63})
        self.assertEqual(core.compare_forecasts(B,a,b)['route'],'check')
        c={'prediction':{'probability':.68},'post_complexity':{'level':'GREEN','reason':'clear'}}
        self.assertAlmostEqual(core.aggregate(B,[a,b,c])['probability'],.68)
    def test_binary_opposite_direction(self):
        a=primary(B,{'probability':.49});b=primary(B,{'probability':.51})
        self.assertEqual(core.compare_forecasts(B,a,b)['reason'],'BINARY_DIRECTION_OPPOSITE')
    def test_binary_large_gap(self):
        a=primary(B,{'probability':.91});b=primary(B,{'probability':.65})
        self.assertEqual(core.compare_forecasts(B,a,b)['route'],'C')
    def test_bad_probability(self):
        for x in (-.1,0,1,1.1,float('nan'),True):
            with self.assertRaises(ValueError):core.validate_prediction('binary',{'probability':x},B)
    def test_multi_top_conflict(self):
        a=primary(M,{'probabilities':{'X':.6,'Y':.3,'Z':.1}})
        b=primary(M,{'probabilities':{'X':.3,'Y':.6,'Z':.1}})
        self.assertEqual(core.compare_forecasts(M,a,b)['reason'],'DIFFERENT_TOP_OPTION')
        c={'prediction':{'probabilities':{'X':.5,'Y':.2,'Z':.3}}}
        self.assertAlmostEqual(sum(core.aggregate(M,[a,b,c])['probabilities'].values()),1)
    def test_multi_bad_options(self):
        with self.assertRaises(ValueError):core.validate_prediction('multiple_choice',{'probabilities':{'X':.5,'Y':.5}},M)
    def test_numeric_interval_conflict(self):
        a=primary(N,{'median':20,'low_80':10,'high_80':30})
        b=primary(N,{'median':80,'low_80':70,'high_80':90})
        self.assertEqual(core.compare_forecasts(N,a,b)['route'],'C')
        c={'prediction':{'median':40,'low_80':30,'high_80':60}}
        self.assertEqual(core.aggregate(N,[a,b,c])['median'],40)
    def test_numeric_invalid_range(self):
        with self.assertRaises(ValueError):core.validate_prediction('numeric',{'median':4,'low_80':5,'high_80':9},N)
    def test_date_conflict(self):
        a=primary(D,{'median_date':'2028-01-01','low_80_date':'2027-10-01','high_80_date':'2028-04-01'})
        b=primary(D,{'median_date':'2030-01-01','low_80_date':'2029-09-01','high_80_date':'2030-05-01'})
        self.assertEqual(core.compare_forecasts(D,a,b)['route'],'C')
        c={'prediction':{'median_date':'2029-01-01','low_80_date':'2028-12-01','high_80_date':'2029-03-01'}}
        self.assertEqual(core.aggregate(D,[a,b,c])['median_date'],'2029-01-01')
    def test_complexity_metadata_only(self):
        a=primary(B,{'probability':.7},'RED','YELLOW_1');b=primary(B,{'probability':.8})
        third=core.validate_third({'prediction':{'probability':.6},'post_complexity':{'level':'RED','reason':'still unclear'},'reasoning':'x'},B)
        out=core.complexity_summary(a,b,third)
        self.assertEqual(out[0]['pre_minus_post'],2)
        self.assertIsNone(out[2]['pre_minus_post'])
        self.assertAlmostEqual(core.aggregate(B,[a,b,third])['probability'],.7)
    def test_malformed_primary_rejected(self):
        with self.assertRaises(ValueError):core.validate_primary({'prediction':{'probability':.7}},B)

if __name__=='__main__':unittest.main()
