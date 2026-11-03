"""Free-search and Wayback crawler relay for independent A/C LLM experiment windows.

The worker runs no language models and makes no competition submissions.
It receives one JSON instruction and uploads actual search / archived-page results.
"""
import argparse,hashlib,json,re,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime,timezone
from common import load_json,normalize_url,ensure_public_url
from search_backends import ddgs_search
from wayback import latest_pre_t0
from crawler import Crawler
from archive_integrity import verify_archive_response
from text_integrity import inspect_text
ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN={'answer','resolution','resolved_outcome','final_answer','api_key','token','secret'}
def utc(s):
    x=datetime.fromisoformat(str(s).replace('Z','+00:00'))
    if x.tzinfo is None:x=x.replace(tzinfo=timezone.utc)
    return x.astimezone(timezone.utc)
def is_url(x):
    if not isinstance(x,str):return False
    u=urlsplit(x)
    return u.scheme in ('http','https') and bool(u.hostname) and not (u.username or u.password)
def validate(d):
    if not isinstance(d,dict) or d.get('arm') not in ('A','C') or d.get('task') not in ('search','fetch','ping'):
        raise ValueError('INVALID_ARM_OR_TASK')
    if set(d)&FORBIDDEN:raise ValueError('FORBIDDEN_ANSWER_OR_SECRET')
    if d['task']=='ping':return d
    if not re.fullmatch(r'Q0(0[1-9]|[12]\d|30)',str(d.get('case_id',''))):
        raise ValueError('ONLY_Q001_TO_Q030')
    if d.get('round') not in (1,2,3):raise ValueError('ROUND_BUDGET')
    if not str(d.get('question','')).strip():raise ValueError('QUESTION_REQUIRED')
    if not d.get('t0_utc') or utc(d['t0_utc'])>datetime.now(timezone.utc):raise ValueError('BAD_T0')
    if d['arm']=='C' and not re.fullmatch('[0-9a-f]{64}',str(d.get('rules_sha256',''))):
        raise ValueError('C_RULES_MUST_BE_FROZEN')
    if d['task']=='search':
        q=d.get('queries')
        if not isinstance(q,list) or not 1<=len(q)<=2 or any(not isinstance(s,str) or not s.strip() or len(s)>350 for s in q):
            raise ValueError('QUERY_BUDGET')
        if len(set(x.strip().casefold() for x in q))!=len(q):raise ValueError('DUPLICATE_QUERY')
    else:
        u=d.get('urls');c=d.get('search_candidate_urls')
        if not isinstance(u,list) or not 1<=len(u)<=2 or not all(map(is_url,u)):
            raise ValueError('FETCH_BUDGET')
        if not isinstance(c,list) or not 1<=len(c)<=16 or not all(map(is_url,c)):
            raise ValueError('SEARCH_CANDIDATES_REQUIRED')
        if len(set(map(normalize_url,u)))!=len(u):raise ValueError('DUPLICATE_URL')
        if not set(map(normalize_url,u)).issubset(set(map(normalize_url,c))):
            raise ValueError('URL_NOT_IN_SEARCH_CANDIDATES')
    return d
def run(d,dest):
    d=validate(d);dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    result={k:d[k] for k in ('arm','task','case_id','round','t0_utc') if k in d}
    result.update(mode='RETROSPECTIVE_DIAGNOSTIC_ONLY',is_competition_submission=False)
    t=time.monotonic()
    if d['task']=='ping':
        result['status']='PING_OK'
    elif d['task']=='search':
        results=[]
        for q in d['queries']:
            try:hits=ddgs_search(q,max_results=8);err=None
            except Exception as e:hits=[];err=type(e).__name__+':'+str(e)[:240]
            results.append({'query':q,'results':hits,'error':err,'engine':'DDGS'})
        result.update(status='SEARCH_DONE',search=results,search_hits=sum(len(r['results']) for r in results))
    else:
        cfg=load_json(ROOT/'config/default.json')
        cfg['robots_unavailable_policy']='deny';cfg['playwright_fallback']=False
        crawler=Crawler(cfg,dest/'crawl')
        records=[]
        for index,u in enumerate(d['urls'],1):
            r={'discovery_url':u,'status':'STARTED'}
            try:
                ensure_public_url(u)
                archive=latest_pre_t0(u,d['t0_utc'])
                r['archive_lookup']=archive
                if archive.get('status')!='PRE_T0_CAPTURE_FOUND':
                    r['status']='NO_PRET0_CAPTURE'
                else:
                    snap=archive.get('snapshot') or {}
                    ts=datetime.strptime(str(snap.get('timestamp','')),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
                    if ts>=utc(d['t0_utc']):
                        r['status']='NOT_STRICTLY_PRET0'
                    elif normalize_url(snap.get('original',''))!=normalize_url(u):
                        r['status']='ARCHIVE_ORIGINAL_MISMATCH'
                    else:
                        target=snap['snapshot_url']
                        f=crawler.fetch(target,source_id=d['case_id']+'_R'+str(d['round'])+'_'+str(index))
                        r['fetch']=f
                        check=verify_archive_response(target,f.get('final_url'),d['t0_utc'])
                        r['archive_integrity']=check
                        if not check['ok']:r['status']='ARCHIVE_INTEGRITY_FAILED'
                        elif f.get('fetch_status')!='READABLE_FULL':r['status']='NOT_READABLE'
                        else:
                            raw=Path(f['raw_path']).read_bytes()
                            txt=Path(f['text_path']).read_text(encoding='utf-8')
                            proof={'raw_hash_matches':hashlib.sha256(raw).hexdigest()==f['raw_sha256'],
                                   'text_hash_matches':hashlib.sha256(txt.encode()).hexdigest()==f['text_sha256'],
                                   'text_integrity':inspect_text(txt)}
                            r['content_integrity']=proof
                            r['status']='ARCHIVED_READABLE_VERIFIED' if proof['raw_hash_matches'] and proof['text_hash_matches'] and proof['text_integrity']['ok'] else 'CONTENT_INTEGRITY_FAILED'
            except Exception as e:
                r['status']='ERROR';r['error']=type(e).__name__+':'+str(e)[:300]
            records.append(r)
        result.update(status='FETCH_DONE',trials=records,verified_readable=sum(r['status']=='ARCHIVED_READABLE_VERIFIED' for r in records))
    result['elapsed_seconds']=round(time.monotonic()-t,3)
    (dest/'BRIDGE_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'case':result.get('case_id'),'search_hits':result.get('search_hits'),'verified_readable':result.get('verified_readable')},ensure_ascii=False),flush=True)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(json.loads(Path(a.request).read_text(encoding='utf-8')),a.out)
