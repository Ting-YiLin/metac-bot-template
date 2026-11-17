"""Isolated HTTP mocks for multiple-choice, numeric, date, discrete live submission.

No Metaculus network calls; validates posting payload and exact GET roundtrip.
"""
import datetime as dt
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sealed_queue import seal,public_document
from live_submit import process_one,get_forecast_readback

TOKEN="metaculus-test-token-"+("a"*45)
NOW=dt.datetime(2026,11,17,9,40,tzinfo=dt.timezone.utc)
class Open:name="OPEN"

class Common:
    id_of_post=70000;id_of_question=70001
    state=Open()
    already_forecasted=False
    scheduled_close_time=NOW+dt.timedelta(minutes=50)
class MultipleChoiceQuestion(Common):
    options=["A","B","C"]
class NumericQuestion(Common):
    lower_bound=0.0;upper_bound=100.0
    open_lower_bound=False;open_upper_bound=False
    zero_point=None;cdf_size=201
class DiscreteQuestion(Common):
    lower_bound=0.0;upper_bound=8.0
    open_lower_bound=False;open_upper_bound=False
    zero_point=None;cdf_size=9
class DateQuestion(Common):
    lower_bound=dt.datetime(2027,1,1,tzinfo=dt.timezone.utc)
    upper_bound=dt.datetime(2027,12,31,tzinfo=dt.timezone.utc)
    open_lower_bound=False;open_upper_bound=False
    zero_point=None;cdf_size=201

class Client:
    def __init__(self,q):self.q=q
    def get_all_open_questions_from_tournament(self,tournament):
        if tournament!="minibench":raise AssertionError("wrong tournament")
        return [self.q]
class Response:
    def __init__(self,status,body):
        self.status_code=status;self.body=body
    def json(self):return self.body
class Session:
    def __init__(self,q):
        self.q=q;self.posted=False;self.expected=[];self.posts=0;self.comments=0;self.text=None
    def get(self,url,headers=None,timeout=None):
        if url.endswith("/posts/70000/"):
            value=self.expected if self.posted else None
            return Response(200,{"question":{"id":70001,"my_forecasts":{"latest":{"forecast_values":value}}}})
        if url.endswith("/comments/123/"):
            return Response(200,{"id":123,"text":self.text,"is_private":True})
        raise AssertionError("unknown GET")
    def post(self,url,headers=None,json=None,timeout=None):
        if url.endswith("/questions/forecast/"):
            self.posts+=1
            if not isinstance(json,list) or len(json)!=1 or json[0].get("question")!=70001:
                raise AssertionError("incorrect forecast API payload")
            fields=json[0]
            if "probability_yes_per_category" in fields:
                self.expected=[fields["probability_yes_per_category"][o] for o in self.q.options]
            else:
                self.expected=fields["continuous_cdf"]
            self.posted=True
            return Response(201,[{"id":1}])
        if url.endswith("/comments/create/"):
            self.comments+=1
            if json.get("is_private") is not True:
                raise AssertionError("comment not private")
            self.text=json["text"]
            return Response(201,{"id":123})
        raise AssertionError("unexpected POST")


def base(name,**extra):
    out={"schema_version":1,"scope":"MINIBENCH_WORK_LIVE_V1",
        "tournament":"minibench","mode":"LIVE","source":"work_luna_sol",
        "question_type":name,"post_id":70000,"question_id":70001,
        "reasoning":"Forecast derived from source evidence, explicit mechanism and resolution criteria.",
        "sources":["https://www.metaculus.com/api/"],
        "sol_model":"gpt-6.1-sol","sol_effort":"high","research_model":"luna-high",
        "evidence_cutoff_utc":"2026-11-17T09:30:00Z",
        "forecast_created_at_utc":"2026-11-17T09:31:00Z"}
    out.update(extra)
    return out

def points(values):
    return [{"p":p,"value":v} for p,v in zip([0.1,0.2,0.4,0.6,0.8,0.9],values)]

class Tests(unittest.TestCase):
    def go(self,q,forecast):
        client=Client(q);session=Session(q)
        r=process_one(seal(forecast,public_document(TOKEN)),client,TOKEN,NOW,session)
        self.assertEqual(r["state"],"FORECAST_AND_PRIVATE_COMMENT_CONFIRMED")
        self.assertTrue(r["forecast_confirmed"])
        self.assertTrue(r["comment_confirmed"])
        self.assertEqual(session.posts,1)
        self.assertEqual(session.comments,1)
        return r,session
    def test_multiple_choice(self):
        r,s=self.go(MultipleChoiceQuestion(),base("MultipleChoiceQuestion",
            option_probabilities={"A":0.5,"B":0.3,"C":0.2}))
        self.assertEqual(r["forecast_type"],"MultipleChoiceQuestion")
        self.assertEqual(r["readback_expected_length"],3)
        self.assertEqual(s.expected,[0.5,0.3,0.2])
    def test_numeric(self):
        r,s=self.go(NumericQuestion(),base("NumericQuestion",
            percentiles=points([10,20,40,60,80,90])))
        self.assertEqual(r["readback_expected_length"],201)
        self.assertEqual(s.expected[0],0.0)
        self.assertEqual(s.expected[-1],1.0)
    def test_discrete(self):
        r,s=self.go(DiscreteQuestion(),base("DiscreteQuestion",
            percentiles=points([1,2,3,4,6,7])))
        self.assertEqual(r["readback_expected_length"],9)
    def test_date(self):
        r,s=self.go(DateQuestion(),base("DateQuestion",percentiles=points([
            "2027-02-01T00:00:00Z","2027-03-01T00:00:00Z",
            "2027-05-01T00:00:00Z","2027-08-01T00:00:00Z",
            "2027-10-01T00:00:00Z","2027-12-01T00:00:00Z",
        ])))
        self.assertEqual(r["readback_expected_length"],201)
    def test_mismatched_type_never_posted(self):
        q=NumericQuestion();session=Session(q)
        r=process_one(seal(base("MultipleChoiceQuestion",option_probabilities={"A":1}),public_document(TOKEN)),
                      Client(q),TOKEN,NOW,session)
        self.assertEqual(session.posts,0)
        self.assertTrue(r["state"].startswith("BLOCKED"))
    def test_group_post_readback_selects_exact_subquestion(self):
        class GroupSession:
            def get(self,url,headers=None,timeout=None):
                return Response(200,{"id":70000,"group_of_questions":{"questions":[
                    {"id":99999,"my_forecasts":{"latest":{"forecast_values":[0.3,0.7]}}},
                    {"id":70001,"my_forecasts":{"latest":{"forecast_values":[0.5,0.3,0.2]}}}
                ]}})
        result=get_forecast_readback(70000,70001,[0.5,0.3,0.2],TOKEN,GroupSession())
        self.assertEqual(result["state"],"FORECAST_CONFIRMED")

    def test_invalid_distribution_never_posted(self):
        q=NumericQuestion();session=Session(q)
        r=process_one(seal(base("NumericQuestion",percentiles=points([90,80,70,60,50,40])),
                        public_document(TOKEN)),Client(q),TOKEN,NOW,session)
        self.assertEqual(r["state"],"BLOCKED_FORECAST_FORMAT")
        self.assertEqual(session.posts,0)

if __name__=="__main__":unittest.main()
