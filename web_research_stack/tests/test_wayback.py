import sys,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wayback import latest_pre_t0

class Resp:
    def __init__(self,data):self._data=data
    def raise_for_status(self):return None
    def json(self):return self._data

class TestWayback(unittest.TestCase):
    def test_accepts_latest_pre_t0_cdx_capture(self):
        s=Mock();s.get.return_value=Resp([
            ['timestamp','original','statuscode','digest','mimetype'],
            ['20260430100000','https://example.com/x','200','ABC','text/html']
        ])
        r=latest_pre_t0('https://example.com/x','2026-04-30T12:00:00Z',session=s,pause_sec=0)
        self.assertEqual(r['status'],'PRE_T0_CAPTURE_FOUND');self.assertEqual(r['method'],'CDX')
    def test_rejects_post_t0_availability_capture(self):
        s=Mock();s.get.side_effect=[
            Resp([['timestamp','original','statuscode','digest','mimetype']]),
            Resp({'archived_snapshots':{'closest':{'available':True,'status':'200','timestamp':'20260501120000','url':'http://web.archive.org/web/20260501120000/https://example.com/'}}})
        ]
        r=latest_pre_t0('https://example.com/','2026-04-30T12:00:00Z',session=s,pause_sec=0)
        self.assertEqual(r['status'],'NO_PRE_T0_CAPTURE')

if __name__=='__main__':unittest.main()
