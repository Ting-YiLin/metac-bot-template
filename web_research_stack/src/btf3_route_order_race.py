"""Paired route-order race. Retrospective discovery only, never a blind forecast."""
import argparse,csv,json,sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import load_json,normalize_url,now_iso
from btf3_t0_search_pilot import historical_queries
from search_backends import search
from ranker import rank_rows
from route_quality import url_date_relation
from wayback import latest_pre_t0
from crawler import Crawler
from archive_integrity import verify_archive_response
from text_integrity import inspect_text
from evidence_quality import evidence_relevance
from evidence_roles import classify_evidence_role

ROOT=Path(__file__).resolve().parents[1]
LABELS=('archive','readable','keyword','target_proxy')

def dedup(rows):
    ans=[];seen=set()
    for r in rows:
        try:u=normalize_url(r.get('url') or r.get('route_url') or '')
        except Exception:continue
        if not u or u in seen:continue
        seen.add(u);x=dict(r);x['url']=u;ans.append(x)
    return ans

def choose_primary_fallback(primary,fallback,primary_cap=3,fallback_cap=3):
    """Same quota rules for both orders; no hidden mixing of evidence."""
    p=dedup(primary)[:primary_cap]
    already={x['url'] for x in p}
    f=[x for x in dedup(fallback) if x['url'] not in already][:fallback_cap]
    return (p+f),len(p)

def source_outcome(rec):
    return {
        'archive':bool(rec.get('capture_found')),
        'readable':bool(rec.get('valid_readable')),
        'keyword':bool(rec.get('keyword')),
        'target_proxy':bool(rec.get('target_proxy'))
    }

def score_plan(plan,outcomes,primary_count):
    by_depth={}
    for depth in (3,6):
        prefix=plan[:depth]
        by_depth[str(depth)] = {
            'slots_used':len(prefix),
            'archive':any(outcomes.get(x['url'],{}).get('archive') for x in prefix),
            'readable':any(outcomes.get(x['url'],{}).get('readable') for x in prefix),
            'keyword':any(outcomes.get(x['url'],{}).get('keyword') for x in prefix),
            'target_proxy':any(outcomes.get(x['url'],{}).get('target_proxy') for x in prefix)
        }
    return {
        'primary_slots':primary_count,
        'by_depth':by_depth,
        'first_target_proxy_rank':next((i for i,x in enumerate(plan,1) if outcomes.get(x['url'],{}).get('target_proxy')),None),
        'plan':[{'url':x['url'],'origin':x.get('origin'),'rank':i} for i,x in enumerate(plan,1)]
    }

def calculate_summary(cases):
    summary={'questions':len(cases),'scope':'DISCOVERY_ONLY_RETROSPECTIVE',
             'claim_guard':'TARGET_SPECIFIC is an automatic topic proxy, not decisive evidence.',
             'budgets':{'primary':3,'fallback':3},
             'arms':{},'paired_differences':{},'case_ids':[x['case_id'] for x in cases]}
    for arm in ('official_first','natural_first'):
        by_depth={}
        for k in ('3','6'):
            by_depth[k]={label:sum(bool(c['arms'][arm]['by_depth'][k][label]) for c in cases) for label in LABELS}
        first=[c['arms'][arm]['first_target_proxy_rank'] for c in cases if c['arms'][arm]['first_target_proxy_rank'] is not None]
        summary['arms'][arm]={'by_depth':by_depth,'first_proxy_rank_mean':round(sum(first)/len(first),3) if first else None,
                             'questions_with_proxy':len(first)}
    for k in ('3','6'):
        summary['paired_differences'][k]={
            x:sum(int(c['arms']['official_first']['by_depth'][k][x])-int(c['arms']['natural_first']['by_depth'][k][x]) for c in cases)
            for x in LABELS
        }
    return summary

