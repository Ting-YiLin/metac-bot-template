import re
from datetime import datetime,timezone
from urllib.parse import urlsplit, unquote

STOP={
    'will','would','could','should','the','and','for','from','with','without','into',
    'between','before','after','have','has','had','this','that','these','those','their',
    'there','which','what','when','where','who','why','how','any','other','than','hold',
    'result','state','states','position','june','july','april','may','2026','2025',
    'official','latest','date','number','announcement','original','record','documentation'
}
GENERIC_PATH_TERMS={
    'about','about-us','jury-service','conduct-of-the-jury','press-releases',
    'news-releases','sec-filings','cabinet-nomination-defeated','documentation',
    'manual','faq','faqs'
}
GENERIC_SECTION_PATHS={'','/','news','en','about','about-us','press-releases','news-releases'}
MONTHS={m.lower():i for i,m in enumerate(
    ['January','February','March','April','May','June','July','August','September','October','November','December'],1
)}
MONTHS.update({k[:3]:v for k,v in list(MONTHS.items())})

def _tokens(s):
    return {x for x in re.findall(r'[a-z0-9][a-z0-9._+-]{2,}',(s or '').lower()) if x not in STOP}

def excluded_terms(question):
    m=re.search(r'excluding\s+([^)]*)',question or '',re.I)
    return _tokens(m.group(1)) if m else set()

def candidate_relevance(row,question):
    qt=_tokens(question)
    text=' '.join([row.get('title') or '',row.get('snippet') or '',row.get('url') or ''])
    ct=_tokens(text)
    overlap=sorted(qt & ct)
    excluded=sorted(excluded_terms(question) & ct)
    score=min(len(overlap),7)*18
    reasons=[]
    if overlap:reasons.append('candidate_overlap:'+','.join(overlap[:7]))
    else:
        score-=120;reasons.append('zero_question_overlap')
    if excluded:
        score-=120*min(len(excluded),2);reasons.append('explicitly_excluded_entity:'+','.join(excluded[:2]))
    return {'score':int(score),'overlap_terms':overlap,'excluded_hits':excluded,'reasons':reasons}

def explicit_url_date(url):
    s=unquote(urlsplit(url or '').path).lower()
    # YYYY-MM-DD or YYYY/MM/DD
    m=re.search(r'(?<!\d)(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])(?!\d)',s)
    if m:
        y,mo,d=map(int,m.groups())
        try:return datetime(y,mo,d,tzinfo=timezone.utc)
        except ValueError:return None
    # compact YYYYMMDD embedded in official/news URLs, e.g. other20260522a.htm
    m=re.search(r'(?<!\\d)(20\\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\\d|3[01])(?!\\d)',s)
    if m:
        y,mo,d=map(int,m.groups())
        try:return datetime(y,mo,d,tzinfo=timezone.utc)
        except ValueError:return None
    # MM-DD-YYYY
    m=re.search(r'(?<!\d)(0?[1-9]|1[0-2])-(0?[1-9]|[12]\d|3[01])-(20\d{2})(?!\d)',s)
    if m:
        mo,d,y=map(int,m.groups())
        try:return datetime(y,mo,d,tzinfo=timezone.utc)
        except ValueError:return None
    # month-name-DD-YYYY, including monday-may-11-2026
    m=re.search(r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)[-_](0?[1-9]|[12]\d|3[01])[-_](20\d{2})',s)
    if m:
        mon,d,y=m.groups();mo=MONTHS.get(mon[:3],MONTHS.get(mon))
        try:return datetime(int(y),int(mo),int(d),tzinfo=timezone.utc)
        except (ValueError,TypeError):return None
    return None

def url_date_relation(url,t0):
    d=explicit_url_date(url)
    if not d:return {'status':'NO_EXPLICIT_URL_DATE','url_date':None}
    s=str(t0).replace('Z','+00:00')
    try:t=datetime.fromisoformat(s)
    except ValueError:t=datetime.strptime(s[:10],'%Y-%m-%d').replace(tzinfo=timezone.utc)
    if t.tzinfo is None:t=t.replace(tzinfo=timezone.utc)
    return {'status':'POST_T0_EXPLICIT_URL_DATE' if d>t else 'PRE_OR_ON_T0_EXPLICIT_URL_DATE','url_date':d.isoformat()}

def route_specificity(row,question):
    u=row.get('url') or ''
    p=urlsplit(u)
    path=unquote(p.path or '/')
    clean=path.strip('/').lower()
    segs=[s for s in clean.split('/') if s]
    qtokens=_tokens(question)
    utokens=_tokens(path+' '+p.query.replace('&',' ').replace('=',' '))
    overlap=sorted(qtokens & utokens)

    score=0; reasons=[]
    if clean in GENERIC_SECTION_PATHS and not p.query:
        score-=85;reasons.append('generic_section_or_homepage')
    depth=min(len(segs),4);score+=depth*6
    if depth>=2: reasons.append('multi_segment_path')
    if overlap:
        score+=min(len(overlap),4)*14;reasons.append('question_terms_in_url:'+','.join(overlap[:4]))
    if p.query:
        score+=10;reasons.append('query_parameters')
    if re.search(r'(?<!20)\d{3,}',path+p.query) or re.search(r'/\d+(?:/|$)',path):
        score+=22;reasons.append('record_or_case_identifier')
    if any(len(s)>=14 and '-' in s for s in segs):
        score+=10;reasons.append('descriptive_slug')
    if re.search(r'/20\d{2}/(?:0?[1-9]|1[0-2])/',path):
        score+=12;reasons.append('dated_article_path')
    generic_hits=[t for t in GENERIC_PATH_TERMS if t in clean]
    if generic_hits:
        score-=min(60,22*len(generic_hits));reasons.append('generic_info_path:'+','.join(sorted(generic_hits)))
    h=(p.hostname or '').lower()
    if 'wikipedia.org' in h and len(segs)<=2:
        score-=28;reasons.append('encyclopedia_profile_penalty')
    return {'score':int(score),'overlap_terms':overlap,'reasons':reasons,'path_depth':len(segs)}
