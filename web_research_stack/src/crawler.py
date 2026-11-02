import json,re,time
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from urllib.robotparser import RobotFileParser
import requests
from common import ensure_public_url,host,normalize_url,sha256_bytes,sha256_text,now_iso,DomainLimiter
from extractors import extract

TEMP_CODES={429,500,502,503,504}
SHELL_RE=re.compile(r'(enable javascript|sign in to continue|are you a robot|access denied|verify you are human|captcha)',re.I)

class CrawlBlocked(RuntimeError): pass
class FetchError(RuntimeError): pass

class Crawler:
    def __init__(self,config,root):
        self.cfg=config; self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.session=requests.Session(); self.session.headers.update({'User-Agent':config['user_agent'],'Accept':'text/html,application/pdf,text/plain,application/json;q=0.9,*/*;q=0.5'})
        self.limiter=DomainLimiter(config['per_domain_delay_sec']); self.robots={}
    def robots_allowed(self,url):
        h=host(url)
        cached=self.robots.get(h)
        if cached is None:
            u=urlsplit(url); robots_url=f'{u.scheme}://{u.netloc}/robots.txt'
            rp=RobotFileParser(); delay=0.0; status='UNKNOWN'; mode='PARSER'
            try:
                ensure_public_url(robots_url)
                r=self.session.get(robots_url,timeout=(self.cfg['connect_timeout_sec'],self.cfg['read_timeout_sec']))
                if r.status_code==404:
                    cached={'mode':'ALLOW_ALL','parser':None,'delay':0.0,'status':'ROBOTS_404_ALLOW'}
                elif r.status_code in (401,403):
                    cached={'mode':'DENY_ALL','parser':None,'delay':0.0,'status':'ROBOTS_DENIED_'+str(r.status_code)}
                else:
                    r.raise_for_status();rp.parse(r.text.splitlines());delay=rp.crawl_delay(self.cfg['user_agent']) or rp.crawl_delay('*') or 0.0
                    cached={'mode':'PARSER','parser':rp,'delay':float(delay or 0.0),'status':'CHECKED'}
            except Exception as e:
                cached={'mode':'ALLOW_ALL','parser':None,'delay':0.0,'status':'ROBOTS_UNAVAILABLE_'+type(e).__name__}
            self.robots[h]=cached
        if cached['mode']=='DENY_ALL': allowed=False
        elif cached['mode']=='ALLOW_ALL': allowed=True
        else: allowed=bool(cached['parser'].can_fetch(self.cfg['user_agent'],url))
        return allowed,float(cached['delay']),cached['status']
    def _render_html(self,url):
        allowed,crawl_delay,robots_state=self.robots_allowed(url)
        if not allowed: raise CrawlBlocked(robots_state)
        self.limiter.wait(host(url),crawl_delay)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise FetchError('PLAYWRIGHT_MISSING') from e
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            try:
                page=browser.new_page(user_agent=self.cfg['user_agent'])
                resp=page.goto(url,wait_until='domcontentloaded',timeout=int(self.cfg['read_timeout_sec']*1000))
                if not resp: raise FetchError('PLAYWRIGHT_NO_RESPONSE')
                if resp.status in (401,403): raise CrawlBlocked('PLAYWRIGHT_HTTP_'+str(resp.status))
                if resp.status>=400: raise FetchError('PLAYWRIGHT_HTTP_'+str(resp.status))
                page.wait_for_timeout(1000)
                final=page.url;ensure_public_url(final)
                ok,_,state2=self.robots_allowed(final)
                if not ok: raise CrawlBlocked('PLAYWRIGHT_REDIRECT_'+state2)
                raw=page.content().encode('utf-8')
                if len(raw)>int(self.cfg['max_response_bytes']): raise FetchError('PLAYWRIGHT_BODY_TOO_LARGE')
                return raw,'text/html; charset=utf-8',final,robots_state,1
            finally:
                browser.close()
    def _request(self,url):
        cur=normalize_url(url); retries=int(self.cfg['http_retries']); redirects=0; last=None
        while True:
            ensure_public_url(cur)
            allowed,crawl_delay,robots_state=self.robots_allowed(cur)
            if not allowed: raise CrawlBlocked(robots_state)
            self.limiter.wait(host(cur),crawl_delay)
            for attempt in range(retries+1):
                try:
                    r=self.session.get(cur,timeout=(self.cfg['connect_timeout_sec'],self.cfg['read_timeout_sec']),allow_redirects=False,stream=True)
                    if r.status_code in (301,302,303,307,308):
                        if redirects>=3: raise FetchError('TOO_MANY_REDIRECTS')
                        nxt=urljoin(cur,r.headers.get('Location','')); ensure_public_url(nxt);cur=normalize_url(nxt);redirects+=1;break
                    if r.status_code in (401,403): raise CrawlBlocked('HTTP_'+str(r.status_code))
                    if r.status_code in TEMP_CODES:
                        last=FetchError('HTTP_'+str(r.status_code))
                        if attempt<retries: time.sleep(min(5,1.5*(attempt+1))); continue
                        raise last
                    r.raise_for_status()
                    data=bytearray();limit=int(self.cfg['max_response_bytes'])
                    for chunk in r.iter_content(65536):
                        data.extend(chunk)
                        if len(data)>limit: raise FetchError('BODY_TOO_LARGE')
                    return bytes(data),r.headers.get('Content-Type',''),r.url,robots_state,attempt+1
                except CrawlBlocked: raise
                except Exception as e:
                    last=e
                    if attempt<retries: time.sleep(min(5,1.5*(attempt+1)));continue
                    raise FetchError(type(e).__name__+':'+str(e)[:240]) from e
            else: raise FetchError('UNKNOWN_FETCH_FAILURE')
    def fetch(self,url,source_id=None):
        source_id=source_id or ('S'+sha256_text(normalize_url(url))[:12])
        started=time.monotonic(); record={'source_id':source_id,'url':normalize_url(url),'retrieved_at':now_iso()}
        try:
            raw,ctype,final,robots_state,attempts=self._request(url)
            ensure_public_url(final)
            text,method,mode,ext=extract(raw,ctype,final)
            state='READABLE_FULL' if len(text)>=int(self.cfg['min_readable_chars']) else 'SHORT_TEXT'
            if SHELL_RE.search(text[:3000]): state='LOGIN_OR_BLOCK_SHELL'
            if state in ('SHORT_TEXT','LOGIN_OR_BLOCK_SHELL') and bool(self.cfg.get('playwright_fallback')) and mode=='HTML':
                try:
                    rraw,rctype,rfinal,rrobots,rattempts=self._render_html(final)
                    rtext,rmethod,rmode,rext=extract(rraw,rctype,rfinal)
                    rstate='READABLE_FULL' if len(rtext)>=int(self.cfg['min_readable_chars']) else 'SHORT_TEXT'
                    if not SHELL_RE.search(rtext[:3000]) and len(rtext)>len(text):
                        raw,ctype,final,robots_state,attempts=rraw,rctype,rfinal,rrobots,rattempts
                        text,method,mode,ext,state=rtext,'PLAYWRIGHT_'+rmethod,rmode,rext,rstate
                except Exception:
                    pass
            raw_dir=self.root/'raw';text_dir=self.root/'text';raw_dir.mkdir(parents=True,exist_ok=True);text_dir.mkdir(parents=True,exist_ok=True)
            raw_sha=sha256_bytes(raw);text_sha=sha256_text(text)
            raw_path=raw_dir/(source_id+ext);raw_path.write_bytes(raw)
            text_path=text_dir/(source_id+'.txt');text_path.write_text(text,encoding='utf-8')
            record.update(final_url=normalize_url(final),content_type=ctype,fetch_status=state,raw_bytes=len(raw),text_chars=len(text),raw_sha256=raw_sha,text_sha256=text_sha,raw_path=str(raw_path),text_path=str(text_path),extraction_method=method,content_mode=mode,robots=robots_state,http_attempts=attempts,error='')
        except Exception as e:
            record.update(fetch_status='BLOCKED' if isinstance(e,CrawlBlocked) else 'ERROR',raw_bytes=0,text_chars=0,error=type(e).__name__+':'+str(e),raw_sha256=None,text_sha256=None)
        record['duration_seconds']=round(time.monotonic()-started,3)
        with (self.root/'fetch_log.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
        return record
