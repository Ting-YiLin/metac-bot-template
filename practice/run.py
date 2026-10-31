"""FutureEval V2.1: read-only five-question search experiment and probabilistic forecast.
No Metaculus posting anywhere. Never modify live competition workflow.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
from practice import core,prompts,research
from practice.fetch import fetch_authorized
from practice.gemini import Gemini,QuotaLedger,ModelFailure,BudgetExceeded,LIMITS

ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'FIXTURES/official_5_previous_run.json'
MOCK=ROOT/'FIXTURES/synthetic_practice.json'


def dump(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');tmp.replace(path)


def load_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def load_questions(dataset,*,count=5):
    if dataset=='previous-five':
        v=load_json(CAPTURE)
        if len(v['questions'])!=5:raise ValueError('CAPTURE_MUST_BE_FIVE')
        return v['questions'][:count],{'source':'FROZEN_PREVIOUS_5_AUTHORIZED_TEST_AREA','coverage':v.get('coverage')}
    if dataset=='authorized-live':
        if not os.getenv('METACULUS_TOKEN'):raise ValueError('NEED_METACULUS_TOKEN')
        q,cov=fetch_authorized()
        return q[:count],{'source':'AUTHORIZED_TEST_AREA_READ_ONLY','coverage':cov}
    v=load_json(MOCK)
    q=[]
    for raw in v['questions'][:count]:
        q.append({'id':raw['id'],'source':'ORIGINAL_SYNTHETIC','type':raw['type'],
                  'text':raw['text'],'resolution_criteria':raw.get('criteria',''),
                  'fine_print':'','background_info':'','post_id':None,'question_id':None,
                  'lower_bound':None,'upper_bound':None,'options':raw.get('options',[])})
    return q,{'source':'ORIGINAL_SYNTHETIC'}


def json_evidence(obj,sources):
    if not isinstance(obj,dict) or not isinstance(obj.get('summary'),str):
        raise ValueError('LITE_INVALID_EVIDENCE_OBJECT')
    valid={s['source_id'] for s in sources}
    out={k:obj.get(k,[]) for k in ('supporting','opposing','limitations','research_gaps','decisive_factors','unverified_claims')}
    for k,v in out.items():
        if not isinstance(v,list) or len(v)>20:raise ValueError('LITE_INVALID_LIST_'+k)
        if k in ('supporting','opposing') and any(x not in valid for x in v):
            raise ValueError('LITE_HALLUCINATED_SOURCE_ID_'+k)
        if k not in ('supporting','opposing') and any(not isinstance(x,str) for x in v):
            raise ValueError('LITE_INVALID_TEXT_'+k)
    return {'summary':obj['summary'][:1700],**out,
            'quality_conclusion':obj.get('quality_conclusion','UNSPECIFIED')}


def research_question(q,gem,*,on_progress=None,fetcher=research.fetch_url):
    """1 Lite planner, 5 parallel angle searches; optional followup Lite planner + 5 searches;
