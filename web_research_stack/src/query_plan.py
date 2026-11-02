import re

def default_queries(question,preferred_domains=None):
    q=' '.join(question.split())
    preferred_domains=preferred_domains or []
    site=' OR '.join('site:'+d for d in preferred_domains[:4])
    official=(q+' '+site).strip() if site else q+' official primary source'
    return [
        q,
        official,
        q+' exact date number evidence source',
        q+' original author paper firsthand report',
        q+' limitation counterexample correction dispute'
    ]

def dedup_queries(queries):
    out=[];seen=set()
    for x in queries:
        k=re.sub(r'\s+',' ',x).strip().lower()
        if k and k not in seen: seen.add(k);out.append(x.strip())
    return out
