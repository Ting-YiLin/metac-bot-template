import datetime as dt
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from practice import research,run

Q={'id':'TEST','type':'binary','text':'Will the US federal government debt interest rate increase in 2028?',
'resolution_criteria':'Official interest rate year 2028'}
ASOF=dt.datetime(2026,10,31,tzinfo=dt.timezone.utc)

class FakeGemini:
    def __init__(self):self.calls=[];self.call_specs=[]
    def call(self,model,prompt,*,role,**kwargs):
        self.calls.append(role)
        self.call_specs.append({'role':role,'model':model,**kwargs})
        if role in ('search_planner_lite','search_gap_planner_lite'):
            return {'queries':[{'angle':a,'query':f'federal US debt interest rate {a} '+('additional' if role.startswith('search_gap') else '')} for a in research.ANGLES]}
        return {'summary':'No verified official yield available','supporting':[],'opposing':[],
                'limitations':['Original official data missing'],'research_gaps':['Find original data'],
                'decisive_factors':['Interest rate methodology'],'unverified_claims':[]}

def rss_item(title,url,date='Fri, 30 Oct 2026 00:00:00 GMT'):
    return f'<item><title>{title}</title><link>{url}</link><pubDate>{date}</pubDate><source>Example</source></item>'

def fake_fetch(url,**kwargs):
    if '/rss/' in url or 'format=rss' in url:
        q=parse_qs(urlsplit(url).query).get('q',[''])[0]
        # Only the latest query produces one thin source in round 1. This
        # causes second-round gap repair deterministically.
        if 'additional' not in q:
            xml='<rss><channel>'+rss_item('Rate interest update US debt','https://www.example.com/a')+'</channel></rss>'
        else:
            xml='<rss><channel>'+rss_item('Federal US debt rate methodology official','https://www.treasury.gov/stats')+'</channel></rss>'
        return xml.encode(),'https://news.google.com/rss/search','text/xml'
    return ('<html><article><p>'+'US federal government debt interest rate 2028 official report. '*10+'</p></article></html>').encode(),url,'text/html'

