"""Synthetic contract tests for five MiniBench forecast formats.

Source template: Metaculus/forecasting-tools NumericDistribution,
Metaculus/metac-bot-template main_with_no_framework.py.
No platform POST is performed.
"""
import datetime as dt
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from all_types_adapter import make_api_payload,forecast_contract,forecast_format_skeleton

class BinaryQuestion: pass
class MultipleChoiceQuestion:
    options=["Alpha","Beta","Other"]
class NumericQuestion:
    lower_bound=0.0;upper_bound=100.0
    open_lower_bound=False;open_upper_bound=False
    zero_point=None;cdf_size=201
class DiscreteQuestion(NumericQuestion):
    lower_bound=0.0;upper_bound=8.0;cdf_size=9
class DateQuestion:
    lower_bound=dt.datetime(2027,1,1,tzinfo=dt.timezone.utc)
    upper_bound=dt.datetime(2027,12,31,tzinfo=dt.timezone.utc)
    open_lower_bound=False;open_upper_bound=False
    zero_point=None;cdf_size=201

def qpoints(values):
    return [{"p":p,"value":v} for p,v in zip([0.1,0.2,0.4,0.6,0.8,0.9],values)]

class Formats(unittest.TestCase):
    def test_binary(self):
        out,vec=make_api_payload({"question_type":"BinaryQuestion","p_yes":0.42},BinaryQuestion())
        self.assertEqual(out,{"probability_yes":0.42})
        self.assertEqual(vec,[0.58,0.42])
    def test_multiple_choice(self):
        out,vec=make_api_payload({"question_type":"MultipleChoiceQuestion",
                                  "option_probabilities":{"Beta":0.3,"Alpha":0.6,"Other":0.1}},
                                 MultipleChoiceQuestion())
        self.assertEqual(vec,[0.6,0.3,0.1])
        self.assertAlmostEqual(sum(out["probability_yes_per_category"].values()),1.0)
    def test_bad_multiple_choice(self):
        with self.assertRaises(ValueError):
            make_api_payload({"question_type":"MultipleChoiceQuestion",
                              "option_probabilities":{"Alpha":0.6,"Beta":0.4}},MultipleChoiceQuestion())
    def test_numeric(self):
        out,vec=make_api_payload({"question_type":"NumericQuestion",
                                  "percentiles":qpoints([10,20,40,60,80,90])},NumericQuestion())
        self.assertEqual(len(vec),201)
        self.assertEqual(out["continuous_cdf"],vec)
        self.assertAlmostEqual(vec[0],0)
        self.assertAlmostEqual(vec[-1],1)
    def test_discrete(self):
        out,vec=make_api_payload({"question_type":"DiscreteQuestion",
                                  "percentiles":qpoints([1,2,3,4,6,7])},DiscreteQuestion())
        self.assertEqual(len(vec),9)
        self.assertEqual(vec,out["continuous_cdf"])
    def test_date(self):
        values=["2027-02-01T00:00:00Z","2027-03-01T00:00:00Z",
                "2027-05-01T00:00:00Z","2027-08-01T00:00:00Z",
                "2027-10-01T00:00:00Z","2027-12-01T00:00:00Z"]
        out,vec=make_api_payload({"question_type":"DateQuestion",
                                  "percentiles":qpoints(values)},DateQuestion())
        self.assertEqual(len(vec),201)
        self.assertEqual(vec,out["continuous_cdf"])
        self.assertEqual(vec[0],0.0)
        self.assertEqual(vec[-1],1.0)
    def test_bad_percentile_order(self):
        with self.assertRaises(ValueError):
            make_api_payload({"question_type":"NumericQuestion",
                              "percentiles":qpoints([10,20,50,40,80,90])},NumericQuestion())
    def test_bad_date_timezone(self):
        bad=qpoints(["2027-01-10T00:00:00","2027-03-01T00:00:00Z",
                     "2027-05-01T00:00:00Z","2027-08-01T00:00:00Z",
                     "2027-10-01T00:00:00Z","2027-12-01T00:00:00Z"])
        with self.assertRaises(ValueError):
            make_api_payload({"question_type":"DateQuestion","percentiles":bad},DateQuestion())
    def test_format_context(self):
        obj=forecast_format_skeleton(DiscreteQuestion())
        self.assertEqual(obj["cdf_size"],9)
        self.assertEqual(obj["lower_bound"],0.0)
    def test_missing_type_contract(self):
        with self.assertRaises(ValueError):forecast_contract({"question_type":"UnknownType"})
    def test_contract_numeric(self):
        self.assertEqual(forecast_contract({"question_type":"NumericQuestion","percentiles":[]}),"NumericQuestion")

if __name__=="__main__":unittest.main()
