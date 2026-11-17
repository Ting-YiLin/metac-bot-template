import base64
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publish_live_receipt import redacted_snapshot,publish

def sample():
    return {"run_id":"44064122277","workflow":"MINIBENCH_LIVE_SCORING",
            "raw_forecasts_redacted":True,
            "processed_at_utc":"2026-11-17T10:30:00Z",
            "state":"BATCH_PROCESSED","files_seen":1,
            "entries":[{"state":"FORECAST_AND_PRIVATE_COMMENT_CONFIRMED",
                         "post_id":1,"question_id":2,"forecast_type":"DateQuestion",
                         "reasoning":"VERY_PRIVATE_TEXT",
                         "p_yes":0.62,"percentiles":[{"p":0.1,"value":33}],
                         "continuous_cdf":[0.1,0.5,0.8],
                         "comment_confirmed":True,"forecast_confirmed":True,
                         "forecast_author":"CONTROLLER_FALLBACK",
                         "subagent_call_status":"FAILED",
                         "model_attestation":"MODEL_ID_NOT_ATTESTED"}]}
class Response:
    status_code=201
class Session:
    def put(self,url,headers=None,json=None,timeout=None):
        self.path=url
        self.content=base64.b64decode(json["content"]).decode("utf-8")
        return Response()
class Tests(unittest.TestCase):
    def test_no_sensitive_fields(self):
        x=redacted_snapshot(sample(),"44064122277")
        txt=json.dumps(x)
        self.assertNotIn("VERY_PRIVATE_TEXT",txt)
        self.assertNotIn("p_yes",txt)
        self.assertNotIn("percentiles",txt)
        self.assertNotIn("continuous_cdf",txt)
        self.assertTrue(x["entries"][0]["forecast_confirmed"])
        self.assertEqual(x["entries"][0]["forecast_author"],"CONTROLLER_FALLBACK")
        self.assertEqual(x["entries"][0]["subagent_call_status"],"FAILED")
        self.assertEqual(x["entries"][0]["model_attestation"],"MODEL_ID_NOT_ATTESTED")
    def test_wrong_run_blocks(self):
        with self.assertRaises(ValueError):
            redacted_snapshot(sample(),"888888888")
    def test_publish_only_redacted(self):
        session=Session()
        path=publish(sample(),"fake-token","44064122277",session)
        self.assertEqual(path,"state/minibench_live_receipts/run-44064122277.json")
        self.assertNotIn("VERY_PRIVATE_TEXT",session.content)
        self.assertNotIn("p_yes",session.content)
if __name__=="__main__":unittest.main()
