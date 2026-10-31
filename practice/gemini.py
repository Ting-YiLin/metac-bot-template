"""Official Gemini generateContent REST client, restricted to 3 approved model IDs.
No keys ever saved to artifacts. No automatic retry or paid fallback.
"""
from __future__ import annotations
import json,os,urllib.request,urllib.error,datetime as dt,time
from pathlib import Path

LIMITS={'gemini-3.5-flash-lite':18,'gemini-3.8-flash':17,'gemini-3.6-flash':8}
KEY_ENV='GEMINI_API_KEY'
class BudgetExceeded(RuntimeError):pass
class ModelFailure(RuntimeError):pass

class QuotaLedger:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        try:self.d=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:self.d={'day_utc':dt.datetime.now(dt.timezone.utc).date().isoformat(),'counts':{}}
        # UTC-based conservative ledger; Google daily reset may differ. Operator checks dashboard separately.
        day=dt.datetime.now(dt.timezone.utc).date().isoformat()
        if self.d.get('day_utc')!=day:self.d={'day_utc':day,'counts':{}}
        self.flush()
    def flush(self):
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.d,indent=2),encoding='utf-8');temp.replace(self.path)
    def reserve(self,model):
        if model not in LIMITS:raise ValueError('MODEL_NOT_ALLOWLISTED')
        n=self.d['counts'].get(model,0)
        if n>=LIMITS[model]:raise BudgetExceeded(f'{model}: budget {LIMITS[model]} reached')
        self.d['counts'][model]=n+1;self.flush()
        return self.d['counts'][model]

class Gemini:
    def __init__(self,ledger,transport=None):
        self.ledger=ledger;self.transport=transport;self.history=[]
    def call(self,model,prompt,*,role,temperature=.3):
        self.ledger.reserve(model)  # count BEFORE every attempt, even failure
        if self.transport is not None:
            result=self.transport(model,prompt,role)
            self.history.append({'role':role,'model_requested':model,'model_returned':model,'usage':None,'mock':True})
            return result
        key=os.getenv(KEY_ENV,'').strip()
        if not key:raise ModelFailure('NEED_GEMINI_API_KEY')
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        body={'contents':[{'role':'user','parts':[{'text':prompt}]}],
              'generationConfig':{'temperature':temperature,'responseMimeType':'application/json','maxOutputTokens':8192}}
        req=urllib.request.Request(url,data=json.dumps(body).encode('utf-8'),method='POST',headers={
            'Content-Type':'application/json','x-goog-api-key':key,'User-Agent':'FutureEvalPracticeV2/1.0'})
        # Hard-coded server avoids URL-based exfiltration; timeout avoids infinite workers.
        try:
            with urllib.request.urlopen(req,timeout=120) as resp:
                raw=json.load(resp)
        except urllib.error.HTTPError as e:
            # No raw HTTP body (may contain echoed prompts, debug data or account details)
            raise ModelFailure(f'GEMINI_HTTP_{e.code}') from None
        except (urllib.error.URLError,TimeoutError,ValueError) as e:
            raise ModelFailure(f'GEMINI_NETWORK_OR_PARSE_{type(e).__name__}') from None
        parts=(raw.get('candidates') or [{}])[0].get('content',{}).get('parts',[])
        text=''.join(p.get('text','') for p in parts if isinstance(p,dict) and not p.get('thought'))
        if not text.strip():raise ModelFailure('GEMINI_EMPTY_TEXT')
        text=text.strip()
        if text.startswith('```'):
            text='\n'.join(text.splitlines()[1:-1]).strip()
        try:obj=json.loads(text)
        except json.JSONDecodeError:raise ModelFailure('GEMINI_INVALID_JSON') from None
        if not isinstance(obj,dict):raise ModelFailure('GEMINI_NOT_OBJECT')
        usage=raw.get('usageMetadata') or {}
        self.history.append({'role':role,'model_requested':model,'model_returned':raw.get('modelVersion','UNKNOWN'),
             'usage':{k:usage.get(k) for k in ('promptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount')},'mock':False})
        return obj
