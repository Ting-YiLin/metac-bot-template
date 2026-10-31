import tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from practice import run

Q={'id':'MOCK_TEST','type':'binary','text':'Will event X happen by 2027?','resolution_criteria':'Official count',
    'options':[],'lower_bound':None,'upper_bound':None,'source':'ORIGINAL_MOCK_NOT_METACULUS'}

def make_primary(p):return {'pre_complexity':{'level':'YELLOW_2','reason':'uncertain'},'prediction':{'probability':p},
                            'post_complexity':{'level':'YELLOW_1','reason':'reviewed'},'reasoning':'limited evidence'}
def third(p):return {'prediction':{'probability':p},'post_complexity':{'level':'GREEN','reason':'verified'},'reasoning':'independent evaluation'}

class FakeGemini:
    def __init__(self,a,b,fail_roles=()):self.history=[];self.a=a;self.b=b;self.fail_roles=set(fail_roles)
    def call(self,model,prompt,*,role,temperature=.3):
        self.history.append({'role':role,'model_requested':model})
        if role in self.fail_roles and not role.endswith('_fallback_3_6'):raise run.ModelFailure('GEMINI_HTTP_503')
        if role=='evidence_lite':return {'summary':'one headline','supporting':['S01'],'opposing':[], 'limitations':[]}
        if role.startswith('A'):return make_primary(self.a)
        if role.startswith('B'):return make_primary(self.b)
        return third(.52)

class PipelineTests(unittest.TestCase):
    def run_case(self,a,b,fail_roles=()):
        gem=FakeGemini(a,b,fail_roles)
        fake_search={'sources':[{'source_id':'S01','title':'Headline','url':'https://news.google.com/x'}], 'errors':[],'queries':[]}
        with tempfile.TemporaryDirectory() as d,patch('practice.run.headlines',return_value=fake_search):
            output=run.evaluate_question(Q,gem,Path(d))
            self.assertTrue((Path(d)/'MOCK_TEST.json').exists())
            self.assertFalse(output['safe_to_submit'])
        return output,gem.history
    def test_consensus_calls_3_6(self):
        output,history=self.run_case(.65,.7)
        self.assertEqual(output['status'],'PASS_PRACTICE_NO_SUBMISSION')
        self.assertEqual(output['third_role'],'check')
        self.assertEqual([z['role'] for z in history],['evidence_lite','A','B','check'])
    def test_opposition_calls_3_8_c(self):
        output,history=self.run_case(.45,.70)
        self.assertEqual(output['third_role'],'C')
        self.assertEqual([z['role'] for z in history],['evidence_lite','A','B','C'])
    def test_38_primary_failure_uses_one_36_fallback_and_stops(self):
        output,history=self.run_case(.45,.70,fail_roles=('A',))
        self.assertEqual(output['status'],'PASS_PRACTICE_NO_SUBMISSION')
        self.assertEqual(output['fallback_3_6_trigger_role'],'A')
        self.assertEqual(output['fallback_3_6_status'],'SUCCESS')
        self.assertEqual(output['fallback_3_6_used_for_role'],'A')
        self.assertEqual([z['role'] for z in history],['evidence_lite','A','A_fallback_3_6','B_3_6','C_3_6'])
        self.assertEqual([z['model_requested'] for z in history[1:]],['gemini-3.8-flash','gemini-3.6-flash','gemini-3.6-flash','gemini-3.6-flash'])
        self.assertIn('forecast_B',output)
        self.assertIn('aggregate',output)
    def test_36_switch_persists_into_next_question(self):
        gem=FakeGemini(.6,.65,fail_roles=('A',))
        fake_search={'sources':[{'source_id':'S01','title':'Headline','url':'https://news.google.com/x'}], 'errors':[],'queries':[]}
        with tempfile.TemporaryDirectory() as d,patch('practice.run.headlines',return_value=fake_search):
            run.evaluate_question(Q,gem,Path(d))
            q2=dict(Q,id='MOCK_TEST_2')
            run.evaluate_question(q2,gem,Path(d))
        second=[x for x in gem.history if x['role'] in ('evidence_lite','A_3_6','B_3_6','check')]
        self.assertEqual([x['role'] for x in second[-4:]],['evidence_lite','A_3_6','B_3_6','check'])
        self.assertTrue(all(x['model_requested']!='gemini-3.8-flash' for x in second[-3:-1]))
    def test_fetch_requires_key_and_does_not_submit(self):
        with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'METACULUS_TOKEN':''}):
            self.assertEqual(run.main(['--mode','fetch-only','--outdir',d]),2)

if __name__=='__main__':unittest.main()
