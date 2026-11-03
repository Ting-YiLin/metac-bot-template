import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from temporal import classify_t0
from crawler import Crawler

class TestBTF3Adaptation(unittest.TestCase):
    def test_pre_t0_archive_is_safe(self):
        r=classify_t0(t0='2026-07-01',archive_snapshot_at='2026-06-30T12:00:00Z')
        self.assertTrue(r['t0_safe']);self.assertEqual(r['t0_status'],'PRE_T0_ARCHIVE')
    def test_official_index_only_not_safe(self):
        r=classify_t0(t0='2026-07-01',official_scraped_at='2026-06-20')
        self.assertFalse(r['t0_safe']);self.assertIn('CURRENT_CONTENT_UNVERIFIED',r['t0_status'])
    def test_robots_unavailable_fail_closed(self):
        cfg={'user_agent':'x','per_domain_delay_sec':0,'connect_timeout_sec':1,'read_timeout_sec':1,'robots_unavailable_policy':'deny'}
        with tempfile.TemporaryDirectory() as td:
            c=Crawler(cfg,Path(td));c.session=Mock();c.session.get.side_effect=RuntimeError('offline')
            allowed,_,state=c.robots_allowed('https://8.8.8.8/path')
            self.assertFalse(allowed);self.assertTrue(state.startswith('ROBOTS_UNAVAILABLE_DENY_'))

if __name__=='__main__':unittest.main()
