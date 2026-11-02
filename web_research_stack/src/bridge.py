#!/usr/bin/env python3
import json,sys
from common import load_json
from search_backends import search
from pipeline import research,ROOT
from crawler import Crawler
from evidence_db import EvidenceDB

def handle(req):
    cfg=load_json(ROOT/'config/default.json');action=req.get('action')
    if action=='search':
        return {'ok':True,'results':search(req['query'],req.get('backend',cfg['search_backend']),int(req.get('max_results',cfg['results_per_query'])),req.get('searxng_base_url',cfg.get('searxng_base_url','')))}
    if action=='research':
        return {'ok':True,'result':research(req.get('project','default'),req['question'],req.get('preferred_domains') or [],req.get('queries') or None,req.get('config_path'))}
    if action=='fetch':
        proj=req.get('project','default');out=ROOT/'runs'/proj;out.mkdir(parents=True,exist_ok=True);c=Crawler(cfg,out/'crawl');r=c.fetch(req['url']);return {'ok':r.get('fetch_status')=='READABLE_FULL','result':r}
    if action=='retrieve':
        db=EvidenceDB(ROOT/'runs'/req.get('project','default')/'evidence.sqlite');return {'ok':True,'results':db.search(req['query'],int(req.get('limit',12)))}
    raise ValueError('unknown action')

if __name__=='__main__':
    raw=sys.stdin.read().strip()
    try:
        req=json.loads(raw);print(json.dumps(handle(req),ensure_ascii=False,indent=2))
    except Exception as e:
        print(json.dumps({'ok':False,'error':type(e).__name__+':'+str(e)},ensure_ascii=False,indent=2));sys.exit(2)
