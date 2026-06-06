"""
Transcription service.

Wraps faster-whisper model loading and audio transcription so that
both the CLI and future server/worker code can call the same logic.

Supported transcript sources (present and planned):
- Whisper output   : transcribe_audio()  ← implemented here
- Teams native     : future – pass pre-built segments/full_text directly to
                     services.artifacts.write_artifacts()
- Uploaded media   : future – supply a media path to transcribe_audio()
- Uploaded transcript: future – parse existing transcript, skip transcription
"""

import time
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Timestamp formatting (shared utility)
# ---------------------------------------------------------------------------


def srt_timestamp(t: float) -> str:
    """Format a floating-point number of seconds as an SRT/VTT timestamp."""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Whisper model loading
# ---------------------------------------------------------------------------

_WM = None  # cached WhisperModel class


def load_whisper(model_size: str, compute_type: str):
    """Load (and cache) a faster-whisper WhisperModel instance."""
    global _WM
    if _WM is None:
        from faster_whisper import WhisperModel as _WM_

        _WM = _WM_
    return _WM(model_size, compute_type=compute_type)


# ---------------------------------------------------------------------------
# Progress display helpers
# ---------------------------------------------------------------------------


def create_progress_bar(current: int, total: int, width: int = 30) -> str:
    """Return a simple ASCII progress bar string."""
    if total == 0:
        return "[" + "?" * width + "]"
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    percentage = int(100 * current / total)
    return f"[{bar}] {percentage:3d}%"


# ---------------------------------------------------------------------------
# Core transcription
# ---------------------------------------------------------------------------


def transcribe_audio(
    model,
    media_path: Path,
    language: str,
    beam_size: int,
    progress_timeout: int,
    verbose: bool = True,
) -> Tuple[List[Tuple[float, float, str]], str, object]:
    """
    Transcribe *media_path* with *model* and return ``(segments, full_text, info)``.

    ``segments`` is a list of ``(start_seconds, end_seconds, text)`` tuples.
    ``full_text`` is the concatenated plain-text transcript.
    ``info`` is the raw faster-whisper ``TranscriptionInfo`` object.

    Raises ``RuntimeError("progress-timeout")`` when no new audio has been
    processed for *progress_timeout* seconds (0 = disabled).
    """
    seg_iter, info = model.transcribe(
        str(media_path),
        language=None if language == "auto" else language,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
    )

    segments: List[Tuple[float, float, str]] = []
    parts: List[str] = []
    last_audio_s = 0.0
    last_wall = time.time()
    last_printed_bucket = -1
    start_time = time.time()

    total_duration: Optional[float] = getattr(info, "duration", None)

    for seg in seg_iter:
        text = seg.text.strip()
        segments.append((seg.start, seg.end, text))
        parts.append(text)

        if verbose:
            bucket = int(seg.end) // 10
            if bucket != last_printed_bucket:
                elapsed = time.time() - start_time
                current_pos = int(seg.end)
                if total_duration and total_duration > 0:
                    progress_bar = create_progress_bar(current_pos, int(total_duration))
                    eta_seconds = (elapsed / current_pos) * (total_duration - current_pos) if current_pos > 0 else 0
                    eta_str = f" | ETA: {int(eta_seconds)}s" if eta_seconds > 0 else ""
                    print(
                        f"    🎵 {progress_bar} {current_pos}s/{int(total_duration)}s{eta_str}",
                        flush=True,
                    )
                else:
                    print(
                        f"    🎵 Processed: {current_pos}s | Elapsed: {int(elapsed)}s",
                        flush=True,
                    )
                last_printed_bucket = bucket

        if seg.end > last_audio_s + 0.5:
            last_audio_s = seg.end
            last_wall = time.time()

        if progress_timeout > 0 and (time.time() - last_wall) > progress_timeout:
            if verbose:
                print(f"    ⚠️  No progress for {progress_timeout}s - aborting", flush=True)
            raise RuntimeError("progress-timeout")

    return segments, " ".join(parts), info


# ---------------------------------------------------------------------------
# Legacy alias – kept so that old call-sites continue to work
# ---------------------------------------------------------------------------


def transcribe_with_feedback(
    model,
    media_path: Path,
    language: str,
    beam_size: int,
    progress_timeout: int,
) -> Tuple[List[Tuple[float, float, str]], str, object]:
    """Deprecated alias for transcribe_audio (verbose=True)."""
    return transcribe_audio(
        model,
        media_path,
        language=language,
        beam_size=beam_size,
        progress_timeout=progress_timeout,
        verbose=True,
    )
