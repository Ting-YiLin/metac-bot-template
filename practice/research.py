"""Adaptive five-angle evidence discovery. Public RSS discovery + bounded body reads.
No Google search grounding, no API search keys, no authenticated Metaculus retrieval here.
All retrieved text is untrusted; never treat it as instructions for the model or for code.
"""
from __future__ import annotations
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

ANGLES=("official_resolution", "historical_baseline", "recent_changes", "supporting_case", "counterevidence")
STOP=set('the a an and or is was were be been to from in on at for by with of if after before will would which how who when what many does have has can some that this these those than among into about near other most least they their its two three value any point during year years under between'.split())
MAX_QUERIES=10
MAX_BODY_FETCH=8
MAX_RESULT_SOURCES=18
MAX_BODY_CHARS=11000


def terms(s):
    return list(dict.fromkeys(w.lower() for w in re.findall(r'[a-zA-Z][a-zA-Z0-9-]{2,}',str(s)) if w.lower() not in STOP))


def heuristic_plan(q, *, followup=False, gaps=None):
    """Conservative search plan if Lite's planner is down. No fabricated search results."""
    words=terms(q.get('text',''))
    subject=' '.join(words[:9]) or 'forecast question'
    base=subject[:160]
    suffixes=(
        'official definition methodology source',
        'historical data trend base rate',
        'latest update news',
        'increase drivers forecast supporting',
        'decrease risks contradictory evidence',
    ) if not followup else (
        'official original report statistics',
        'primary source latest data',
        'alternative scenarios skeptical view',
        'historical series last 5 years',
        'counterarguments uncertainty expert',
    )
    return [{'angle':a,'query':(base+' '+s).strip()[:180]} for a,s in zip(ANGLES,suffixes)]


def validate_plan(obj, q, *, previous=()):
    if not isinstance(obj,dict) or not isinstance(obj.get('queries'),list):
        raise ValueError('PLANNER_JSON_MISSING_QUERIES')
    entries=obj['queries']
    if len(entries)!=5:raise ValueError('PLAN_REQUIRES_FIVE_ANGLES')
    result=[];seen={x.lower().strip() for x in previous}
    for i,item in enumerate(entries):
        if not isinstance(item,dict) or item.get('angle')!=ANGLES[i]:
            raise ValueError('PLAN_ANGLE_MISMATCH')
        s=item.get('query')
        if not isinstance(s,str) or not 5<=len(s.strip())<=180 or any(x in s for x in ('\n','\r','\x00')):
            raise ValueError('PLAN_INVALID_QUERY')
        s=re.sub(r'\s+',' ',s).strip()
        if s.lower() in seen:raise ValueError('PLAN_DUPLICATE_QUERY')
        seen.add(s.lower());result.append({'angle':ANGLES[i],'query':s})
    return result


def ensure_public_https(url):
    try:u=urllib.parse.urlsplit(url)
    except ValueError:return False
    host=(u.hostname or '').lower().rstrip('.')
    try:port=u.port
    except ValueError:return False
    if u.scheme!='https' or not host or u.username or u.password or port not in (None,443):return False
    if host in ('localhost','metadata.google.internal') or host.endswith(('.local','.internal','.localhost')):return False
    try:
        ip=ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:pass
    return bool(re.fullmatch(r'[a-z0-9.-]+',host) and '.' in host and not host.startswith('-'))


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not ensure_public_https(newurl):raise urllib.error.URLError('NONPUBLIC_REDIRECT_BLOCKED')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_url(url,*,limit=350000,timeout=10):
    if not ensure_public_https(url):raise ValueError('URL_NOT_PUBLIC_HTTPS')
    opener=urllib.request.build_opener(SafeRedirect)
    req=urllib.request.Request(url,headers={'User-Agent':'FutureEvalResearchV21/1.0 (public evidence research)','Accept':'application/rss+xml,text/xml,text/html;q=0.8,*/*;q=0.1'})
    with opener.open(req,timeout=timeout) as response:
        final_url=response.geturl()
        if not ensure_public_https(final_url):raise ValueError('UNSAFE_FINAL_URL')
        payload=response.read(limit+1)
        if len(payload)>limit:raise ValueError('FETCH_BYTES_LIMIT')
        kind=response.headers.get('content-type','').lower()
        if not any(t in kind for t in ('xml','html','text','rss','atom')):raise ValueError('CONTENT_TYPE_NOT_TEXT')
        return payload,final_url,kind


class Extractor(HTMLParser):
    BLOCKED=('script','style','nav','footer','header','aside','form','svg','noscript')
    KEEP=('p','h1','h2','h3','article','main','time','li')
    def __init__(self):
        super().__init__(convert_charrefs=True);self.skip=0;self.keep=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in self.BLOCKED:self.skip+=1
        if tag in self.KEEP:self.keep+=1
    def handle_endtag(self,tag):
        if tag in self.BLOCKED:self.skip=max(0,self.skip-1)
        if tag in self.KEEP:
            self.keep=max(0,self.keep-1)
            if not self.skip:self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip and self.keep>0:self.parts.append(data)


