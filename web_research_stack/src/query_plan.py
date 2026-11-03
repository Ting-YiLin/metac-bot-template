import re

STOPWORDS = {
    "what","when","where","which","who","whom","whose","why","how",
    "is","are","was","were","be","been","being","do","does","did",
    "will","would","should","could","can","may","might","must",
    "the","a","an","and","or","of","to","for","from","in","on","at","by",
    "with","without","about","into","over","under","between","through",
    "this","that","these","those","it","its","their","there","here",
    "official","evidence","states","state","according","source",
}

def compact_query(question, max_terms=12):
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._%+-]*|[\u3400-\u9fff]{2,}", question)
    out=[];seen=set()
    for t in tokens:
        k=t.lower()
        if k in STOPWORDS or len(k)<2 or k in seen:
            continue
        seen.add(k);out.append(t)
        if len(out)>=max_terms:
            break
    return " ".join(out) or " ".join(question.split())[:180]

def default_queries(question,preferred_domains=None):
    preferred_domains=preferred_domains or []
    base=compact_query(question)
    site=" OR ".join("site:"+d for d in preferred_domains[:3])
    official=(base+" "+site).strip() if site else base+" official primary source"
    return [
        base,
        official,
        base+" latest date number announcement",
        base+" original record documentation",
        base+" correction dispute counterexample",
    ]

def dedup_queries(queries):
    out=[];seen=set()
    for x in queries:
        k=re.sub(r"\s+"," ",x).strip().lower()
        if k and k not in seen:
            seen.add(k);out.append(x.strip())
    return out
