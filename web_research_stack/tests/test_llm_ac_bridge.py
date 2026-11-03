import unittest,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from llm_ac_bridge import validate,run

def sample(task='search'):
    return {'arm':'A','task':task,'case_id':'Q001','round':1,
            'question':'Does an event happen?','t0_utc':'2026-06-01T00:00:00Z'}

class BridgeTests(unittest.TestCase):
    def assert_bad(self,d):
        with self.assertRaises(ValueError):validate(d)
    def test_ping(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run({'arm':'A','task':'ping'},d)['status'],'PING_OK')
    def test_search(self):
        x=sample();x['queries']=['named event docket','named event schedule'];validate(x)
    def test_query_budget(self):
        x=sample();x['queries']=['a','b','c'];self.assert_bad(x)
    def test_duplicate_queries(self):
        x=sample();x['queries']=['One',' one '];self.assert_bad(x)
    def test_answer_leak(self):
        x=sample();x.update(queries=['x'],resolution='yes');self.assert_bad(x)
    def test_no_c_without_freeze(self):
        x=sample();x.update(arm='C',queries=['x']);self.assert_bad(x)
        x['rules_sha256']='f'*64;validate(x)
    def test_fetch_budget_and_provenance(self):
        x=sample('fetch');x.update(urls=['https://example.org/a'],search_candidate_urls=['https://example.org/a']);validate(x)
        x['urls']=['https://example.org/b'];self.assert_bad(x)
    def test_case_range(self):
        x=sample();x.update(queries=['x'],case_id='Q031');self.assert_bad(x)
    def test_round_limit(self):
        x=sample();x.update(queries=['x'],round=4);self.assert_bad(x)

if __name__=='__main__':unittest.main()
