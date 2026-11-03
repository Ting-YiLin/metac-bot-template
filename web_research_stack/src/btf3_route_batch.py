import argparse,csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import load_json,now_iso
from crawler import Crawler
from temporal import classify_t0

ROOT=Path(__file__).resolve().parents[1]

def run(input_csv,out_dir,config=None,max_per_question=5,case_limit=None,t0_by_case=None,cases_json=None):
    cfg=load_json(config or ROOT/'config/default.json')
    if cases_json and not t0_by_case:
        cases=json.loads(Path(cases_json).read_text(encoding='utf-8'))
        t0_by_case={cid:(meta.get('t0_utc') or meta.get('present_date')) for cid,meta in cases.items()}
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    crawler=Crawler(cfg,out/'crawl')
    rows=list(csv.DictReader(open(input_csv,encoding='utf-8-sig')))
    chosen=[]; seen={}; allowed_cases=[]
    for r in rows:
        cid=r.get('case_id','')
        if cid not in seen:
            if case_limit is not None and len(allowed_cases)>=int(case_limit): continue
            allowed_cases.append(cid);seen[cid]=0
        if cid not in allowed_cases or seen[cid]>=int(max_per_question): continue
        seen[cid]+=1;chosen.append(r)
    results=[]
    for i,r in enumerate(chosen,1):
        rec=crawler.fetch(r['route_url'],source_id=f"{r.get('case_id','Q')}_R{r.get('rank',i)}")
        t0=(t0_by_case or {}).get(r.get('case_id','')) or r.get('t0_utc')
        temp=classify_t0(t0=t0,official_scraped_at=(r.get('scraped_at') or r.get('date_scraped')),retrieved_at=rec.get('retrieved_at'))
        rec.update({k:r.get(k,'') for k in ('case_id','question','rank','domain','route_origin','source_family','route_role_pre_fetch','route_confidence_pre_fetch','scraped_at','date_scraped','t0_route_status','t0_utc','resolution')})
        rec.update(temp);results.append(rec)
    fields=sorted({k for r in results for k in r}) if results else []
    with open(out/'btf3_fetch_results.csv','w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(results)
    (out/'btf3_fetch_results.json').write_text(json.dumps({'created_at':now_iso(),'count':len(results),'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input-csv',required=True);p.add_argument('--out-dir',required=True);p.add_argument('--config');p.add_argument('--max-per-question',type=int,default=5);p.add_argument('--case-limit',type=int);p.add_argument('--cases-json')
    a=p.parse_args(); rr=run(a.input_csv,a.out_dir,a.config,a.max_per_question,a.case_limit,cases_json=a.cases_json);print(json.dumps({'count':len(rr),'out_dir':a.out_dir},ensure_ascii=False))
