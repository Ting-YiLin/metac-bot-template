# -*- coding: utf-8 -*-
"""One-shot authenticated READ of an official question, output fields only."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.request

API='https://www.metaculus.com/api/posts/43325/'
OUT=Path('QUESTION_EXPORT_43325.json')


def main():
    token=os.getenv('METACULUS_TOKEN')
    if not token:raise RuntimeError('QUESTION_RETRIEVAL_CREDENTIAL_UNAVAILABLE')
    req=urllib.request.Request(API,headers={
        'Authorization':'Token '+token,'Accept-Language':'en',
        'Accept':'application/json','User-Agent':'FutureEval-L1.1-export/1.0'})
    with urllib.request.urlopen(req,timeout=25) as resp:
        if resp.status!=200:raise RuntimeError('OFFICIAL_RESPONSE_NOT_OK')
        raw=resp.read(20_000_001)
        if len(raw)>20_000_000:raise RuntimeError('RESPONSE_TOO_LARGE')
    obj=json.loads(raw)
    group=obj.get('group_of_questions',{})
    if obj.get('id')!=43325 or not isinstance(group,dict):
        raise RuntimeError('POST_ID_OR_GROUP_MISMATCH')
    questions=group.get('questions',[])
    selected=[q for q in questions if isinstance(q,dict) and q.get('id')==43330]
    if len(selected)!=1:raise RuntimeError('SUBQUESTION_ID_UNAVAILABLE')
    # Only the official question definition, never forecast histories or user metadata.
    compact={'id':obj['id'],'title':obj.get('title',''),
             'group_of_questions':{
               k:group.get(k,'') for k in ('title','description','resolution_criteria','fine_print')
             }}
    compact['group_of_questions']['questions']=[{
        k:q.get(k,'') for k in ('id','label','title','type','status')
    } for q in selected]
    raw2=json.dumps(compact,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
    out={'export_version':'L11_AUTHENTICATED_METADATA_V1','api_url':API,
         'fetched_at_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
         'original_api_sha256':hashlib.sha256(raw).hexdigest(),
         'post_payload_sha256':hashlib.sha256(raw2).hexdigest(),
         'source_run_url':f"https://github.com/{os.getenv('GITHUB_REPOSITORY','Ting-YiLin/metac-bot-template')}/actions/runs/{os.getenv('GITHUB_RUN_ID','')}",
         'post':compact}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('READ_ONLY_OFFICIAL_EXPORT_READY post=43325 subquestion=43330')

if __name__=='__main__': main()

