"""
Summarization service.

Wraps Facebook BART (via Hugging Face *transformers*) so that the same
summarization logic can be used by the CLI, server workers, or any other
consumer that has a plain-text transcript.
"""

import re as _re
from typing import List

# ---------------------------------------------------------------------------
# Internal pipeline cache
# ---------------------------------------------------------------------------

_summ = None  # cached transformers pipeline


def _load_summarizer() -> None:
    global _summ
    from transformers import pipeline
    _summ = pipeline("summarization", model="facebook/bart-large-cnn", device_map="auto")


# ---------------------------------------------------------------------------
# Chunking helper
# ---------------------------------------------------------------------------


def _chunk(text: str, max_chars: int = 3500) -> List[str]:
    """Split *text* into chunks of at most *max_chars* characters, breaking on sentences."""
    text = _re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text]
    sents = _re.split(r"(?<=[.!?])\s+", text)
    chunks, cur = [], ""
    for s in sents:
        if len(cur) + len(s) + 1 > max_chars and cur:
            chunks.append(cur.strip())
            cur = s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur:
        chunks.append(cur.strip())
    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def summarize_text(full_text: str, max_sentences: int = 8) -> List[str]:
    """
    Summarize *full_text* using Facebook BART and return up to *max_sentences*
    bullet-point sentences.

    Returns an empty list when *full_text* is blank.
    Lazily loads the model on first call.
    """
    if not full_text.strip():
        return []
    if _summ is None:
        _load_summarizer()
    first = []
    for c in _chunk(full_text, 3500):
        first.append(_summ(c, max_length=128, min_length=40, do_sample=False)[0]["summary_text"])
    merged = " ".join(first)
    out2 = _summ(merged, max_length=128, min_length=40, do_sample=False)[0]["summary_text"]
    sents = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", out2) if s.strip()]
    return sents[:max_sentences]