def body_extract(payload,*,max_chars=MAX_BODY_CHARS):
    parser=Extractor();parser.feed(payload.decode('utf-8','replace'))
    text=html.unescape(''.join(parser.parts))
    text=re.sub(r'\s+',' ',text).strip()
    return text[:max_chars]


def date_stamp(date,asof):
    try:
        parsed=parsedate_to_datetime(date)
        if parsed.tzinfo is None:return None
        utc=parsed.astimezone(dt.timezone.utc)
        if utc>asof:return None
        return utc.isoformat()
    except (ValueError,TypeError,OverflowError):return None


def engine_url(query,engine):
    if engine=='google':
        return 'https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':query,'hl':'en-US','gl':'US','ceid':'US:en'})
    return 'https://www.bing.com/news/search?'+urllib.parse.urlencode({'q':query,'format':'rss'})


def discover_rss(query,*,angle,round_number,asof,fetcher=fetch_url,engines=('google','bing'),per_engine=5):
    items=[];errors=[]
    for engine in engines:
        try:
            raw=fetcher(engine_url(query,engine))[0]
            root=ET.fromstring(raw)
            for it in root.findall('.//item')[:per_engine]:
                title=(it.findtext('title') or '').strip()
                url=(it.findtext('link') or '').strip()
                date=(it.findtext('pubDate') or '').strip()
                published=date_stamp(date,asof)
                if not title or not ensure_public_https(url) or not published:continue
                publisher=(it.findtext('source') or '').strip()
                items.append({'title':title[:250],'url':url,'published_at':published,
                              'publisher':publisher[:90], 'engine':engine,'angle':angle,
                              'round':round_number,'access_level':'RSS_HEADLINE_ONLY',
                              'extracted_excerpt':'','body_length':0})
        except Exception as e:errors.append({'engine':engine,'angle':angle,'error_type':type(e).__name__})
    return items,errors


def domain(url):return (urllib.parse.urlsplit(url).hostname or '').lower().removeprefix('www.')


def first_party_domain(host):
    # Stronger primary-evidence flag only for government and supranational sites.
    return host.endswith(('.gov','.gov.au','.gov.uk','.europa.eu','.int')) or host in ('data.worldbank.org','fred.stlouisfed.org','www.federalreserve.gov')


def source_relevance(q,item):
    primary=terms(q.get('text',''))[:15]
    if not primary:return 0.
    target=set(primary)
    title=set(terms(item.get('title','')))
    excerpt=set(terms(item.get('extracted_excerpt','')))
    # Require topic anchors for cases with common collisions in previous run:
    # e.g. Israel elections must not count as sources for the US House election.
    qtext=q.get('text','').lower()
    candidate=(item.get('title','')+' '+item.get('extracted_excerpt','')).lower()
    if 'house of representatives' in qtext and not any(t in candidate for t in (
        'house of representatives','u.s. house','us house','congress','united states','us midterm')):
        return 0.0
    if 'ukraine' in qtext and not any(t in candidate for t in ('ukraine','ukrainian')):
        return 0.0
    # Avoid inflated scores from generic titles and broad election terms.
    return round(min(1.,(len(target&title)+.35*len(target&excerpt))/max(2.,min(5.,len(target)))),3)


def expand_page(item,*,fetcher=fetch_url):
    u=item['url']
    if not ensure_public_https(u):return dict(item,body_error='URL_NOT_PUBLIC_HTTPS')
    try:
        raw,final,kind=fetcher(u,limit=550000,timeout=10)
        if domain(final) in ('news.google.com','bing.com'):
            return dict(item,final_url=final,final_domain=domain(final),access_level='AGGREGATOR_ONLY_NOT_ORIGINAL_ARTICLE',body_length=0)
        text=body_extract(raw)
        # Text is NOT verified factual truth; it is page content only.
        status='PAGE_TEXT_EXTRACTED' if len(text)>=200 else 'PAGE_TEXT_TOO_SHORT'
        return dict(item,final_url=final,final_domain=domain(final),access_level=status,
                    body_length=len(text),body_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    extracted_excerpt=text[:950] if len(text)>=200 else '')
    except Exception as e:return dict(item,body_error=type(e).__name__)


