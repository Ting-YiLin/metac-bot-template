import json,sys
from pathlib import Path
from common import load_json
from crawler import Crawler
ROOT=Path(__file__).resolve().parents[1]
URLS=['https://www.rba.gov.au/monetary-policy/','https://www.nobelprize.org/prizes/','https://ai.google.dev/gemma/docs']
if __name__=='__main__':
    cfg=load_json(ROOT/'config/default.json'); c=Crawler(cfg,ROOT/'runs/_smoke/crawl');passed=[];rows=[]
    for u in URLS:
        r=c.fetch(u);rows.append(r)
        if r.get('fetch_status')=='READABLE_FULL' and r.get('raw_sha256') and r.get('text_sha256'):
            passed.append(u.split('/')[2])
        if len(set(passed))>=2:break
    status='PASS' if len(set(passed))>=2 else 'FAIL'
    out={'status':status,'passed_hosts':sorted(set(passed)),'results':rows}
    (ROOT/'runs/_smoke').mkdir(parents=True,exist_ok=True);(ROOT/'runs/_smoke/LIVE_SMOKE.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2));sys.exit(0 if status=='PASS' else 3)
