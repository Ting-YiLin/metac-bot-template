"""Free-tier-only Gemini REST client: bounded transient retries, auditable attempt ledger.
No secrets written. No provider fallback beyond explicit model allowlist.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

LIMITS={'gemini-3.5-flash-lite':450,'gemini-3.8-flash':18,'gemini-3.6-flash':18}
KEY_ENV='GEMINI_API_KEY'
MAX_OUTPUT_TOKENS=32768
def default_thinking_level(model,role):
    if model=='gemini-3.5-flash-lite':
        return 'high' if role in ('search_planner_lite','search_gap_planner_lite') else 'medium'
    return 'high'

class BudgetExceeded(RuntimeError):pass
class ModelFailure(RuntimeError):
    def __init__(self,code,**details):
        self.details=details
        super().__init__(code)

class QuotaLedger:
    def __init__(self,path,baseline=None,day=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        current_day=day or dt.datetime.now(dt.timezone.utc).date().isoformat()
        self.baseline={k:int((baseline or {}).get(k,0)) for k in LIMITS}
        try:data=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:data={}
        if data.get('day_utc')!=current_day:
            data={'day_utc':current_day,'counts':{},'baseline':self.baseline}
        else:
            for k in LIMITS:
                if self.baseline[k]<int(data.get('baseline',{}).get(k,0)):
                    raise BudgetExceeded('BASELINE_WOULD_DECREASE: '+k)
            data['baseline']={k:max(self.baseline[k],int(data.get('baseline',{}).get(k,0))) for k in LIMITS}
        self.d=data;self.flush()
    def flush(self):
        p=self.path.with_suffix('.tmp')
        p.write_text(json.dumps(self.d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');p.replace(self.path)
    def reserve(self,model):
        if model not in LIMITS:raise ValueError('MODEL_NOT_ALLOWLISTED')
        used=int(self.d['counts'].get(model,0));outside=int(self.d['baseline'].get(model,0))
        if outside+used>=LIMITS[model]:raise BudgetExceeded(f'{model}: budget {LIMITS[model]} (baseline {outside}, local {used}) reached')
        self.d['counts'][model]=used+1;self.flush();return outside+used+1
    def snapshot(self):return {'day_utc':self.d['day_utc'],'baseline':self.d['baseline'],'attempts':self.d['counts'],'guard':LIMITS}

class Gemini:
    def __init__(self,ledger,transport=None,sleep=time.sleep):
        self.ledger=ledger;self.transport=transport;self.sleep=sleep;self.history=[]
    @staticmethod
    def retryable(code):
        # Do not blindly retry 429: could indicate DAILY exhausted, as opposed to RPM.
        return code in ('GEMINI_HTTP_408','GEMINI_HTTP_500','GEMINI_HTTP_502','GEMINI_HTTP_503','GEMINI_HTTP_504','GEMINI_NETWORK_OR_PARSE_TimeoutError','GEMINI_NETWORK_OR_PARSE_URLError')
    def call(self,model,prompt,*,role,temperature=None,max_attempts=2,thinking_level=None):
        if model not in LIMITS:raise ValueError('MODEL_NOT_ALLOWLISTED')
        if not 1<=max_attempts<=3:raise ValueError('MAX_ATTEMPTS_OUT_OF_RANGE')
        level=(thinking_level or default_thinking_level(model,role)).lower()
        if level not in ('low','medium','high'):raise ValueError('THINKING_LEVEL_NOT_ALLOWLISTED')
        for attempt in range(1,max_attempts+1):
            stamp=dt.datetime.now(dt.timezone.utc).isoformat()
            try:self.ledger.reserve(model)
            except BudgetExceeded as e:
                self.history.append({'at_utc':stamp,'role':role,'attempt':attempt,
                    'model_requested':model,'thinking_level':level,'max_output_tokens':MAX_OUTPUT_TOKENS,
                    'status':'NOT_SENT_BUDGET','error_code':str(e)[:120],'latency_ms':0})
                raise
            started=time.perf_counter()
            try:
                if self.transport is not None:
                    obj=self.transport(model,prompt,role)
                    model_name=model;usage=None;response_id=None;finish_reason=None
                else:
                    obj,model_name,usage,response_id,finish_reason=self._request(
                        model,prompt,temperature,level,MAX_OUTPUT_TOKENS)
                self.history.append({'at_utc':stamp,'role':role,'attempt':attempt,
                    'model_requested':model,'model_returned':model_name,'model_version':model_name,
                    'thinking_level':level,'max_output_tokens':MAX_OUTPUT_TOKENS,
                    'status':'SUCCESS','usage':usage,'response_id':response_id,
                    'finish_reason':finish_reason,'latency_ms':round((time.perf_counter()-started)*1000,3)})
                return obj
            except (ModelFailure,TimeoutError,urllib.error.URLError) as e:
                code=str(e) if isinstance(e,ModelFailure) else 'GEMINI_NETWORK_OR_PARSE_'+type(e).__name__
                record={'at_utc':stamp,'role':role,'attempt':attempt,'model_requested':model,
                    'thinking_level':level,'max_output_tokens':MAX_OUTPUT_TOKENS,'status':'FAILED',
                    'error_code':code[:90],'latency_ms':round((time.perf_counter()-started)*1000,3)}
                if isinstance(e,ModelFailure):record.update(e.details)
                self.history.append(record)
                if attempt>=max_attempts or not self.retryable(code):
                    raise ModelFailure(code) from None
                # short exponential backoff, reproducible upper bound, zero in mocked tests
                self.sleep(1.5*(2**(attempt-1)))
        raise AssertionError('UNREACHABLE')
    def _request(self,model,prompt,temperature,thinking_level,max_output_tokens):
        key=os.getenv(KEY_ENV,'').strip()
        if not key:raise ModelFailure('NEED_GEMINI_API_KEY')
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        gen={'responseMimeType':'application/json','maxOutputTokens':max_output_tokens,
             'thinkingConfig':{'thinkingLevel':thinking_level}}
        # Gemini 3.6+ temperature is ignored/deprecated per current docs; omit.
        if temperature is not None and model=='gemini-3.5-flash-lite':gen['temperature']=temperature
        body={'contents':[{'role':'user','parts':[{'text':prompt}]}],'generationConfig':gen}
        req=urllib.request.Request(url,data=json.dumps(body).encode('utf-8'),method='POST',headers={
            'Content-Type':'application/json','x-goog-api-key':key,'User-Agent':'FutureEvalV21Practice/1.0'})
        try:
            with urllib.request.urlopen(req,timeout=95) as resp:raw=json.load(resp)
        except urllib.error.HTTPError as e:raise ModelFailure(f'GEMINI_HTTP_{e.code}') from None
        except (urllib.error.URLError,TimeoutError,ValueError) as e:
            raise ModelFailure(f'GEMINI_NETWORK_OR_PARSE_{type(e).__name__}') from None
        candidates=raw.get('candidates') or []
        candidate=candidates[0] if candidates else {}
        usage_meta=raw.get('usageMetadata') or {}
        usage={k:usage_meta.get(k) for k in ('promptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount')}
        details={'model_version':raw.get('modelVersion','UNKNOWN'),'usage':usage,
                 'response_id':raw.get('responseId'),'finish_reason':candidate.get('finishReason')}
        if not candidates:raise ModelFailure('GEMINI_NO_CANDIDATES',**details)
        if candidate.get('finishReason')=='MAX_TOKENS':
            raise ModelFailure('GEMINI_MAX_OUTPUT_TOKENS',**details)
        parts=candidate.get('content',{}).get('parts',[])
        text=''.join(p.get('text','') for p in parts if isinstance(p,dict) and not p.get('thought'))
        if not text.strip():raise ModelFailure('GEMINI_EMPTY_TEXT',**details)
        text=text.strip()
        if text.startswith('```'):text='\n'.join(text.splitlines()[1:-1]).strip()
        try:obj=json.loads(text)
        except json.JSONDecodeError:raise ModelFailure('GEMINI_INVALID_JSON',**details) from None
        if not isinstance(obj,dict):raise ModelFailure('GEMINI_NOT_OBJECT',**details)
        return obj,details['model_version'],usage,details['response_id'],details['finish_reason']
