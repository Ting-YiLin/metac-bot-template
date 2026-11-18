"""GET-only MiniBench collector. All public output is redacted.
Token is used only in the runner's memory; no probability vector, private
rationale, or bearer credential is serialized, logged, or uploaded.
"""
import csv,hashlib,json,os,sys,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
from score_core import *
API='https://www.metaculus.com/api'
CASES=[(46610,46870,'BinaryQuestion','44061634254','LEGACY_NOT_ATTESTED'),
       (46609,46869,'NumericQuestion','44066723602','LEGACY_NOT_ATTESTED'),
       (46611,46871,'BinaryQuestion','44070413407','SOL_SUBAGENT'),
       (46617,46877,'NumericQuestion','44217443215','CONTROLLER_FALLBACK')]
FIELDS=['schema_version','retrieved_at_utc','source_commit_sha','tournament','post_id','question_id','question_type','run_id',
        'forecast_author','model_attestation','platform_state','resolution_class','has_resolution','my_history_accessible',
        'historic_vector_readable','forecast_timestamp_present','forecast_valid_before_close','official_spot_peer_score',
        'official_score_source','score_status','binary_brier','binary_log_loss','multiclass_brier','multiclass_log_loss',
        'numeric_aux_score','numeric_aux_method','reason_missing','source_url','record_hash_sha256','http_status']
def now():return datetime.now(timezone.utc).isoformat()
def get_post(post,token):
    req=urllib.request.Request(f'{API}/posts/{post}/',method='GET',
          headers={'Authorization':'Token '+token,'Accept':'application/json','User-Agent':'MiniBench-Readonly-Audit/1.0'})
    with urllib.request.urlopen(req,timeout=25) as r:
        body=r.read(3000001)
        if len(body)>3000000:raise ValueError('API_BODY_TOO_LARGE')
        return json.loads(body),hashlib.sha256(body).hexdigest(),r.status
def matching_question(root,qid):
    stack=[root];matches=[];seen=0
    while stack and seen<3000:
        z=stack.pop();seen+=1
        if isinstance(z,dict):
            if z.get('id')==qid and any(k in z for k in ('my_forecasts','resolution','type')):matches.append(z)
            stack.extend(v for v in z.values() if isinstance(v,(dict,list)))
        elif isinstance(z,list):stack.extend(v for v in z if isinstance(v,(dict,list)))
    if len(matches)!=1:raise ValueError('QUESTION_NOT_FOUND_OR_AMBIGUOUS')
    return matches[0]
def get_history(q):
    own=q.get('my_forecasts')
    if not isinstance(own,dict):return None
    h=own.get('history')
    if isinstance(h,list):return h
    if isinstance(h,dict):
        for k in ('entries','forecasts','history'):
            if isinstance(h.get(k),list):return h[k]
    return None
def scalar(x):
    if isinstance(x,str):
        if x.lower()=='yes':return 1
        if x.lower()=='no':return 0
        try:return float(x)
        except ValueError:return x
    return x
