"""Offline verification of same-turn refresh bridge. No network or posting."""
import base64
import datetime as dt
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import refresh_bridge as rb

REQ="req-20261117T223355Z-v2m223355"
SHA="ef8cb4435c6f73db0ae1858c3a96c3d0bc18bbe0"
RUN=44191314564
NOW=dt.datetime(2026,11,17,22,35,tzinfo=dt.timezone.utc)

def run(status="completed",conclusion="success",sha=SHA,path=".github/workflows/experimental_minibench_readonly.yml",id=RUN):
    return {"id":id,"head_sha":sha,"event":"push",
            "head_branch":rb.BRANCH,"path":path,
            "status":status,"conclusion":conclusion}

def feed(ids=(46871,),req=REQ,runid=RUN,checked="2026-11-17T22:34:20+00:00",
         published="2026-11-17T22:34:38+00:00",expires="2026-11-17T22:54:38+00:00"):
    return {"scope":"AUTHENTICATED_OPEN_SLICE_ONLY_READ_ONLY_NO_SUBMISSION",
            "tournament_requested":"minibench","refresh_request_id":req,
            "refresh_run_id":str(runid),"refresh_trigger":"WORK_REQUEST",
            "checked_at_utc":checked,"published_at_utc":published,
            "freshness_expires_utc":expires,"truncated":False,
            "eligible_after_status_and_deadline_check":len(ids),
            "items":[{"question_id":i,"post_id":i-1,
                      "question_type":"BinaryQuestion",
                      "close_time_utc":"2026-11-17T23:10:00Z"} for i in ids]}

class FakeAPI:
    def __init__(self, sequences,feed_value):
        self.seq=list(sequences);self.feed_value=feed_value
        self.calls=[];self.iteration=0
    def __call__(self,url,params=None):
        self.calls.append((url,params))
        if url.endswith("/actions/runs"):
            n=min(self.iteration,len(self.seq)-1)
            self.iteration+=1
            return {"workflow_runs":self.seq[n]}
        if "/contents/" in url:
            contents=json.dumps(self.feed_value).encode()
            return {"content":base64.b64encode(contents).decode(),"encoding":"base64"}
        raise AssertionError("Unexpected URL:"+url)

class Tests(unittest.TestCase):
    def test_exact_success_after_run_queue_wait(self):
        api=FakeAPI([[],[run("in_progress",None)],[run()]],feed())
        with patch.object(rb,"timestamp",side_effect=rb.timestamp):
            # Patch datetime for the clock-dependent feed check, without changing
            # real time globally or using mock network.
            old=rb.evaluate_feed
            def check(f,r,id,now=None):
                return old(f,r,id,NOW)
            with patch.object(rb,"evaluate_feed",side_effect=check):
                states=[]
                for _ in range(3):
                    states.append(rb.probe_once(REQ,SHA,api)["state"])
        self.assertEqual(states,["WAIT_RUN","WAIT_REFRESH","READY"])
        self.assertEqual(api.iteration,3)
        self.assertEqual(len([x for x in api.calls if "/contents/" in x[0]]),1)

    def test_mismatched_request_or_run_does_not_accept_old_feed(self):
        self.assertEqual(rb.evaluate_feed(feed(req="req-20261117T213355Z-other12"),
                                          REQ,RUN,NOW)["state"],"WAIT_FEED")
        self.assertEqual(rb.evaluate_feed(feed(runid=RUN-1),REQ,RUN,NOW)["state"],"WAIT_FEED")

    def test_zero_candidates_only_from_verified_matching_fresh_feed(self):
        x=rb.evaluate_feed(feed(ids=()),REQ,RUN,NOW)
        self.assertEqual(x["state"],"NO_ACTION")
        self.assertEqual(x["eligible"],0)

    def test_old_or_expired_feed_never_gives_no_action(self):
        x=rb.evaluate_feed(feed(ids=(),expires="2026-11-17T22:34:50+00:00"),REQ,RUN,NOW)
        self.assertEqual(x["state"],"BLOCKED_MATCHED_FEED_EXPIRED")

    def test_fails_when_refresh_workflow_fails(self):
        x=rb.evaluate_run(run(status="completed",conclusion="failure"))
        self.assertEqual(x["state"],"BLOCKED_REFRESH_FAILED")

    def test_ignore_other_workflows_same_sha(self):
        results=[run(path=".github/workflows/experimental_minibench_work_ci.yml"),run()]
        self.assertEqual(rb.find_exact_run(results,SHA)["path"],run()["path"])

    def test_timeout_returns_explicit_not_no_action(self):
        api=FakeAPI([[],[]],feed())
        clock=[0.]
        def monotonic():
            return clock[0]
        def sleep(seconds):
            clock[0]+=seconds
        out=rb.wait(REQ,SHA,timeout_seconds=24,interval_seconds=12,
                    get_json=api,monotonic=monotonic,sleep=sleep)
        self.assertEqual(out["state"],"BLOCKED_REFRESH_TIMEOUT")
        self.assertEqual(out["checks"],3)

    def test_no_guess_when_wrong_tournament(self):
        f=feed();f["tournament_requested"]="bot-testing-area"
        with self.assertRaisesRegex(rb.BridgeError,"FEED_TOURNAMENT_MISMATCH"):
            rb.evaluate_feed(f,REQ,RUN,NOW)

    def test_bad_identifiers_rejected(self):
        with self.assertRaisesRegex(rb.BridgeError,"INVALID_REQUEST_IDENTIFIERS"):
            rb.probe_once("req-invalid",SHA,get_json=FakeAPI([[]],feed()))
        with self.assertRaisesRegex(rb.BridgeError,"INVALID_REQUEST_IDENTIFIERS"):
            rb.probe_once(REQ,"0"*15,get_json=FakeAPI([[]],feed()))

    def test_wait_feeds_mismatch_never_reports_success(self):
        api=FakeAPI([[run()]],feed(req="req-20261117T213355Z-other12"))
        clock=[0.]
        def monotonic():return clock[0]
        def sleep(s):clock[0]+=s
        out=rb.wait(REQ,SHA,timeout_seconds=12,interval_seconds=6,
                    get_json=api,monotonic=monotonic,sleep=sleep)
        self.assertEqual(out["state"],"BLOCKED_REFRESH_TIMEOUT")
        self.assertEqual(out["last_state"],"WAIT_FEED")

if __name__=="__main__":
    unittest.main()
