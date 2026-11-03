import unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from btf3_route_order_race import dedup,choose_primary_fallback,score_plan,calculate_summary

def r(u):return {'url':'https://x.example/'+u,'origin':'TEST'}

class TestMethodRace(unittest.TestCase):
    def test_equal_3_plus_3_with_overlap(self):
        o=[r('a'),r('b'),r('c'),r('d')]
        n=[r('c'),r('d'),r('e'),r('f')]
        a,ap=choose_primary_fallback(o,n)
        b,bp=choose_primary_fallback(n,o)
        self.assertEqual(len(a),6)
        self.assertEqual(len(b),5)
        self.assertEqual(ap,3);self.assertEqual(bp,3)
        self.assertEqual(a[0]['url'],r('a')['url'])
        self.assertEqual(b[0]['url'],r('c')['url'])
    def test_target_at_fourth_not_third(self):
        p=[r('a'),r('b'),r('c'),r('d')]
        o={x['url']:{'archive':True,'readable':True,'keyword':True,'target_proxy':False} for x in p}
        o[p[3]['url']]['target_proxy']=True
        s=score_plan(p,o,3)
        self.assertFalse(s['by_depth']['3']['target_proxy'])
        self.assertTrue(s['by_depth']['6']['target_proxy'])
        self.assertEqual(s['first_target_proxy_rank'],4)
    def test_no_evidence_is_not_false_evidence(self):
        a,ap=choose_primary_fallback([],[])
        self.assertEqual(a,[]);self.assertEqual(ap,0)
        s=score_plan([],{},0)
        self.assertFalse(s['by_depth']['3']['target_proxy'])
    def test_paired_diff_direction(self):
        x={'case_id':'Q001','arms':{
            'official_first':{'by_depth':{'3':{'archive':1,'readable':1,'keyword':1,'target_proxy':1},'6':{'archive':1,'readable':1,'keyword':1,'target_proxy':1}},'first_target_proxy_rank':1},
            'natural_first':{'by_depth':{'3':{'archive':0,'readable':0,'keyword':0,'target_proxy':0},'6':{'archive':1,'readable':1,'keyword':1,'target_proxy':1}},'first_target_proxy_rank':4}
        }}
        s=calculate_summary([x]);self.assertEqual(s['paired_differences']['3']['target_proxy'],1)
        self.assertEqual(s['paired_differences']['6']['target_proxy'],0)

if __name__=='__main__':unittest.main()
