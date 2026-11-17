"""V2 in-process multi-question batch safety and fail-continuation tests.

The live Work producer should normally queue one encrypted file per commit,
but the consumer must still handle a grouped batch without losing later
entries or reposting a duplicate question.
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import live_submit
from sealed_queue import seal,public_document

TOKEN="metaculus-test-token-"+("x"*45)


def envelope(post_id,question_id):
    doc={
        "schema_version":2,"scope":"MINIBENCH_WORK_LIVE_V1",
        "tournament":"minibench","mode":"LIVE","source":"work_luna_sol",
        "question_type":"BinaryQuestion","post_id":post_id,"question_id":question_id,
        "p_yes":0.4,
        "reasoning":"Forecast derived from the public question criteria and historical evidence.",
        "sources":["https://example.org/official-evidence"],
        "sol_model":"unavailable","sol_effort":"not_run","research_model":"luna-high-ui-selected",
        "forecast_author":"CONTROLLER_FALLBACK",
        "subagent_call_status":"FAILED","model_attestation":"MODEL_ID_NOT_ATTESTED",
        "evidence_cutoff_utc":"2026-11-17T09:19:00Z",
        "forecast_created_at_utc":"2026-11-17T09:20:00Z",
    }
    return seal(doc,public_document(TOKEN))


class BatchTests(unittest.TestCase):
    def go(self,ids,response_states):
        with tempfile.TemporaryDirectory() as temp:
            paths=[]
            for i,(pid,qid) in enumerate(ids):
                path=Path(temp)/f"sealed-{i+1:012x}.json"
                path.write_text(json.dumps(envelope(pid,qid)),encoding="utf-8")
                paths.append(path)
            receipt=Path(temp)/"receipt.json"
            calls=[]
            def fake_process(env,client,token):
                from sealed_queue import unseal
                q=unseal(env,TOKEN)
                calls.append(q["question_id"])
                state=response_states[len(calls)-1]
                return {
                    "state":state,"post_id":q["post_id"],"question_id":q["question_id"],
                    "forecast_post_attempted":state=="FORECAST_AND_PRIVATE_COMMENT_CONFIRMED",
                    "forecast_confirmed":state=="FORECAST_AND_PRIVATE_COMMENT_CONFIRMED",
                    "comment_confirmed":state=="FORECAST_AND_PRIVATE_COMMENT_CONFIRMED",
                }
            env={"BTF3_MINIBENCH_LIVE_APPROVED":"1","METACULUS_TOKEN":TOKEN,
                 "GITHUB_EVENT_NAME":"push","GITHUB_RUN_ID":"12345678"}
            with (patch.dict(os.environ,env),
                  patch.object(live_submit,"changed_files",return_value=paths),
                  patch.object(live_submit,"RECEIPT",receipt),
                  patch("forecasting_tools.MetaculusClient",return_value=object()),
                  patch.object(live_submit,"process_one",side_effect=fake_process)):
                code=live_submit.main()
            return code,json.loads(receipt.read_text(encoding="utf-8")),calls

    def test_first_question_blocks_but_next_is_attempted(self):
        code,rec,calls=self.go([(10,11),(12,13)],[
            "BLOCKED_FORECAST_FORMAT","FORECAST_AND_PRIVATE_COMMENT_CONFIRMED"])
        self.assertEqual(code,0)
        self.assertEqual(calls,[11,13])
        self.assertEqual(len(rec["entries"]),2)
        self.assertEqual(rec["entries"][1]["state"],"FORECAST_AND_PRIVATE_COMMENT_CONFIRMED")

    def test_same_question_after_one_post_is_not_repeated_in_batch(self):
        code,rec,calls=self.go([(10,11),(10,11),(12,13)],[
            "FORECAST_AND_PRIVATE_COMMENT_CONFIRMED",
            "FORECAST_AND_PRIVATE_COMMENT_CONFIRMED"])
        self.assertEqual(code,0)
        self.assertEqual(calls,[11,13])
        self.assertEqual(len(rec["entries"]),3)
        self.assertEqual(rec["entries"][1]["state"],"BLOCKED_DUPLICATE_IN_SAME_BATCH")
        self.assertFalse(rec["entries"][1]["forecast_post_attempted"])
        self.assertEqual(rec["entries"][2]["state"],"FORECAST_AND_PRIVATE_COMMENT_CONFIRMED")

if __name__=="__main__":unittest.main()
