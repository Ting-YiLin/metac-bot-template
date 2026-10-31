import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from practice.gemini import (RateLimiter,Gemini,QuotaLedger,ModelFailure,
                             BudgetExceeded,GOOGLE_LIMITS,ROUTER_MODEL,google_day)
from practice.router import FreeFallbackLLM,OpenRouterFree
from practice import run

Q={'id':'SYNTHETIC','type':'binary','text':'Will event happen by 2027?',
   'options':[],'resolution_criteria':'Official resolution','lower_bound':None,'upper_bound':None}

def a_reply(p):
    return {'pre_complexity':{'level':'YELLOW_2','reason':'two disputed facts'},
            'prediction':{'probability':p},
            'post_complexity':{'level':'YELLOW_2','reason':'facts remain disputed'},
            'reasoning':'Independent evidence review'}
def third_reply(p):
    return {'prediction':{'probability':p},'post_complexity':{'level':'YELLOW_2','reason':'still uncertain'},
            'reasoning':'Review both positions'}
EVIDENCE={'research':{'quality':{'pass_for_bounded_research':False,'score':0.2,'metrics':{},'flags':['LOW_SOURCE_QUALITY']},
 'sources':[], 'queries':[], 'errors':[]},'evidence_lite':{'summary':'No source','supporting':[],
 'opposing':[],'limitations':[],'research_gaps':[],'decisive_factors':[],
 'quality_conclusion':'INSUFFICIENT_EVIDENCE'}}

class FakeTime:
    def __init__(self):self.t=100.;self.sleeps=[]
    def clock(self):return self.t
    def sleep(self,s):self.sleeps.append(s);self.t+=s

