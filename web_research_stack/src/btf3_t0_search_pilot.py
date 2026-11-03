import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import load_json,normalize_url,save_json,now_iso
from query_plan import default_queries,dedup_queries
from search_backends import search
from ranker import rank_rows
from crawler import Crawler
from evidence_db import EvidenceDB
from wayback import latest_pre_t0

ROOT=Path(__file__).resolve().parents[1]

def run(cases_path,out_dir,archive_candidates=4,target_archives=2):
    cfg=load_json(ROOT/'config/default.json')
    cases=json.loads(Path(cases_path).read_text(encoding='utf-8'))
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    all_summary=[]

    for case in cases:
        cid=case['case_id']; q=case['question']; t0=case['t0_utc']; prefs=case.get('preferred_domains') or []
        cdir=out/cid;cdir.mkdir(parents=True,exist_ok=True)
        queries=dedup_queries(default_queries(q,prefs))[:3]
        candidates=[];search_log=[]
        for query in queries:
            try:
                rows=search(query,cfg['search_backend'],int(cfg['results_per_query']),cfg.get('searxng_base_url',''))
                search_log.append({'query':query,'count':len(rows),'error':None});candidates.extend(rows)
            except Exception as e:
                search_log.append({'query':query,'count':0,'error':type(e).__name__+':'+str(e)})
        ded={}
        for x in candidates:
            try:ded.setdefault(normalize_url(x['url']),x)
            except Exception:pass
        ranked=rank_rows(list(ded.values()),q,prefs,ROOT/'config/authority_weights.json',int(cfg['per_domain_preferred_limit']))
        save_json(cdir/'search_log.json',search_log);save_json(cdir/'ranked_candidates.json',ranked)

        archive_checks=[];safe_sources=[];db=EvidenceDB(cdir/'evidence.sqlite')
        crawler=Crawler(cfg,cdir/'archive_crawl')
        for i,row in enumerate(ranked[:int(archive_candidates)],1):
            wb=latest_pre_t0(row['url'],t0)
            item={'rank':i,'candidate':row,'wayback':wb}
            if wb.get('status')=='PRE_T0_CAPTURE_FOUND':
                snap=wb['snapshot']; rec=crawler.fetch(snap['snapshot_url'],source_id=f'{cid}_A{i}')
                rec.update(title=row.get('title',''),source_type=row.get('source_type','unknown'),
                           authority_score=row.get('authority_score',0),rank_score=row.get('rank_score',0),
                           original_url=row['url'],archive_timestamp=snap['timestamp'],
                           archive_digest=snap.get('digest'),t0=t0,t0_safe=True)
                item['fetch']=rec
                if rec.get('fetch_status')=='READABLE_FULL':
                    txt=Path(rec['text_path']).read_text(encoding='utf-8')
                    db.add_source(rec,txt,int(cfg['chunk_chars']),int(cfg['chunk_overlap_chars']))
                    safe_sources.append(rec)
                    if len(safe_sources)>=int(target_archives):
                        archive_checks.append(item);break
            archive_checks.append(item)
        hits=db.search(q,min(10,int(cfg['evidence_packet_chunks'])))
        db.db.close()
        packet={
            'case_id':cid,'question':q,'t0':t0,'resolution':case.get('resolution'),
            'created_at':now_iso(),'queries':queries,'candidate_count':len(ranked),
            'archive_checks':archive_checks,'t0_safe_readable_sources':safe_sources,
            'evidence_chunks':hits,
            'limitations':['Search results are route discovery only. Only pre-T0 archived bytes are admitted as evidence.']
        }
        save_json(cdir/'T0_EVIDENCE_PACKET.json',packet)
        all_summary.append({
            'case_id':cid,'candidate_count':len(ranked),'archive_checked':len(archive_checks),
            'pre_t0_capture_found':sum(1 for x in archive_checks if x['wayback'].get('status')=='PRE_T0_CAPTURE_FOUND'),
            'pre_t0_readable':len(safe_sources),'evidence_chunks':len(hits),
            'top_url':ranked[0]['url'] if ranked else None,
            'top_rank_score':ranked[0].get('rank_score') if ranked else None
        })

    summary={
        'created_at':now_iso(),'questions':len(all_summary),
        'questions_with_pre_t0_capture':sum(1 for x in all_summary if x['pre_t0_capture_found']>0),
        'questions_with_readable_pre_t0_evidence':sum(1 for x in all_summary if x['pre_t0_readable']>0),
        'total_pre_t0_readable_sources':sum(x['pre_t0_readable'] for x in all_summary),
        'cases':all_summary
    }
    save_json(out/'SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',required=True);p.add_argument('--out-dir',required=True)
    p.add_argument('--archive-candidates',type=int,default=4);p.add_argument('--target-archives',type=int,default=2)
    a=p.parse_args();run(a.cases,a.out_dir,a.archive_candidates,a.target_archives)
