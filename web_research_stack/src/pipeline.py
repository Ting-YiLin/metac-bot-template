import argparse,json,sys
from pathlib import Path
from common import load_json,save_json,normalize_url,now_iso
from query_plan import default_queries,dedup_queries
from search_backends import search
from ranker import rank_rows
from crawler import Crawler
from evidence_db import EvidenceDB

ROOT=Path(__file__).resolve().parents[1]

def research(project,question,preferred_domains=None,queries=None,config_path=None):
    cfg=load_json(config_path or ROOT/'config/default.json'); preferred_domains=preferred_domains or []
    out=ROOT/'runs'/project; out.mkdir(parents=True,exist_ok=True)
    qs=dedup_queries(queries or default_queries(question,preferred_domains))[:int(cfg['queries_per_question'])]
    candidates=[];search_log=[]
    for q in qs:
        try:
            rows=search(q,cfg['search_backend'],int(cfg['results_per_query']),cfg.get('searxng_base_url',''))
            search_log.append({'query':q,'count':len(rows),'error':None});candidates.extend(rows)
        except Exception as e:search_log.append({'query':q,'count':0,'error':type(e).__name__+':'+str(e)})
    dedup={}
    for x in candidates:dedup.setdefault(normalize_url(x['url']),x)
    ranked=rank_rows(list(dedup.values()),question,preferred_domains,ROOT/'config/authority_weights.json',int(cfg['per_domain_preferred_limit']))
    save_json(out/'search_log.json',search_log);save_json(out/'ranked_candidates.json',ranked)
    crawler=Crawler(cfg,out/'crawl');db=EvidenceDB(out/'evidence.sqlite')
    readable=[];attempted=0;domain_attempts={}
    for row in ranked:
        if len(readable)>=int(cfg['target_readable_sources']) or attempted>=int(cfg['max_fetch_attempts']): break
        h=row['url'].split('/')[2].lower(); n=domain_attempts.get(h,0)
        if n>=int(cfg['per_domain_attempt_limit']):continue
        domain_attempts[h]=n+1;attempted+=1
        rec=crawler.fetch(row['url'],source_id=f'S{attempted:03d}')
        rec.update(title=row.get('title',''),source_type=row.get('source_type','unknown'),authority_score=row.get('authority_score',0),source_family=row.get('source_family',''))
        if rec.get('fetch_status')=='READABLE_FULL':
            text=Path(rec['text_path']).read_text(encoding='utf-8');db.add_source(rec,text,int(cfg['chunk_chars']),int(cfg['chunk_overlap_chars']));readable.append(rec)
    hits=db.search(question,int(cfg['evidence_packet_chunks']))
    packet={'project':project,'question':question,'created_at':now_iso(),'queries':qs,'candidate_count':len(ranked),'fetch_attempts':attempted,'readable_sources':len(readable),'sources':readable,'evidence_chunks':hits,'limitations':['READABLE_FULL is technical readability only; semantic support must be judged separately.']}
    save_json(out/'evidence_packet.json',packet)
    md=['# Evidence Packet','',f'Question: {question}','',f'Readable sources: {len(readable)} / fetch attempts: {attempted}','']
    for i,h in enumerate(hits,1):
        md += [f'## {i}. {h["source_id"]} — {h.get("title") or h.get("url")}',f'- URL: {h["url"]}',f'- Type: {h["source_type"]}; authority prior: {h["authority_score"]}',f'- Characters: {h["start_char"]}–{h["end_char"]}','',h['text'].strip(),'']
    (out/'EVIDENCE_PACKET.md').write_text('\n'.join(md),encoding='utf-8')
    return packet

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--question',required=True);p.add_argument('--preferred-domain',action='append',default=[]);p.add_argument('--query',action='append',default=[]);p.add_argument('--config')
    a=p.parse_args(); print(json.dumps(research(a.project,a.question,a.preferred_domain,a.query or None,a.config),ensure_ascii=False,indent=2))