class V22Tests(unittest.TestCase):
    def test_google_daily_boundary_is_pacific_not_utc(self):
        self.assertEqual(google_day(dt.datetime(2026,11,1,4,0,tzinfo=dt.timezone.utc)),'2026-10-31')
        self.assertEqual(google_day(dt.datetime(2026,11,1,8,0,tzinfo=dt.timezone.utc)),'2026-11-01')
    def test_strong_models_share_one_30second_limiter(self):
        fake=FakeTime();limit=RateLimiter(clock=fake.clock,sleep=fake.sleep)
        limit.wait_before('gemini-3.8-flash');limit.wait_before('gemini-3.6-flash');limit.wait_before('gemini-3.8-flash')
        self.assertEqual([e['wait_seconds'] for e in limit.events],[0,30,30])
    def test_lite_and_strong_pacing_independent(self):
        fake=FakeTime();lim=RateLimiter(clock=fake.clock,sleep=fake.sleep)
        lim.wait_before('gemini-3.5-flash-lite');lim.wait_before('gemini-3.8-flash')
        self.assertEqual([e['wait_seconds'] for e in lim.events],[0,0])
    def test_high_for_google_strong_models(self):
        with tempfile.TemporaryDirectory() as t:
            g=Gemini(QuotaLedger(Path(t)/'l.json'),transport=lambda m,p,r:{'ok':True})
            g.call('gemini-3.8-flash','test',role='A')
            g.call('gemini-3.6-flash','test',role='check')
            self.assertEqual([x['thinking_level'] for x in g.history],['high','high'])
            with self.assertRaises(ValueError):g.call('gemini-3.8-flash','test',role='A',thinking_level='low')
    def test_503_45_90_backoff_and_three_attempts(self):
        fake=FakeTime();tries=[]
        def transport(m,p,r):tries.append(1);raise ModelFailure('GEMINI_HTTP_503')
        with tempfile.TemporaryDirectory() as t:
            ledger=QuotaLedger(Path(t)/'l.json')
            pacer=RateLimiter(clock=fake.clock,sleep=fake.sleep)
            g=Gemini(ledger,transport=transport,sleep=fake.sleep,pacer=pacer,clock=fake.clock,jitter=lambda:0)
            with self.assertRaises(ModelFailure) as ctx:g.call('gemini-3.8-flash','x',role='A')
            self.assertEqual(ctx.exception.code,'GEMINI_HTTP_503')
            self.assertEqual(len(tries),3)
            self.assertEqual([int(x) for x in fake.sleeps if x>=45],[45,90])
            self.assertEqual(ledger.d['counts']['gemini-3.8-flash'],3)
    def test_persistent_503_routes_once_to_free_only(self):
        def google_transport(m,p,r):raise ModelFailure('GEMINI_HTTP_503')
        router_calls=[]
        def free_transport(m,p,r):router_calls.append((m,r));return {'answer':'OK'},'nvidia/example:free',{'total_tokens':21}
        with tempfile.TemporaryDirectory() as t:
            g=Gemini(QuotaLedger(Path(t)/'l.json'),transport=google_transport,sleep=lambda _:None,jitter=lambda:0)
            routed=FreeFallbackLLM(g,allow_free_fallback=True,router_transport=free_transport)
            self.assertEqual(routed.call('gemini-3.8-flash','text',role='A'),{'answer':'OK'})
            self.assertEqual(router_calls,[(ROUTER_MODEL,'A')])
            self.assertEqual(routed.last_success('A')['model_returned'],'nvidia/example:free')
            self.assertEqual(routed.last_success('A')['thinking_level'],'NOT_GUARANTEED')
            self.assertEqual(g.ledger.d['counts']['gemini-3.8-flash'],3)
            self.assertEqual(g.ledger.d['counts'][ROUTER_MODEL],1)
    def test_lite_503_does_not_consume_router_budget(self):
        def google_transport(m,p,r):raise ModelFailure('GEMINI_HTTP_503')
        with tempfile.TemporaryDirectory() as t:
            g=Gemini(QuotaLedger(Path(t)/'l.json'),transport=google_transport,sleep=lambda _:None,jitter=lambda:0)
            calls=[]
            def free_transport(*args):calls.append(1);return {},'unknown',{}
            routed=FreeFallbackLLM(g,allow_free_fallback=True,router_transport=free_transport)
            with self.assertRaises(ModelFailure):routed.call('gemini-3.5-flash-lite','test',role='evidence_lite')
            self.assertFalse(calls)
    def test_429_does_not_trigger_fallback(self):
        calls=[]
        def google_transport(m,p,r):raise ModelFailure('GEMINI_HTTP_429')
        def free_transport(m,p,r):calls.append(1);return {},'model',{}
        with tempfile.TemporaryDirectory() as t:
            g=Gemini(QuotaLedger(Path(t)/'l.json'),transport=google_transport,sleep=lambda _:None)
            routed=FreeFallbackLLM(g,allow_free_fallback=True,router_transport=free_transport)
            with self.assertRaises(ModelFailure):routed.call('gemini-3.8-flash','x',role='A')
            self.assertFalse(calls)
    def test_disabled_fallback_does_not_route(self):
        def google_transport(m,p,r):raise ModelFailure('GEMINI_HTTP_503')
        with tempfile.TemporaryDirectory() as t:
            g=Gemini(QuotaLedger(Path(t)/'l.json'),transport=google_transport,sleep=lambda _:None,jitter=lambda:0)
            routed=FreeFallbackLLM(g,allow_free_fallback=False,router_transport=lambda *args:({},{},{}))
            with self.assertRaises(ModelFailure):routed.call('gemini-3.8-flash','x',role='A')
            self.assertEqual(g.ledger.d['counts'].get(ROUTER_MODEL,0),0)
    def test_router_budget_fail_closed(self):
        with tempfile.TemporaryDirectory() as t:
            ledger=QuotaLedger(Path(t)/'l.json',baseline={ROUTER_MODEL:45})
            free=OpenRouterFree(ledger,[],transport=lambda *args:({'x':1},'some-model',{}),
                                pacer=RateLimiter(sleep=lambda _:None))
            with self.assertRaises(BudgetExceeded):free.call('x',role='A')
    def test_router_missing_key_fail_closed(self):
        with tempfile.TemporaryDirectory() as t:
            g=Gemini(QuotaLedger(Path(t)/'l.json'),transport=lambda *a: (_ for _ in ()).throw(ModelFailure('GEMINI_HTTP_503')),
                     sleep=lambda _:None,jitter=lambda:0)
            with patch.dict('os.environ',{'OPENROUTER_API_KEY':''}):
                routed=FreeFallbackLLM(g,allow_free_fallback=True)
                with self.assertRaises(ModelFailure) as ctx:routed.call('gemini-3.8-flash','x',role='A')
            self.assertEqual(ctx.exception.code,'NEED_OPENROUTER_API_KEY')
            self.assertEqual(g.ledger.d['counts'].get(ROUTER_MODEL,0),0)
    def test_pipeline_free_fallback_is_not_mislabeled_gemini(self):
        def google_transport(m,p,r):
            if r=='A':raise ModelFailure('GEMINI_HTTP_503')
            if r=='B':return a_reply(.66)
            if r=='check':return third_reply(.62)
            raise AssertionError(r)
        def free_transport(m,p,r):
            self.assertEqual(m,ROUTER_MODEL)
            self.assertEqual(r,'A')
            return a_reply(.64),'free/resolved-model',{'total_tokens':150}
        with tempfile.TemporaryDirectory() as t:
            g=Gemini(QuotaLedger(Path(t)/'l.json'),transport=google_transport,sleep=lambda _:None,jitter=lambda:0)
            llm=FreeFallbackLLM(g,allow_free_fallback=True,router_transport=free_transport)
            with patch('practice.run.research_question',return_value=EVIDENCE):
                result=run.evaluate_question(Q,llm,Path(t))
            self.assertEqual(result['status'],'PASS_PRACTICE_WITH_FALLBACK')
            self.assertEqual(result['aggregate_class'],'FULL_3_RESPONSE_WITH_FREE_FALLBACK')
            self.assertEqual(result['provenance_A']['provider'],'openrouter')
            self.assertEqual(result['model_A'],'free/resolved-model')
            self.assertAlmostEqual(result['aggregate']['probability'],.64)
            self.assertEqual(result['submission_count'],0)
    def test_incomplete_when_two_roles_fail(self):
        with tempfile.TemporaryDirectory() as t:
            def google_transport(m,p,r):raise ModelFailure('GEMINI_HTTP_503')
            g=Gemini(QuotaLedger(Path(t)/'l.json'),transport=google_transport,sleep=lambda _:None,jitter=lambda:0)
            llm=FreeFallbackLLM(g,allow_free_fallback=False)
            with patch('practice.run.research_question',return_value=EVIDENCE):
                res=run.evaluate_question(Q,llm,Path(t))
            self.assertEqual(res['status'],'PARTIAL_INSUFFICIENT_PRIMARY_FORECASTS')
            self.assertNotIn('aggregate',res)

if __name__=='__main__':unittest.main()
