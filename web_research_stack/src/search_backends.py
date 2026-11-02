import requests
from common import normalize_url

class SearchError(RuntimeError): pass

def ddgs_search(query,max_results=8):
    try: from ddgs import DDGS
    except ImportError as e: raise SearchError('DDGS_MISSING: pip install ddgs') from e
    try: rows=list(DDGS().text(query,max_results=max_results))
    except Exception as e: raise SearchError(f'DDGS_FAILED:{type(e).__name__}:{e}') from e
    out=[]
    for x in rows:
        u=x.get('href') or x.get('url')
        if u and u.startswith(('http://','https://')):
            out.append({'url':normalize_url(u),'title':x.get('title',''),'snippet':x.get('body',''),'engine':'DDGS','query':query})
    return out

def searxng_search(query,base_url,max_results=8,timeout=20):
    if not base_url: raise SearchError('SEARXNG_BASE_URL_EMPTY')
    url=base_url.rstrip('/')+'/search'
    try:
        r=requests.get(url,params={'q':query,'format':'json'},timeout=timeout,headers={'Accept':'application/json'})
        r.raise_for_status(); data=r.json()
    except Exception as e: raise SearchError(f'SEARXNG_FAILED:{type(e).__name__}:{e}') from e
    out=[]
    for x in data.get('results',[])[:max_results]:
        u=x.get('url','')
        if u.startswith(('http://','https://')):
            out.append({'url':normalize_url(u),'title':x.get('title',''),'snippet':x.get('content',''),'engine':'SearXNG','query':query})
    return out

def search(query,backend='ddgs',max_results=8,searxng_base_url=''):
    if backend=='ddgs': return ddgs_search(query,max_results)
    if backend=='searxng': return searxng_search(query,searxng_base_url,max_results)
    raise SearchError('UNKNOWN_BACKEND:'+backend)
