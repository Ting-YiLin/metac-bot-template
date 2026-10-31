"""V2.3 regression: 600 second timeouts and full-system reporting remain fail closed."""
import unittest
from practice.gemini import REQUEST_TIMEOUT_SECONDS, Gemini, QuotaLedger, ModelFailure
from practice.router import FreeFallbackLLM
from practice.run import system_reliability_report
import tempfile
from pathlib import Path

class V23Smoke(unittest.TestCase):
    def test_timeout_exact(self):
        self.assertEqual(REQUEST_TIMEOUT_SECONDS,600)
    def test_timeout_no_multiple_600s_retries(self):
        calls=[]
        def fail(*a):
            calls.append(1)
            raise ModelFailure('GEMINI_NETWORK_OR_PARSE_TimeoutError')
        with tempfile.TemporaryDirectory() as t:
            gem=Gemini(QuotaLedger(Path(t)/'l.json'),transport=fail,sleep=lambda _:None)
            with self.assertRaises(ModelFailure):
                gem.call('gemini-3.8-flash','x',role='A')
        self.assertEqual(len(calls),1)
    def test_report_never_approves_automated_submission(self):
        result=system_reliability_report([],[])
        self.assertEqual(result['overall_competition_readiness'],'NOT_APPROVED_FOR_AUTOMATED_SUBMISSION')
        self.assertEqual(result['submission_count'],0)

if __name__=='__main__': unittest.main()
