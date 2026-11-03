import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from temporal import classify_t0
from crawler import Crawler
from evidence_roles import classify_evidence_role

class Resp404:
    status_code=404
    def raise_for_status(self):return None

class TestBTF3Adaptation(unittest.TestCase):
    def cfg(self,retries=0):
        return {'user_agent':'x','per_domain_delay_sec':0,'connect_timeout_sec':1,'read_timeout_sec':1,'robots_unavailable_policy':'deny','http_retries':retries}
    def test_pre_t0_archive_is_safe(self):
        r=classify_t0(t0='2026-07-01',archive_snapshot_at='2026-06-30T12:00:00Z')
        self.assertTrue(r['t0_safe']);self.assertEqual(r['t0_status'],'PRE_T0_ARCHIVE')
    def test_official_index_only_not_safe(self):
        r=classify_t0(t0='2026-07-01',official_scraped_at='2026-06-20')
        self.assertFalse(r['t0_safe']);self.assertIn('CURRENT_CONTENT_UNVERIFIED',r['t0_status'])
    def test_robots_unavailable_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            c=Crawler(self.cfg(1),Path(td));c.session=Mock();c.session.get.side_effect=RuntimeError('offline')
            allowed,_,state=c.robots_allowed('https://8.8.8.8/path')
            self.assertFalse(allowed);self.assertTrue(state.startswith('ROBOTS_UNAVAILABLE_DENY_'))
    def test_robots_transient_failure_retries_without_weakening_policy(self):
        with tempfile.TemporaryDirectory() as td:
            c=Crawler(self.cfg(1),Path(td));c.session=Mock();c.session.get.side_effect=[RuntimeError('transient'),Resp404()]
            allowed,_,state=c.robots_allowed('https://8.8.8.8/path')
            self.assertTrue(allowed);self.assertEqual(state,'ROBOTS_404_ALLOW')

    def test_role_classifier_named_case_precedent_is_context(self):
        q='Will the U.S. Supreme Court rule that section 922(g)(3) is unconstitutional in United States v. Hemani?'
        t='SUPREME COURT OF THE UNITED STATES. UNITED STATES v. RAHIMI. The respondent challenges section 922(g)(8) as unconstitutional under the Second Amendment.'
        self.assertEqual(classify_evidence_role(q,t)['role'],'CONTEXT')
    def test_role_classifier_unrelated_same_agency_is_noise(self):
        q='Will the U.S. Supreme Court rule in favor of the FCC in FCC v. AT&T, Inc. No. 25-406?'
        t='FCC announces rules to retire copper lines and accelerate high-speed networks.'
        self.assertEqual(classify_evidence_role(q,t)['role'],'NOISE')
    def test_role_classifier_excluded_entity_is_noise(self):
        q='Will any country (excluding China, Indonesia, and the DRC) announce a critical mineral export restriction?'
        t='China announced rare earth export restrictions and critical mineral controls.'
        self.assertEqual(classify_evidence_role(q,t)['role'],'NOISE')
    def test_role_classifier_local_target_is_specific(self):
        q='Will Kevin Warsh be confirmed by the U.S. Senate as Federal Reserve Chair?'
        t='Kevin Warsh appeared before the Senate Banking Committee for his confirmation hearing. Senators will vote on the nomination.'
        self.assertEqual(classify_evidence_role(q,t)['role'],'TARGET_SPECIFIC')

if __name__=='__main__':unittest.main()
