"""
Python dataclasses mirroring every Supabase/Postgres table.

Each class maps one-to-one with a table defined in
``migrations/001_initial_schema.sql``.  Fields that are nullable in the
schema are typed ``Optional[…]`` with a default of ``None`` so that callers
can construct partial objects when not all columns are relevant.

Timestamps coming from Supabase are returned as ISO-8601 strings.  This
module does *not* coerce them to :class:`datetime` objects to keep the layer
lightweight and dependency-free.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# tenant_settings
# ---------------------------------------------------------------------------


@dataclass
class TenantSettings:
    """Row in the ``tenant_settings`` table."""

    tenant_id: str
    settings: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# user_identities
# ---------------------------------------------------------------------------


@dataclass
class UserIdentity:
    """Row in the ``user_identities`` table."""

    tenant_id: str
    user_oid: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# meeting_jobs
# ---------------------------------------------------------------------------

MEETING_SOURCE_TYPES = frozenset({"teams_native", "uploaded_media", "uploaded_transcript", "bot_capture"})

MEETING_JOB_STATUSES = frozenset(
    {
        "pending",
        "processing",
        "completed",
        "failed",
        "missing_source_artifact",
        "authorization_failed",
    }
)


@dataclass
class MeetingJob:
    """Row in the ``meeting_jobs`` table."""

    tenant_id: str
    source_type: str = "teams_native"
    status: str = "pending"
    meeting_id: Optional[str] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error_message: Optional[str] = None
    created_by: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# meeting_artifacts
# ---------------------------------------------------------------------------


@dataclass
class MeetingArtifact:
    """Row in the ``meeting_artifacts`` table."""

    meeting_job_id: str
    artifact_type: str
    storage_path: str
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    id: Optional[str] = None
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# generated_notes
# ---------------------------------------------------------------------------


@dataclass
class GeneratedNotes:
    """Row in the ``generated_notes`` table."""

    meeting_job_id: str
    content: str = ""
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# sharepoint_uploads
# ---------------------------------------------------------------------------


@dataclass
class SharePointUpload:
    """Row in the ``sharepoint_uploads`` table."""

    meeting_job_id: str
    sharepoint_item_id: str
    artifact_id: Optional[str] = None
    web_url: Optional[str] = None
    drive_id: Optional[str] = None
    site_id: Optional[str] = None
    uploaded_at: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# audit_events
# ---------------------------------------------------------------------------


@dataclass
class AuditEvent:
    """Row in the ``audit_events`` table (append-only)."""

    event_type: str
    actor_id: Optional[str] = None
    actor_email: Optional[str] = None
    tenant_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None
    created_at: Optional[str] = None
