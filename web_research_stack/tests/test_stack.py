import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from common import normalize_url
from extractors import extract_html
from ranker import rank_rows
from evidence_db import EvidenceDB

class TestStack(unittest.TestCase):
    def test_url_normalize(self):
        self.assertEqual(normalize_url('https://Example.com/a?utm_source=x&b=2#z'),'https://example.com/a?b=2')
    def test_html_extract(self):
        raw=(ROOT/'fixtures/article.html').read_bytes();text,method=extract_html(raw)
        self.assertIn('2026-09-29',text);self.assertNotIn('Menu',text)
    def test_authority_priority(self):
        rows=[{'url':'https://forum.example.com/post','title':'Exact target 4.60','snippet':'lots of keywords'}, {'url':'https://www.rba.gov.au/test','title':'Policy statement','snippet':'target'}]
        r=rank_rows(rows,'policy target 4.60',['rba.gov.au'],ROOT/'config/authority_weights.json')
        self.assertTrue(r[0]['url'].startswith('https://www.rba.gov.au'))
    def test_db(self):
        with tempfile.TemporaryDirectory() as td:
            db=EvidenceDB(Path(td)/'e.sqlite');txt='澳洲央行現金利率目標為4.60%。 Policy date 2026-09-29.'
            db.add_source({'source_id':'S1','url':'https://x','title':'t','source_type':'official','authority_score':600,'text_path':'x','retrieved_at':'now'},txt,40,5)
            hits=db.search('澳洲央行 4.60',10);self.assertTrue(hits);db.db.close()

if __name__=='__main__':unittest.main()
