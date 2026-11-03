"""Independent post-search historic validation of frozen B source candidates.

This script does not call a language model, search for new URLs, or predict
outcomes. It reads only the B-frozen candidate CSV. B is not fed results back.
"""
import argparse,csv,hashlib,json,time
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path
from common import load_json,normalize_url
from wayback import latest_pre_t0
from crawler import Crawler
from archive_integrity import verify_archive_response
from text_integrity import inspect_text

ROOT=Path(__file__).resolve().parents[1]
def dt(s):
    return datetime.fromisoformat(str(s).replace("Z","+00:00")).astimezone(timezone.utc)
def run(input_csv,shard,out_dir):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    cfg=load_json(ROOT/'config/default.json')
    cfg['robots_unavailable_policy']='deny'
    cfg['playwright_fallback']=False
    rows=list(csv.DictReader(open(input_csv,encoding='utf-8-sig')))
    assert rows and all(x['case_id'].startswith('Q0') and 1<=int(x['case_id'][1:])<=30 for x in rows)
    assert all(1<=int(x['frozen_rank'])<=6 for x in rows)
    select=[x for x in rows if (int(x['case_id'][1:])-1)//10+1==shard]
    crawler=Crawler(cfg,out/'archive_bytes')
    ledger=[]
    for i,x in enumerate(select,1):
        rec={'case_id':x['case_id'],'t0_utc':x['t0_utc'],'url':x['url'],
             'rank':int(x['frozen_rank']),'origin':x['origin'],'arm_hidden':'BLIND_SOURCE',
             'status':'NOT_STARTED','verified':False}
        try:
            wb=latest_pre_t0(x['url'],x['t0_utc'],timeout=13,pause_sec=0.3)
            rec['wayback_status']=wb.get('status')
            rec['wayback_method']=wb.get('method')
            rec['wayback_error']=wb.get('error')
            if wb.get('status')!='PRE_T0_CAPTURE_FOUND':
                rec['status']='NO_PRET0_CAPTURE'
            else:
                snap=wb.get('snapshot') or {}
                rec['archive_timestamp']=snap.get('timestamp')
                rec['archive_original']=snap.get('original')
                rec['archive_url']=snap.get('snapshot_url')
                t=datetime.strptime(str(snap['timestamp']),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
                if t>=dt(x['t0_utc']):
                    rec['status']='NOT_STRICTLY_PRET0'
                elif normalize_url(snap.get('original') or '')!=normalize_url(x['url']):
                    rec['status']='ARCHIVE_ORIGINAL_MISMATCH'
                else:
                    target=snap['snapshot_url']
                    result=crawler.fetch(target,source_id=x['case_id']+'_'+str(x['frozen_rank']))
                    rec['fetch_status']=result.get('fetch_status')
                    rec['fetch_error']=result.get('error')
                    proof=verify_archive_response(target,result.get('final_url'),x['t0_utc'])
                    rec['archive_integrity']=proof
                    if not proof.get('ok'):
                        rec['status']='ARCHIVE_RESPONSE_INTEGRITY_FAILED'
                    elif result.get('fetch_status')!='READABLE_FULL':
                        rec['status']='NOT_READABLE'
                    else:
                        raw=Path(result['raw_path']).read_bytes()
                        text=Path(result['text_path']).read_text(encoding='utf-8')
                        integrity=inspect_text(text)
                        good=(hashlib.sha256(raw).hexdigest()==result['raw_sha256'] and
                              hashlib.sha256(text.encode('utf-8')).hexdigest()==result['text_sha256'] and
                              integrity['ok'])
                        rec.update(raw_sha256=result['raw_sha256'],text_sha256=result['text_sha256'],
                                   raw_bytes=len(raw),text_chars=len(text),
                                   archive_integrity=proof,text_integrity=integrity,
                                   raw_file=str(Path(result['raw_path']).relative_to(out)),
                                   text_file=str(Path(result['text_path']).relative_to(out)))
                        rec['status']='ARCHIVED_READABLE_VERIFIED' if good else 'CONTENT_INTEGRITY_FAILED'
                        rec['verified']=good
        except Exception as e:
            rec.update(status='LOOKUP_OR_FETCH_ERROR',error=type(e).__name__+':'+str(e)[:250])
        ledger.append(rec)
        print(json.dumps({'shard':shard,'case_id':rec['case_id'],'rank':rec['rank'],'status':rec['status']},ensure_ascii=False),flush=True)
    with (out/'B_HISTORY_VALIDATION.jsonl').open('w',encoding='utf8') as f:
        for x in ledger:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    summary={'shard':shard,'rows':len(ledger),'verified':sum(x['verified'] for x in ledger),
             'cases_with_verified':len(set(x['case_id'] for x in ledger if x['verified'])),
             'status_counts':dict(Counter(x['status'] for x in ledger)),
             'all_cases_in_shard':[f'Q{j:03d}' for j in range((shard-1)*10+1,shard*10+1)],
             'retrospective_discovery_diagnostic':True,
             'original_search_arm_did_not_use_crawler':True,
             'not_an_independent_semantic_review':True}
    (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print('SHARD_SUMMARY',json.dumps(summary),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True)
    p.add_argument('--shard',type=int,choices=[1,2,3],required=True)
    p.add_argument('--out',required=True)
    a=p.parse_args()
    run(a.input,a.shard,a.out)
