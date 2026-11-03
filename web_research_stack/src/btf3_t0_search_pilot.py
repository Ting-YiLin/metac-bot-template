import argparse,csv,json,re,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import load_json,normalize_url,save_json,now_iso
from query_plan import compact_query,dedup_queries
from search_backends import search
from ranker import rank_rows
from route_quality import url_date_relation,excluded_terms
from crawler import Crawler
from evidence_db import EvidenceDB
from evidence_quality import evidence_relevance
from wayback import latest_pre_t0
from archive_integrity import verify_archive_response

ROOT=Path(__file__).resolve().parents[1]

def _dt(x):
    s=str(x).replace('Z','+00:00');d=datetime.fromisoformat(s)
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def historical_queries(question,t0,prefs):
    d=_dt(t0); first=d.replace(day=1); prev=first-timedelta(days=1)
    month=prev.strftime('%B %Y')
    base=compact_query(question,max_terms=14)
    # Strip obvious forecast deadline tokens so search does not overfit to post-resolution pages.
    words=[w for w in base.split() if w.lower() not in {
        'january','february','march','april','may','june','july','august','september','october','november','december',
        '2026','2025','2024','2023','1','01','31','30','23:59','utc'
    }]
    ex=excluded_terms(question)
    words=[w for w in words if w.lower().strip('(),.') not in ex]
    core=' '.join(words[:12])
    neg=' '.join('-'+x for x in sorted(ex))
    site=' OR '.join('site:'+d for d in prefs[:3])
    return dedup_queries([
        (core+' '+month).strip(),
        (core+' '+month+' '+site).strip() if site else '',
        (core+' '+neg+' '+month).strip() if neg else '',
        (core+' official '+month).strip(),
        compact_query(question,max_terms=12)
    ])

def load_seed_routes(path):
    out={}
    if not path:return out
    for r in csv.DictReader(open(path,encoding='utf-8-sig')):
        out.setdefault(r.get('case_id',''),[]).append(r)
    return out