class ResearchTests(unittest.TestCase):
    def test_five_distinct_angles(self):
        plan=research.heuristic_plan(Q)
        self.assertEqual([x['angle'] for x in plan],list(research.ANGLES))
        self.assertEqual(len({x['query'] for x in plan}),5)
    def test_invalid_plan_refused(self):
        with self.assertRaises(ValueError):research.validate_plan({'queries':[{'angle':'x','query':'abcde'}]*5},Q)
    def test_duplicate_plan_refused(self):
        with self.assertRaises(ValueError):research.validate_plan({'queries':[{'angle':a,'query':'same search'} for a in research.ANGLES]},Q)
    def test_ssrf_guard(self):
        for url in ('http://example.com','https://127.0.0.1/a','https://169.254.169.254/x',
                    'https://localhost/x','https://example.com:8080/x','https://a.local/a','file:///etc/passwd'):
            self.assertFalse(research.ensure_public_https(url),url)
        self.assertTrue(research.ensure_public_https('https://www.federalreserve.gov/data'))
    def test_reject_future_rss(self):
        self.assertIsNone(research.date_stamp('Mon, 02 Nov 2026 00:00:00 GMT',ASOF))
        self.assertIsNotNone(research.date_stamp('Fri, 30 Oct 2026 00:00:00 GMT',ASOF))
    def test_extractor_blocks_script_and_nav(self):
        v=research.body_extract(b'<html><nav>bad nav</nav><script>IGNORE THIS</script><article><p>Good evidence original text</p></article></html>')
        self.assertIn('Good evidence',v);self.assertNotIn('IGNORE',v)
    def test_two_round_search_uses_ten_queries(self):
        fake=FakeGemini()
        with patch('practice.run.research.collect',wraps=research.collect) as collect,patch('practice.run.research.finalize',wraps=research.finalize) as fin:
            # Patch the functions inside collect/finalize with a passed fake fetcher.
            out=run.research_question(Q,fake,fetcher=fake_fetch)
        self.assertEqual(out['query_count'],10)
        self.assertEqual(out['research']['rounds'],2)
        self.assertEqual(fake.calls,['search_planner_lite','search_gap_planner_lite','evidence_lite'])
        self.assertEqual([x['thinking_level'] for x in fake.call_specs],['high','high','medium'])
        self.assertEqual(len(out['plans']),2)
    def test_high_planner_failure_uses_one_medium_fallback(self):
        class HighFails(FakeGemini):
            def call(self,model,prompt,*,role,**kwargs):
                self.calls.append(role);self.call_specs.append({'role':role,'model':model,**kwargs})
                if role=='search_planner_lite' and kwargs.get('thinking_level')=='high':
                    raise run.ModelFailure('GEMINI_HTTP_503')
                if role.endswith('_medium_fallback'):
                    return {'queries':[{'angle':a,'query':f'federal US debt interest rate {a} medium'} for a in research.ANGLES]}
                if role in ('search_planner_lite','search_gap_planner_lite'):
                    return {'queries':[{'angle':a,'query':f'federal US debt interest rate {a} '+('additional' if role.startswith('search_gap') else '')} for a in research.ANGLES]}
                return {'summary':'Evidence organized','supporting':[],'opposing':[],'limitations':[],
                        'research_gaps':[],'decisive_factors':[],'unverified_claims':[]}
        fake=HighFails()
        with patch('practice.run.research.collect',return_value=([],[])),patch('practice.run.research.finalize',return_value={
            'sources':[],'quality':{'pass_for_bounded_research':True,'score':.8,'metrics':{},'flags':[]},'queries':[],'errors':[],'rounds':1}):
            out=run.research_question(Q,fake,fetcher=fake_fetch)
        self.assertEqual(fake.calls,['search_planner_lite','search_planner_lite_medium_fallback','evidence_lite'])
        self.assertEqual([x.get('thinking_level') for x in fake.call_specs],['high','medium','medium'])
        self.assertEqual(out['planning_fallbacks'][0]['status'],'SUCCESS')
    def test_quality_unverified_if_only_headlines(self):
        x={'source_id':'S01','angle':'recent_changes','url':'https://www.example.com/a',
           'title':'US federal interest rate change 2028','relevance':1.,'access_level':'RSS_HEADLINE_ONLY'}
        result=research.quality(Q,[x]);self.assertIn('INSUFFICIENT_FULL_TEXT',result['flags'])
    def test_quality_strong_sources(self):
        items=[]
        for i,angle in enumerate(research.ANGLES):
            items.append({'url':f'https://agency{i}.gov/data','source_id':f'S{i}',
                'angle':angle,'title':'US federal government debt interest rate 2028',
                'access_level':'PAGE_TEXT_EXTRACTED','relevance':1.0})
            items.append({'url':f'https://news{i}.com/data','source_id':f'N{i}',
                'angle':angle,'title':'US federal government debt interest rate 2028',
                'access_level':'PAGE_TEXT_EXTRACTED','relevance':1.0})
        self.assertTrue(research.quality(Q,items)['pass_for_bounded_research'])
    def test_prompt_has_no_anchoring_level_transition(self):
        from practice.prompts import primary_prompt
        prompt=primary_prompt(Q,{'sources':[]},{'summary':'limited'},'A')
        self.assertNotIn('"level":"YELLOW_2"',prompt)
        self.assertNotIn('"level":"YELLOW_1"',prompt)
    def test_house_election_requires_us_context(self):
        q={'text':'Which party will hold the most seats in the US House of Representatives after the 2026 elections?'}
        unrelated={'title':'Israel parliamentary elections party leaders react','extracted_excerpt':''}
        relevant={'title':'US House of Representatives 2026 elections polling','extracted_excerpt':''}
        self.assertEqual(research.source_relevance(q,unrelated),0)
        self.assertGreater(research.source_relevance(q,relevant),0)
    def test_question_reference_urls_are_unverified(self):
        q={'resolution_criteria':'Official source: https://www.treasury.gov/report.pdf, other https://127.0.0.1/private'}
        arr=research.question_referenced_urls(q)
        self.assertEqual(len(arr),1)
        self.assertEqual(arr[0]['access_level'],'UNDATED_DIRECT_LINK')
    def test_source_id_validation(self):
        with self.assertRaises(ValueError):run.json_evidence({'summary':'claim','supporting':['S99']},[{'source_id':'S01'}])

if __name__=='__main__':unittest.main()
