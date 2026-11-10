"""Read-only diagnostic: workflow scheduling and available unforecasted testing questions."""
import json, os, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
import requests

REPO = "Ting-YiLin/metac-bot-template"
OUTPUT = Path("testing_area_diagnostic_20261110.json")

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def state_from_github():
    token=os.getenv("GITHUB_TOKEN", "")
    headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
    if token: headers["Authorization"]="Bearer "+token
    urls={
      "workflow_state":f"https://api.github.com/repos/{REPO}/actions/workflows/run_bot_testing_area.yaml",
      "workflow_runs":f"https://api.github.com/repos/{REPO}/actions/workflows/run_bot_testing_area.yaml/runs?per_page=40",
      "repository_actions_permissions":f"https://api.github.com/repos/{REPO}/actions/permissions",
    }
    out={}
    for key,url in urls.items():
        try:
            response=requests.get(url,headers=headers,timeout=20)
            if response.status_code!=200:
                out[key]={"http_status":response.status_code,"error":"HTTP_"+str(response.status_code)}
                continue
            data=response.json()
            if key=="workflow_state":
                out[key]={k:data.get(k) for k in ("id","name","path","state","created_at","updated_at")}
            elif key=="repository_actions_permissions":
                out[key]={k:data.get(k) for k in ("enabled","allowed_actions","selected_actions_url")}
            else:
                runs=data.get("workflow_runs",[])
                out[key]={
                    "total_count":data.get("total_count"),
                    "recent":[{k:x.get(k) for k in ("id","event","status","conclusion","created_at","updated_at","head_sha")} for x in runs[:10]],
                }
        except Exception as exc:
            out[key]={"error_type":type(exc).__name__}
    return out

def testing_area_candidates():
    from forecasting_tools import MetaculusClient
    from forecasting_tools.data_models.questions import QuestionState
    client=MetaculusClient()
    result={}
    for tournament in ("bot-testing-area",):
        try:
            rows=client.get_all_open_questions_from_tournament(tournament)
            result[tournament]={
                "status":"OK",
                "retrieved_open_questions":len(rows),
                "eligible_unforecasted":sum(1 for q in rows if q.state==QuestionState.OPEN and q.already_forecasted is False),
                "already_forecasted":sum(1 for q in rows if q.already_forecasted is True),
                "ambiguous_forecast_state":sum(1 for q in rows if q.already_forecasted is None),
                "unforecasted_items":[
                    {
                     "post_id":getattr(q,"id_of_post",None),
                     "question_id":getattr(q,"id_of_question",None),
                     "question_type":type(q).__name__,
                     "state":str(getattr(q,"state","")),
                     "url":getattr(q,"page_url",None),
                    }
                    for q in rows if q.state==QuestionState.OPEN and q.already_forecasted is False
                ][:25],
            }
        except Exception as exc:
            result[tournament]={"status":"ERROR","exception_type":type(exc).__name__,"message":str(exc)[:300]}
    return result

if __name__=="__main__":
    result={"checked_at_utc":utc_now(),"audit_mode":"READ_ONLY_NO_MODEL_CALL_NO_SUBMISSION","repo":REPO}
    result["github"]=state_from_github()
    result["testing_area"]=testing_area_candidates()
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
