"""
Artifact writing service.

Writes all transcript output files for a processed video.  Keeping this
logic in a dedicated module means that CLI, server workers, and any future
code that produces transcription *segments* can generate identical output
files without duplicating the writing logic.

Supported output files
----------------------
- transcript.txt  – timestamped transcript (one line per segment)
- captions.srt    – SubRip subtitle format
- captions.vtt    – WebVTT caption format
- full.txt        – plain concatenated text
- summary.md      – AI-generated bullet-point summary (optional)
"""

from pathlib import Path
from typing import List, Tuple

from services.transcription import srt_timestamp
from services.summarization import summarize_text

# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------


def ensure_dirs(out_dir: Path) -> None:
    """Create *out_dir* (and any missing parents) if it does not yet exist."""
    out_dir.mkdir(parents=True, exist_ok=True)


def outputs_present(out_dir: Path) -> bool:
    """Return ``True`` when the directory already contains completed outputs.

    A directory is considered complete when both the timestamped transcript
    and the summary/notes file are present (even an empty summary placeholder
    satisfies this check).
    """
    return (out_dir / "transcript.txt").exists() and (out_dir / "summary.md").exists()


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------


def write_artifacts(
    out_dir: Path,
    segments: List[Tuple[float, float, str]],
    full_text: str,
    stem: str,
    do_summary: bool,
    summary_max: int,
) -> None:
    """Write all output files for a single transcribed video.

    Parameters
    ----------
    out_dir:
        Directory in which all files will be created.
    segments:
        List of ``(start_seconds, end_seconds, text)`` tuples produced by
        the transcription service.
    full_text:
        Plain concatenated transcript text.
    stem:
        Sanitised video filename stem used as the summary heading.
    do_summary:
        When ``True`` the BART summarizer is invoked and its output is
        written to ``summary.md``.  When ``False`` a placeholder file is
        written instead (so that :func:`outputs_present` still returns
        ``True`` on the next run).
    summary_max:
        Maximum number of bullet-point sentences in the summary.
    """
    # transcript.txt – one timestamped line per segment
    with (out_dir / "transcript.txt").open("w", encoding="utf-8") as f:
        for start, end, text in segments:
            f.write(f"[{srt_timestamp(start)} - {srt_timestamp(end)}] {text}\n")

    # captions.srt
    with (out_dir / "captions.srt").open("w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(segments, 1):
            f.write(f"{i}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text.strip()}\n\n")

    # captions.vtt
    with (out_dir / "captions.vtt").open("w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for start, end, text in segments:
            vtt_start = srt_timestamp(start).replace(",", ".")
            vtt_end = srt_timestamp(end).replace(",", ".")
            f.write(f"{vtt_start} --> {vtt_end}\n{text.strip()}\n\n")

    # full.txt
    (out_dir / "full.txt").write_text(full_text, encoding="utf-8")

    # summary.md
    if do_summary:
        bullets = summarize_text(full_text, max_sentences=summary_max)
        with (out_dir / "summary.md").open("w", encoding="utf-8") as f:
            f.write(f"# Summary: {stem}\n\n")
            if bullets:
                for b in bullets:
                    f.write(f"- {b}\n")
            else:
                f.write("- No content to summarize.\n")
    else:
        if not (out_dir / "summary.md").exists():
            (out_dir / "summary.md").write_text("# Summary\n\n", encoding="utf-8")
