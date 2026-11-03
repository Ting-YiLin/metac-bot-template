import re

STOP={
    'will','would','could','should','the','and','for','from','with','without','into',
    'between','before','after','have','has','had','this','that','these','those','their',
    'there','which','what','when','where','who','why','how','any','other','than','hold',
    'result','state','states','position','june','july','april','may','january','february',
    'march','august','september','october','november','december','by','on','in','at','of',
    'to','a','an','is','are','was','were','be','been','being','do','does','did','can',
    'as','or','if','its','it','utc','2026','2025','2024','2023'
}
GENERIC_ENTITY={
    'supreme','court','senate','federal','reserve','chair','us','usa','u.s','u.s.',
    'fda','adhd','ai','utc','case','flight','group','media','technology','country',
    'organization','official','republic','new','section'
}
PREDICATE_STEMS={
    'launch','approv','confirm','reserv','judg','verdict','settle','announc','implement',
    'export','restrict','strike','resum','government','token','distribut','leaderboard',
    'rank','office','file','lawsuit','publish','open','pass','vote','elect','appoint',
    'release','acquire','merger','deal','tariff','ban','sanction','ceasefire','hearing',
    'trial','jury','docket','complaint'
}

def _tokens(s):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9._+-]*",(s or ''))

def _norm(t):
    return re.sub(r"^[^a-z0-9]+|[^a-z0-9._+-]+$", "", t.lower())

def excluded_terms(question):
    m=re.search(r'excluding\s+([^)]*)',question or '',re.I)
    if not m:return set()
    return {_norm(x) for x in _tokens(m.group(1)) if _norm(x) not in STOP and _norm(x) not in {'excluding'}}

def entity_anchors(question):
    ex=excluded_terms(question); out=[]
    for i,t in enumerate(_tokens(question)):
        n=_norm(t)
        mixed=any(c.isupper() for c in t[1:]) or bool(re.search(r'\d',t))
        proper=(i>0 and t[:1].isupper()) or t.isupper() or mixed
        if proper and n not in STOP and n not in GENERIC_ENTITY and n not in ex and len(n)>=3:
            if n not in out:out.append(n)
    return out

def evidence_relevance(question,text):
    qt=[_norm(x) for x in _tokens(question) if _norm(x) not in STOP]
    tt=[_norm(x) for x in _tokens(text)]
    ts=set(tt)

    hits=[x for x in dict.fromkeys(qt) if x in ts]
    ex=excluded_terms(question)
    excluded_hits=sorted(x for x in ex if x in ts)
    entities=entity_anchors(question)
    entity_hits=[x for x in entities if x in ts]
    predicate_hits=sorted(p for p in PREDICATE_STEMS if any(w.startswith(p) for w in tt))

    reasons=[]
    accepted=True
    if len(hits)<2:
        accepted=False;reasons.append('insufficient_question_anchor_match')
    if entities and not entity_hits:
        accepted=False;reasons.append('missing_specific_entity_or_identifier')
    if not predicate_hits:
        accepted=False;reasons.append('missing_outcome_or_event_predicate')
    # Exclusion questions are fail-closed for automatic admission. A source mentioning an
    # excluded entity can still be retained for manual review, but cannot be auto-evidence.
    if excluded_hits:
        accepted=False;reasons.append('excluded_entity_present_fail_closed')

    return {
        'accepted':bool(accepted),
        'score':len(hits)*10+len(entity_hits)*15+len(predicate_hits)*5-(60 if excluded_hits else 0),
        'hits':hits,'entity_anchors':entities,'entity_hits':entity_hits,
        'predicate_hits':predicate_hits,'excluded_hits':excluded_hits,
        'reason':'accepted' if accepted else ';'.join(reasons)
    }
