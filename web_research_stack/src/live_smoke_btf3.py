import json,sys
from pathlib import Path
from common import load_json
from crawler import Crawler

ROOT=Path(__file__).resolve().parents[1]
URLS=[
    'https://www.rba.gov.au/monetary-policy/',
    'https://www.nobelprize.org/prizes/',
    'https://www.federalreserve.gov/monetarypolicy.htm',
    'https://www.senate.gov/legislative/votes_new.htm',
    'https://www.supremecourt.gov/opinions/opinions.aspx',
]

if __name__=='__main__':
    cfg=load_json(ROOT/'config/default.json')
    c=Crawler(cfg,ROOT/'runs/_btf3_smoke/crawl')
    rows=[];passed=[]
    for u in URLS:
        r=c.fetch(u);rows.append(r)
        if r.get('fetch_status')=='READABLE_FULL' and r.get('raw_sha256') and r.get('text_sha256'):
            passed.append(u.split('/')[2])
    out={
        'status':'PASS' if len(set(passed))>=2 else 'FAIL',
        'required_distinct_successes':2,
        'attempted_hosts':[u.split('/')[2] for u in URLS],
        'passed_hosts':sorted(set(passed)),
        'results':rows,
    }
    d=ROOT/'runs/_btf3_smoke';d.mkdir(parents=True,exist_ok=True)
    (d/'BTF3_LIVE_SMOKE_5DOMAIN.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))
    sys.exit(0 if out['status']=='PASS' else 3)