1 Lite final factual organizer. No fabricated retrieval in case planners fail.
    """
    log={'status':'IN_PROGRESS','strategy':'ADAPTIVE_FIVE_ANGLES_TWO_ROUNDS',
         'max_query_count':10,'max_rounds':2,'call_roles':[], 'planner_errors':[]}
    def save():
        if on_progress:on_progress(dict(log))
    def plan(followup=False, prior=(),quality=None):
        role='search_gap_planner_lite' if followup else 'search_planner_lite'
        prompt=prompts.planner_prompt(q,previous=prior,quality=quality)
        try:
            obj=gem.call('gemini-3.5-flash-lite',prompt,role=role,thinking_level='high',max_attempts=1)
            queries=research.validate_plan(obj,q,previous=prior)
            log['call_roles'].append(role)
            return queries
        except (ModelFailure,BudgetExceeded,ValueError,TypeError) as e:
            high_error={'role':role,'thinking_level':'high','error_type':type(e).__name__,'error_code':str(e)[:80]}
            log['planner_errors'].append(high_error)
            # A high-level planner gets one medium-level fallback, never a third request.
            # A local budget stop or HTTP 429 is not retried at another thinking level.
            blocked=isinstance(e,BudgetExceeded) or str(e).startswith('GEMINI_HTTP_429')
            if not blocked:
                try:
                    obj=gem.call('gemini-3.5-flash-lite',prompt,role=role+'_medium_fallback',
                                 thinking_level='medium',max_attempts=1)
                    queries=research.validate_plan(obj,q,previous=prior)
                    log['call_roles'].append(role+'_medium_fallback')
                    log.setdefault('planning_fallbacks',[]).append({'role':role,'from':'high','to':'medium','status':'SUCCESS'})
                    return queries
                except (ModelFailure,BudgetExceeded,ValueError,TypeError) as medium_error:
                    log['planner_errors'].append({'role':role+'_medium_fallback','thinking_level':'medium',
                        'error_type':type(medium_error).__name__,'error_code':str(medium_error)[:80]})
                    log.setdefault('planning_fallbacks',[]).append({'role':role,'from':'high','to':'medium','status':'FAILED'})
            fallback=research.heuristic_plan(q,followup=followup)
            old=set(z.lower().strip() for z in prior)
            for i,z in enumerate(fallback):
                if z['query'].lower() in old:z['query']=(z['query']+' corroboration '+str(i))[:180]
            return fallback
    p1=plan()
    log['plans']=[p1];save()
    raw,errors=research.collect(q,p1,fetcher=fetcher,round_number=1)
    raw=research.question_referenced_urls(q)+raw
    r1=research.finalize(q,raw,fetcher=fetcher,queries=p1,errors=errors)
    log['quality_after_first_round']=r1['quality'];log['query_count']=5;save()
    if not r1['quality']['pass_for_bounded_research']:
        prev=[z['query'] for z in p1]
        p2=plan(True,prev,r1['quality'])
        log['plans'].append(p2);save()
        more,errs=research.collect(q,p2,fetcher=fetcher,round_number=2)
        raw+=more;errors+=errs
        r=research.finalize(q,raw,fetcher=fetcher,rounds=2,queries=p1+p2,errors=errors)
        log['query_count']=10
    else:r=r1
    log['research']=r;log['status']='SEARCH_COMPLETE';save()
    try:
        evidence=json_evidence(gem.call('gemini-3.5-flash-lite',prompts.lite_prompt(q,r),
                                        role='evidence_lite',thinking_level='medium'),r['sources'])
        log['call_roles'].append('evidence_lite');log['evidence_lite']=evidence
    except (ModelFailure,BudgetExceeded,ValueError,TypeError) as e:
        log['evidence_error']={'type':type(e).__name__,'code':str(e)[:100]}
        log['evidence_lite']={'summary':'INSUFFICIENT_EVIDENCE: source planner output unavailable',
                              'supporting':[],'opposing':[],'limitations':['LITE_EVIDENCE_FAILED'],
                              'decisive_factors':[],'research_gaps':['LITE_EVIDENCE_FAILED'],
                              'unverified_claims':[],'quality_conclusion':'INSUFFICIENT_EVIDENCE'}
    log['status']='SEARCH_EVIDENCE_SAVED';save()
    return log


def evaluate_question(q,gem,folder,*,research_only=False,fetcher=research.fetch_url):
    out=Path(folder);out.mkdir(parents=True,exist_ok=True)
    path=out/(q['id']+'.json')
    result={'question_id':q['id'],'question':q,'status':'IN_PROGRESS',
            'safe_to_submit':False,'submission_count':0,
            'started_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'pipeline':'V21_SEARCH_ADAPTIVE'}
    hist_before=len(gem.history)
    def save():dump(path,result)
    save()
    try:
        result['research_progress']={'status':'STARTED'};save()
        res=research_question(q,gem,on_progress=lambda x:(result.update({'research_progress':x}),save()),fetcher=fetcher)
        result['public_research']=res['research'];result['evidence_lite']=res['evidence_lite']
        result['source_quality']=res['research']['quality'];save()
        if research_only:
            result['status']='PASS_RESEARCH_ONLY' if result['source_quality']['pass_for_bounded_research'] else 'PARTIAL_RESEARCH_WEAK'
            return result
        a=b=third=None
        # Distinct role output without sharing A/B reasoning with each other.
        def primary(role):
            if getattr(gem,'switch_to_36',False):model='gemini-3.6-flash'
            else:model='gemini-3.8-flash'
            prompt=prompts.primary_prompt(q,result['public_research'],result['evidence_lite'],role)
            try:
                v=gem.call(model,prompt,role=role)
                return core.validate_primary(v,q),model
            except (ModelFailure,BudgetExceeded,ValueError,TypeError,KeyError) as e:
                result[f'{role}_error']={'type':type(e).__name__,'code':str(e)[:100], 'attempted_model':model};save()
                if model=='gemini-3.8-flash' and isinstance(e,ModelFailure):
                    # A degraded-but-traceable fallback; never count it as a 3.8 result.
                    gem.switch_to_36=True
                    v=gem.call('gemini-3.6-flash',prompt,role=role+'_fallback_3_6',max_attempts=2)
                    return core.validate_primary(v,q),'gemini-3.6-flash'
                raise
        for role in ('A','B'):
            try:
                response,model=primary(role);result['forecast_'+role]=response
                result['model_'+role]=model;save()
            except (ModelFailure,BudgetExceeded,ValueError,TypeError,KeyError) as e:
                result[role+'_final_failure']={'type':type(e).__name__,'code':str(e)[:90]};save()
        a=result.get('forecast_A');b=result.get('forecast_B')
        if a is not None and b is not None:
            route=core.compare_forecasts(q,a,b);result['route']=route;save()
            try:
                route_name=route['route']
                model='gemini-3.6-flash' if route_name=='check' or getattr(gem,'switch_to_36',False) else 'gemini-3.8-flash'
                prompt=prompts.third_prompt(q,result['public_research'],result['evidence_lite'],route_name,a,b)
                third=core.validate_third(gem.call(model,prompt,role='check' if route_name=='check' else 'C'),q)
                result['forecast_third']=third;result['model_third']=model;save()
            except (ModelFailure,BudgetExceeded,ValueError,TypeError,KeyError) as e:
                result['third_failure']={'type':type(e).__name__,'code':str(e)[:90]};save()
            p=[a,b]+([third] if third else [])
            result['aggregate']=core.aggregate(q,p)
            result['aggregate_model_count']=len(p)
            result['aggregate_class']='FULL_3_MODEL' if third else 'DEGRADED_2_MODEL'
            if third:result['complexity']=core.complexity_summary(a,b,third)
            else:result['complexity']=core.complexity_summary(a,b,None)
            result['status']='PASS_PRACTICE_NO_SUBMISSION' if third else 'PARTIAL_TWO_MODEL_AGGREGATE'
        else:
            result['status']='PARTIAL_INSUFFICIENT_PRIMARY_FORECASTS'
        if not result['source_quality']['pass_for_bounded_research']:
            result['evidence_warning']='SEARCH_QUALITY_LOW_DO_NOT_ASSUME_VERIFIED'
        save()
    except (ModelFailure,BudgetExceeded,ValueError,TypeError,KeyError,IndexError) as e:
        result['status']='PARTIAL_'+type(e).__name__.upper();result['error_code']=str(e)[:90]
    except Exception as e:
        result['status']='PARTIAL_UNHANDLED_EXCEPTION';result['error_code']=type(e).__name__
    finally:
        result['model_calls']=gem.history[hist_before:]
        result['finished_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat();save()
    return result


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--mode',required=True,choices=('offline-test','fetch-only','research-only','live-practice','mock-live'))
    p.add_argument('--dataset',choices=('previous-five','authorized-live','synthetic'),default='previous-five')
    p.add_argument('--max-questions',type=int,default=5)
    p.add_argument('--outdir',default=str(ROOT/'OUTPUT'))
    args=p.parse_args(argv)
    out=Path(args.outdir).resolve();out.mkdir(parents=True,exist_ok=True)
    if not 1<=args.max_questions<=5:
        dump(out/'STATUS.json',{'status':'STOP_INVALID_QUESTION_COUNT'});return 4
    if args.mode=='offline-test':
        import unittest
        suite=unittest.TestLoader().discover(str(ROOT/'tests'),pattern='test_*.py',top_level_dir=str(ROOT))
        r=unittest.TextTestRunner(verbosity=2).run(suite)
        dump(out/'STATUS.json',{'mode':args.mode,'status':'PASS' if r.wasSuccessful() else 'FAIL',
                                'tests_run':r.testsRun,'failures':len(r.failures),'errors':len(r.errors)})
        return 0 if r.wasSuccessful() else 1
    if args.dataset!='synthetic' and os.getenv('V21_AUTHORIZED_METACULUS_DATA_USE')!='YES':
        dump(out/'STATUS.json',{'mode':args.mode,'status':'NEED_USER_DATA_AUTH_CONFIRMATION'});return 5
    try:q,provenance=load_questions(args.dataset,count=args.max_questions)
    except Exception as e:
        dump(out/'STATUS.json',{'status':'FETCH_FAILED','error_type':type(e).__name__});return 3
    dump(out/'SELECTED_QUESTIONS.json',{'questions':q,'provenance':provenance})
    if args.mode=='fetch-only':
        dump(out/'STATUS.json',{'mode':args.mode,'status':'PASS_FIVE_QUESTIONS' if len(q)==5 else 'PARTIAL_FEWER_THAN_FIVE',
                                'selected':len(q)});return 0 if q else 4
    if args.mode in ('research-only','live-practice','mock-live'):
        if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_RUN_ATTEMPT')!='1' or os.getenv('GITHUB_REPOSITORY')!='Ting-YiLin/metac-bot-template':
            dump(out/'STATUS.json',{'status':'STOP_NOT_APPROVED_FIRST_GITHUB_RUN'});return 5
        if os.getenv('V21_FREE_TIER_CONFIRMED')!='YES':
            dump(out/'STATUS.json',{'status':'STOP_FREE_TIER_CONFIRMATION_REQUIRED'});return 5
        if not os.getenv('GEMINI_API_KEY'):
            dump(out/'STATUS.json',{'status':'NEED_USER_AUTH','secret_name':'GEMINI_API_KEY'});return 2
    # Baselines must be declared from Google AI Studio before using any model quota.
    baseline={}
    try:
        for model,suffix in [('gemini-3.5-flash-lite','LITE'),('gemini-3.8-flash','38'),('gemini-3.6-flash','36')]:
            raw=os.getenv('V21_ALREADY_USED_'+suffix,'')
            if not raw.isdecimal():raise ValueError('UNDECLARED_DAILY_USAGE_'+suffix)
            n=int(raw)
            if not 0<=n<=LIMITS[model]:raise ValueError('INVALID_BASELINE_'+suffix)
            baseline[model]=n
    except ValueError as e:
        dump(out/'STATUS.json',{'status':'STOP_UNDECLARED_OR_INVALID_DAILY_BASELINE','code':str(e)});return 5
    ledger=QuotaLedger(out/'usage_ledger.json',baseline=baseline)
    gem=Gemini(ledger)
    reports=[]
    for x in q[:5]:
        reports.append(evaluate_question(x,gem,out/'QUESTION_REPORTS',research_only=args.mode=='research-only'))
        dump(out/'SUMMARY.json',{'mode':args.mode,'total':len(reports),
                                'complete':sum(z['status']=='PASS_PRACTICE_NO_SUBMISSION' for z in reports),
                                'two_model_aggregate':sum(z['status']=='PARTIAL_TWO_MODEL_AGGREGATE' for z in reports),
                                'research_complete':sum(z['status']=='PASS_RESEARCH_ONLY' for z in reports),
                                'partial':sum(z['status'].startswith('PARTIAL') for z in reports),
                                'results':[{k:z.get(k) for k in ('question_id','status','aggregate_class','source_quality')} for z in reports],
                                'quota_ledger':ledger.snapshot(),'submission_count':0})
    statuses={r['status'] for r in reports}
    code=0 if all(s in ('PASS_PRACTICE_NO_SUBMISSION','PASS_RESEARCH_ONLY') for s in statuses) else 6
    dump(out/'STATUS.json',{'status':'PASS' if code==0 else 'PARTIAL_NEEDS_REVIEW',
                            'total':len(reports),'complete':sum(r['status']=='PASS_PRACTICE_NO_SUBMISSION' for r in reports),
                            'submission_count':0,'source':'TEST_ONLY'})
    print('V21 practice:', 'PASS' if code==0 else 'PARTIAL', 'questions:',len(reports), 'submissions: 0')
    return code

if __name__=='__main__':raise SystemExit(main())
