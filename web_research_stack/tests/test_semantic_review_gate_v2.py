import unittest,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from semantic_review_gate_v2 import validate_source,validate_review,paired_review_verdict
TEXT='The Supreme Court reserved judgment in the Sabarimala reference case on May 15, 2026.'
RAW=TEXT.encode('utf8')
ARCH='https://web.archive.org/web/20260515120000id_/https://example.org/case'
SRC={'case_id':'Q073','t0':'2026-05-16T16:30:23Z','original_url':'https://example.org/case',
     'snapshot_url':ARCH,'final_url':ARCH,'archive_verified':True,
     'raw_sha256':hashlib.sha256(RAW).hexdigest(),'text_sha256':hashlib.sha256(TEXT.encode()).hexdigest()}
def review(who='a',role='DIRECT_PRET0_EVENT_STATUS'):
    return {'reviewer_id':who,'case_id':'Q073','source_url':SRC['original_url'],
            'role':role,'target_entity':'Sabarimala reference','event_action':'reserved judgment',
            'event_time_scope':'by 2026-05-16','reason':'specific historic court status',
            'quotes':[TEXT]}
class SemanticReviewV2Tests(unittest.TestCase):
    def test_good(self):
        self.assertTrue(validate_source(SRC,RAW,TEXT)['ok'])
        self.assertEqual(paired_review_verdict(SRC,RAW,TEXT,review('a'),review('b'))['status'],'AGREED_REVIEW_CANDIDATE')
    def test_wrong_hash(self):
        self.assertEqual(paired_review_verdict(SRC,RAW+b'X',TEXT,review('a'),review('b'))['status'],'REJECT_SOURCE_INTEGRITY')
    def test_post_t0(self):
        u=ARCH.replace('20260515120000','20260517120000')
        bad=dict(SRC,snapshot_url=u,final_url=u)
        self.assertFalse(validate_source(bad,RAW,TEXT)['ok'])
    def test_live_redirect(self):
        self.assertFalse(validate_source(dict(SRC,final_url='https://example.org/case'),RAW,TEXT)['ok'])
    def test_wrong_original(self):
        self.assertFalse(validate_source(dict(SRC,original_url='https://example.org/unrelated'),RAW,TEXT)['ok'])
    def test_query_tamper(self):
        bad=dict(SRC,final_url=ARCH+'?q=changed')
        self.assertFalse(validate_source(bad,RAW,TEXT)['ok'])
    def test_fake_quote(self):
        r=review();r['quotes']=['This completely made up quote is absent from evidence']
        self.assertFalse(validate_review(r,SRC,TEXT)['ok'])
    def test_resolution_leak(self):
        r=review();r['resolution']=1
        self.assertFalse(validate_review(r,SRC,TEXT)['ok'])
    def test_disagreement(self):
        r=paired_review_verdict(SRC,RAW,TEXT,review('a'),review('b','BACKGROUND_OR_WRONG_EVENT'))
        self.assertEqual(r['status'],'DISAGREEMENT_REQUIRES_ADJUDICATION')
    def test_same_reviewer(self):
        self.assertEqual(paired_review_verdict(SRC,RAW,TEXT,review('a'),review('a'))['status'],'REVIEWER_NOT_INDEPENDENT')
    def test_single_reviewer(self):
        self.assertEqual(paired_review_verdict(SRC,RAW,TEXT,review('a'),None)['status'],'NEED_TWO_INDEPENDENT_REVIEWS')
if __name__=='__main__':unittest.main()
