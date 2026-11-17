"""No-network MiniBench intake tests; no Metaculus POST method exists."""
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from queue_dryrun import process_one

UTC=dt.timezone.utc
NOW=dt.datetime(2026,11,17,9,1,tzinfo=UTC)
PATH="experimental_minibench_work/pending/q-46608-46868-a1b2c3.json"
class Open: name="OPEN"
class BinaryQuestion:
    id_of_post=46608
    id_of_question=46868
    state=Open()
    already_forecasted=False
    scheduled_close_time=NOW+dt.timedelta(hours=1)
class NumericQuestion(BinaryQuestion):pass
class Client:
    def __init__(self,qs=None):self.qs=qs if qs is not None else [BinaryQuestion()];self.calls=[]
    def get_all_open_questions_from_tournament(self,x):
        self.calls.append(x);return self.qs

def payload(**changes):
    obj={"schema_version":1,"scope":"MINIBENCH_WORK_DRY_RUN","tournament":"minibench",
         "mode":"DRY_RUN","source":"work_luna_sol",
         "post_id":46608,"question_id":46868,"p_yes":0.32,
         "reasoning":"Long independent forecast with resolution and event direction verified.",
         "sources":["https://www.metaculus.com/questions/46608"],
         "forecast_created_at_utc":"2026-11-17T09:00:00Z",
         "evidence_cutoff_utc":"2026-11-17T08:55:00Z"}
    obj.update(changes);return obj

class QueueTests(unittest.TestCase):
    def test_valid_binary_dry_run(self):
        c=Client();r=process_one(payload(),PATH,c,NOW)
        self.assertEqual(r["status"],"PASS_DRY_RUN")
        self.assertFalse(r["submission_performed"])
        self.assertFalse(r["account_competition_admission_verified"])
        self.assertEqual(c.calls,["minibench"])
    def test_wrong_tournament(self):
        r=process_one(payload(tournament="bot-testing-area"),PATH,Client(),NOW)
        self.assertEqual(r["status"],"REJECTED")
    def test_submit_mode_blocked(self):
        r=process_one(payload(mode="LIVE"),PATH,Client(),NOW)
        self.assertEqual(r["status"],"REJECTED")
    def test_mismatch_qid_blocked(self):
        r=process_one(payload(question_id=99999),PATH,Client(),NOW)
        self.assertEqual(r["status"],"REJECTED")
    def test_closed_blocked(self):
        q=BinaryQuestion();q.scheduled_close_time=NOW-dt.timedelta(minutes=1)
        r=process_one(payload(),PATH,Client([q]),NOW)
        self.assertEqual(r["status"],"BLOCKED_CLOSE_TIME")
    def test_account_forecast_unknown(self):
        q=BinaryQuestion();q.already_forecasted=None
        r=process_one(payload(),PATH,Client([q]),NOW)
        self.assertEqual(r["status"],"BLOCKED_OPEN_OR_FORECAST_STATUS")
    def test_nonbinary_blocked(self):
        r=process_one(payload(),PATH,Client([NumericQuestion()]),NOW)
        self.assertEqual(r["status"],"BLOCKED_UNSUPPORTED_TYPE")
    def test_missing_current_question(self):
        r=process_one(payload(),PATH,Client([]),NOW)
        self.assertEqual(r["status"],"BLOCKED_NOT_FOUND_IN_CURRENT_MINIBENCH")
    def test_stale_forecast(self):
        r=process_one(payload(forecast_created_at_utc="2026-11-17T07:00:00Z"),PATH,Client(),NOW)
        self.assertEqual(r["status"],"REJECTED")
    def test_probability_range(self):
        r=process_one(payload(p_yes=1.0),PATH,Client(),NOW)
        self.assertEqual(r["status"],"REJECTED")

if __name__=="__main__": unittest.main()