def process_case(item,token,commit):
    post,qid,kind,run,author=item
    out=dict.fromkeys(FIELDS,None)
    out.update(schema_version='1.0',retrieved_at_utc=now(),source_commit_sha=commit,
               tournament='minibench',post_id=post,question_id=qid,question_type=kind,
               run_id=run,forecast_author=author,model_attestation='MODEL_ID_NOT_ATTESTED',
               source_url=f'{API}/posts/{post}/',score_status='NOT_QUERIED')
    if not token:
        out.update(score_status='BLOCKED_PRIVATE_FORECAST_ACCESS',
                   reason_missing='METACULUS_TOKEN_NOT_AVAILABLE')
        return out
    try:
        root,digest,http=get_post(post,token)
        out.update(record_hash_sha256=digest,http_status=http)
        q=matching_question(root,qid)
        state=q.get('status') or q.get('state')
        raw=q.get('resolution')
        cls,truth=norm_resolution(state,raw)
        out.update(platform_state=state,resolution_class=cls,has_resolution=raw is not None)
        history=get_history(q)
        out.update(my_history_accessible=history is not None,historic_vector_readable=False)
        # Probe historical vector in transient memory even before resolution.
        # Only status flags are persisted; probability values never leave the runner.
        if history is not None:
            hist_fore,hist_err=choose_last_before_close(history,q.get('scheduled_close_time') or q.get('close_time'))
            out['forecast_timestamp_present']=(hist_err is None)
            if hist_fore is not None and vector_valid(hist_fore.get('forecast_values'),kind):
                vector_probe=hist_fore['forecast_values']
                out['historic_vector_readable']=(kind!='BinaryQuestion' or len(vector_probe)==2)
                out['forecast_valid_before_close']=out['historic_vector_readable']
        if cls!='RESOLVED_VALID':
            out.update(score_status=cls,reason_missing='NOT_ELIGIBLE_FOR_SCORING')
            return out
        if history is None:
            out.update(score_status='BLOCKED_PRIVATE_FORECAST_ACCESS',reason_missing='HISTORY_NOT_AVAILABLE')
            return out
        f,err=choose_last_before_close(history,q.get('scheduled_close_time') or q.get('close_time'))
        if err:
            out.update(score_status=err,reason_missing=err,forecast_timestamp_present=err!='HISTORY_TIMESTAMP_MISSING')
            return out
        vector=f.get('forecast_values')
        if not vector_valid(vector,kind) or (kind=='BinaryQuestion' and len(vector)!=2):
            out.update(score_status='MISSING_FORECAST_VECTOR',reason_missing='INVALID_LENGTH_OR_SHAPE')
            return out
        out.update(historic_vector_readable=True,forecast_timestamp_present=True,forecast_valid_before_close=True)
        truth=scalar(truth)
        if kind=='BinaryQuestion':
            if truth not in (0,1):raise ValueError('UNRECOGNIZED_BINARY_TRUTH')
            out.update(binary_metrics(vector,truth))
        elif kind=='MultipleChoiceQuestion':
            opts=q.get('options')
            win=resolve_choice(raw,opts)
            if len(opts)!=len(vector):raise ValueError('OPTION_VECTOR_MISMATCH')
            out.update(choice_metrics(vector,win))
        elif kind in ('NumericQuestion','DateQuestion','DiscreteQuestion'):
            if q.get('zero_point') is not None or str(q.get('scaling','linear')).lower() not in ('linear','none'):
                raise ValueError('AUX_NOT_SUPPORTED_SCALE')
            lo=q.get('lower_bound');hi=q.get('upper_bound')
            if kind=='DateQuestion':
                lo=timestamp(lo).timestamp();hi=timestamp(hi).timestamp();truth=timestamp(truth).timestamp()
            if type(truth) not in (int,float) or type(lo) not in (int,float) or type(hi) not in (int,float):
                raise ValueError('NUMERIC_BOUNDS_OR_TRUTH_MISSING')
            out.update(numeric_aux_score=numeric_crps(vector,truth,lo,hi),
                       numeric_aux_method='LINEAR_201POINT_CDF_CRPS_APPROX_V1_NOT_OFFICIAL')
        out.update(score_status='AUX_SCORE_ONLY_OFFICIAL_SCORE_UNAVAILABLE',
                   reason_missing='OFFICIAL_SPOT_PEER_SCORE_NOT_VERIFIED')
    except urllib.error.HTTPError as e:
        out.update(http_status=e.code,score_status='HTTP_ACCESS_ERROR',reason_missing=f'HTTP_{e.code}')
    except (urllib.error.URLError,TimeoutError) as e:
        out.update(score_status='NETWORK_ERROR',reason_missing=type(e).__name__)
    except (ValueError,TypeError,KeyError,OverflowError) as e:
        out.update(score_status='UNVERIFIED_API_SCHEMA_OR_SCORE',reason_missing=str(e)[:90])
    return out
def main():
    output=Path(os.getenv('AUDIT_OUTPUT_DIR','audit_public_results'))
    output.mkdir(parents=True,exist_ok=True)
    token=os.getenv('METACULUS_TOKEN','')
    commit=os.getenv('AUDIT_SOURCE_COMMIT','1dbf44015fbba9979cf9ebe1fe2831c7dbc3dce6')
    rows=[process_case(z,token,commit) for z in CASES]
    with (output/'scoring_catalog.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    report={'schema_version':'1.0','retrieved_at_utc':now(),'source_commit_sha':commit,
            'confirmed_submission_cases':4,'history_vectors_available_in_memory':sum(z['historic_vector_readable'] is True for z in rows),
            'resolved_valid':sum(z['resolution_class']=='RESOLVED_VALID' for z in rows),
            'aux_scored':sum(z['score_status']=='AUX_SCORE_ONLY_OFFICIAL_SCORE_UNAVAILABLE' for z in rows),
            'official_spot_peer_score_count':0,
            'status_counts':{k:sum(z['score_status']==k for z in rows) for k in sorted({z['score_status'] for z in rows})},
            'no_forecast_submission':True,'raw_forecast_values_persisted':False}
    (output/'retrieval_status.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (output/'AUDIT_REPORT.md').write_text(
        '# MiniBench read-only scoring\n\n'+
        'Generated: '+report['retrieved_at_utc']+'\n\n'+
        'Recovered histories (transient): '+str(report['history_vectors_available_in_memory'])+'; '+
        'confirmed resolutions: '+str(report['resolved_valid'])+'; '+
        'aux scores: '+str(report['aux_scored'])+'; official Spot Peer: 0.\n\n'+
        'No raw forecast vectors or secrets are persisted.\n',encoding='utf-8')
    print(json.dumps({'status':'PUBLIC_REDACTED_ONLY','cases':4,'history_available':report['history_vectors_available_in_memory'],
                      'resolved':report['resolved_valid'],'official_scores':0},separators=(',',':')))
    return 0
if __name__=='__main__':sys.exit(main())
