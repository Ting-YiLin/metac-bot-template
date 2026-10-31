"""OpenRouter FREE fallback ONLY after persistent Gemini HTTP 503.
Uses `openrouter/free` exclusively. Never calls paid routing modes or paid models.
No secrets, prompts or raw responses stored in reports.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
from .gemini import Gemini,ModelFailure,BudgetExceeded,ROUTER_MODEL,RateLimiter,REQUEST_TIMEOUT_SECONDS

class OpenRouterFree:
    def __init__(self,ledger,history,*,transport=None,pacer=None,clock=time.perf_counter):
        self.ledger=ledger;self.history=history;self.transport=transport
        self.pacer=pacer or RateLimiter();self.clock=clock

    def call(self,prompt,*,role):
        stamp=dt.datetime.now(dt.timezone.utc).isoformat()
        self.pacer.wait_before(ROUTER_MODEL)
        try:self.ledger.reserve(ROUTER_MODEL)
        except BudgetExceeded:
            self.history.append({'at_utc':stamp,'provider':'openrouter','model_requested':ROUTER_MODEL,
                 'role':role,'status':'NOT_SENT_BUDGET','error_code':'BUDGET_STOP','thinking_level':'NOT_GUARANTEED'})
            raise
        start=self.clock()
        try:
            if self.transport is not None:
                obj,actual,usage=self.transport(ROUTER_MODEL,prompt,role)
                rid=None;finish=None
            else:
                obj,actual,usage,rid,finish=self._request(prompt)
            self.history.append({'at_utc':stamp,'provider':'openrouter','role':role,
                'model_requested':ROUTER_MODEL,'model_returned':actual,
                'thinking_level':'NOT_GUARANTEED','timeout_seconds':REQUEST_TIMEOUT_SECONDS,'status':'SUCCESS','usage':usage,
                'response_id':rid,'finish_reason':finish,'latency_ms':round((self.clock()-start)*1000,3),
                'free_router':True})
            return obj
        except (ModelFailure,TimeoutError,urllib.error.URLError) as e:
            code=e.code if isinstance(e,ModelFailure) else 'ROUTER_NETWORK_'+type(e).__name__
            self.history.append({'at_utc':stamp,'provider':'openrouter','role':role,
                'model_requested':ROUTER_MODEL,'thinking_level':'NOT_GUARANTEED','timeout_seconds':REQUEST_TIMEOUT_SECONDS,
                'status':'FAILED','error_code':code,'latency_ms':round((self.clock()-start)*1000,3)})
            raise ModelFailure(code) from None

    def _request(self,prompt):
        key=os.getenv('OPENROUTER_API_KEY','').strip()
        if not key:raise ModelFailure('NEED_OPENROUTER_API_KEY')
        body={'model':ROUTER_MODEL,'stream':False,
              'messages':[{'role':'system','content':'Reply with one valid JSON object only. Preserve the requested schema. No markdown.'},
                          {'role':'user','content':prompt}],
              'response_format':{'type':'json_object'},'max_tokens':8192}
        url='https://openrouter.ai/api/v1/chat/completions'
        req=urllib.request.Request(url,data=json.dumps(body).encode('utf-8'),method='POST',headers={
             'Content-Type':'application/json','Authorization':'Bearer '+key,
             'User-Agent':'FutureEvalV22Practice/1.0'})
        try:
            with urllib.request.urlopen(req,timeout=REQUEST_TIMEOUT_SECONDS) as resp:raw=json.load(resp)
        except urllib.error.HTTPError as e:raise ModelFailure(f'OPENROUTER_HTTP_{e.code}') from None
        except (urllib.error.URLError,TimeoutError,ValueError) as e:
            raise ModelFailure('OPENROUTER_NETWORK_OR_PARSE_'+type(e).__name__) from None
        choices=raw.get('choices') or []
        if not choices:raise ModelFailure('OPENROUTER_NO_CHOICES')
        text=choices[0].get('message',{}).get('content')
        if isinstance(text,list):text=''.join(x.get('text','') for x in text if isinstance(x,dict) and x.get('type')=='text')
        if not isinstance(text,str) or not text.strip():raise ModelFailure('OPENROUTER_EMPTY_TEXT')
        text=text.strip()
        if text.startswith('```'):text='\n'.join(text.splitlines()[1:-1]).strip()
        try:obj=json.loads(text)
        except json.JSONDecodeError:raise ModelFailure('OPENROUTER_INVALID_JSON') from None
        if not isinstance(obj,dict):raise ModelFailure('OPENROUTER_NOT_OBJECT')
        returned=str(raw.get('model') or 'UNKNOWN_OPENROUTER_RESOLVED_MODEL')
        return obj,returned,raw.get('usage'),raw.get('id'),choices[0].get('finish_reason')

class FreeFallbackLLM:
    """Keep call(model,prompt,role=...) interface expected by existing pipeline.
    Provider fallback NOT used on budget, authentication, invalid schema or HTTP 429.
    """
    def __init__(self,google:Gemini,*,allow_free_fallback=False,router_transport=None):
        self.google=google
        self.history=google.history
        self.allow_free_fallback=allow_free_fallback
        self.transient_failures={'gemini-3.8-flash':0,'gemini-3.6-flash':0}
        self.circuit_limit=2
        self.free=OpenRouterFree(google.ledger,self.history,transport=router_transport,pacer=google.pacer)
    def call(self,model,prompt,*,role,**kwargs):
        strong=model in self.transient_failures
        if strong and self.transient_failures[model]>=self.circuit_limit:
            self.history.append({'provider':'google','role':role,'model_requested':model,
                                 'status':'NOT_SENT_CIRCUIT_OPEN','error_code':'GOOGLE_CIRCUIT_OPEN'})
            if not self.allow_free_fallback:
                raise ModelFailure('GOOGLE_CIRCUIT_OPEN')
            return self._free_call(prompt,role)
        try:
            result=self.google.call(model,prompt,role=role,**kwargs)
            if strong:self.transient_failures[model]=0
            return result
        except ModelFailure as e:
            transient=e.code in ('GEMINI_HTTP_503','GEMINI_HTTP_502','GEMINI_HTTP_504',
                                 'GEMINI_NETWORK_OR_PARSE_TimeoutError',
                                 'GEMINI_NETWORK_OR_PARSE_URLError')
            if not strong or not transient:raise
            self.transient_failures[model]+=1
            if not self.allow_free_fallback:raise
            return self._free_call(prompt,role)
    def _free_call(self,prompt,role):
        if not os.getenv('OPENROUTER_API_KEY') and self.free.transport is None:
            self.history.append({'provider':'openrouter','role':role,'model_requested':ROUTER_MODEL,
                                 'status':'NOT_SENT_NO_AUTH','error_code':'NEED_OPENROUTER_API_KEY'})
            raise ModelFailure('NEED_OPENROUTER_API_KEY') from None
        return self.free.call(prompt,role=role)
    def last_success(self,role):
        for row in reversed(self.history):
            if row.get('role')==role and row.get('status')=='SUCCESS':
                return {'provider':row.get('provider'),'model_requested':row.get('model_requested'),
                        'model_returned':row.get('model_returned'),
                        'thinking_level':row.get('thinking_level')}
        return None
