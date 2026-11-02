import hashlib,json,re,time,ipaddress,socket
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode

TRACK_PREFIX=('utm_','gclid','fbclid','mc_cid','mc_eid')

def load_json(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def save_json(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha256_bytes(b): return hashlib.sha256(b).hexdigest()
def sha256_text(s): return hashlib.sha256(s.encode('utf-8')).hexdigest()
def normalize_url(url):
    u=urlsplit(url.strip())
    q=[]
    for k,v in parse_qsl(u.query,keep_blank_values=True):
        lk=k.lower()
        if lk in TRACK_PREFIX or any(lk.startswith(x) for x in TRACK_PREFIX if x.endswith('_')): continue
        q.append((k,v))
    return urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path or '/',urlencode(q,doseq=True),''))
def host(url): return (urlsplit(url).hostname or '').lower()
def ensure_public_url(url):
    u=urlsplit(url)
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password: raise ValueError('unsafe_or_invalid_url')
    h=u.hostname.lower()
    if h in ('localhost','localhost.localdomain') or h.endswith('.local'): raise ValueError('local_host_blocked')
    addrs=[]
    try: addrs=[str(ipaddress.ip_address(h))]
    except ValueError:
        for info in socket.getaddrinfo(h,u.port or (443 if u.scheme=='https' else 80),type=socket.SOCK_STREAM):
            addrs.append(info[4][0])
    for a in set(addrs):
        try:
            ip=ipaddress.ip_address(a)
            if not ip.is_global: raise ValueError('private_or_reserved_ip_blocked:'+a)
        except ValueError as e:
            if str(e).startswith('private_or_reserved'): raise
    return True

def compact_text(text):
    lines=[re.sub(r'[ \t\u00a0]+',' ',x).strip() for x in re.split(r'\r?\n+',text)]
    return '\n'.join(x for x in lines if x)

def now_iso():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()

class DomainLimiter:
    def __init__(self,delay=5.0): self.delay=float(delay);self.last={}
    def wait(self,domain,extra_delay=0.0):
        d=max(self.delay,float(extra_delay or 0.0)); last=self.last.get(domain)
        if last is not None:
            remain=d-(time.monotonic()-last)
            if remain>0: time.sleep(remain)
        self.last[domain]=time.monotonic()
