import re,sqlite3
from pathlib import Path
from common import now_iso

CJK=re.compile(r'[\u3400-\u9fff]+')
WORD=re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]{1,}')

def search_tokens(text):
    out=[]
    out.extend(m.group(0).lower() for m in WORD.finditer(text))
    for m in CJK.finditer(text):
        s=m.group(0)
        if len(s)<=2: out.append(s)
        else:
            out.extend(s[i:i+2] for i in range(len(s)-1))
            out.extend(s[i:i+3] for i in range(len(s)-2))
    return ' '.join(out)

def chunks(text,size=1800,overlap=250):
    if size<=overlap: raise ValueError('chunk size must exceed overlap')
    out=[];i=0
    while i<len(text):
        j=min(len(text),i+size);out.append((i,j,text[i:j]))
        if j==len(text): break
        i=j-overlap
    return out

class EvidenceDB:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY,url TEXT,title TEXT,source_type TEXT,authority_score REAL,text_path TEXT,text_chars INTEGER,retrieved_at TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,source_id TEXT,start_char INTEGER,end_char INTEGER,text TEXT,search_text TEXT)')
        try:self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(search_text, content='chunks', content_rowid='id')")
        except sqlite3.OperationalError:pass
        self.db.commit()
    def add_source(self,meta,text,chunk_size=1800,overlap=250):
        sid=meta['source_id']; self.db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?,?,?)',(sid,meta.get('url',''),meta.get('title',''),meta.get('source_type','unknown'),meta.get('authority_score',0),meta.get('text_path',''),len(text),meta.get('retrieved_at',now_iso())))
        old=[r[0] for r in self.db.execute('SELECT id FROM chunks WHERE source_id=?',(sid,))]
        if old:
            try:self.db.executemany('DELETE FROM chunks_fts WHERE rowid=?',[(x,) for x in old])
            except sqlite3.OperationalError:pass
        self.db.execute('DELETE FROM chunks WHERE source_id=?',(sid,))
        for st,en,tx in chunks(text,chunk_size,overlap):
            cur=self.db.execute('INSERT INTO chunks(source_id,start_char,end_char,text,search_text) VALUES(?,?,?,?,?)',(sid,st,en,tx,search_tokens(tx)))
            rid=cur.lastrowid
            try:self.db.execute('INSERT INTO chunks_fts(rowid,search_text) VALUES(?,?)',(rid,search_tokens(tx)))
            except sqlite3.OperationalError:pass
        self.db.commit()
    def search(self,query,limit=20):
        qt=search_tokens(query).split(); terms=[];seen=set()
        for t in qt:
            if len(t)>=2 and t not in seen:seen.add(t);terms.append(t)
        if not terms:return []
        fts=' OR '.join('"'+t.replace('"','')+'"' for t in terms[:30])
        try:
            sql='''SELECT c.source_id,c.start_char,c.end_char,c.text,s.url,s.title,s.source_type,s.authority_score,bm25(chunks_fts) AS score
                   FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid JOIN sources s ON s.source_id=c.source_id
                   WHERE chunks_fts MATCH ? ORDER BY score ASC, s.authority_score DESC LIMIT ?'''
            rows=self.db.execute(sql,(fts,int(limit))).fetchall()
        except sqlite3.OperationalError:
            like='%'+terms[0]+'%';rows=self.db.execute('''SELECT c.source_id,c.start_char,c.end_char,c.text,s.url,s.title,s.source_type,s.authority_score,0 FROM chunks c JOIN sources s ON s.source_id=c.source_id WHERE c.search_text LIKE ? ORDER BY s.authority_score DESC LIMIT ?''',(like,int(limit))).fetchall()
        keys=['source_id','start_char','end_char','text','url','title','source_type','authority_score','score']
        return [dict(zip(keys,r)) for r in rows]