def run(cases_path,out_dir,archive_candidates=6,target_archives=2,seed_routes_path=None):
    cfg=load_json(ROOT/'config/default.json')
    cases=json.loads(Path(cases_path).read_text(encoding='utf-8'))
    seeds=load_seed_routes(seed_routes_path)
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    all_summary=[];archive_crawler=Crawler(cfg,out/'archive_crawl')

    for case in cases:
        cid=case['case_id'];q=case['question'];t0=case['t0_utc'];prefs=case.get('preferred_domains') or []
        cdir=out/cid;cdir.mkdir(parents=True,exist_ok=True)
        queries=historical_queries(q,t0,prefs)[:5]
        candidates=[];search_log=[]
        for query in queries:
            if not query:continue
            try:
                rows=search(query,cfg['search_backend'],int(cfg['results_per_query']),cfg.get('searxng_base_url',''))
                search_log.append({'query':query,'count':len(rows),'error':None});candidates.extend(rows)
            except Exception as e:
                search_log.append({'query':query,'count':0,'error':type(e).__name__+':'+str(e)})
        for r in seeds.get(cid,[]):
            candidates.append({
                'url':r.get('route_url',''),'title':'','snippet':'','engine':'PRE_T0_SEED','query':'',
                'route_origin':r.get('route_origin',''),'t0_route_status':r.get('t0_route_status',''),
                'scraped_at':r.get('scraped_at') or r.get('date_scraped') or ''
            })
        ded={}
        for x in candidates:
            try:ded.setdefault(normalize_url(x['url']),x)
            except Exception:pass
        ranked=rank_rows(list(ded.values()),q,prefs,ROOT/'config/authority_weights.json',int(cfg['per_domain_preferred_limit']))
        for r in ranked:r['url_date_relation']=url_date_relation(r['url'],t0)
        save_json(cdir/'search_log.json',search_log);save_json(cdir/'ranked_candidates.json',ranked)

        archive_checks=[];readable_sources=[];accepted_sources=[];rejected_readable=[];db=EvidenceDB(cdir/'evidence.sqlite')
        queried=0;temporal_skipped=0
        for row in ranked:
            if queried>=int(archive_candidates):break
            date_rel=row.get('url_date_relation') or {}
            if date_rel.get('status')=='POST_T0_EXPLICIT_URL_DATE':
                temporal_skipped+=1
                archive_checks.append({'rank':row.get('rank'),'candidate':row,'wayback':{
                    'status':'SKIPPED_POST_T0_URL_DATE','method':'URL_DATE_GATE','snapshot':None,
                    'url':row['url'],'t0':t0,'error':None,'url_date':date_rel.get('url_date')}})
                continue
            queried+=1
            wb=latest_pre_t0(row['url'],t0)
            item={'rank':row.get('rank'),'candidate':row,'wayback':wb}
            if wb.get('status')=='PRE_T0_CAPTURE_FOUND':
                snap=wb['snapshot'];rec=archive_crawler.fetch(snap['snapshot_url'],source_id=f"{cid}_A{row.get('rank')}")
                archive_proof=verify_archive_response(snap['snapshot_url'],rec.get('final_url'),t0)
                rec.update(title=row.get('title',''),source_type=row.get('source_type','unknown'),
                           authority_score=row.get('authority_score',0),rank_score=row.get('rank_score',0),
                           original_url=row['url'],archive_timestamp=snap['timestamp'],
                           archive_digest=snap.get('digest'),t0=t0,t0_safe=archive_proof['ok'],
                           archive_verification=archive_proof)
                item['fetch']=rec
                if rec.get('fetch_status')=='READABLE_FULL' and rec['t0_safe']:
                    txt=Path(rec['text_path']).read_text(encoding='utf-8',errors='replace')
                    qual=evidence_relevance(q,txt);rec['evidence_relevance']=qual
                    readable_sources.append(rec)
                    if qual['accepted']:
                        db.add_source(rec,txt,int(cfg['chunk_chars']),int(cfg['chunk_overlap_chars']))
                        accepted_sources.append(rec)
                        if len(accepted_sources)>=int(target_archives):
                            archive_checks.append(item);break
                    else:
                        rejected_readable.append(rec)
            archive_checks.append(item)
        hits=db.search(q,min(10,int(cfg['evidence_packet_chunks'])));db.db.close()
        packet={
            'case_id':cid,'question':q,'t0':t0,'created_at':now_iso(),
            'discovery_mode':'LIVE_SEARCH_RETROSPECTIVE_DIAGNOSTIC',
            'queries':queries,'candidate_count':len(ranked),'archive_checks':archive_checks,
            't0_safe_readable_sources':readable_sources,'accepted_evidence_sources':accepted_sources,
            'rejected_readable_sources':rejected_readable,'evidence_chunks':hits,
            'limitations':['Search results are route discovery only. The deterministic semantic gate admits related candidates, not decisive evidence. Live search-based discovery is retrospective only. Only archive-verified pre-T0 bytes are admitted.']
        }
        save_json(cdir/'T0_EVIDENCE_PACKET.json',packet)
        all_summary.append({
            'case_id':cid,'candidate_count':len(ranked),'archive_queried':queried,'temporal_skipped':temporal_skipped,
            'pre_t0_capture_found':sum(1 for x in archive_checks if x['wayback'].get('status')=='PRE_T0_CAPTURE_FOUND'),
            'pre_t0_readable':len(readable_sources),'semantic_t0_evidence':len(accepted_sources),
            'evidence_chunks':len(hits),'rejected_readable':len(rejected_readable),
            'top_url':ranked[0]['url'] if ranked else None,'top_rank_score':ranked[0].get('rank_score') if ranked else None,
            'top_seed_bonus':ranked[0].get('pre_t0_seed_bonus') if ranked else None
        })

    summary={
        'created_at':now_iso(),'questions':len(all_summary),
        'questions_with_pre_t0_capture':sum(1 for x in all_summary if x['pre_t0_capture_found']>0),
        'questions_with_readable_pre_t0_evidence':sum(1 for x in all_summary if x['pre_t0_readable']>0),
        'questions_with_semantic_t0_evidence':sum(1 for x in all_summary if x['semantic_t0_evidence']>0),
        'total_semantic_t0_sources':sum(x['semantic_t0_evidence'] for x in all_summary),
        'total_rejected_readable':sum(x['rejected_readable'] for x in all_summary),
        'total_temporal_skips':sum(x['temporal_skipped'] for x in all_summary),
        'cases':all_summary
    }
    save_json(out/'SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2));return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',required=True);p.add_argument('--out-dir',required=True)
    p.add_argument('--archive-candidates',type=int,default=6);p.add_argument('--target-archives',type=int,default=2);p.add_argument('--seed-routes')
    a=p.parse_args();run(a.cases,a.out_dir,a.archive_candidates,a.target_archives,a.seed_routes)
