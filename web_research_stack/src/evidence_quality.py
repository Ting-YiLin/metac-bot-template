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

def _tokens(s):
    return re.findall(r'[a-z0-9][a-z0-9._+-]{2,}',(s or '').lower())

def evidence_relevance(question,text):
    q=[];seen=set()
    for t in _tokens(question):
        if t in STOP or t in seen:continue
        seen.add(t);q.append(t)
    tt=set(_tokens(text))
    hits=[t for t in q if t in tt]
    distinctive=[t for t in q if len(t)>=5 or re.search(r'\d',t) or t in {'musk','warsh','iran','fda','adhd','drc'}]
    distinctive_hits=[t for t in distinctive if t in tt]
    accepted=len(hits)>=2 and len(distinctive_hits)>=1
    return {
        'accepted':accepted,
        'score':len(hits)*10+len(distinctive_hits)*8,
        'hits':hits,'distinctive_hits':distinctive_hits,'anchors':q,
        'reason':'anchor_and_distinctive_match' if accepted else 'insufficient_question_anchor_match'
    }
