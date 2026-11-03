import re, unicodedata

STOP=set('''will would could should the and for from with without into between before after have has had this that these those their there which what when where who why how any other than hold result state states position june july april may january february march august september october november december by on in at of to a an is are was were be been being do does did can as or if its it utc 2026 2025 2024 2023 1 2 3 30 31'''.split())
GENERIC=set('''supreme court senate federal reserve chair us usa fda adhd ai utc case flight group media technology country organization official republic new section team stage rider final top public consumer annual policy meeting resolution world health assembly united government act online safety time trial tour'''.split())
PREDICATE_STEMS=('launch','approv','confirm','reserv','judg','verdict','settle','announc','implement','export','restrict','strike','resum','government','token','distribut','leaderboard','rank','office','file','lawsuit','publish','open','pass','vote','elect','appoint','release','acquire','merger','deal','tariff','ban','sanction','ceasefire','hearing','trial','jury','docket','complaint','withdraw','geoblock','repeal','replace','dissent','adopt','casualt','catch','stack','markup','inflation','reintegrat','troop','charging','constitutional','statut','appeal')

def _fold(s):
    return unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode()

def _tokens(s):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9._:+-]*",_fold(s))

def _norm(t):
    return re.sub(r"^[^a-z0-9]+|[^a-z0-9._:+-]+$","",t.lower())

def content_tokens(question):
    return list(dict.fromkeys(_norm(t) for t in _tokens(question) if _norm(t) and _norm(t) not in STOP and len(_norm(t))>=3))

def excluded_terms(question):
    m=re.search(r'excluding\s+([^)]*)',_fold(question),re.I)
    if not m:return set()
    return {_norm(t) for t in _tokens(m.group(1)) if _norm(t) not in STOP and len(_norm(t))>=3}

def critical_anchors(question):
    q=_fold(question); out=[]
    for m in re.finditer(r'\bv\.?\s+([A-Z][A-Za-z0-9&.-]+)',q):
        n=_norm(m.group(1))
        if n and n not in STOP and n not in GENERIC:out.append(n)
    for t in _tokens(q):
        n=_norm(t)
        if re.search(r'\d',n) and (('-' in n) or (':' in n)) and len(n)>=4:out.append(n)
    ts=_tokens(q)
    for i,t in enumerate(ts):
        n=_norm(t); mixed=any(c.isupper() for c in t[1:])
        proper=(i>0 and t[:1].isupper()) or t.isupper() or mixed
        if proper and len(n)>=4 and n not in STOP and n not in GENERIC:out.append(n)
    return list(dict.fromkeys(out))

def _predicates(words):
    return [p for p in PREDICATE_STEMS if any(w.startswith(p) for w in words)]

def classify_evidence_role(question,text,window_tokens=100):
    qt=content_tokens(question); cr=critical_anchors(question); ex=excluded_terms(question)
    words=[_norm(t) for t in _tokens(text)]; global_set=set(words)
    excluded_hits=sorted(ex & global_set)
    if excluded_hits:
        return {'role':'NOISE','reason':'excluded_entity_present','excluded_hits':excluded_hits,'critical_anchors':cr}

    global_hits=[x for x in qt if x in global_set]
    global_predicates=_predicates(global_set)
    centers=[i for i,w in enumerate(words) if w in cr]
    if not centers:
        qpos=[i for i,w in enumerate(words) if w in qt]
        stride=max(1,len(qpos)//25 or 1);centers=qpos[::stride]
    best={'score':-1,'question_hits':[],'critical_hits':[],'predicate_hits':[]}
    for i in centers:
        ws=set(words[max(0,i-window_tokens):min(len(words),i+window_tokens+1)])
        qh=[x for x in qt if x in ws];ch=[x for x in cr if x in ws];ph=_predicates(ws)
        score=2*len(qh)+5*len(ch)+2*len(ph)
        if score>best['score']:best={'score':score,'question_hits':qh,'critical_hits':ch,'predicate_hits':ph}

    parties=[_norm(m.group(1)) for m in re.finditer(r'\bv\.?\s+([A-Z][A-Za-z0-9&.-]+)',_fold(question))]
    party_ok=not parties or any(p in best['critical_hits'] for p in parties)
    if cr and best['critical_hits'] and len(best['question_hits'])>=3 and best['predicate_hits'] and party_ok:
        role='TARGET_SPECIFIC';reason='specific_anchor_local_cooccurrence'
    elif not cr and len(best['question_hits'])>=5 and best['predicate_hits']:
        role='TARGET_SPECIFIC';reason='dense_local_topic_cooccurrence'
    elif len(global_hits)>=3 and global_predicates:
        role='CONTEXT';reason='topical_but_not_target_specific'
    else:
        role='NOISE';reason='insufficient_target_relevance'
    return {'role':role,'reason':reason,'critical_anchors':cr,'global_hits':global_hits,'global_predicates':global_predicates,'best_window':best,'excluded_hits':excluded_hits}
