import re
from urllib.parse import urlsplit, unquote, parse_qs

STOP={
    'will','would','could','should','the','and','for','from','with','without','into',
    'between','before','after','have','has','had','this','that','these','those','their',
    'there','which','what','when','where','who','why','how','any','other','than','hold',
    'result','state','states','position','june','july','april','may','2026','2025'
}
GENERIC_PATH_TERMS={
    'about','about-us','jury-service','conduct-of-the-jury','press-releases',
    'news-releases','sec-filings','cabinet-nomination-defeated','documentation',
    'manual','faq','faqs'
}
GENERIC_SECTION_PATHS={'','/','news','en','about','about-us','press-releases','news-releases'}

def _tokens(s):
    return {x for x in re.findall(r'[a-z0-9][a-z0-9._+-]{2,}',(s or '').lower()) if x not in STOP}

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
    depth=min(len(segs),4)
    score+=depth*6
    if depth>=2: reasons.append('multi_segment_path')
    if overlap:
        add=min(len(overlap),4)*14;score+=add;reasons.append('question_terms_in_url:'+','.join(overlap[:4]))
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
        penalty=min(60,22*len(generic_hits));score-=penalty;reasons.append('generic_info_path:'+','.join(sorted(generic_hits)))
    h=(p.hostname or '').lower()
    if 'wikipedia.org' in h and len(segs)<=2:
        score-=28;reasons.append('encyclopedia_profile_penalty')
    return {'score':int(score),'overlap_terms':overlap,'reasons':reasons,'path_depth':len(segs)}
