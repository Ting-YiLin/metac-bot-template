"""Five-question practice pipeline; NEVER submits a forecast to Metaculus.
Execute: python -m practice.run --mode offline-test|fetch-only|live-practice|mock-live
"""
from __future__ import annotations
import argparse,datetime as dt,json,os,sys,traceback
from pathlib import Path
from practice import core,prompts
from practice.fetch import fetch_authorized,select_five
from practice.search import headlines
from practice.gemini import Gemini,QuotaLedger,ModelFailure,BudgetExceeded

ROOT=Path(__file__).resolve().parents[1]
MOCKS=ROOT/'FIXTURES'/'synthetic_practice.json'

def dump(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    tmp.replace(path)

def mocks():
    data=json.loads(MOCKS.read_text(encoding='utf-8'))
    r=[]
    for raw in data['questions']:
        q={'id':raw['id'],'source':'ORIGINAL_MOCK_NOT_METACULUS','type':raw['type'],'text':raw['text'],
           'resolution_criteria':raw['criteria'],'fine_print':'','background_info':'',
           'url':None,'post_id':None,'question_id':None,'lower_bound':None,'upper_bound':None}
        if q['type']=='multiple_choice':q['options']=['memory','logic','analog','optoelectronics']
        r.append(q)
    return r

def evaluate_question(q,gem,output_folder):
    output_folder=Path(output_folder)
    result={'question_id':q['id'],'question':q,'status':'IN_PROGRESS','safe_to_submit':False,
            'notes':['NO_METACULUS_FORECAST_POST_IN_THIS_PROGRAM'],
            'started_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'model_policy_at_start':'gemini-3.6-flash_after_prior_3.8_failure' if getattr(gem,'switch_to_36',False) else 'gemini-3.8-flash_until_failure'}
    file=output_folder/(q['id']+'.json')
    def save():dump(file,result)
    call_errors=(ModelFailure,BudgetExceeded,ValueError,TypeError,KeyError,IndexError)
    def call_primary(role,prompt):
        if getattr(gem,'switch_to_36',False):
            return core.validate_primary(gem.call('gemini-3.6-flash',prompt,role=role+'_3_6'),q)
        try:
            return core.validate_primary(gem.call('gemini-3.8-flash',prompt,role=role),q)
        except call_errors as error:
            # Switch the rest of this run to 3.6. The one fallback repeats this
            # same independent role with the same prompt, and is never retried.
            gem.switch_to_36=True
            result[role+'_3_8_error_code']=str(error)[:120]
            result['fallback_3_6_trigger_role']=role
            result['fallback_3_6_status']='IN_PROGRESS'
            save()
            try:
                value=core.validate_primary(gem.call('gemini-3.6-flash',prompt,role=role+'_fallback_3_6'),q)
            except call_errors as fallback_error:
                result['fallback_3_6_status']='FAILED'
                result['fallback_3_6_error_code']=str(fallback_error)[:120]
                result['status']='PARTIAL_3_8_AND_3_6_FAILURE'
                save()
                raise
            result['fallback_3_6_status']='SUCCESS'
            result['fallback_3_6_used_for_role']=role
            result['model_switch_triggered_this_question']=True
            save()
            return value
    def call_c(prompt):
        if getattr(gem,'switch_to_36',False):
            return core.validate_third(gem.call('gemini-3.6-flash',prompt,role='C_3_6'),q),'C_3_6'
        try:
            return core.validate_third(gem.call('gemini-3.8-flash',prompt,role='C'),q),'C'
        except call_errors as error:
            gem.switch_to_36=True
            result['C_3_8_error_code']=str(error)[:120]
            result['fallback_3_6_trigger_role']='C'
            result['fallback_3_6_status']='IN_PROGRESS'
            save()
            try:
                value=core.validate_third(gem.call('gemini-3.6-flash',prompt,role='C_fallback_3_6'),q)
            except call_errors as fallback_error:
                result['fallback_3_6_status']='FAILED'
                result['fallback_3_6_error_code']=str(fallback_error)[:120]
                result['status']='PARTIAL_3_8_AND_3_6_FAILURE'
                save()
                raise
            result['fallback_3_6_status']='SUCCESS'
            result['fallback_3_6_used_for_role']='C'
            result['model_switch_triggered_this_question']=True
            save()
            return value,'C_fallback_3_6'
    save()
    try:
        research=headlines(q)
        result['public_search']=research
        if not research['sources']:result['notes'].append('SEARCH_EMPTY_OR_UNAVAILABLE_HEADLINES_ONLY')
        save()
        evidence=gem.call('gemini-3.5-flash-lite',prompts.lite_prompt(q,research['sources']),role='evidence_lite')
        if not isinstance(evidence,dict) or not isinstance(evidence.get('summary'),str):
            raise ValueError('LITE_INVALID_EVIDENCE_STRUCTURE')
        # Important: source ids claimed by Lite must originate from retrieved RSS results
        allowed={item['source_id'] for item in research['sources']}
        for key in ('supporting','opposing'):
            ids=evidence.get(key,[])
            if not isinstance(ids,list) or any(i not in allowed for i in ids):
                raise ValueError('LITE_HALLUCINATED_SOURCE_ID_'+key)
        result['evidence_lite']=evidence;save()
        # A and B are fully independent: same frozen evidence, never see each other's answer.
        a=call_primary('A',prompts.primary_prompt(q,research['sources'],evidence,'A'))
        result['forecast_A']=a;save()
        b=call_primary('B',prompts.primary_prompt(q,research['sources'],evidence,'B'))
        result['forecast_B']=b;save()
        route=core.compare_forecasts(q,a,b)
        result['route']=route;save()
        if route['route']=='C':
            third,role=call_c(prompts.third_prompt(q,research['sources'],evidence,'C',a,b))
        else:
            role='check'
            third=core.validate_third(gem.call('gemini-3.6-flash',prompts.third_prompt(q,research['sources'],evidence,'check'),role=role),q)
        result['third_role']=role;result['forecast_third']=third;save()
        result['aggregate']=core.aggregate(q,[a,b,third]);result['complexity']=core.complexity_summary(a,b,third)
        result['status']='PASS_PRACTICE_NO_SUBMISSION' if research['sources'] else 'PARTIAL_NO_PUBLIC_SOURCES'
    except (ModelFailure,BudgetExceeded,ValueError,TypeError,KeyError,IndexError) as e:
        # Known errors have no credential-bearing body; never serialize exception tracebacks.
        if result.get('fallback_3_6_status')!='FAILED':
            result['status']='PARTIAL_'+type(e).__name__.upper()
        result['error_code']=str(e)[:120]
    except Exception as e:
        result['status']='PARTIAL_UNHANDLED_EXCEPTION'
        result['error_code']=type(e).__name__
    finally:
        result['finished_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        result['model_calls']=gem.history.copy()  # cumulative calls; full per-question delta in summary
        save()
    return result

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--mode',required=True,choices=('offline-test','fetch-only','live-practice','mock-live'))
    p.add_argument('--outdir',default=str(ROOT/'OUTPUT'))
    a=p.parse_args(argv)
    out=Path(a.outdir).resolve();out.mkdir(parents=True,exist_ok=True)
    if a.mode=='offline-test':
        from unittest import TestLoader,TextTestRunner
        suite=TestLoader().discover(str(ROOT/'tests'),pattern='test_*.py',top_level_dir=str(ROOT))
        r=TextTestRunner(verbosity=2).run(suite)
        dump(out/'STATUS.json',{'mode':a.mode,'status':'PASS' if r.wasSuccessful() else 'FAIL',
                               'tests_run':r.testsRun,'failures':len(r.failures),'errors':len(r.errors)})
        return 0 if r.wasSuccessful() else 1
    if a.mode in ('fetch-only','live-practice'):
        if not os.getenv('METACULUS_TOKEN'):
            dump(out/'STATUS.json',{'mode':a.mode,'status':'NEED_USER_AUTH','secret_name':'METACULUS_TOKEN'})
            return 2
        try:q,coverage=fetch_authorized()
        except Exception as e:
            dump(out/'STATUS.json',{'mode':a.mode,'status':'FETCH_FAILED','exception_type':type(e).__name__})
            return 3
        dump(out/'SELECTED_QUESTIONS.json',{'questions':q,'coverage':coverage,'source':'AUTHORIZED_TEST_AREA_READ_ONLY'})
        if a.mode=='fetch-only':
            status='PASS_FIVE_QUESTIONS' if len(q)==5 else 'PARTIAL_INSUFFICIENT_TEST_QUESTION_TYPES'
            dump(out/'STATUS.json',{'mode':a.mode,'status':status,'count':len(q),'coverage':coverage})
            return 0 if q else 4
    else:
        q=mocks()[:5]
        coverage={'target':'five original mocks','selected':len(q)}
        dump(out/'SELECTED_QUESTIONS.json',{'questions':q,'coverage':coverage,'source':'ORIGINAL_MOCKS_NOT_OFFICIAL'})
    if a.mode in ('live-practice','mock-live') and os.getenv('V2_FREE_TIER_CONFIRMED')!='YES':
        dump(out/'STATUS.json',{'mode':a.mode,'status':'STOP_NEED_FREE_TIER_CONFIRMATION'})
        return 5
    if not os.getenv('GEMINI_API_KEY'):
        dump(out/'STATUS.json',{'mode':a.mode,'status':'NEED_USER_AUTH','secret_name':'GEMINI_API_KEY'})
        return 2
    if os.getenv('GITHUB_ACTIONS')=='true' and os.getenv('GITHUB_RUN_ATTEMPT')!='1':
        dump(out/'STATUS.json',{'mode':a.mode,'status':'STOP_RERUN_BUDGET_REVIEW'})
        return 5
    if not q:
        dump(out/'STATUS.json',{'mode':a.mode,'status':'NO_ELIGIBLE_TEST_QUESTIONS'})
        return 4
    ledger=QuotaLedger(out/'usage_ledger.json')
    g=Gemini(ledger)
    reports=[]
    for x in q[:5]:reports.append(evaluate_question(x,g,out/'QUESTION_REPORTS'))
    completed=sum(x['status']=='PASS_PRACTICE_NO_SUBMISSION' for x in reports)
    partial=sum(x['status'].startswith('PARTIAL') for x in reports)
    summary={'mode':a.mode,'total':len(reports),'fully_completed_with_public_sources':completed,
             'partial':partial,'question_types':{k:sum(x['question']['type']==k for x in reports) for k in core.TYPES},
             'budget_utc':ledger.d,'model_call_history':g.history,
             'submission_count':0,
             'status':'PASS_PRACTICE' if completed==5 and len(q)==5 else 'PARTIAL_NEEDS_REVIEW',
             'note':'No scored Metaculus forecasts; complexity is exploratory not a correctness estimate.'}
    dump(out/'SUMMARY.json',summary);dump(out/'STATUS.json',summary)
    print('Practice:',summary['status'],'real questions:',len(q),'complete:',completed,'partial:',partial)
    return 0 if completed==5 else 6

if __name__=='__main__':sys.exit(main())
