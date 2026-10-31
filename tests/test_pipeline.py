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
    def __init__(self,a,b):self.history=[];self.a=a;self.b=b
    def call(self,model,prompt,*,role,temperature=.3):
        self.history.append({'role':role,'model_requested':model})
        if role=='evidence_lite':return {'summary':'one headline','supporting':['S01'],'opposing':[], 'limitations':[]}
        if role=='A':return make_primary(self.a)
        if role=='B':return make_primary(self.b)
        return third(.52)

class PipelineTests(unittest.TestCase):
    def run_case(self,a,b):
        gem=FakeGemini(a,b)
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
    def test_fetch_requires_key_and_does_not_submit(self):
        with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'METACULUS_TOKEN':''}):
            self.assertEqual(run.main(['--mode','fetch-only','--outdir',d]),2)

if __name__=='__main__':unittest.main()
