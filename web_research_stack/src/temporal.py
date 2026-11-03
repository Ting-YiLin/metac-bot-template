from datetime import datetime, timezone

def _parse_dt(x):
    if not x: return None
    s=str(x).strip().replace('Z','+00:00')
    try:
        d=datetime.fromisoformat(s)
    except ValueError:
        try: d=datetime.strptime(s[:10],'%Y-%m-%d')
        except ValueError: return None
    if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def classify_t0(t0=None, official_scraped_at=None, archive_snapshot_at=None, published_at=None, retrieved_at=None):
    """Classify temporal usability without pretending a live page is a historical snapshot."""
    T=_parse_dt(t0)
    if not T: return {'t0_status':'NO_T0','t0_safe':None,'reason':'no_t0_supplied'}
    a=_parse_dt(archive_snapshot_at)
    if a and a < T:
        return {'t0_status':'PRE_T0_ARCHIVE','t0_safe':True,'reason':'archive_snapshot_before_t0'}
    p=_parse_dt(published_at)
    if p and p < T:
        return {'t0_status':'PRE_T0_PUBLISHED_CURRENT_COPY','t0_safe':False,'reason':'publication_pre_t0_but_current_bytes_may_have_changed'}
    s=_parse_dt(official_scraped_at)
    if s and s < T:
        return {'t0_status':'URL_KNOWN_PRE_T0_CURRENT_CONTENT_UNVERIFIED','t0_safe':False,'reason':'official_index_saw_url_before_t0_but_current_content_is_not_historical_proof'}
    return {'t0_status':'POST_T0_OR_UNKNOWN','t0_safe':False,'reason':'no_pre_t0_snapshot_or_verified_content_date'}
