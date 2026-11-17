import datetime as dt
import sys
import unittest
from pathlib import Path
from copy import deepcopy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publish_snapshot import validate_snapshot, publish

NOW=dt.datetime(2026,11,17,9,0,tzinfo=dt.timezone.utc)

def feed():
    return {
      "schema_version":1,"scope":"AUTHENTICATED_OPEN_SLICE_ONLY_READ_ONLY_NO_SUBMISSION",
      "tournament_requested":"minibench","checked_at_utc":"2026-11-17T08:59:00Z",
      "eligible_after_status_and_deadline_check":1,"truncated":False,
      "items":[{"post_id":1,"question_id":2,"question_type":"BinaryQuestion"}]
    }

class FakeResponse:
    def __init__(self,code):self.status_code=code
    def json(self):return {"sha":"old-sha"}
class Session:
    def __init__(self):self.payload=None
    def get(self,*args,**kwargs):return FakeResponse(404)
    def put(self,*args,**kwargs):
        self.payload=kwargs.get("json")
        return FakeResponse(201)

class Tests(unittest.TestCase):
    def test_valid_fresh(self):
        self.assertIsNotNone(validate_snapshot(feed(),NOW))
    def test_wrong_tournament(self):
        f=feed();f["tournament_requested"]="bot-testing-area"
        with self.assertRaises(ValueError):validate_snapshot(f,NOW)
    def test_stale_fails(self):
        with self.assertRaises(ValueError):validate_snapshot(feed(),NOW+dt.timedelta(minutes=30))
    def test_count_mismatch_fails(self):
        f=feed();f["eligible_after_status_and_deadline_check"]=3
        with self.assertRaises(ValueError):validate_snapshot(f,NOW)
    def test_truncation_fails(self):
        f=feed();f["truncated"]=True
        with self.assertRaises(ValueError):validate_snapshot(f,NOW)
    def test_unknown_type_fails(self):
        f=feed();f["items"][0]["question_type"]="Unrecognized"
        with self.assertRaises(ValueError):validate_snapshot(f,NOW)
    def test_publish_isolation(self):
        s=Session();f=feed();original=deepcopy(f)
        o=publish(f,"fake-token","5678",session=s,now=NOW)
        self.assertEqual(o["refresh_run_id"],"5678")
        self.assertFalse(o["is_live_tournament_submission_authorized"])
        self.assertEqual(f,original)
        self.assertEqual(s.payload["branch"],"tingyi001-test-state")
    def test_missing_github_token(self):
        with self.assertRaises(RuntimeError):
            publish(feed(),"","run",session=Session(),now=NOW)

if __name__=="__main__":unittest.main()
