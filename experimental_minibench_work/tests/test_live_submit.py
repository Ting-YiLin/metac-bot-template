import datetime as dt
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sealed_queue import public_document,seal
from live_submit import validate_data,process_one

TOKEN="metaculus-test-token-"+("x"*45)
NOW=dt.datetime(2026,11,17,9,25,tzinfo=dt.timezone.utc)

class Open: name="OPEN"
class BinaryQuestion:
    id_of_post=77777
    id_of_question=88888
    state=Open()
    already_forecasted=False
    scheduled_close_time=NOW+dt.timedelta(minutes=60)
class NumericQuestion(BinaryQuestion):pass

class Client:
    def __init__(self,qs=None):
        self.qs=[BinaryQuestion()] if qs is None else qs
        self.posts=0
    def get_all_open_questions_from_tournament(self,id):
        if id!="minibench":raise AssertionError("wrong tournament")
        return self.qs
    def post_binary_question_prediction(self,question_id,prediction_in_decimal):
        self.posts+=1
        if question_id!=88888 or prediction_in_decimal!=0.40:
            raise AssertionError("posted wrong forecast")
class Response:
    def __init__(self,status_code,payload):
        self.status_code=status_code;self.payload=payload
    def json(self):return self.payload
class Session:
    def __init__(self,client):self.client=client;self.comments=0
    def get(self,url,headers=None,timeout=None):
        if "/posts/77777/" in url:
            values=[0.6,0.4] if self.client.posts else None
            return Response(200,{"question":{"id":88888,"my_forecasts":{"latest":{"forecast_values":values}}}})
        if "/comments/321/" in url:
            return Response(200,{"id":321,"text":self.text,"is_private":True})
        raise AssertionError("unexpected GET")
    def post(self,url,headers=None,json=None,timeout=None):
        if "/comments/create/" not in url or json.get("is_private") is not True:
            raise AssertionError("not a private comment")
        self.comments+=1
        self.text=json["text"]
        return Response(201,{"id":321})

def sample(**overrides):
    out={"schema_version":1,"scope":"MINIBENCH_WORK_LIVE_V1",
        "tournament":"minibench","mode":"LIVE","source":"work_luna_sol",
        "question_type":"BinaryQuestion","post_id":77777,"question_id":88888,
        "p_yes":0.40,"reasoning":"Future probability estimated from evidence and resolution clauses. Minimum reasoning length.",
        "sources":["https://example.org/source"],
        "sol_model":"gpt-6.1-sol","sol_effort":"high","research_model":"luna-high",
        "evidence_cutoff_utc":"2026-11-17T09:20:00Z",
        "forecast_created_at_utc":"2026-11-17T09:21:00Z"}
    out.update(overrides);return out

class LiveTests(unittest.TestCase):
    def test_scored_forecast_plus_private_comment_readback(self):
        c=Client();s=Session(c)
        result=process_one(seal(sample(),public_document(TOKEN)),c,TOKEN,NOW,s)
        self.assertEqual(result["state"],"FORECAST_AND_PRIVATE_COMMENT_CONFIRMED")
        self.assertEqual(c.posts,1);self.assertEqual(s.comments,1)
        self.assertTrue(result["forecast_confirmed"])
        self.assertTrue(result["comment_confirmed"])
        self.assertNotIn("0.4",str(result))
    def test_previewed_question_excluded(self):
        with self.assertRaises(ValueError):
            validate_data(sample(question_id=46868),NOW)
    def test_duplicate_account_fails_closed(self):
        q=BinaryQuestion();q.already_forecasted=True
        c=Client([q]);s=Session(c)
        result=process_one(seal(sample(),public_document(TOKEN)),c,TOKEN,NOW,s)
        self.assertEqual(c.posts,0);self.assertEqual(s.comments,0)
        self.assertEqual(result["state"],"BLOCKED_ALREADY_FORECASTED_OR_UNKNOWN")
    def test_missing_question_fails_closed(self):
        c=Client([]);s=Session(c)
        result=process_one(seal(sample(),public_document(TOKEN)),c,TOKEN,NOW,s)
        self.assertEqual(c.posts,0)
    def test_stale_forecast_rejected(self):
        c=Client();s=Session(c)
        result=process_one(seal(sample(forecast_created_at_utc="2026-11-17T06:00:00Z"),public_document(TOKEN)),c,TOKEN,NOW,s)
        self.assertEqual(c.posts,0);self.assertEqual(result["state"],"REJECTED_INPUT")
    def test_empty_rationale_rejected(self):
        with self.assertRaises(ValueError):validate_data(sample(reasoning="short"),NOW)
    def test_wrong_tournament_rejected(self):
        with self.assertRaises(ValueError):validate_data(sample(tournament="bot-testing-area"),NOW)
if __name__=="__main__":unittest.main()
