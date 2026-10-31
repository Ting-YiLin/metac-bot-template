"""FutureEval V2.2: Gemini free-tier HIGH thinking, paced calls, bounded retries.
No publishing, no paid model, no secret values in reports.
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
from zoneinfo import ZoneInfo

GOOGLE_LIMITS = {'gemini-3.5-flash-lite':450,'gemini-3.8-flash':18,'gemini-3.6-flash':18}
ROUTER_MODEL = 'openrouter/free'
LIMITS = {**GOOGLE_LIMITS, ROUTER_MODEL:45}
GOOGLE_KEY_ENV='GEMINI_API_KEY'
MAX_OUTPUT_TOKENS=32768
REQUEST_TIMEOUT_SECONDS=600
PACIFIC=ZoneInfo('America/Los_Angeles')

def google_day(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(PACIFIC).date().isoformat()

def default_thinking_level(model,role):
    if model=='gemini-3.5-flash-lite':
        return 'high' if role in ('search_planner_lite','search_gap_planner_lite') else 'medium'
    return 'high'

class BudgetExceeded(RuntimeError):pass

class ModelFailure(RuntimeError):
    def __init__(self,code,**details):
        self.code=code
        self.details=details
        super().__init__(code)

class QuotaLedger:
    """Explicit operator-provided per-provider baseline; reserve BEFORE sending.

    Google calendar-day: Pacific. OpenRouter: conservative no-auto-reset within a ledger;
    each new workflow must supply an observed platform baseline for its current day.
    """
    def __init__(self,path,baseline=None,day=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        current_day=day or google_day()
        self.baseline={k:int((baseline or {}).get(k,0)) for k in LIMITS}
        try:data=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:data={}
        if data.get('google_day_pacific')!=current_day:
            # New Google quota period; preserve conservative router requests from prior local ledger.
            old_router=int(data.get('counts',{}).get(ROUTER_MODEL,0))
            data={'google_day_pacific':current_day,'counts':{ROUTER_MODEL:old_router},'baseline':self.baseline}
        else:
            for k in LIMITS:
                if self.baseline[k]<int(data.get('baseline',{}).get(k,0)):
                    raise BudgetExceeded('BASELINE_WOULD_DECREASE:'+k)
            data['baseline']={k:max(self.baseline[k],int(data.get('baseline',{}).get(k,0))) for k in LIMITS}
        self.d=data
        self.flush()
    def flush(self):
        p=self.path.with_suffix('.tmp')
        p.write_text(json.dumps(self.d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        p.replace(self.path)
    def reserve(self,model):
        if model not in LIMITS:raise ValueError('MODEL_NOT_ALLOWLISTED')
        used=int(self.d['counts'].get(model,0));outside=int(self.d['baseline'].get(model,0))
        if outside+used>=LIMITS[model]:
            raise BudgetExceeded(f'{model}: local guard {LIMITS[model]}, prior {outside}, local {used}')
        self.d['counts'][model]=used+1
        self.flush()
        return outside+used+1
    def snapshot(self):
        return {'google_day_pacific':self.d['google_day_pacific'],
                'openrouter_reset':'NOT_AUTOMATIC_ASSUME_USER_BASELINE_AND_CONSERVATIVE_LOCAL',
                'baseline':self.d['baseline'],'attempts':self.d['counts'],'guard':LIMITS}

class RateLimiter:
    """Non-concurrent in-process pacing; injected clock/sleep permit deterministic unit tests.
    Strong Gemini requests (across BOTH models): 30 seconds minimum start-to-start.
    """
    def __init__(self,*,clock=time.monotonic,sleep=time.sleep,strong_gap=30.,lite_gap=4.,router_gap=4.):
        self.clock=clock;self.sleep=sleep
        self.strong_gap=strong_gap;self.lite_gap=lite_gap;self.router_gap=router_gap
        self.next_strong=0.;self.next_lite=0.;self.next_router=0.
        self.events=[]
    def wait_before(self,model):
        if model in ('gemini-3.8-flash','gemini-3.6-flash'):
            key='next_strong';gap=self.strong_gap
        elif model=='gemini-3.5-flash-lite':key='next_lite';gap=self.lite_gap
        elif model==ROUTER_MODEL:key='next_router';gap=self.router_gap
        else:raise ValueError('PACING_MODEL_NOT_ALLOWED')
        now=self.clock();due=getattr(self,key)
        wait=max(0.,due-now)
        if wait:self.sleep(wait)
        # For mock clocks with no advancing sleep, reserve virtual future position anyway.
        start=max(now,due)
        setattr(self,key,start+gap)
        self.events.append({'model':model,'wait_seconds':round(wait,3),'minimum_gap_seconds':gap})
        return wait

class Gemini:
    def __init__(self,ledger,transport=None,sleep=time.sleep,pacer=None,clock=time.perf_counter,jitter=None):
        self.ledger=ledger;self.transport=transport;self.sleep=sleep
        self.pacer=pacer or RateLimiter(sleep=(lambda _:None) if transport is not None else sleep)
        self.clock=clock
        self.jitter=jitter if jitter is not None else lambda:random.uniform(0,4)
        self.history=[]
    @staticmethod
    def retryable(code):
        return code in ('GEMINI_HTTP_408','GEMINI_HTTP_500','GEMINI_HTTP_502','GEMINI_HTTP_503',
                        'GEMINI_HTTP_504')
    def call(self,model,prompt,*,role,temperature=None,max_attempts=None,thinking_level=None):
        if model not in GOOGLE_LIMITS:raise ValueError('GEMINI_MODEL_NOT_ALLOWED')
        attempts=max_attempts if max_attempts is not None else (3 if model!='gemini-3.5-flash-lite' else 2)
        if not 1<=attempts<=3:raise ValueError('MAX_ATTEMPTS_OUT_OF_RANGE')
        level=(thinking_level or default_thinking_level(model,role)).lower()
        if level not in ('low','medium','high'):raise ValueError('THINKING_LEVEL_NOT_ALLOWLISTED')
        if model!='gemini-3.5-flash-lite' and level!='high':raise ValueError('STRONG_MODEL_MUST_USE_HIGH')
        for attempt in range(1,attempts+1):
            stamp=dt.datetime.now(dt.timezone.utc).isoformat()
            self.pacer.wait_before(model)
            try:self.ledger.reserve(model)
            except BudgetExceeded as e:
                self.history.append({'at_utc':stamp,'provider':'google','role':role,'attempt':attempt,
                     'model_requested':model,'thinking_level':level,'timeout_seconds':REQUEST_TIMEOUT_SECONDS,'status':'NOT_SENT_BUDGET',
                     'error_code':'BUDGET_STOP','latency_ms':0})
                raise
            started=self.clock()
            try:
                if self.transport is not None:
                    obj=self.transport(model,prompt,role)
                    actual=model;usage=None;response_id=None;finish_reason=None
                else:
                    obj,actual,usage,response_id,finish_reason=self._request(model,prompt,temperature,level,MAX_OUTPUT_TOKENS)
                self.history.append({'at_utc':stamp,'provider':'google','role':role,'attempt':attempt,
                    'model_requested':model,'model_returned':actual,'model_version':actual,'thinking_level':level,
                    'max_output_tokens':MAX_OUTPUT_TOKENS,'timeout_seconds':REQUEST_TIMEOUT_SECONDS,'status':'SUCCESS','usage':usage,
                    'response_id':response_id,'finish_reason':finish_reason,
                    'latency_ms':round((self.clock()-started)*1000,3)})
                return obj
            except (ModelFailure,TimeoutError,urllib.error.URLError) as e:
                code=e.code if isinstance(e,ModelFailure) else 'GEMINI_NETWORK_OR_PARSE_'+type(e).__name__
                row={'at_utc':stamp,'provider':'google','role':role,'attempt':attempt,
                    'model_requested':model,'thinking_level':level,'max_output_tokens':MAX_OUTPUT_TOKENS,
                    'status':'FAILED','timeout_seconds':REQUEST_TIMEOUT_SECONDS,'error_code':code,'latency_ms':round((self.clock()-started)*1000,3)}
                if isinstance(e,ModelFailure):row.update(e.details)
                self.history.append(row)
                if attempt>=attempts or not self.retryable(code):raise ModelFailure(code) from None
                # User-approved 45s, 90s backoff plus bounded jitter; no rapid-fire retry.
                self.sleep((45 if attempt==1 else 90)+self.jitter())
        raise AssertionError('UNREACHABLE')
    def _request(self,model,prompt,temperature,thinking_level,max_output_tokens):
        key=os.getenv(GOOGLE_KEY_ENV,'').strip()
        if not key:raise ModelFailure('NEED_GEMINI_API_KEY')
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        gen={'responseMimeType':'application/json','maxOutputTokens':max_output_tokens,
             'thinkingConfig':{'thinkingLevel':thinking_level}}
        if temperature is not None and model=='gemini-3.5-flash-lite':gen['temperature']=temperature
        body={'contents':[{'role':'user','parts':[{'text':prompt}]}],'generationConfig':gen}
        req=urllib.request.Request(url,data=json.dumps(body).encode('utf-8'),method='POST',headers={
            'Content-Type':'application/json','x-goog-api-key':key,'User-Agent':'FutureEvalV22Practice/1.0'})
        try:
            with urllib.request.urlopen(req,timeout=REQUEST_TIMEOUT_SECONDS) as resp:raw=json.load(resp)
        except urllib.error.HTTPError as e:
            # Never persist response bodies, HTTP headers, credential strings or prompts.
            raise ModelFailure(f'GEMINI_HTTP_{e.code}',http_status=e.code) from None
        except (urllib.error.URLError,TimeoutError,ValueError) as e:
            raise ModelFailure(f'GEMINI_NETWORK_OR_PARSE_{type(e).__name__}') from None
        c=(raw.get('candidates') or [{}])[0]
        usage_meta=raw.get('usageMetadata') or {}
        usage={k:usage_meta.get(k) for k in ('promptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount')}
        details={'model_version':raw.get('modelVersion','UNKNOWN'),'usage':usage,
                 'response_id':raw.get('responseId'),'finish_reason':c.get('finishReason')}
        if not raw.get('candidates'):raise ModelFailure('GEMINI_NO_CANDIDATES',**details)
        if c.get('finishReason')=='MAX_TOKENS':raise ModelFailure('GEMINI_MAX_OUTPUT_TOKENS',**details)
        parts=c.get('content',{}).get('parts',[])
        text=''.join(p.get('text','') for p in parts if isinstance(p,dict) and not p.get('thought')).strip()
        if not text:raise ModelFailure('GEMINI_EMPTY_TEXT',**details)
        if text.startswith('```'):text='\n'.join(text.splitlines()[1:-1]).strip()
        try:obj=json.loads(text)
        except json.JSONDecodeError:raise ModelFailure('GEMINI_INVALID_JSON',**details) from None
        if not isinstance(obj,dict):raise ModelFailure('GEMINI_NOT_OBJECT',**details)
        return obj,details['model_version'],usage,details['response_id'],details['finish_reason']