def run(cases_path,route_csv,out_dir,case_limit=10,primary_cap=3,fallback_cap=3,results_per_query=8):
    cases=json.loads(Path(cases_path).read_text(encoding='utf-8'))
    cfg=load_json(ROOT/'config/default.json')
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    official_rows=defaultdict(list)
    for row in csv.DictReader(open(route_csv,encoding='utf-8-sig')):
        official_rows[row.get('case_id','')].append(row)
    crawler=Crawler(cfg,out/'crawl')
    records=[]
    for case in cases[:int(case_limit)]:
        cid,q,t0=case['case_id'],case['question'],case['t0_utc']
        pref=case.get('preferred_domains') or []
        # Historical index observations get priority over rule-template URLs.
        official=[]
        for r in sorted(official_rows.get(cid,[]),key=lambda x:(x.get('t0_route_status')!='PRE_T0_INDEXED',int(x.get('rank') or 999))):
            status=r.get('t0_route_status')
            if status not in ('PRE_T0_INDEXED','ROUTE_TEMPLATE_ONLY'):continue
            official.append({
                'url':r['route_url'],'origin':'INDEX_PRE_T0' if status=='PRE_T0_INDEXED' else 'CRITERIA_TEMPLATE',
                'observed_at':r.get('date_scraped') or None,'rank_prior':r.get('rank')
            })
        official=dedup(official)

        queries=historical_queries(q,t0,pref)[:3]
        found=[];qlog=[]
        for query in queries:
            if not query:continue
            try:
                result=search(query,cfg['search_backend'],results_per_query,cfg.get('searxng_base_url',''))
                found.extend(result);qlog.append({'query':query,'count':len(result),'error':None})
            except Exception as e:
                qlog.append({'query':query,'count':0,'error':type(e).__name__+':'+str(e)[:200]})
        ranked=rank_rows(dedup(found),q,pref,ROOT/'config/authority_weights.json',int(cfg['per_domain_preferred_limit']))
        natural=dedup([dict(x,origin='DDGS_RETROSPECTIVE') for x in ranked])
        # Same time gate for both arms. A post-T0-dated URL is not a candidate.
        filtered={}
        for name,arr in (('official',official),('natural',natural)):
            filtered[name]=[x for x in arr if url_date_relation(x['url'],t0).get('status')!='POST_T0_EXPLICIT_URL_DATE']
        official,natural=filtered['official'],filtered['natural']
        op,on=choose_primary_fallback(official,natural,primary_cap,fallback_cap)
        np,nn=choose_primary_fallback(natural,official,primary_cap,fallback_cap)
        union=dedup(op+np)
        trials={};outcomes={}
        for i,x in enumerate(union,1):
            url=x['url']
            try:wb=latest_pre_t0(url,t0)
            except Exception as e:wb={'status':'LOOKUP_ERROR','error':type(e).__name__+':'+str(e)[:160]}
            rec={'url':url,'wayback':wb,'capture_found':False,'valid_readable':False,'keyword':False,'target_proxy':False}
            if wb.get('status')=='PRE_T0_CAPTURE_FOUND':
                snap=wb.get('snapshot') or {}
                rec['capture_found']=True
                record=crawler.fetch(snap['snapshot_url'],source_id=f'{cid}_U{i:02d}')
                proof=verify_archive_response(snap['snapshot_url'],record.get('final_url'),t0)
                rec['fetch']=record
                rec['archive_integrity']=proof
                if proof['ok'] and record.get('fetch_status')=='READABLE_FULL':
                    rawtext=Path(record['text_path']).read_text(encoding='utf-8',errors='replace')
                    textcheck=inspect_text(rawtext)
                    rec['text_integrity']=textcheck
                    if textcheck['ok']:
                        qual=evidence_relevance(q,rawtext)
                        role=classify_evidence_role(q,rawtext)
                        rec.update(valid_readable=True,keyword=qual['accepted'],
                                   target_proxy=(role['role']=='TARGET_SPECIFIC' and qual['accepted']),
                                   keyword_detail=qual,role_diagnostic=role)
            trials[url]=rec;outcomes[url]=source_outcome(rec)
        arms={'official_first':score_plan(op,outcomes,on),'natural_first':score_plan(np,outcomes,nn)}
        case_record={
            'case_id':cid,'t0':t0,'question':q,
            'retrieval_queries':qlog,'official_candidate_count':len(official),
            'natural_candidate_count':len(natural),'official_index_count':sum(x.get('origin')=='INDEX_PRE_T0' for x in official),
            'arms':arms,'trials':trials,
            'warning':'Retrospective query results may use discoveries unavailable at T0; no forecast performance or decisive evidence is established.'
        }
        (out/f'{cid}.json').write_text(json.dumps(case_record,ensure_ascii=False,indent=2),encoding='utf-8')
        records.append(case_record)
        print(json.dumps({'case_id':cid,'official':len(official),'natural':len(natural),
                          'official_proxy3':arms['official_first']['by_depth']['3']['target_proxy'],
                          'natural_proxy3':arms['natural_first']['by_depth']['3']['target_proxy']},ensure_ascii=False),flush=True)
    summary=calculate_summary(records)
    (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    cols=['case_id','arm','primary_slots','candidate_slots','archives3','readable3','keyword3','target_proxy3','archives6','readable6','keyword6','target_proxy6','first_target_proxy_rank','official_index_count','natural_candidate_count']
    with (out/'RACE_CASE_RESULTS.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for c in records:
            for name,arm in c['arms'].items():
                b3,b6=arm['by_depth']['3'],arm['by_depth']['6']
                w.writerow({'case_id':c['case_id'],'arm':name,
                            'primary_slots':arm['primary_slots'],'candidate_slots':len(arm['plan']),
                            'archives3':b3['archive'],'readable3':b3['readable'],'keyword3':b3['keyword'],'target_proxy3':b3['target_proxy'],
                            'archives6':b6['archive'],'readable6':b6['readable'],'keyword6':b6['keyword'],'target_proxy6':b6['target_proxy'],
                            'first_target_proxy_rank':arm['first_target_proxy_rank'],
                            'official_index_count':c['official_index_count'],'natural_candidate_count':c['natural_candidate_count']})
    print('FINAL_SUMMARY',json.dumps(summary,ensure_ascii=False),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--cases',required=True);p.add_argument('--official-routes',required=True);p.add_argument('--out-dir',required=True)
    p.add_argument('--case-limit',type=int,default=10);p.add_argument('--primary-cap',type=int,default=3)
    p.add_argument('--fallback-cap',type=int,default=3);p.add_argument('--results-per-query',type=int,default=8)
    a=p.parse_args()
    run(a.cases,a.official_routes,a.out_dir,a.case_limit,a.primary_cap,a.fallback_cap,a.results_per_query)
