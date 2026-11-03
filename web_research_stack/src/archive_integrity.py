"""Verify archive replay identity before admitting historical evidence."""
import re
from urllib.parse import urlsplit,unquote
from datetime import datetime,timezone

STAMP=re.compile(r'^/web/(\d{14})id_/(.+)$')

def _dt(x):
    s=str(x).strip().replace('Z','+00:00')
    d=datetime.fromisoformat(s)
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def verify_archive_response(expected_snapshot_url,final_url,t0):
    a=urlsplit(expected_snapshot_url or ''); b=urlsplit(final_url or '')
    if a.scheme!='https' or b.scheme!='https':
        return {'ok':False,'reason':'NON_HTTPS_ARCHIVE'}
    if a.hostname!='web.archive.org' or b.hostname!='web.archive.org':
        return {'ok':False,'reason':'OUTSIDE_ARCHIVE_HOST'}
    am=STAMP.match(unquote(a.path));bm=STAMP.match(unquote(b.path))
    if not am or not bm:return {'ok':False,'reason':'NOT_ID_ARCHIVE_PATH'}
    if am.group(1)!=bm.group(1):return {'ok':False,'reason':'ARCHIVE_TIMESTAMP_CHANGED'}
    if am.group(2)!=bm.group(2):return {'ok':False,'reason':'ARCHIVE_ORIGINAL_CHANGED'}
    stamp=datetime.strptime(bm.group(1),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    if stamp>=_dt(t0):return {'ok':False,'reason':'NOT_STRICTLY_PRE_T0'}
    return {'ok':True,'reason':'ARCHIVE_CAPTURE_VERIFIED','capture_timestamp':stamp.isoformat()}
