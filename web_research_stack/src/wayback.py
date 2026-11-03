import json,time
from datetime import datetime,timezone
from urllib.parse import urlencode
import requests

CDX='https://web.archive.org/cdx/search/cdx'
AVAIL='https://archive.org/wayback/available'

def _dt(x):
    if isinstance(x,datetime):
        d=x
    else:
        s=str(x).strip().replace('Z','+00:00')
        try:d=datetime.fromisoformat(s)
        except ValueError:d=datetime.strptime(s[:10],'%Y-%m-%d')
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def _stamp(d):
    return _dt(d).strftime('%Y%m%d%H%M%S')

def _capture_ok(ts,t0):
    try:return datetime.strptime(ts,'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc) <= _dt(t0)
    except Exception:return False

def latest_pre_t0(url,t0,session=None,timeout=20,pause_sec=0.15):
    s=session or requests.Session()
    headers={'User-Agent':'OpenResearchEvidenceBot/1.0 historical-evidence lookup'}
    target=_stamp(t0)
    params={
        'url':url,'to':target,'filter':'statuscode:200',
        'fl':'timestamp,original,statuscode,digest,mimetype',
        'output':'json','limit':'-1'
    }
    out={'url':url,'t0':_dt(t0).isoformat(),'status':'NO_PRE_T0_CAPTURE','method':None,'snapshot':None,'error':None}
    try:
        r=s.get(CDX,params=params,headers=headers,timeout=timeout)
        r.raise_for_status()
        data=r.json()
        if isinstance(data,list) and len(data)>=2:
            hdr=data[0]; row=dict(zip(hdr,data[-1]))
            ts=str(row.get('timestamp',''))
            if _capture_ok(ts,t0):
                original=row.get('original') or url
                snap=f'https://web.archive.org/web/{ts}id_/{original}'
                out.update(status='PRE_T0_CAPTURE_FOUND',method='CDX',snapshot={
                    'timestamp':ts,'original':original,'statuscode':row.get('statuscode'),
                    'digest':row.get('digest'),'mimetype':row.get('mimetype'),'snapshot_url':snap
                })
                if pause_sec:time.sleep(pause_sec)
                return out
    except Exception as e:
        out['error']='CDX:'+type(e).__name__+':'+str(e)[:160]

    try:
        r=s.get(AVAIL,params={'url':url,'timestamp':target},headers=headers,timeout=timeout)
        r.raise_for_status(); data=r.json()
        c=(data.get('archived_snapshots') or {}).get('closest') or {}
        ts=str(c.get('timestamp',''))
        if c.get('available') and str(c.get('status'))=='200' and _capture_ok(ts,t0):
            snap_url=str(c.get('url') or '').replace('http://','https://',1)
            if '/web/' in snap_url and 'id_/' not in snap_url:
                marker=f'/web/{ts}/'
                if marker in snap_url:snap_url=snap_url.replace(marker,f'/web/{ts}id_/',1)
            out.update(status='PRE_T0_CAPTURE_FOUND',method='AVAILABILITY',snapshot={
                'timestamp':ts,'original':url,'statuscode':'200','digest':None,
                'mimetype':None,'snapshot_url':snap_url
            })
        else:
            out['method']='AVAILABILITY'
    except Exception as e:
        suffix='AVAIL:'+type(e).__name__+':'+str(e)[:160]
        out['error']=(out['error']+' | '+suffix) if out['error'] else suffix
    if pause_sec:time.sleep(pause_sec)
    return out
