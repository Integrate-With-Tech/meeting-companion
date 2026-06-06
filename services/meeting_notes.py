"""
Meeting notes generation helpers shared by CLI and application code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from pathlib import Path
from typing import Any, Dict, List

from services.notes_storage import build_generated_note_exports
from services.summarization import summarize_text
from services.teams_native import parse_vtt_segments

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_ACTION_PATTERNS = (
    re.compile(r"^(action item|action|todo|follow up|follow-up|next step)\b", re.IGNORECASE),
    re.compile(r"\b(will|needs to|need to|owner|due)\b", re.IGNORECASE),
)
_DECISION_PATTERNS = (
    re.compile(r"^(decision|decided|approved|resolved)\b", re.IGNORECASE),
    re.compile(r"\b(agreed|approve|approved|decide|decided)\b", re.IGNORECASE),
)
_AGENDA_PATTERNS = (
    re.compile(r"^(agenda|topic|topics)\b", re.IGNORECASE),
    re.compile(r"\b(discuss|discussed|review|reviewed|plan|planned)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class TranscriptPayload:
    source_type: str
    title: str
    meeting_date: date
    full_text: str
    structured_notes: Dict[str, Any]
    markdown_notes: str


def _split_sentences(text: str) -> List[str]:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return []
    return [part.strip() for part in _SENTENCE_RE.split(collapsed) if part.strip()]


def _append_unique(items: List[str], value: str) -> None:
    normalized = value.strip()
    if normalized and normalized not in items:
        items.append(normalized)


def _classify_sentences(sentences: List[str]) -> Dict[str, List[str]]:
    agenda: List[str] = []
    action_items: List[str] = []
    decisions: List[str] = []

    for sentence in sentences:
        if any(pattern.search(sentence) for pattern in _ACTION_PATTERNS):
            _append_unique(action_items, sentence)
        if any(pattern.search(sentence) for pattern in _DECISION_PATTERNS):
            _append_unique(decisions, sentence)
        if any(pattern.search(sentence) for pattern in _AGENDA_PATTERNS):
            _append_unique(agenda, sentence)

    if not agenda:
        for sentence in sentences[:3]:
            _append_unique(agenda, sentence)

    return {
        "agenda": agenda,
        "action_items": action_items,
        "decisions": decisions,
    }


def _render_markdown(title: str, summary: List[str], agenda: List[str], action_items: List[str], decisions: List[str]) -> str:
    lines = [f"# {title}", ""]
    sections = [
        ("Summary", summary),
        ("Agenda", agenda),
        ("Action Items", action_items),
        ("Decisions", decisions),
    ]
    for heading, items in sections:
        lines.append(f"## {heading}")
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("- None identified.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _infer_meeting_date(path: Path) -> date:
    return date.fromtimestamp(path.stat().st_mtime)


def load_transcript_payload(transcript_path: Path) -> Dict[str, Any]:
    if transcript_path.suffix.lower() == ".vtt":
        vtt_content = transcript_path.read_text(encoding="utf-8")
        segments = parse_vtt_segments(vtt_content)
        full_text = " ".join(segment.text for segment in segments).strip()
        return {"source_type": "teams_native", "full_text": full_text, "segments": segments}

    full_text = transcript_path.read_text(encoding="utf-8").strip()
    return {"source_type": "plain_text", "full_text": full_text, "segments": []}


def generate_notes_payload(
    *,
    transcript_path: Path,
    meeting_title: str,
    summarizer: str,
    summary_max: int,
) -> TranscriptPayload:
    transcript = load_transcript_payload(transcript_path)
    full_text = str(transcript["full_text"]).strip()
    if not full_text:
        raise ValueError("Transcript is empty.")

    summary = (
        summarize_text(full_text, max_sentences=summary_max)
        if summarizer == "bart"
        else _split_sentences(full_text)[:summary_max]
    )
    classified = _classify_sentences(summary or _split_sentences(full_text))
    structured_notes = {
        "meeting_title": meeting_title,
        "meeting_date": _infer_meeting_date(transcript_path).isoformat(),
        "source_type": transcript["source_type"],
        "summary": summary,
        "agenda": classified["agenda"],
        "action_items": classified["action_items"],
        "decisions": classified["decisions"],
    }
    markdown_notes = _render_markdown(
        meeting_title,
        structured_notes["summary"],
        structured_notes["agenda"],
        structured_notes["action_items"],
        structured_notes["decisions"],
    )
    return TranscriptPayload(
        source_type=str(transcript["source_type"]),
        title=meeting_title,
        meeting_date=_infer_meeting_date(transcript_path),
        full_text=full_text,
        structured_notes=structured_notes,
        markdown_notes=markdown_notes,
    )


def write_notes_exports(
    *, transcript_path: Path, output_dir: Path, meeting_title: str, summarizer: str, summary_max: int
) -> Dict[str, Any]:
    payload = generate_notes_payload(
        transcript_path=transcript_path,
        meeting_title=meeting_title,
        summarizer=summarizer,
        summary_max=summary_max,
    )
    exports = build_generated_note_exports(
        meeting_date=payload.meeting_date,
        meeting_title=payload.title,
        markdown_notes=payload.markdown_notes,
        structured_notes=payload.structured_notes,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    written_files = []
    for export in exports.values():
        target = output_dir / export.filename
        target.write_text(export.text_content, encoding="utf-8")
        written_files.append(target)
    return {"payload": payload, "files": written_files}