def quality(q,items,*,all_angles=ANGLES):
    relevant=[x for x in items if x.get('relevance',0)>=.4]
    bodies=[x for x in relevant if x.get('access_level')=='PAGE_TEXT_EXTRACTED']
    domains={x.get('final_domain') or domain(x['url']) for x in relevant}
    domains-=set(('news.google.com','bing.com'))
    angle_cov={x['angle'] for x in relevant}
    primary=[x for x in relevant if first_party_domain(x.get('final_domain') or domain(x['url']))]
    has_counter='counterevidence' in angle_cov
    stats={'total_candidates':len(items),'relevant':len(relevant),'body_extracted':len(bodies),
           'independent_domains':len(domains),'angles_covered':len(angle_cov),
           'primary_domain_sources':len(primary),'counterevidence_angle':has_counter}
    components={'relevance':min(1,len(relevant)/8),'fulltext':min(1,len(bodies)/2),
                'diversity':min(1,len(domains)/3),'angles':min(1,len(angle_cov)/5),
                'primary':min(1,len(primary)/1)}
    score=round(.22*components['relevance']+.25*components['fulltext']+.2*components['diversity']+.18*components['angles']+.15*components['primary'],3)
    flags=[]
    if len(bodies)<2:flags.append('INSUFFICIENT_FULL_TEXT')
    if len(primary)<1:flags.append('NO_PRIMARY_GOV_OR_INSTITUTIONAL_DOMAIN')
    if not has_counter:flags.append('NO_COUNTEREVIDENCE_ANGLE')
    if len(domains)<3:flags.append('LOW_SOURCE_DIVERSITY')
    if score<.72:flags.append('LOW_QUALITY_SCORE')
    return {'score':score,'metrics':stats,'components':components,'flags':flags,
            'pass_for_bounded_research':len(flags)==0}


def ranked(q,raw,*,fetcher=fetch_url,body_limit=MAX_BODY_FETCH):
    # Merge duplicate publisher URLs across RSS engines and multiple query angles.
    unique={}
    for x in raw:
        key=(domain(x['url']),re.sub(r'\W+','',x['title'].lower())[:125])
        if key not in unique:unique[key]=dict(x,angles_seen=[x['angle']])
        elif x['angle'] not in unique[key]['angles_seen']:unique[key]['angles_seen'].append(x['angle'])
    candidates=list(unique.values())
    for x in candidates:x['relevance']=source_relevance(q,x)
    candidates.sort(key=lambda x:(first_party_domain(domain(x['url'])),x['relevance'],len(x['angles_seen'])),reverse=True)
    # Rotate anchors so top same-angle results don't starve oppositional evidence.
    selected=[];used=set()
    # Give explicit question-provided primary URLs a chance to be read even
    # when their generic link labels cannot pass the headline relevance check.
    for j,x in enumerate(candidates):
        if x.get('engine')=='QUESTION_REFERENCE':
            selected.append(x);used.add(j)
    for angle in ANGLES:
        for j,x in enumerate(candidates):
            if j not in used and angle in x['angles_seen'] and x['relevance']>=.4:
                selected.append(x);used.add(j);break
    for j,x in enumerate(candidates):
        if len(selected)>=MAX_RESULT_SOURCES:break
        if j not in used:selected.append(x);used.add(j)
    expanded=[]
    for i,x in enumerate(selected):
        y=expand_page(x,fetcher=fetcher) if i<body_limit else x
        y['source_id']=f'S{i+1:02d}'
        y['relevance']=source_relevance(q,y)
        expanded.append(y)
    return expanded



def question_referenced_urls(q,*,asof=None):
    """User/platform-provided official-reference URLs are seed leads, not verified facts.

    Avoid including URLs pointing to Metaculus platform itself; this is external
    factual evidence only. Publication date remains unknown until the page is read.
    """
    leads=[];seen=set()
    for key in ('resolution_criteria','background_info','fine_print'):
        for raw in re.findall(r'https://[^\s<>"\']+',str(q.get(key) or ''))[:5]:
            url=raw.rstrip('.,;:)]}')
            if url in seen or not ensure_public_https(url):continue
            seen.add(url)
            if domain(url).endswith('metaculus.com'):continue
            leads.append({'title':'Question-provided reference URL (not independently verified)',
               'url':url,'published_at':None,'publisher':'QUESTION_REFERENCE',
               'engine':'QUESTION_REFERENCE','angle':'official_resolution','round':0,
               'access_level':'UNDATED_DIRECT_LINK','extracted_excerpt':'','body_length':0})
    return leads[:6]

def collect(q,plan,*,asof=None,fetcher=fetch_url,round_number=1,engines=('google','bing')):
    if asof is None:asof=dt.datetime.now(dt.timezone.utc)
    if len(plan)>5:raise ValueError('MORE_THAN_FIVE_QUERIES_PER_ROUND')
    raw=[];errors=[]
    def work(item):
        return discover_rss(item['query'],angle=item['angle'],round_number=round_number,
                            asof=asof,fetcher=fetcher,engines=engines)
    # Five independent angle searches execute concurrently, but results are
    # merged in plan order for reproducibility and stable source IDs.
    with ThreadPoolExecutor(max_workers=5) as pool:
        for rows,errs in pool.map(work,plan):
            raw.extend(rows);errors.extend(errs)
    return raw,errors


def finalize(q,raw,*,fetcher=fetch_url,rounds=1,queries=(),errors=()):
    sources=ranked(q,raw,fetcher=fetcher)
    return {'sources':sources,'quality':quality(q,sources),'queries':list(queries),
            'errors':list(errors),'rounds':rounds,
            'source_rule':'SOURCE_TEXT_IS_UNTRUSTED_DATA; excerpts are page text not fact verification'}
