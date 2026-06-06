"""
Microsoft Teams native transcript/recording ingestion helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from services.db.models import AuditEvent, MeetingArtifact

_TIMESTAMP_RE = re.compile(r"^(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})(?:\s+.*)?$")
_SPEAKER_TAG_RE = re.compile(r"^<v(?:\s+([^>]+))?>(.*)$", re.IGNORECASE)
_ALLOWED_SPEAKER_CHARS = " .'-"


class TeamsGraphPermissionError(RuntimeError):
    """Raised when Graph permissions are insufficient to read artifacts."""


class TeamsGraphClient(Protocol):
    """Subset of Graph operations required for native artifact ingestion."""

    def get_transcript_vtt(self, meeting_id: str) -> Optional[str]:
        """Return transcript VTT content if available."""

    def list_recording_artifacts(self, meeting_id: str) -> Sequence[Dict[str, Any]]:
        """Return available recording artifacts for the meeting."""


@dataclass(frozen=True)
class TranscriptSegment:
    """Normalized transcript segment."""

    start_seconds: float
    end_seconds: float
    text: str
    speaker: Optional[str] = None


def _to_seconds(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _normalize_cue_text(cue_lines: List[str]) -> Tuple[str, Optional[str]]:
    text = " ".join(line.strip() for line in cue_lines if line.strip()).strip()
    if not text:
        return "", None

    speaker = None
    tag_match = _SPEAKER_TAG_RE.match(text)
    if tag_match:
        if tag_match.group(1):
            speaker = tag_match.group(1).strip() or None
        text = tag_match.group(2).strip()
    elif ": " in text:
        candidate, rest = text.split(": ", 1)
        if _is_valid_speaker_name(candidate):
            speaker = candidate.strip() or None
            text = rest.strip()

    text = re.sub(r"</?[^>]+>", "", text).strip()
    return text, speaker


def _is_valid_speaker_name(name: str) -> bool:
    normalized = name.strip()
    if not normalized:
        return False
    if not any(ch.isalnum() for ch in normalized):
        return False
    return all(ch.isalnum() or ch in _ALLOWED_SPEAKER_CHARS for ch in normalized)


def parse_vtt_segments(vtt_content: str) -> List[TranscriptSegment]:
    """Parse VTT into normalized transcript segments."""
    segments: List[TranscriptSegment] = []
    lines = vtt_content.splitlines()
    idx = 0

    while idx < len(lines):
        line = lines[idx].strip()
        if not line or line == "WEBVTT" or line.startswith("NOTE"):
            idx += 1
            continue

        if line.isdigit() and idx + 1 < len(lines):
            candidate = lines[idx + 1].strip()
            if _TIMESTAMP_RE.match(candidate):
                idx += 1
                line = candidate

        match = _TIMESTAMP_RE.match(line)
        if not match:
            idx += 1
            continue

        idx += 1
        cue_lines: List[str] = []
        while idx < len(lines) and lines[idx].strip():
            cue_lines.append(lines[idx])
            idx += 1

        text, speaker = _normalize_cue_text(cue_lines)
        if text:
            segments.append(
                TranscriptSegment(
                    start_seconds=_to_seconds(match.group("start")),
                    end_seconds=_to_seconds(match.group("end")),
                    text=text,
                    speaker=speaker,
                )
            )

    return segments


def ingest_teams_native_artifacts(
    *,
    meeting_id: str,
    meeting_job_id: str,
    tenant_id: str,
    meeting_completed: bool,
    graph_client: TeamsGraphClient,
    jobs_repo: Any,
    artifacts_repo: Any,
    audit_repo: Any,
) -> Dict[str, Any]:
    """Ingest Teams-native transcript/recording metadata for one meeting job."""
    jobs_repo.update_status(meeting_job_id, "processing")
    audit_repo.append(
        AuditEvent(
            event_type="meeting_job.ingestion_started",
            tenant_id=tenant_id,
            resource_type="meeting_job",
            resource_id=meeting_job_id,
            metadata={"source": "teams_native", "meeting_id": meeting_id},
        )
    )

    try:
        vtt_content = graph_client.get_transcript_vtt(meeting_id)
        recording_artifacts = list(graph_client.list_recording_artifacts(meeting_id))
    except TeamsGraphPermissionError as exc:
        jobs_repo.update_status(meeting_job_id, "authorization_failed", error_message=str(exc))
        audit_repo.append(
            AuditEvent(
                event_type="meeting_job.authorization_failed",
                tenant_id=tenant_id,
                resource_type="meeting_job",
                resource_id=meeting_job_id,
                metadata={"source": "teams_native", "error": str(exc)},
            )
        )
        return {"status": "authorization_failed", "source": "teams_native", "segments": []}

    if vtt_content:
        segments = parse_vtt_segments(vtt_content)
        digest = hashlib.sha256(vtt_content.encode("utf-8")).hexdigest()
        artifacts_repo.create(
            MeetingArtifact(
                meeting_job_id=meeting_job_id,
                artifact_type="transcript_vtt",
                storage_path=f"graph://onlineMeetings/{meeting_id}/transcripts/native.vtt",
                checksum=digest,
                size_bytes=len(vtt_content.encode("utf-8")),
            )
        )
        jobs_repo.update_status(meeting_job_id, "completed")
        audit_repo.append(
            AuditEvent(
                event_type="meeting_job.transcript_ingested",
                tenant_id=tenant_id,
                resource_type="meeting_job",
                resource_id=meeting_job_id,
                metadata={
                    "source": "teams_native",
                    "artifact_type": "transcript_vtt",
                    "hash": digest,
                    "segment_count": len(segments),
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        return {"status": "completed", "source": "teams_native", "hash": digest, "segments": segments}

    skipped_recordings = 0
    persisted_recordings = 0
    for artifact in recording_artifacts:
        # Prefer direct download URLs when available; fall back to stable Graph IDs.
        download_url = artifact.get("download_url")
        artifact_id = artifact.get("id")
        storage_candidate = (
            download_url if isinstance(download_url, str) else artifact_id if isinstance(artifact_id, str) else ""
        )
        storage_path = storage_candidate.strip()
        if not storage_path:
            skipped_recordings += 1
            continue
        artifacts_repo.create(
            MeetingArtifact(
                meeting_job_id=meeting_job_id,
                artifact_type="teams_recording",
                storage_path=storage_path,
            )
        )
        persisted_recordings += 1

    if skipped_recordings:
        audit_repo.append(
            AuditEvent(
                event_type="meeting_job.recording_artifact_skipped",
                tenant_id=tenant_id,
                resource_type="meeting_job",
                resource_id=meeting_job_id,
                metadata={"source": "teams_native", "skipped_count": skipped_recordings},
            )
        )

    if meeting_completed and not vtt_content and persisted_recordings == 0:
        jobs_repo.update_status(meeting_job_id, "missing_source_artifact")
        audit_repo.append(
            AuditEvent(
                event_type="meeting_job.missing_source_artifact",
                tenant_id=tenant_id,
                resource_type="meeting_job",
                resource_id=meeting_job_id,
                metadata={"source": "teams_native", "meeting_id": meeting_id},
            )
        )
        return {"status": "missing_source_artifact", "source": "teams_native", "segments": []}

    jobs_repo.update_status(meeting_job_id, "completed")
    audit_repo.append(
        AuditEvent(
            event_type="meeting_job.recording_artifacts_detected",
            tenant_id=tenant_id,
            resource_type="meeting_job",
            resource_id=meeting_job_id,
            metadata={"source": "teams_native", "artifact_count": len(recording_artifacts)},
        )
    )
    return {"status": "completed", "source": "teams_native", "segments": []}
