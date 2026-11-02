"""Adapter from a forecasting question object to the evidence research stack.

No LLM is used here. Search, fetch, extraction, persistence and retrieval remain
deterministic program layers. The returned text is evidence context for the
forecasting LLM to judge semantically.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from pipeline import ROOT, research

URL_RE = re.compile(r"https?://[^\s<>\]\[\)\(\"']+")
MAX_CONTEXT_CHARS = 12000


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _preferred_domains(question) -> list[str]:
    fields = [
        _text(getattr(question, "resolution_criteria", "")),
        _text(getattr(question, "fine_print", "")),
        _text(getattr(question, "background_info", "")),
    ]
    out = []
    for raw in URL_RE.findall("\n".join(fields)):
        try:
            h = (urlsplit(raw.rstrip(".,;:")).hostname or "").lower()
        except Exception:
            continue
        if not h or h.endswith("metaculus.com"):
            continue
        if h.startswith("www."):
            h = h[4:]
        if h not in out:
            out.append(h)
    return out[:4]


def _project_id(question) -> str:
    qid = getattr(question, "id_of_question", None)
    pid = getattr(question, "id_of_post", None)
    return f"forecast_p{pid or 'x'}_q{qid or 'x'}"


def evidence_context(packet: dict, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    chunks = packet.get("evidence_chunks") or []
    if not chunks:
        return (
            "External research returned no retrievable full-text evidence. "
            "Do not invent web evidence; forecast from the question materials and general knowledge."
        )
    parts = [
        "External evidence packet. Search snippets were NOT treated as evidence.",
        "Each excerpt below comes from a fetched full-text source. Judge relevance, conflicts, dates, and limitations yourself.",
        "",
    ]
    used = len("\n".join(parts))
    for i, h in enumerate(chunks, 1):
        block = (
            f"[E{i}] source={h.get('source_id')} type={h.get('source_type')} "
            f"authority_prior={h.get('authority_score')}\n"
            f"URL: {h.get('url')}\n"
            f"Excerpt: {h.get('text','').strip()}\n"
        )
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    parts += [
        "",
        "Important: technical readability is not proof. Distinguish direct support, partial support, missing evidence, and contradiction.",
    ]
    return "\n".join(parts)


def research_for_question(question, config_path: str | None = None) -> str:
    question_text = _text(getattr(question, "question_text", ""))
    if not question_text:
        raise ValueError("QUESTION_TEXT_MISSING")
    cfg = config_path or str(ROOT / "config" / "forecast.json")
    packet = research(
        project=_project_id(question),
        question=question_text,
        preferred_domains=_preferred_domains(question),
        queries=None,
        config_path=cfg,
    )
    return evidence_context(packet)
