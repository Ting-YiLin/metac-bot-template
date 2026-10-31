import unittest,tempfile,pathlib
from practice.gemini import Gemini,QuotaLedger,ModelFailure,BudgetExceeded,LIMITS

class BudgetTests(unittest.TestCase):
    def test_separate_roles_and_reservation(self):
        with tempfile.TemporaryDirectory() as d:
            l=QuotaLedger(pathlib.Path(d)/'ledger.json')
            g=Gemini(l,transport=lambda m,p,r:{'ok':True})
            g.call('gemini-3.8-flash','x',role='A')
            g.call('gemini-3.8-flash','x',role='B')
            self.assertEqual(l.d['counts']['gemini-3.8-flash'],2)
            self.assertEqual([z['role'] for z in g.history],['A','B'])
            self.assertTrue((pathlib.Path(d)/'ledger.json').exists())
    def test_unknown_model_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            g=Gemini(QuotaLedger(pathlib.Path(d)/'ledger.json'),transport=lambda m,p,r:{})
            with self.assertRaises(ValueError):g.call('gemini-4-argon','x',role='TEST')
    def test_budget_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            l=QuotaLedger(pathlib.Path(d)/'ledger.json')
            for _ in range(LIMITS['gemini-3.8-flash']):l.reserve('gemini-3.8-flash')
            with self.assertRaises(BudgetExceeded):l.reserve('gemini-3.8-flash')

if __name__=='__main__':unittest.main()
