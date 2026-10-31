"""Prompt builders. Shared evidence; isolated A and B forecasts."""
import json

def jd(o):return json.dumps(o,ensure_ascii=False,sort_keys=True,default=str)

COMPLEXITY = '''Use these fixed complexity levels: GREEN (decisive conditions clear, strong evidence),
YELLOW_1 (mostly clear; one limited decisive gap), YELLOW_2 (multiple interacting drivers or unresolved interpretations),
RED (unresolved decisive evidence, incompatible key sources, or fundamentally ambiguous resolution).
Distinguish intrinsic event uncertainty from missing evidence. Do not equate prediction confidence with complexity.
PRE = unresolved evidentiary/structural complexity before choosing a forecast. POST = complexity left after your forecast argument.
Both are tentative self-reports in a SINGLE response, not independently locked measures. Do not use complexity to adjust probability mechanically.'''

def prediction_contract(question):
    k=question['type']
    if k=='binary':return '{"probability":0.37} (number strictly between 0.001 and 0.999)'
    if k=='multiple_choice':return '{"probabilities": {option: probability, ...}} (exact provided options, nonnegative, sum 1)'
    if k=='numeric':return '{"median":number,"low_80":number,"high_80":number} (ordered 80% credible interval; honor numeric bounds)'
    return '{"median_date":"YYYY-MM-DD","low_80_date":"YYYY-MM-DD","high_80_date":"YYYY-MM-DD"} (ordered 80% credible interval; honor date bounds)'

def lite_prompt(q, sources):
    return '''You are a source-checking assistant, NOT a forecaster. Organize these factual HEADLINE/FEED snippets.
Do not invent article bodies, access, verified facts, citations or outcomes; treat a headline as headline-only evidence.
Identify decisive conditions, opposing interpretations, the original source and UTC publication date. Explicitly say if evidence is thin.
Return ONLY a JSON object with keys: summary (string <=1400 chars), supporting (array of source_ids), opposing (array of source_ids),
limitations (array of strings), research_gaps (array of strings), decisive_factors (array of strings).
Question: '''+jd(q)+'''\nRetrieved sources: '''+jd(sources)

def primary_prompt(q,sources,evidence,role):
    return '''You are FORECASTER '''+role+''' independently estimating a forecasting probability.
You have not seen any other forecaster's answer; use only the supplied question, criteria and retrieved dated sources.
Do not assume any external headline proves its full article. No external searches/tools in this step. Do not use resolved outcomes dated after the run.
'''+COMPLEXITY+'''
ONE CALL ONLY. IN THIS ORDER: (1) PRE complexity, (2) probability prediction, (3) POST complexity.
Output exactly one JSON object with keys in this order:
{"pre_complexity":{"level":"YELLOW_2","reason":"..."},"prediction":'''+prediction_contract(q)+''',"post_complexity":{"level":"YELLOW_1","reason":"..."},"reasoning":"evidence-based short rationale incl. URLs/source IDs, contrary evidence, unresolved factors"}.
Sample numeric values are syntax examples, NOT suggested forecasts.
Question: '''+jd(q)+'''\nSources (headlines only): '''+jd(sources)+'''\nEvidence organizer: '''+jd(evidence)

def third_prompt(q,sources,evidence,route,a=None,b=None):
    if route=='check':
        job='You are an INDEPENDENT evidence checker (Gemini 3.6). You must not see A/B probabilities or reasoning. Draw your own forecast.'
        other=''
    else:
        job='You are a conflict adjudicator (Gemini 3.8). A and B have conflicting predictions. Assess their opposing factual arguments and give your own numerical forecast, NOT a vote. Do not average merely to compromise.'
        other='\nLocked forecasts from A and B: '+jd({'A':a,'B':b})
    return job+'''\nReview the question and the evidence. Output exactly JSON:
{"prediction":'''+prediction_contract(q)+''',"post_complexity":{"level":"YELLOW_1","reason":"remaining evidence uncertainty AFTER this review"},"reasoning":"brief decisive evidence audit with source IDs; flag unsupported claims"}.
Complexity levels: GREEN, YELLOW_1, YELLOW_2, RED. Complexity is exploratory; do not treat it as calibrated correctness.
Question: '''+jd(q)+'''\nSources: '''+jd(sources)+'''\nEvidence: '''+jd(evidence)+other
