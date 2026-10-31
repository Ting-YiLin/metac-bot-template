"""Public RSS headlines, no search keys, no unsupported full-article claims."""
from __future__ import annotations
import datetime as dt
import re,urllib.parse,urllib.request,xml.etree.ElementTree as ET

STOP={'will','the','of','on','be','by','is','to','a','an','in','for','at','with','and','as','before','after','this','how','many','what','who','which','when','between','during'}

def query_variants(question):
    text=question.get('text','')
    words=[w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9'-]*",text) if w.lower() not in STOP]
    unique=list(dict.fromkeys(words))
    base=' '.join(unique[:9])
    if not base:return []
    return [base, ' '.join(unique[:5])+' latest'] if len(unique)>=5 else [base]

def headlines(question,*,asof=None,fetcher=None,per_query=4):
    if asof is None:asof=dt.datetime.now(dt.timezone.utc)
    if fetcher is None:
        def fetcher(url):
            req=urllib.request.Request(url,headers={'User-Agent':'FutureEvalPracticeV2/1.0'})
            with urllib.request.urlopen(req,timeout=12) as response:return response.read(500000)
    seen=set();results=[];errors=[]
    for query in query_variants(question):
        url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':query,'hl':'en-US','gl':'US','ceid':'US:en'})
        try:
            root=ET.fromstring(fetcher(url))
            for item in root.findall('.//item')[:per_query]:
                title=(item.findtext('title') or '').strip()
                link=(item.findtext('link') or '').strip()
                date=(item.findtext('pubDate') or '').strip()
                publisher=(item.findtext('source') or '').strip()
                if not title or not link or not link.startswith('https://') or (title,link) in seen:continue
                seen.add((title,link))
                # RFC822 may be parsed by email.utils; only dated sources <= asof.
                from email.utils import parsedate_to_datetime
                try:
                    parsed=parsedate_to_datetime(date)
                    if parsed.tzinfo is None:continue
                    if parsed.astimezone(dt.timezone.utc)>asof:continue
                    stamp=parsed.isoformat()
                except (TypeError,ValueError,OverflowError):continue
                results.append({'source_id':f'S{len(results)+1:02d}','title':title[:260],
                                'url':link,'published_at':stamp,'publisher':publisher[:100],
                                'access_level':'HEADLINE_ONLY_RSS_NOT_FULL_ARTICLE'})
        except Exception as e:
            errors.append({'query':query,'error_type':type(e).__name__})
    return {'sources':results[:10],'queries':query_variants(question),'errors':errors,'asof_utc':asof.isoformat()}
