import hashlib,re
from collections import Counter
from common import host,load_json
from route_quality import route_specificity,candidate_relevance

GOV_HINTS=('.gov','.gov.au','.gc.ca','.europa.eu')
ACADEMIC_HOSTS=('doi.org','pubmed.ncbi.nlm.nih.gov','science.org','nature.com','arxiv.org','osf.io')
FORUM_HOSTS=('reddit.com','stackoverflow.com','stackexchange.com','quora.com')
MEDIA_HINTS=('reuters.com','apnews.com','bbc.','abc.net.au','nytimes.com','theguardian.com')

def source_family(row):
    u=(row.get('url') or '').lower();title=(row.get('title') or '').lower()
    m=re.search(r'10\.\d{4,9}/[^\s?#]+',u)
    if m:return 'doi:'+m.group(0).rstrip(').')
    m=re.search(r'arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})',u)
    if m:return 'arxiv:'+m.group(1)
    t=' '.join(re.findall(r'[a-z0-9\u4e00-\u9fff]+',title))
    return 'title:'+hashlib.sha256(t.encode()).hexdigest()[:16] if len(t)>30 else 'url:'+u.split('#')[0]

def classify(row,preferred_domains=None):
    h=host(row.get('url','')); u=(row.get('url') or '').lower(); text=((row.get('title') or '')+' '+(row.get('snippet') or '')).lower()
    preferred_domains=preferred_domains or []
    if any(h==d or h.endswith('.'+d) for d in preferred_domains): return 'preferred_official'
    if h.endswith(GOV_HINTS) or '.gov.' in h: return 'government_or_regulator'
    if any(h==d or h.endswith('.'+d) for d in ACADEMIC_HOSTS): return 'original_paper'
    if 'docs.' in h or '/docs/' in u or 'documentation' in text or 'manual' in text: return 'official_rules_or_docs'
    if any(h==d or h.endswith('.'+d) for d in FORUM_HOSTS): return 'forum_general'
    if any(x in h for x in MEDIA_HINTS): return 'professional_media'
    return row.get('source_type') or 'unknown'

def rank_rows(rows,question,preferred_domains=None,weights_path=None,domain_limit=3):
    if weights_path:
        w=load_json(weights_path)
    else:
        w={'preferred_official':600,'government_or_regulator':590,'official_rules_or_docs':580,'original_paper':570,'first_person_author':560,'original_record':550,'professional_media':370,'research_analysis':320,'forum_firsthand':280,'forum_general':190,'other':100,'unknown':100,'keyword_overlap_cap':25}
    qt=set(re.findall(r'[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}',question.lower()))
    ranked=[]
    for row in rows:
        x=dict(row);typ=classify(x,preferred_domains);fam=source_family(x)
        toks=set(re.findall(r'[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}',((x.get('title') or '')+' '+(x.get('snippet') or '')).lower()))
        overlap=min(len(qt&toks),int(w.get('keyword_overlap_cap',25)))
        authority=int(w.get(typ,w.get('unknown',100)))+overlap
        rq=route_specificity(x,question);rel=candidate_relevance(x,question)
        seed_bonus=0
        if str(x.get('t0_route_status',''))=='PRE_T0_INDEXED': seed_bonus+=140
        if str(x.get('route_origin','')).endswith('URL_PRET0_EXACT'): seed_bonus+=25
        rank_score=authority+rq['score']+rel['score']+seed_bonus
        x.update(source_type=typ,source_family=fam,authority_score=authority,
                 route_specificity_score=rq['score'],route_specificity_reasons=rq['reasons'],
                 relevance_score=rel['score'],relevance_overlap_terms=rel['overlap_terms'],
                 relevance_excluded_hits=rel['excluded_hits'],relevance_reasons=rel['reasons'],
                 pre_t0_seed_bonus=seed_bonus,rank_score=rank_score)
        ranked.append(x)
    ranked.sort(key=lambda x:(-x['rank_score'],-x['relevance_score'],-x['authority_score'],x.get('url','')))
    out=[];families=Counter();domains=Counter();remaining=list(ranked)
    while remaining:
        opts=[x for x in remaining if families[x['source_family']]<1 and domains[host(x['url'])]<domain_limit]
        if not opts: opts=[x for x in remaining if domains[host(x['url'])]<domain_limit]
        if not opts: opts=remaining
        pick=opts[0];remaining.remove(pick);out.append(pick);families[pick['source_family']]+=1;domains[host(pick['url'])]+=1
    for i,x in enumerate(out,1):x['rank']=i
    return out
