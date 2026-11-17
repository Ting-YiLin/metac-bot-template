"""Publish public encryption key to state branch, never the Metaculus credential."""
from __future__ import annotations
import base64
import json
import os
import requests
from sealed_queue import public_document

REPO="Ting-YiLin/metac-bot-template"
BRANCH="tingyi001-test-state"
PATH="state/minibench_work_public_key.json"
URL=f"https://api.github.com/repos/{REPO}/contents/{PATH}"

def publish_key(token,github_token,session=requests):
    if not github_token:
        raise ValueError("GITHUB_TOKEN_MISSING")
    data=public_document(token)
    headers={"Authorization":"Bearer "+github_token,
             "Accept":"application/vnd.github+json",
             "User-Agent":"BTF3WorkPublicEncryptionKey"}
    prior=session.get(URL,headers=headers,params={"ref":BRANCH},timeout=20)
    if prior.status_code not in (200,404):
        raise RuntimeError("GH_KEY_READ_"+str(prior.status_code))
    if prior.status_code==200:
        old=prior.json()
        try:
            present=json.loads(base64.b64decode(old["content"]).decode("utf-8"))
            if present.get("public_key_id")==data["public_key_id"]:
                return "PUBLIC_KEY_ALREADY_CURRENT",data["public_key_id"]
        except Exception:
            pass
    payload={"branch":BRANCH,"message":"Publish MiniBench Work forecast queue encryption public key",
             "content":base64.b64encode((json.dumps(data,ensure_ascii=False,indent=2)+"\n").encode()).decode()}
    if prior.status_code==200:payload["sha"]=prior.json()["sha"]
    written=session.put(URL,headers=headers,json=payload,timeout=20)
    if written.status_code not in (200,201):
        raise RuntimeError("GH_KEY_WRITE_"+str(written.status_code))
    return "PUBLIC_KEY_PUBLISHED",data["public_key_id"]

if __name__=="__main__":
    try:
        result,key_id=publish_key(os.getenv("METACULUS_TOKEN",""),os.getenv("GITHUB_TOKEN",""))
        print(json.dumps({"status":result,"key_id":key_id}))
    except Exception as exc:
        print(json.dumps({"status":"PUBLIC_KEY_PUBLICATION_FAILED","error_type":type(exc).__name__}))
        raise SystemExit(2)
