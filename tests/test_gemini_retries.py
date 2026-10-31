import tempfile,unittest
from pathlib import Path
from practice.gemini import Gemini,QuotaLedger,ModelFailure,BudgetExceeded,LIMITS

class RetryTests(unittest.TestCase):
    def setup_gem(self,func,baseline=None):
        t=tempfile.TemporaryDirectory()
        l=QuotaLedger(Path(t.name)/'ledger.json',baseline=baseline)
        return t,Gemini(l,transport=func,sleep=lambda _:None)
    def test_503_retry_and_attempt_count(self):
        calls=[]
        def f(m,p,r):
            calls.append(m)
            if len(calls)==1:raise ModelFailure('GEMINI_HTTP_503')
            return {'summary':'ok'}
        t,g=self.setup_gem(f)
        with t:
            self.assertEqual(g.call('gemini-3.8-flash','hi',role='A')['summary'],'ok')
            self.assertEqual(g.ledger.d['counts']['gemini-3.8-flash'],2)
            self.assertEqual([r['status'] for r in g.history],['FAILED','SUCCESS'])
            self.assertEqual([r['thinking_level'] for r in g.history],['high','high'])
            self.assertTrue(all(r['max_output_tokens']==32768 for r in g.history))
            self.assertTrue(all(r['latency_ms']>=0 for r in g.history))
    def test_429_not_retried(self):
        calls=[]
        def f(m,p,r):calls.append(1);raise ModelFailure('GEMINI_HTTP_429')
        t,g=self.setup_gem(f)
        with t:
            with self.assertRaises(ModelFailure):g.call('gemini-3.8-flash','hi',role='A')
            self.assertEqual(len(calls),1)
    def test_baseline_budget_no_overflow(self):
        t,g=self.setup_gem(lambda m,p,r: {'ok':1},baseline={'gemini-3.8-flash':17})
        with t:
            g.call('gemini-3.8-flash','hi',role='A')
            with self.assertRaises(BudgetExceeded):g.call('gemini-3.8-flash','hi',role='B')
    def test_no_unknown_model(self):
        t,g=self.setup_gem(lambda m,p,r:{'ok':1})
        with t:
            with self.assertRaises(ValueError):g.call('openrouter/free','hi',role='A')
    def test_explicit_high_and_usage_metadata_are_saved(self):
        t,g=self.setup_gem(lambda m,p,r:{'ok':1})
        with t:
            g=Gemini(g.ledger)
            g._request=lambda model,prompt,temperature,level,max_tokens:(
                {'ok':1},'gemini-3.8-flash-20261031',
                {'promptTokenCount':11,'candidatesTokenCount':17,'thoughtsTokenCount':23,'totalTokenCount':51},
                'response-123','STOP')
            self.assertEqual(g.call('gemini-3.8-flash','hi',role='A'),{'ok':1})
            row=g.history[-1]
            self.assertEqual(row['thinking_level'],'high')
            self.assertEqual(row['model_version'],'gemini-3.8-flash-20261031')
            self.assertEqual(row['usage']['thoughtsTokenCount'],23)
            self.assertEqual(row['usage']['totalTokenCount'],51)
            self.assertEqual(row['response_id'],'response-123')
            self.assertEqual(row['finish_reason'],'STOP')
            self.assertGreaterEqual(row['latency_ms'],0)
    def test_truncated_response_preserves_usage_and_error(self):
        t,g=self.setup_gem(lambda m,p,r:{'ok':1})
        with t:
            g=Gemini(g.ledger)
            def truncated(*args):
                raise ModelFailure('GEMINI_MAX_OUTPUT_TOKENS',model_version='gemini-3.8-flash-20261031',
                    usage={'promptTokenCount':10,'candidatesTokenCount':32768,'thoughtsTokenCount':12000,
                           'totalTokenCount':44778},response_id='truncated-1',finish_reason='MAX_TOKENS')
            g._request=truncated
            with self.assertRaises(ModelFailure):g.call('gemini-3.8-flash','hi',role='A',max_attempts=1)
            row=g.history[-1]
            self.assertEqual(row['status'],'FAILED')
            self.assertEqual(row['error_code'],'GEMINI_MAX_OUTPUT_TOKENS')
            self.assertEqual(row['usage']['thoughtsTokenCount'],12000)
            self.assertEqual(row['finish_reason'],'MAX_TOKENS')
    def test_local_budget_refusal_is_audited_as_not_sent(self):
        t,g=self.setup_gem(lambda m,p,r:{'ok':1},baseline={'gemini-3.8-flash':LIMITS['gemini-3.8-flash']})
        with t:
            with self.assertRaises(BudgetExceeded):g.call('gemini-3.8-flash','hi',role='A')
            self.assertEqual(g.history[-1]['status'],'NOT_SENT_BUDGET')
            self.assertEqual(g.history[-1]['latency_ms'],0)

if __name__=='__main__':unittest.main()
