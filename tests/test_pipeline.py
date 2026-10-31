import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from practice import run

Q={'id':'MOCK_TEST','type':'binary','text':'Will the Federal Reserve reduce interest rates by 2027?',
   'resolution_criteria':'Federal Reserve FOMC rate','options':[],'lower_bound':None,'upper_bound':None,'source':'ORIGINAL_MOCK'}

def primary(p):return {'pre_complexity':{'level':'RED','reason':'material ambiguity'},
 'prediction':{'probability':p},'post_complexity':{'level':'RED','reason':'still ambiguous'},'reasoning':'Missing official evidence'}
def third(p):return {'prediction':{'probability':p},'post_complexity':{'level':'RED','reason':'third assessment'},'reasoning':'independent review'}

class FakeGemini:
    def __init__(self,a,b,fail_roles=()):self.history=[];self.a=a;self.b=b;self.fail_roles=set(fail_roles)
    def call(self,model,prompt,*,role,**kwargs):
        self.history.append({'role':role,'model_requested':model})
        if role in self.fail_roles:raise run.ModelFailure('GEMINI_HTTP_503')
        if role.startswith('A'):return primary(self.a)
        if role.startswith('B'):return primary(self.b)
        return third(.52)

STUB={'research':{'quality':{'pass_for_bounded_research':True,'score':0.9,'metrics':{},'flags':[]},
                  'sources':[{'source_id':'S01','title':'FOMC press release','url':'https://www.federalreserve.gov/x',
                              'access_level':'PAGE_TEXT_EXTRACTED'}], 'queries':[], 'errors':[]},
      'evidence_lite':{'summary':'Original release','supporting':['S01'],'opposing':[],
                       'limitations':[],'research_gaps':[],'decisive_factors':[],'quality_conclusion':'SUFFICIENT_FOR_EXPLORATORY_FORECAST'}}

class PipelineTests(unittest.TestCase):
    def run_case(self,a,b,fail_roles=()):
        gem=FakeGemini(a,b,fail_roles)
        with tempfile.TemporaryDirectory() as d,patch('practice.run.research_question',return_value=STUB):
            output=run.evaluate_question(Q,gem,Path(d))
            self.assertTrue((Path(d)/'MOCK_TEST.json').exists())
            self.assertFalse(output['safe_to_submit']);self.assertEqual(output['submission_count'],0)
        return output,gem.history
    def test_consensus_calls_36(self):
        out,h=self.run_case(.65,.70)
        self.assertEqual(out['status'],'PASS_PRACTICE_NO_SUBMISSION')
        self.assertEqual([z['role'] for z in h],['A','B','check'])
    def test_conflict_calls_38(self):
        out,h=self.run_case(.45,.70)
        self.assertEqual(out['route']['route'],'C')
        self.assertEqual([z['model_requested'] for z in h],['gemini-3.8-flash']*3)
    def test_38_failure_never_silently_promotes_36_to_primary(self):
        out,h=self.run_case(.46,.75,fail_roles=('A',))
        self.assertEqual(out['status'],'PARTIAL_INSUFFICIENT_PRIMARY_FORECASTS')
        self.assertEqual([z['role'] for z in h],['A','B'])
        self.assertEqual(h[-1]['model_requested'],'gemini-3.8-flash')
    def test_third_failure_keeps_two_forecasts(self):
        out,h=self.run_case(.60,.65,fail_roles=('check',))
        self.assertEqual(out['status'],'PARTIAL_TWO_MODEL_AGGREGATE')
        self.assertEqual(out['aggregate_class'],'DEGRADED_2_MODEL')
        self.assertEqual(out['aggregate_model_count'],2)
        self.assertAlmostEqual(out['aggregate']['probability'],.625)
    def test_one_valid_forecast_not_marked_aggregate(self):
        out,h=self.run_case(.60,.65,fail_roles=('B',))
        self.assertEqual(out['status'],'PARTIAL_INSUFFICIENT_PRIMARY_FORECASTS')
        self.assertNotIn('aggregate',out)
    def test_fetch_authorization_gate(self):
        with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'V21_AUTHORIZED_METACULUS_DATA_USE':'NO'}):
            rc=run.main(['--mode','fetch-only','--outdir',d])
            self.assertEqual(rc,5)
    def test_live_requires_explicit_meter_baseline(self):
        with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'GITHUB_ACTIONS':'true','GITHUB_RUN_ATTEMPT':'1',
            'GITHUB_REPOSITORY':'Ting-YiLin/metac-bot-template','V21_AUTHORIZED_METACULUS_DATA_USE':'YES',
            'V21_FREE_TIER_CONFIRMED':'YES','GEMINI_API_KEY':'MOCK-NOT-USED',
            'V21_ALREADY_USED_38':'NOT_CHECKED','V21_ALREADY_USED_LITE':'NOT_CHECKED',
            'V21_ALREADY_USED_36':'NOT_CHECKED'}):
            self.assertEqual(run.main(['--mode','research-only','--outdir',d]),5)

if __name__=='__main__':unittest.main()
