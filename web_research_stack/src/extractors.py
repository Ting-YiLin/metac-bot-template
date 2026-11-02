import io,json,re
from common import compact_text

class ExtractError(RuntimeError): pass

def extract_html(raw):
    try:
        import trafilatura
        text=trafilatura.extract(raw,include_tables=True,include_comments=False,output_format='txt') or ''
        if len(text.strip())>=200: return compact_text(text),'TRAFILATURA'
    except Exception: pass
    try:
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(raw,'html.parser')
        for el in soup(['script','style','nav','footer','header','form','aside','svg','noscript']): el.decompose()
        node=soup.select_one('main, article, [role="main"], .article-content, .entry-content, #content')
        text=(node if node else soup.body or soup).get_text(separator='\n',strip=True)
        return compact_text(text),'BEAUTIFULSOUP'
    except Exception as e: raise ExtractError('HTML_PARSE_FAILED:'+type(e).__name__) from e

def extract_pdf(raw):
    try:
        import fitz
        d=fitz.open(stream=raw,filetype='pdf')
        text='\n\n'.join(p.get_text() for p in d)
        if text.strip(): return compact_text(text),'PYMUPDF'
    except Exception: pass
    try:
        from pypdf import PdfReader
        r=PdfReader(io.BytesIO(raw),strict=False)
        text='\n\n'.join((p.extract_text() or '') for p in r.pages)
        return compact_text(text),'PYPDF'
    except Exception as e: raise ExtractError('PDF_PARSE_FAILED:'+type(e).__name__) from e

def extract(raw,content_type,url):
    c=(content_type or '').split(';')[0].strip().lower(); low=url.lower()
    if raw[:5]==b'%PDF-' or c=='application/pdf' or low.endswith('.pdf'):
        text,method=extract_pdf(raw);return text,method,'PDF','.pdf'
    if c in ('application/json','application/ld+json') or c.endswith('+json'):
        obj=json.loads(raw.decode('utf-8-sig','replace'));return json.dumps(obj,ensure_ascii=False,indent=2),'JSON','JSON','.json'
    if 'xml' in c or low.endswith(('.xml','.rss','.atom')):
        try:
            from bs4 import BeautifulSoup
            text=BeautifulSoup(raw,'xml').get_text('\n',strip=True)
            return compact_text(text),'BS4_XML','XML','.xml'
        except Exception as e: raise ExtractError('XML_PARSE_FAILED:'+type(e).__name__) from e
    if c.startswith('text/plain') or low.endswith(('.txt','.md','.markdown')):
        return compact_text(raw.decode('utf-8-sig','replace')),'PLAIN_TEXT','TEXT','.txt'
    text,method=extract_html(raw);return text,method,'HTML','.html'
