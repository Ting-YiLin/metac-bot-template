import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import refresh_protocol as rp

NOW=dt.datetime(2026,11,17,9,0,tzinfo=dt.timezone.utc)
ID="req-20261117T090000Z-abcdef12"
class Tests(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root=Path(self.td.name)/"refresh_requests"
        self.root.mkdir()
        self.path=self.root/(ID+".json")
        self.payload={
            "schema_version":1,"request_id":ID,"source":"chatgpt_work_scheduled_forecast",
            "tournament":"minibench","intent":"READ_ONLY_REFRESH",
            "created_at_utc":"2026-11-17T09:00:00Z"}
        self.mock=patch.object(rp,"DIR",self.root)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self._write()
    def _write(self):
        self.path.write_text(json.dumps(self.payload),encoding="utf-8")
    def test_valid(self):
        self.assertEqual(rp.validate_request(self.path,NOW),ID)
    def test_wrong_tournament(self):
        self.payload["tournament"]="bot-testing-area";self._write()
        with self.assertRaises(ValueError):rp.validate_request(self.path,NOW)
    def test_submit_scope_block(self):
        self.payload["intent"]="SUBMIT";self._write()
        with self.assertRaises(ValueError):rp.validate_request(self.path,NOW)
    def test_old_request_block(self):
        with self.assertRaises(ValueError):rp.validate_request(self.path,NOW+dt.timedelta(minutes=31))
    def test_not_utc(self):
        self.payload["created_at_utc"]="2026-11-17T19:00:00+10:00";self._write()
        with self.assertRaises(ValueError):rp.validate_request(self.path,NOW)
    def test_request_id_mismatch(self):
        self.payload["request_id"]="req-20261117T090000Z-xxxxxx";self._write()
        with self.assertRaises(ValueError):rp.validate_request(self.path,NOW)
    def test_extra_keys_rejected(self):
        self.payload["submit_authorized"]=True;self._write()
        with self.assertRaises(ValueError):rp.validate_request(self.path,NOW)
if __name__=="__main__":unittest.main()
