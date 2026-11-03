"""Deterministic extracted-text integrity check; never infer semantic relevance."""
def inspect_text(text):
    text=text or ''
    n=max(1,len(text))
    replacement=text.count('\ufffd')
    nul=text.count('\x00')
    controls=sum(1 for c in text if ord(c)<32 and c not in '\n\r\t')
    ratio=replacement/n
    ctrl=(controls+nul)/n
    ok=(ratio<=0.01 and ctrl<=0.02)
    return {
        'ok':bool(ok),'replacement_ratio':round(ratio,6),
        'control_ratio':round(ctrl,6),'replacement_count':replacement,
        'null_count':nul,'reason':'OK' if ok else 'CORRUPTED_EXTRACTED_TEXT'
    }
