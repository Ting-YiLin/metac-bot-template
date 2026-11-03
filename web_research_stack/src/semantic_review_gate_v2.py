"""Model-independent two-reviewer evidence gate. This never predicts outcomes."""
import hashlib,re
from datetime import datetime,timezone
from urllib.parse import urlsplit,unquote
VALID_ROLES={
    'BACKGROUND_OR_WRONG_EVENT','ROUTE_OR_BASELINE_ONLY',
    'EVENT_SPECIFIC_PRET0_PRECURSOR','DIRECT_PRET0_EVENT_STATUS',
    'CONFLICTING_EVIDENCE','INSUFFICIENT_EVIDENCE'
}
QUOTE_REQUIRED={'EVENT_SPECIFIC_PRET0_PRECURSOR','DIRECT_PRET0_EVENT_STATUS','CONFLICTING_EVIDENCE'}
ARCHIVE_RE=re.compile(r'^/web/(\d{14})id_/(.+)$')

def _utc(x):
    d=datetime.fromisoformat(str(x).replace('Z','+00:00'))
    return (d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d).astimezone(timezone.utc)

def validate_source(src,raw_bytes,full_text):
    errors=[]
    required=('case_id','t0','original_url','snapshot_url','final_url','raw_sha256','text_sha256')
    errors += ['MISSING_'+k.upper() for k in required if not src.get(k)]
    if not src.get('archive_verified'):errors.append('ARCHIVE_NOT_VERIFIED')
    if raw_bytes is None:errors.append('RAW_NOT_PRESENT')
    if full_text is None:errors.append('FULLTEXT_NOT_PRESENT')
    if errors:return {'ok':False,'issues':errors}
    if hashlib.sha256(raw_bytes).hexdigest()!=src['raw_sha256']:errors.append('RAW_HASH_MISMATCH')
    if hashlib.sha256(full_text.encode('utf-8')).hexdigest()!=src['text_sha256']:errors.append('TEXT_HASH_MISMATCH')
    a=urlsplit(src['snapshot_url']);b=urlsplit(src['final_url'])
    if a.scheme!='https' or b.scheme!='https' or a.hostname!='web.archive.org' or b.hostname!='web.archive.org':
        errors.append('ARCHIVE_HOST_MISMATCH')
    ma=ARCHIVE_RE.match(unquote(a.path));mb=ARCHIVE_RE.match(unquote(b.path))
    if not ma or not mb:errors.append('INVALID_ARCHIVE_PATH')
    elif ma.group(1)!=mb.group(1) or ma.group(2)!=mb.group(2):
        errors.append('CAPTURE_ORIGINAL_CHANGED')
    else:
        prefix='/web/'+ma.group(1)+'id_/'
        orig=src['snapshot_url'].split(prefix,1)[-1]
        final=src['final_url'].split(prefix,1)[-1]
        if orig!=final:errors.append('QUERY_OR_ORIGINAL_CHANGED')
        if orig!=src['original_url']:errors.append('SOURCE_ORIGINAL_MISMATCH')
        try:
            stamp=datetime.strptime(ma.group(1),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
            if stamp>=_utc(src['t0']):errors.append('POST_T0_CAPTURE')
        except (TypeError,ValueError):errors.append('INVALID_TIMESTAMP')
    return {'ok':not errors,'issues':errors}

def validate_review(review,src,full_text):
    if not isinstance(review,dict):return {'ok':False,'issues':['NOT_A_DICT']}
    errors=[]
    for k in ('resolution','final_answer','prediction','future_outcome','winning_answer'):
        if k in review:errors.append('FORBIDDEN_FIELD_'+k.upper())
    required=('reviewer_id','case_id','source_url','role','target_entity','event_action','event_time_scope','reason','quotes')
    errors+=['MISSING_'+k.upper() for k in required if k not in review]
    if review.get('case_id')!=src.get('case_id'):errors.append('CASE_MISMATCH')
    if review.get('source_url')!=src.get('original_url'):errors.append('SOURCE_MISMATCH')
    if review.get('role') not in VALID_ROLES:errors.append('INVALID_ROLE')
    q=review.get('quotes')
    if not isinstance(q,list):errors.append('INVALID_QUOTES');q=[]
    if review.get('role') in QUOTE_REQUIRED and not q:errors.append('QUOTE_REQUIRED')
    for v in q:
        if not isinstance(v,str) or len(v.strip())<12:errors.append('QUOTE_TOO_SHORT')
        elif v not in (full_text or ''):errors.append('QUOTE_NOT_EXACT')
    for k in ('reviewer_id','target_entity','event_action','event_time_scope','reason'):
        if not str(review.get(k) or '').strip():errors.append('EMPTY_'+k.upper())
    return {'ok':not errors,'issues':errors}

def paired_review_verdict(src,raw_bytes,full_text,first,second):
    v=validate_source(src,raw_bytes,full_text)
    if not v['ok']:return {'status':'REJECT_SOURCE_INTEGRITY','details':v}
    if first is None or second is None:return {'status':'NEED_TWO_INDEPENDENT_REVIEWS'}
    a,b=validate_review(first,src,full_text),validate_review(second,src,full_text)
    if not a['ok'] or not b['ok']:return {'status':'INVALID_REVIEW_PAYLOAD','review1':a,'review2':b}
    if first['reviewer_id'].strip().casefold()==second['reviewer_id'].strip().casefold():
        return {'status':'REVIEWER_NOT_INDEPENDENT'}
    keys=('role','target_entity','event_action','event_time_scope')
    bad=[k for k in keys if ' '.join(str(first[k]).casefold().split())!=' '.join(str(second[k]).casefold().split())]
    if bad:return {'status':'DISAGREEMENT_REQUIRES_ADJUDICATION','fields':bad}
    return {'status':'AGREED_REVIEW_CANDIDATE','agreed_role':first['role'],
            'is_final_prediction':False,'requires_independent_calibration':True}
