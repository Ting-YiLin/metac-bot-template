import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from route_quality import route_specificity,candidate_relevance,url_date_relation

Q1="Will SpaceX's Starship Flight 12 launch by May 31, 2026?"
Q2="Will Trump Media & Technology Group complete its digital token distribution?"
Q3="Will the Musk v. Altman trial result in a jury verdict or settlement?"

class TestRouteQuality(unittest.TestCase):
    def s(self,url,q):return route_specificity({'url':url},q)['score']
    def test_specific_launch_record_beats_homepage(self):
        self.assertGreater(self.s('https://nextspaceflight.com/launches/details/8002/',Q1),self.s('https://space.com/',Q1))
    def test_issuer_query_beats_generic_ir_landing(self):
        self.assertGreater(self.s('https://sec.gov/cgi-bin/browse-edgar?action=getcompany&company=trump+media&type=8-K',Q2),self.s('https://ir.tmtgcorp.com/news-events/press-releases/',Q2))
    def test_specific_docket_beats_generic_jury_help(self):
        self.assertGreater(self.s('https://courtlistener.com/docket/69013420/musk-v-altman/',Q3),self.s('https://uscourts.gov/court-programs/jury-service',Q3))
    def test_post_t0_explicit_date_is_detected(self):
        r=url_date_relation('https://x.test/story-2026-05-22/','2026-05-03T10:00:00Z')
        self.assertEqual(r['status'],'POST_T0_EXPLICIT_URL_DATE')
    def test_excluded_entity_is_penalized(self):
        q='Will any country (excluding China, Indonesia, and the DRC) announce a critical mineral export restriction?'
        bad=candidate_relevance({'url':'https://x.test/indonesia-critical-mineral-export','title':'Indonesia critical mineral export','snippet':''},q)
        good=candidate_relevance({'url':'https://x.test/australia-critical-mineral-export','title':'Australia critical mineral export','snippet':''},q)
        self.assertLess(bad['score'],good['score'])

if __name__=='__main__':unittest.main()
