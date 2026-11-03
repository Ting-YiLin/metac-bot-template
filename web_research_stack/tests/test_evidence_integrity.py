import unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from text_integrity import inspect_text
from archive_integrity import verify_archive_response

class TestEvidenceIntegrity(unittest.TestCase):
    def test_binary_mojibake_is_rejected(self):
        s=('valid text '+ '\ufffd'*45 + '\x00'*3 + ' some words')*50
        r=inspect_text(s);self.assertFalse(r['ok']);self.assertGreater(r['replacement_ratio'],0.01)
    def test_normal_multilingual_is_accepted(self):
        s='台灣歷史資料：法院案件進展、官方公告。'*100
        self.assertTrue(inspect_text(s)['ok'])
    def test_archive_fixed_capture_pre_t0(self):
        u='https://web.archive.org/web/20260415123000id_/https://example.org/test'
        self.assertTrue(verify_archive_response(u,u,'2026-04-30T12:00:00Z')['ok'])
    def test_redirect_to_live_is_rejected(self):
        u='https://web.archive.org/web/20260415123000id_/https://example.org/test'
        self.assertFalse(verify_archive_response(u,'https://example.org/test','2026-04-30T12:00:00Z')['ok'])
    def test_archive_redirect_to_post_t0_is_rejected(self):
        u='https://web.archive.org/web/20260415123000id_/https://example.org/test'
        v='https://web.archive.org/web/20260501123000id_/https://example.org/test'
        self.assertFalse(verify_archive_response(u,v,'2026-04-30T12:00:00Z')['ok'])
    def test_future_snapshot_is_rejected(self):
        u='https://web.archive.org/web/20260501123000id_/https://example.org/test'
        self.assertFalse(verify_archive_response(u,u,'2026-04-30T12:00:00Z')['ok'])
    def test_wrong_original_is_rejected(self):
        u='https://web.archive.org/web/20260415123000id_/https://example.org/test'
        v='https://web.archive.org/web/20260415123000id_/https://example.org/else'
        self.assertFalse(verify_archive_response(u,v,'2026-04-30T12:00:00Z')['ok'])

if __name__=='__main__': unittest.main()
